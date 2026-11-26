"""All LLM calls go through this module (M4 step 4).

* Runtime (`config.yaml` llm.runtime): a local Ollama server (no key), or
  OpenRouter's API (key from the environment variable named in
  llm.api_key_env; document text is sent to OpenRouter and the model provider).
* Output: JSON constrained by a JSON schema (Ollama structured outputs) and
  validated with pydantic. Invalid JSON is retried `max_retries` times, then
  returned as a failure; a failure is never written to the graph.
* Cache: SQLite keyed by (content hash, prompt version + prompt file hash,
  model). Every real call logs tokens in / out, seconds and attempts.
* Thinking is switched off (`think: false`); a reply that still carries thinking
  text is counted (`thinking_chars`) so it can be reported.

Only the standard library is used for HTTP, so no new dependency.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kg.config import LLMSettings

EntityTypeName = Literal["Concept", "Role", "Artifact", "Body", "Place", "Other"]


class ExtractedMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: EntityTypeName
    term: str = Field(min_length=1, max_length=200)


class MentionList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mentions: list[ExtractedMention]


class ImpactVerdict(BaseModel):
    """M5 step 13: the checker's answer for one (change, candidate) pair."""

    model_config = ConfigDict(extra="forbid")
    verdict: Literal["needs_update", "not_affected", "unsure"]
    reason: str = Field(max_length=600)
    evidence: str = Field(max_length=600)  # quoted from the candidate passage


class MergeVerdict(BaseModel):
    """Layer 3: are two entity names the same thing?"""

    model_config = ConfigDict(extra="forbid")
    verdict: Literal["same", "different", "unsure"]
    reason: str = Field(max_length=600)


class DependsVerdict(BaseModel):
    """Layer 4: does one passage use a fact stated in the other without citing it?"""

    model_config = ConfigDict(extra="forbid")
    direction: Literal["a_on_b", "b_on_a", "none"]
    fact: str = Field(max_length=400)
    evidence_dependent: str = Field(max_length=600)  # quoted from the dependent passage
    evidence_source: str = Field(max_length=600)     # quoted from the passage it relies on


@dataclass
class CallResult:
    mentions: list[ExtractedMention] | None  # None = failure after all retries
    attempts: int = 0
    valid_first: bool = False
    cached: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    thinking_chars: int = 0
    errors: list[str] = field(default_factory=list)
    data: BaseModel | None = None  # the validated reply


class LLMUnavailable(RuntimeError):
    """The model cannot answer at all (bad key, no credits, forbidden): retrying
    or continuing a run would only record failures, so the run stops."""


# A transport takes the request body and returns Ollama's /api/chat response.
Transport = Callable[[dict], dict]


def ollama_transport(settings: LLMSettings) -> Transport:
    url = settings.endpoint.rstrip("/") + "/api/chat"

    def send(body: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=settings.timeout_seconds) as r:
            return json.loads(r.read().decode("utf-8"))

    return send


