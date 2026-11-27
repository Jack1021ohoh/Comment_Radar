"""The sentiment seam without downloading a model: fake pipelines stand in for the transformers."""

from radar_mcp import sentiment


def fake_pipe(label):
    calls = []

    def pipe(texts, batch_size):
        calls.append(list(texts))
        return [[{"label": label, "score": 0.9}, {"label": "neutral", "score": 0.1}] for _ in texts]

    pipe.calls = calls
    return pipe


def test_non_latin():
    assert sentiment.non_latin("а тебе какое дело?")
    assert sentiment.non_latin("一推左謬留言")
    assert not sentiment.non_latin("café is great 😂😂😂")
    assert not sentiment.non_latin("😂😂😂")
    assert not sentiment.non_latin("Thanks Trump! Спасибо")  # mostly Latin


def test_routed_sends_non_latin_to_the_multilingual_model(monkeypatch):
    main, multi = fake_pipe("positive"), fake_pipe("negative")
    monkeypatch.setenv("SENTIMENT_BACKEND", "routed")
    monkeypatch.setattr(sentiment, "_classifier", ("routed", (main, multi)))
    out = sentiment.classify(["Great video", "а тебе какое дело?", "Great video"])
    assert [r["label"] for r in out] == ["positive", "negative", "positive"]
    assert main.calls == [["Great video"]] and multi.calls == [["а тебе какое дело?"]]
    assert "+" in sentiment.model_name()


def test_routed_skips_a_model_with_nothing_to_do(monkeypatch):
    main, multi = fake_pipe("positive"), fake_pipe("negative")
    monkeypatch.setattr(sentiment, "_classifier", ("routed", (main, multi)))
    assert sentiment.classify(["only English here"])[0]["label"] == "positive"
    assert multi.calls == []
