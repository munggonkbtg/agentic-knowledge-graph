"""LLM client and fallback with a fake transport (no model, no server)."""

import json
from pathlib import Path

import pytest

from kg.config import LLMSettings
from kg.layer2_entities import EntityRegistry, LLMFallback, occurs_in
from kg.llm import LLMClient, MentionList

ROOT = Path(__file__).resolve().parents[1]


def _reply(content, thinking="", tin=50, tout=10):
    return {"message": {"content": content, "thinking": thinking},
            "prompt_eval_count": tin, "eval_count": tout}


class Fake:
    """Returns the queued replies in order and records the requests."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, body):
        self.requests.append(body)
        return self.replies.pop(0)


def _client(tmp_path, fake, **kw):
    s = LLMSettings(cache_file=tmp_path / "llm.sqlite", prompt_file=ROOT / "prompts/mentions_v1.md",
                    **kw)
    return LLMClient(s, root=ROOT, transport=fake)


def test_request_uses_schema_no_thinking_and_short_context(tmp_path):
    fake = Fake(_reply('{"mentions": []}'))
    _client(tmp_path, fake).extract_mentions("text")
    body = fake.requests[0]
    assert body["think"] is False and body["stream"] is False
    assert body["format"] == MentionList.model_json_schema()
    assert body["options"]["num_ctx"] == 2048 and body["options"]["temperature"] == 0.0


def test_invalid_json_is_retried_then_recorded_as_failure(tmp_path):
    ok = json.dumps({"mentions": [{"type": "Role", "term": "manager"}]})
    c = _client(tmp_path, Fake(_reply("not json"), _reply(ok)))
    res = c.extract_mentions("your manager")
    assert res.attempts == 2 and not res.valid_first and res.mentions[0].term == "manager"
    assert res.tokens_in == 100 and res.tokens_out == 20
    bad = _client(tmp_path, Fake(*[_reply('{"mentions": [{"type": "Person"}]}')] * 3))
    res = bad.extract_mentions("something else")
    assert res.mentions is None and res.attempts == 3 and len(res.errors) == 3


def test_cache_by_content_prompt_and_model(tmp_path):
    ok = json.dumps({"mentions": [{"type": "Concept", "term": "sabbatical"}]})
    fake = Fake(_reply(ok), _reply(ok), _reply(ok))
    c = _client(tmp_path, fake)
    c.extract_mentions("a sabbatical")
    again = c.extract_mentions("a sabbatical")
    assert again.cached and len(fake.requests) == 1
    c.extract_mentions("a sabbatical", use_cache=False)  # stability rerun bypasses it
    assert len(fake.requests) == 2
    other = _client(tmp_path, fake, model="another-model")
    assert not other.extract_mentions("a sabbatical").cached


def test_thinking_text_is_counted(tmp_path):
    c = _client(tmp_path, Fake(_reply('{"mentions": []}', thinking="let me think")))
    assert c.extract_mentions("x").thinking_chars == len("let me think")


@pytest.mark.parametrize("term,text,lang,ok", [
    ("short-term disability", "file a Short Term Disability claim", "en", True),
    ("manager", "your managers", "en", False),  # whole words only
    ("the program", "this policy", "en", False),
    ("ค่าชดเชย", "ให้จ่ายค่า ชดเชย[๓] แก่ลูกจ้าง", "th", True),
    ("ค่าชดเชยพิเศษ", "ให้จ่ายค่าชดเชย", "th", False),
])
def test_terms_must_occur_in_the_block(term, text, lang, ok):
    assert occurs_in(term, text, lang) is ok


def test_fallback_links_known_aliases_and_keeps_new_terms_apart(tmp_path):
    reg = EntityRegistry()
    known = reg.add("Sabbatical", "Concept", "en", "heading:x")
    reply = json.dumps({"mentions": [
        {"type": "Concept", "term": "sabbatical"},   # registry alias -> existing entity
        {"type": "Role", "term": "People Ops"},      # new -> LLM-sourced entity
        {"type": "Artifact", "term": "Airtable"},    # not in the text -> dropped
        {"type": "Other", "term": "onboarding"}]})   # Other -> counted, not linked
    text = "Ask People Ops about onboarding before your sabbatical."
    fb = LLMFallback(reg, _client(tmp_path, Fake(_reply(reply))), max_entities=0)
    ids = fb.entities_for(text, "en", registry_entities=set())
    assert ids == {known.entity_id, "llm:role:en:people-ops"}
    e = fb.new_entities["llm:role:en:people-ops"]
    assert e.entity_type == "Role" and e.sources == {"llm:qwen3.5:4b-q4_K_M"}
    st = fb.stats
    assert (st.returned, st.dropped, st.other, st.linked_existing, st.new_terms) == (4, 1, 1, 1, 1)
    assert known.entity_id not in fb.new_entities  # never merged into the registry entity


def test_threshold_decides_which_blocks_go_to_the_llm(tmp_path):
    fake = Fake()
    fb = LLMFallback(EntityRegistry(), _client(tmp_path, fake), max_entities=0)
    assert fb.entities_for("text", "en", registry_entities={"concept:en:x"}) == set()
    assert fake.requests == [] and fb.stats.blocks_called == 0
    assert not LLMFallback(EntityRegistry(), None, max_entities=None).needs_llm(0)


def test_impact_check_uses_its_own_prompt_schema_and_context(tmp_path):
    from kg.llm import ImpactVerdict

    reply = json.dumps({"verdict": "needs_update", "reason": "repeats the old value",
                        "evidence": "18 days"})
    fake = Fake(_reply(reply), _reply('{"verdict": "maybe", "reason": "", "evidence": ""}'),
                _reply('{"verdict": "maybe", "reason": "", "evidence": ""}'),
                _reply('{"verdict": "maybe", "reason": "", "evidence": ""}'))
    s = LLMSettings(cache_file=tmp_path / "llm.sqlite", prompt_file=ROOT / "prompts/mentions_v1.md",
                    check_prompt_file=ROOT / "prompts/impact_check_v1.md")
    c = LLMClient.for_check(s, root=ROOT, transport=fake)
    res = c.check_impact("18 days", "25 days", "New hires get 18 days.", "doc > Vacation")
    assert res.data.verdict == "needs_update" and res.data.evidence == "18 days"
    body = fake.requests[0]
    assert body["format"] == ImpactVerdict.model_json_schema()
    assert body["options"]["num_ctx"] == s.check_num_ctx
    assert c.prompt_key.startswith("impact-check-v1#")
    assert "OLD:\n18 days" in body["messages"][1]["content"]
    # removed passage: NEW says so; an invalid verdict is retried, then a failure
    bad = c.check_impact("old rule", "", "a candidate", "doc > A")
    assert bad.data is None and bad.attempts == s.max_retries + 1
    assert "(none: the passage was removed)" in fake.requests[1]["messages"][1]["content"]
    # cached by the whole input
    again = c.check_impact("18 days", "25 days", "New hires get 18 days.", "doc > Vacation")
    assert again.cached and again.data.verdict == "needs_update"


def test_openrouter_transport_shapes_the_request_and_reply(tmp_path, monkeypatch):
    """A fake HTTP server stands in for OpenRouter: no real request is made."""
    import io
    import urllib.error
    import urllib.request

    from kg.llm import LLMUnavailable, openrouter_transport

    monkeypatch.setenv("KG_TEST_OR_KEY", "test-key-not-real")
    s = LLMSettings(runtime="openrouter", endpoint="https://example.test/api/v1",
                    model="vendor/model", api_key_env="KG_TEST_OR_KEY",
                    cache_file=tmp_path / "c.sqlite", prompt_file=ROOT / "prompts/mentions_v1.md")
    sent = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        sent["url"], sent["auth"] = req.full_url, req.headers.get("Authorization")
        sent["body"] = json.loads(req.data.decode())
        return Resp(json.dumps({"choices": [{"message": {"content": '{"mentions": []}'}}],
                                "usage": {"prompt_tokens": 12, "completion_tokens": 3}}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = LLMClient(s, root=ROOT, transport=openrouter_transport(s, env_file=None))
    res = c.extract_mentions("text", use_cache=False)
    assert res.data.mentions == [] and (res.tokens_in, res.tokens_out) == (12, 3)
    b = sent["body"]
    assert sent["url"] == "https://example.test/api/v1/chat/completions"
    assert sent["auth"] == "Bearer test-key-not-real"
    assert b["response_format"]["json_schema"]["schema"] == MentionList.model_json_schema()
    assert b["provider"] == {"require_parameters": True, "data_collection": "deny"}
    assert b["reasoning"] == {"enabled": False} and b["model"] == "vendor/model"

    def no_credits(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {},
                                     io.BytesIO(b'{"error": "Insufficient credits"}'))

    monkeypatch.setattr(urllib.request, "urlopen", no_credits)
    with pytest.raises(LLMUnavailable, match="402"):
        c.extract_mentions("other text", use_cache=False)


def test_openrouter_needs_the_key_variable(tmp_path, monkeypatch):
    from kg.config import MissingEnvError
    from kg.llm import openrouter_transport

    monkeypatch.delenv("KG_TEST_OR_MISSING", raising=False)
    s = LLMSettings(runtime="openrouter", api_key_env="KG_TEST_OR_MISSING")
    with pytest.raises(MissingEnvError, match="KG_TEST_OR_MISSING"):
        openrouter_transport(s, env_file=None)
