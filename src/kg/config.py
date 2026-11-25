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


class DiffSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edit_similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    cross_section_edit_threshold: float | None = Field(default=0.8, ge=0.0, le=1.0)
    align_renamed_sections: bool = True
    detect_cross_document_moves: bool = True
    exact_only_sections: list[str] = Field(default_factory=lambda: ["เชิงอรรถ"])


class AppConfig(BaseModel):
    """Everything in config.yaml. Unknown keys are an error, to catch typos."""

    model_config = ConfigDict(extra="forbid")
    neo4j: Neo4jSettings = Neo4jSettings()
    layer0: Layer0Settings = Layer0Settings()
    diff: DiffSettings = DiffSettings()


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
