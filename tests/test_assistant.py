"""Advisor agent tests — fake Gemini transport, no network, no LLM cost."""
import assistant


def make_transport(script):
    """Yields scripted Gemini responses in order."""
    responses = iter(script)

    def transport(payload, api_key, model):
        return next(responses)
    return transport


def text_response(text):
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}


def call_response(name, args=None):
    return {"candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": name, "args": args or {}}}]}}]}


def test_plain_text_reply_no_tools():
    reply, history, fx = assistant.chat(
        "what is a micro purchase?", api_key="TEST",
        transport=make_transport([text_response("Buys under $10,000.")]),
    )
    assert "10,000" in reply
    assert fx == {}
    assert history[-1]["parts"][0]["text"] == "Buys under $10,000."


def test_tool_call_executes_and_side_effects_flow(monkeypatch):
    seen_args = {}

    def fake_find(keyword, naics_code=None):
        seen_args["keyword"] = keyword
        return {"summary": {"total": 3}}, {"report": {"fake": True}, "keyword": keyword}

    monkeypatch.setitem(assistant.TOOLS, "find_contracts", fake_find)
    reply, history, fx = assistant.chat(
        "find me glove contracts", api_key="TEST",
        transport=make_transport([
            call_response("find_contracts", {"keyword": "gloves"}),
            text_response("Found 3 leads."),
        ]),
    )
    assert seen_args["keyword"] == "gloves"
    assert fx["report"] == {"fake": True}
    assert "3 leads" in reply
    # tool response was fed back into the conversation
    assert any("functionResponse" in str(m) for m in history)


def test_tool_error_is_relayed_not_raised(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("API down")
    monkeypatch.setitem(assistant.TOOLS, "market_stats", broken)
    reply, _, fx = assistant.chat(
        "market for boots?", api_key="TEST",
        transport=make_transport([
            call_response("market_stats", {"keyword": "boots"}),
            text_response("The market tool failed, sorry."),
        ]),
    )
    assert "failed" in reply.lower()
    assert fx == {}


def test_unknown_tool_handled():
    reply, _, _ = assistant.chat(
        "hello", api_key="TEST",
        transport=make_transport([
            call_response("nonexistent_tool"),
            text_response("Recovered."),
        ]),
    )
    assert reply == "Recovered."


def test_missing_api_key_gives_setup_help(monkeypatch):
    # chat() falls back to config's GOOGLE_API_KEY (loaded from .env); clear it so
    # the test stays offline and actually exercises the missing-key path.
    monkeypatch.setattr(assistant, "GOOGLE_API_KEY", "")
    reply, _, _ = assistant.chat("hi", api_key="")
    assert "GOOGLE_API_KEY" in reply


def test_niche_scan_scoring(monkeypatch):
    import pandas as pd

    def fake_awards(kw, naics, days, limit):
        if kw == "hot niche":  # 10 awards, 9 micro, 2 winners
            return pd.DataFrame({"amount": [500] * 9 + [50000],
                                 "recipient": ["A"] * 5 + ["B"] * 5})
        # crowded niche: 10 awards, 2 micro, 8 winners
        return pd.DataFrame({"amount": [50000] * 8 + [500] * 2,
                             "recipient": list("ABCDEFGH") + ["A", "B"]})

    import analytics
    monkeypatch.setattr(analytics, "fetch_historical_awards", fake_awards)
    result, fx = assistant._tool_discover_niches(["hot niche", "crowded niche"])
    ranked = result["ranked_niches"]
    assert ranked[0]["keyword"] == "hot niche"
    assert ranked[0]["niche_score"] > ranked[1]["niche_score"]
    assert ranked[0]["micro_share_pct"] == 90.0