def openrouter_transport(settings: LLMSettings, env_file: Path | None = Path(".env")) -> Transport:
    """OpenRouter's OpenAI-style chat API. Takes the same request the client
    builds for Ollama and returns the reply in Ollama's shape, so caching,
    validation and retries are unchanged.

    * The key is read from the environment variable named in
      `llm.api_key_env` (a local .env is loaded into the environment if present);
      it is sent only in the Authorization header and never logged.
    * JSON is constrained by the schema (`response_format` json_schema, strict)
      and `provider.require_parameters` routes only to providers that support it.
    * `provider.data_collection` (default "deny") routes only to providers that
      do not store or train on the data.
    * Reasoning follows `llm.think` (off by default)."""
    import os

    from dotenv import load_dotenv

    from kg.config import MissingEnvError

    if env_file is not None and env_file.exists():
        load_dotenv(env_file, override=False)
    key = os.environ.get(settings.api_key_env)
    if not key:
        raise MissingEnvError(f"Missing environment variable {settings.api_key_env} "
                              "(the OpenRouter API key); put it in .env.")
    url = settings.endpoint.rstrip("/") + "/chat/completions"

    def send(body: dict) -> dict:
        payload = {
            "model": body["model"], "messages": body["messages"],
            "temperature": body["options"]["temperature"],
            "max_tokens": settings.max_tokens,
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "answer", "strict": True, "schema": body["format"]}},
            "reasoning": {"enabled": bool(body.get("think"))},
            "provider": {"require_parameters": True,
                         "data_collection": settings.data_collection},
        }
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                     "X-Title": "kg-pipeline"})
        try:
            with urllib.request.urlopen(req, timeout=settings.timeout_seconds) as r:
                reply = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (401, 402, 403):
                raise LLMUnavailable(f"OpenRouter HTTP {e.code}: {detail}") from None
            raise OSError(f"OpenRouter HTTP {e.code}: {detail}") from None
        if "error" in reply:
            raise OSError(f"OpenRouter error: {str(reply['error'])[:300]}")
        msg = reply["choices"][0]["message"]
        usage = reply.get("usage") or {}
        return {"message": {"content": msg.get("content") or "",
                            "thinking": msg.get("reasoning") or ""},
                "prompt_eval_count": usage.get("prompt_tokens", 0),
                "eval_count": usage.get("completion_tokens", 0)}

    return send


def make_transport(settings: LLMSettings) -> Transport:
    if settings.runtime == "openrouter":
        return openrouter_transport(settings)
    return ollama_transport(settings)


