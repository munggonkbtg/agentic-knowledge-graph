"""Loading settings.

Two sources, kept apart on purpose:

* ``config.yaml`` holds tunable, non-secret values (thresholds, model names...).
* Environment variables hold secrets (Neo4j password, API keys). A local ``.env``
  file is loaded into the environment if present; it is never committed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

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
    dimensions: int = Field(default=1024, ge=1)  # vector index size in Neo4j


class Layer2Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Entities mentioned in more than this share of the body blocks of their
    # language are flagged hub = true and not used for candidates. None = no hubs.
    hub_block_share: float | None = Field(default=0.2, gt=0.0, le=1.0)
    manual_file: Path = Path("registry/entities_manual.yaml")
    rule_version: str = "L2-v2"
    mention_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    # LLM fallback (M4 step 4): run on body blocks with at most this many non-hub
    # registry entities. None = never.
    llm_fallback_max_entities: int | None = Field(default=0, ge=0)


class LLMSettings(BaseModel):
    """A local model behind Ollama (no key needed). If a runtime ever needs a key,
    it is read from an environment variable, never from this file."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    runtime: Literal["ollama", "openrouter"] = "ollama"
    # openrouter: the key is read from this environment variable (never from config)
    api_key_env: str = "OPENROUTER_API_KEY"
    # openrouter: "deny" routes only to providers that do not store or train on data
    data_collection: Literal["deny", "allow"] = "deny"
    max_tokens: int = Field(default=1024, ge=16)  # cap on each answer (openrouter)
    endpoint: str = "http://localhost:11434"
    model: str = "qwen3.5:4b-q4_K_M"
    num_ctx: int = Field(default=2048, ge=256)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    think: bool = False
    max_retries: int = Field(default=2, ge=0, le=5)
    timeout_seconds: float = Field(default=120.0, gt=0)
    prompt_version: str = "mentions-v1"
    prompt_file: Path = Path("prompts/mentions_v1.md")
    cache_file: Path = Path("data/cache/llm.sqlite")
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    # impact check (M5 step 13): its own prompt and a larger context (old + new +
    # candidate passage)
    check_prompt_version: str = "impact-check-v1"
    check_prompt_file: Path = Path("prompts/impact_check_v1.md")
    check_num_ctx: int = Field(default=4096, ge=256)
    # layer 3 (entity merge) and layer 4 (DEPENDS) prompts
    merge_prompt_version: str = "merge-v1"
    merge_prompt_file: Path = Path("prompts/merge_v1.md")
    depends_prompt_version: str = "depends-v1"
    depends_prompt_file: Path = Path("prompts/depends_v1.md")
    depends_num_ctx: int = Field(default=4096, ge=256)


class ImpactSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # graph_first: graph-reached blocks by signal strength, then hybrid order
    # rrf: Reciprocal Rank Fusion of hybrid and the graph signal rankings
    ranking: Literal["graph_first", "rrf"] = "graph_first"
    top_n: int = Field(default=20, ge=1)  # candidates reported per change
    report_dir: Path = Path("data/reports")  # not in git (reports quote document text)
    check_top_n: int = Field(default=10, ge=1)  # candidates per change the LLM checks
    # human review (step 14): sheets and the review history live with the labels,
    # so `kg backup-labels` covers them (not in git)
    review_dir: Path = Path("data/labels/reviews")
    # step 15: a rejected review multiplies the confidence of the edges behind it
    review_reject_factor: float = Field(default=0.5, ge=0.0, le=1.0)


class Layer3Settings(BaseModel):
    """Entity merge (M6). Candidates by name containment and e5 similarity of the
    names; the local LLM confirms; only "same" merges, same type only."""

    model_config = ConfigDict(extra="forbid")
    rule_version: str = "L3-v1"
    min_similarity: float = Field(default=0.85, ge=0.0, le=1.0)
    top_k: int = Field(default=3, ge=1)  # nearest names per entity sent to the LLM
    min_containment_chars: int = Field(default=4, ge=1)
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class Layer4Settings(BaseModel):
    """DEPENDS (M7). Candidate pairs: shared non-hub entity + nearest blocks by e5,
    capped per block; only the most central blocks within the budget."""

    model_config = ConfigDict(extra="forbid")
    rule_version: str = "L4-v1"
    nearest_k: int = Field(default=5, ge=0)
    max_pairs_per_block: int = Field(default=5, ge=1)
    central_share: float = Field(default=0.2, gt=0.0, le=1.0)  # 0.2 = variant B, 1.0 = C
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)


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
    llm: LLMSettings = LLMSettings()
    impact: ImpactSettings = ImpactSettings()
    layer3: Layer3Settings = Layer3Settings()
    layer4: Layer4Settings = Layer4Settings()


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
