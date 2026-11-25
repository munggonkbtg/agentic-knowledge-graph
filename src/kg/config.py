"""Loading settings.

Two sources, kept apart on purpose:

* ``config.yaml`` holds tunable, non-secret values (thresholds, model names...).
* Environment variables hold secrets (Neo4j password, API keys). A local ``.env``
  file is loaded into the environment if present; it is never committed.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr

DEFAULT_CONFIG_PATH = Path("config.yaml")


class Neo4jSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = "neo4j"


class Layer0Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title_heading_in_path: bool = False
    strip_footnote_markers: bool = True
    footnote_marker_pattern: str = r"\[[0-9๐-๙]+\]"
    thai_digits_to_arabic: bool = True
    footnote_sections: list[str] = Field(default_factory=lambda: ["เชิงอรรถ"])
    split_list_over_chars: int | None = Field(default=1500, ge=1)


class DiffSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edit_similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    cross_section_edit_threshold: float | None = Field(default=0.8, ge=0.0, le=1.0)
    move_similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    split_window: int = Field(default=3, ge=1, le=10)
    align_renamed_sections: bool = True
    detect_cross_document_moves: bool = True


class IdentifySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept_text_similarity: float = Field(default=0.7, ge=0.0, le=1.0)
    accept_margin: float = Field(default=0.2, ge=0.0, le=1.0)
    new_document_below: float = Field(default=0.45, ge=0.0, le=1.0)
    compare_chars: int = Field(default=20000, ge=100)
    queue_file: Path = Path("data/labels/doc_identification_queue.csv")


class Layer1Confidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explicit: float = Field(default=1.0, ge=0.0, le=1.0)
    link: float = Field(default=1.0, ge=0.0, le=1.0)
    self_document: float = Field(default=0.9, ge=0.0, le=1.0)
    same_block_context: float = Field(default=0.85, ge=0.0, le=1.0)
    issued_under: float = Field(default=0.7, ge=0.0, le=1.0)
    name_without_year: float = Field(default=0.8, ge=0.0, le=1.0)
    title_mention: float = Field(default=0.7, ge=0.0, le=1.0)
    subject_name: float = Field(default=0.7, ge=0.0, le=1.0)


class Layer1Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rule_version: str = "L1-v3"
    confidence: Layer1Confidence = Layer1Confidence()
    aliases_file: Path = Path("registry/aliases.yaml")


class EmbeddingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    model: str = "intfloat/multilingual-e5-large"
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    device: str = "cpu"


class Layer2Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Entities mentioned in more than this share of the body blocks of their
    # language are flagged hub = true and not used for candidates. None = no hubs.
    hub_block_share: float | None = Field(default=0.2, gt=0.0, le=1.0)
    manual_file: Path = Path("registry/entities_manual.yaml")
    rule_version: str = "L2-v1"
    mention_confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class AppConfig(BaseModel):
    """Everything in config.yaml. Unknown keys are an error, to catch typos."""

    model_config = ConfigDict(extra="forbid")
    neo4j: Neo4jSettings = Neo4jSettings()
    layer0: Layer0Settings = Layer0Settings()
    diff: DiffSettings = DiffSettings()
    identify: IdentifySettings = IdentifySettings()
    layer1: Layer1Settings = Layer1Settings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    layer2: Layer2Settings = Layer2Settings()


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.model_validate(raw)


class Neo4jCredentials(BaseModel):
    uri: str
    user: str
    # SecretStr hides the value when printed or logged: str(x) gives '**********'.
    password: SecretStr


class MissingEnvError(RuntimeError):
    pass


NEO4J_ENV_VARS = ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")


def load_neo4j_credentials(env_file: Path | None = Path(".env")) -> Neo4jCredentials:
    """Read Neo4j connection details from environment variables.

    Only the *names* of missing variables are ever reported, never values.
    """
    if env_file is not None and env_file.exists():
        load_dotenv(env_file, override=False)
    missing = [name for name in NEO4J_ENV_VARS if not os.environ.get(name)]
    if missing:
        raise MissingEnvError(
            "Missing environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in."
        )
    return Neo4jCredentials(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=SecretStr(os.environ["NEO4J_PASSWORD"]),
    )