class LLMClient:
    def __init__(self, settings: LLMSettings, root: Path = Path("."),
                 transport: Transport | None = None) -> None:
        self.s = settings
        prompt = (root / settings.prompt_file).read_text(encoding="utf-8")
        self.system_prompt = prompt
        self.prompt_key = f"{settings.prompt_version}#{_sha(prompt)[:12]}"
        self.transport = transport or make_transport(settings)
        path = root / settings.cache_file
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS calls (content_hash TEXT, prompt TEXT, model TEXT, "
            "response TEXT, tokens_in INTEGER, tokens_out INTEGER, seconds REAL, "
            "attempts INTEGER, valid_first INTEGER, thinking_chars INTEGER, created TEXT, "
            "PRIMARY KEY (content_hash, prompt, model))")
        self.log: list[CallResult] = []

    def close(self) -> None:
        self.db.close()

    def _body(self, user_content: str, schema: type[BaseModel]) -> dict:
        return {"model": self.s.model, "stream": False, "think": self.s.think,
                "format": schema.model_json_schema(), "keep_alive": "10m",
                "options": {"num_ctx": self.s.num_ctx, "temperature": self.s.temperature},
                "messages": [{"role": "system", "content": self.system_prompt},
                             {"role": "user", "content": user_content}]}

    def _ask(self, key_text: str, user_content: str, schema: type[BaseModel],
             use_cache: bool) -> CallResult:
        """One validated call (cached by key_text, prompt and model). The parsed
        reply is in CallResult.data; None after all retries failed."""
        key = (_sha(key_text), self.prompt_key, self.s.model)
        if use_cache:
            row = self.db.execute(
                "SELECT response, tokens_in, tokens_out, seconds, attempts, valid_first, "
                "thinking_chars FROM calls WHERE content_hash=? AND prompt=? AND model=?",
                key).fetchone()
            if row:
                res = CallResult(None, row[4], bool(row[5]), True, row[1], row[2], row[3],
                                 row[6], data=schema.model_validate_json(row[0]))
                self.log.append(res)
                return res
        res = CallResult(None)
        start = time.time()
        for attempt in range(1, self.s.max_retries + 2):
            res.attempts = attempt
            try:
                reply = self.transport(self._body(user_content, schema))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                res.errors.append(f"transport: {type(e).__name__}: {str(e)[:200]}")
                continue
            res.tokens_in += int(reply.get("prompt_eval_count") or 0)
            res.tokens_out += int(reply.get("eval_count") or 0)
            msg = reply.get("message") or {}
            res.thinking_chars += len(msg.get("thinking") or "")
            try:
                res.data = schema.model_validate_json(msg.get("content") or "")
            except ValidationError as e:
                res.errors.append(f"invalid: {e.error_count()} error(s)")
                continue
            res.valid_first = attempt == 1
            break
        res.seconds = time.time() - start
        if res.data is not None and use_cache:
            self.db.execute(
                "INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (*key, res.data.model_dump_json(), res.tokens_in, res.tokens_out, res.seconds,
                 res.attempts, int(res.valid_first), res.thinking_chars))
            self.db.commit()
        self.log.append(res)
        return res

    def extract_mentions(self, text: str, use_cache: bool = True) -> CallResult:
        res = self._ask(text, f"Passage:\n{text}", MentionList, use_cache)
        res.mentions = res.data.mentions if res.data is not None else None
        return res

    def check_impact(self, old_text: str, new_text: str, candidate: str, context: str,
                     use_cache: bool = True) -> CallResult:
        """M5 step 13: does `candidate` need updating after old_text became new_text?
        CallResult.data is an ImpactVerdict (None after failed retries)."""
        user = (f"CHANGED PASSAGE ({context})\nOLD:\n{old_text or '(none: the passage was added)'}"
                f"\nNEW:\n{new_text or '(none: the passage was removed)'}\n\n"
                f"CANDIDATE PASSAGE:\n{candidate}")
        return self._ask(user, user, ImpactVerdict, use_cache)

    @classmethod
    def for_check(cls, settings: LLMSettings, root: Path = Path("."),
                  transport: Transport | None = None) -> LLMClient:
        """A client with the impact-check prompt and its context size."""
        s = settings.model_copy(update={"prompt_file": settings.check_prompt_file,
                                        "prompt_version": settings.check_prompt_version,
                                        "num_ctx": settings.check_num_ctx})
        return cls(s, root, transport)

    def confirm_merge(self, a: dict, b: dict, use_cache: bool = True) -> CallResult:
        """Layer 3: do two entity names refer to the same thing? a, b: name, type,
        language and up to two short example passages. data: MergeVerdict."""
        def show(e: dict, label: str) -> str:
            ctx = "\n".join(f"  - {x}" for x in e.get("examples", [])[:2])
            return (f"{label}: \"{e['name']}\" (type {e['type']}, language {e['language']})"
                    + (f"\n  used in:\n{ctx}" if ctx else ""))
        user = show(a, "NAME A") + "\n\n" + show(b, "NAME B")
        return self._ask(user, user, MergeVerdict, use_cache)

    def judge_dependency(self, a_text: str, b_text: str, a_context: str, b_context: str,
                         use_cache: bool = True) -> CallResult:
        """Layer 4: does one passage use a fact stated in the other without citing
        it? data: DependsVerdict."""
        user = (f"PASSAGE A ({a_context}):\n{a_text}\n\n"
                f"PASSAGE B ({b_context}):\n{b_text}")
        return self._ask(user, user, DependsVerdict, use_cache)

    @classmethod
    def for_task(cls, settings: LLMSettings, task: str, root: Path = Path("."),
                 transport: Transport | None = None) -> LLMClient:
        """A client with the prompt and context size of one task: mentions (the
        default settings), check, merge or depends."""
        if task == "mentions":
            return cls(settings, root, transport)
        update = {"check": {"prompt_file": settings.check_prompt_file,
                            "prompt_version": settings.check_prompt_version,
                            "num_ctx": settings.check_num_ctx},
                  "merge": {"prompt_file": settings.merge_prompt_file,
                            "prompt_version": settings.merge_prompt_version},
                  "depends": {"prompt_file": settings.depends_prompt_file,
                              "prompt_version": settings.depends_prompt_version,
                              "num_ctx": settings.depends_num_ctx}}[task]
        return cls(settings.model_copy(update=update), root, transport)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
