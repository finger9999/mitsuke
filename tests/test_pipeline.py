from finder import notifier, pipeline
from finder.models import Listing
from finder.store import Store


def L(n, title="PORTER タンカー", price=10000, search="s"):
    return Listing(id=f"mercari:m{n}", search=search, title=title, price_jpy=price, image_url=None, url=f"u{n}")


CONFIG = {"searches": [{"keyword": "s", "price_max": 20000}], "defaults": {"exclude_keywords": ["ジャンク"]}}


def run(store, results, monkeypatch):
    sent = []
    monkeypatch.setattr(notifier, "notify", lambda l, url: sent.append((l.id, url)) or True)
    stats = pipeline.run(CONFIG, store, search_fn=lambda kw, page_size: results, sleep=lambda s: None)
    return stats, sent


def test_first_run_evaluates_without_notifying(monkeypatch):
    store = Store(":memory:")
    stats, sent = run(store, [L(1), L(2, price=50000)], monkeypatch)
    assert stats.seeded == 2 and sent == []
    rows = {r["id"]: r["status"] for r in store.recent(10, include_filtered=True)}
    assert rows == {"mercari:m1": "passed", "mercari:m2": "filtered"}


def test_second_run_notifies_new_passing(monkeypatch):
    store = Store(":memory:")
    run(store, [L(1)], monkeypatch)
    stats, sent = run(store, [L(4, price=50000), L(3, title="ジャンク"), L(2), L(1)], monkeypatch)
    assert stats.new == 3
    assert stats.filtered == 2
    assert sent == [("mercari:m2", "https://buyee.jp/mercari/item/m2")]
    rows = {r["id"]: r for r in store.recent(10, include_filtered=True)}
    assert rows["mercari:m2"]["status"] == "notified"
    assert "예산" in rows["mercari:m4"]["filter_reason"]


def test_search_error_does_not_stop_run(monkeypatch):
    store = Store(":memory:")
    config = {"searches": [{"keyword": "bad"}, {"keyword": "good"}]}

    def search_fn(kw, page_size):
        if kw == "bad":
            raise RuntimeError("boom")
        return [L(1, search=kw)]

    stats = pipeline.run(config, store, notify=False, search_fn=search_fn, sleep=lambda s: None)
    assert len(stats.errors) == 1 and stats.seeded == 1


def test_reevaluate_seeded_keeps_first_seen_and_feedback(monkeypatch):
    store = Store(":memory:")
    store.add(L(1), status="seeded")
    store.add(L(2, price=50000), status="seeded")
    store.conn.execute("UPDATE listings SET first_seen = 100")
    store.set_feedback("mercari:m1", 1)
    scorer = FakeScorer({"mercari:m1": 95})
    sent = []
    monkeypatch.setattr(notifier, "notify", lambda *a: sent.append(a) or True)
    stats = pipeline.reevaluate(CONFIG, store, scorer=scorer, describe_fn=lambda i: "", sleep=lambda s: None)
    rows = {r["id"]: r for r in store.recent(10, include_filtered=True)}
    assert rows["mercari:m1"]["status"] == "scored" and rows["mercari:m1"]["score"] == 95
    assert rows["mercari:m1"]["first_seen"] == 100 and rows["mercari:m1"]["feedback"] == 1
    assert rows["mercari:m2"]["status"] == "filtered"
    assert sent == [] and stats.scored == 1


def test_rules_for_merges_defaults():
    rules = pipeline.rules_for(
        {"keyword": "k", "exclude_keywords": ["b"], "category_price_max": {"31": 50000}},
        {"price_max": 30000, "exclude_keywords": ["a"], "category_price_max": {12: 70000}, "exclude_categories": [186]},
    )
    assert rules.price_max == 30000
    assert rules.exclude_keywords == ["a", "b"]
    assert rules.category_price_max == {12: 70000, 31: 50000}
    assert rules.exclude_categories == [186]


class FakeScorer:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def score(self, listing, description=""):
        from finder.scorer import Score
        self.calls.append(listing.id)
        return Score(self.scores.get(listing.id, 50), "이유", "fake", 0.001)


def scored_run(store, results, scorer, monkeypatch, config_extra=None):
    sent = []
    monkeypatch.setattr(notifier, "notify", lambda l, url, *a: sent.append(l.id) or True)
    config = CONFIG | (config_extra or {})
    stats = pipeline.run(config, store, search_fn=lambda kw, page_size: results, sleep=lambda s: None,
                         scorer=scorer, describe_fn=lambda i: "")
    return stats, sent


def test_only_high_scores_notify(monkeypatch):
    store = Store(":memory:")
    scored_run(store, [L(1)], FakeScorer({}), monkeypatch)  # 기준점
    scorer = FakeScorer({"mercari:m2": 95, "mercari:m3": 60})
    stats, sent = scored_run(store, [L(3), L(2), L(1)], scorer, monkeypatch)
    assert sent == ["mercari:m2"]
    rows = {r["id"]: r for r in store.recent(10)}
    assert rows["mercari:m2"]["status"] == "notified" and rows["mercari:m2"]["score"] == 95
    assert rows["mercari:m3"]["status"] == "scored"
    assert stats.scored == 2


def test_llm_limit_and_score_categories(monkeypatch):
    store = Store(":memory:")
    scored_run(store, [L(1)], FakeScorer({}), monkeypatch)
    coat = L(2)
    coat.category_id = 149  # 아우터
    shirt = L(3)
    shirt.category_id = 122  # 상의
    coat2 = L(4)
    coat2.category_id = 149
    scorer = FakeScorer({})
    stats, _ = scored_run(store, [coat2, shirt, coat, L(1)], scorer, monkeypatch,
                          {"score_categories": [12, 31], "llm_calls_per_run": 1})
    assert scorer.calls == ["mercari:m2"]  # 상의는 채점 안 함, 두 번째 코트는 상한
    rows = {r["id"]: r for r in store.recent(10)}
    assert rows["mercari:m3"]["status"] == "passed" and rows["mercari:m3"]["score_reason"] is None
    assert "상한" in rows["mercari:m4"]["score_reason"]


def test_scorer_failure_still_lists(monkeypatch):
    store = Store(":memory:")
    scored_run(store, [L(1)], FakeScorer({}), monkeypatch)

    class Broken:
        def score(self, listing, description=""):
            raise RuntimeError("API down")

    stats, sent = scored_run(store, [L(2), L(1)], Broken(), monkeypatch)
    row = store.recent(1)[0]
    assert row["status"] == "passed" and "채점 실패" in row["score_reason"] and sent == []


def test_billing_error_halts_scoring(monkeypatch):
    store = Store(":memory:")
    scored_run(store, [L(1)], FakeScorer({}), monkeypatch)

    class NoCredit(Exception):
        code = 402

    class Broke:
        calls = 0

        def score(self, listing, description=""):
            Broke.calls += 1
            raise NoCredit("credits depleted")

    scored_run(store, [L(4), L(3), L(2), L(1)], Broke(), monkeypatch)
    assert Broke.calls == 1  # 첫 실패 뒤로는 호출하지 않음
    reasons = {r["id"]: r["score_reason"] for r in store.recent(10)}
    assert "선불 크레딧" in reasons["mercari:m2"] and "채점 중단" in reasons["mercari:m4"]


def test_retry_unscored_from_previous_run(monkeypatch):
    store = Store(":memory:")
    scored_run(store, [L(1)], FakeScorer({}), monkeypatch)  # 첫 실행 (기준점)
    # 상한 1: m2만 채점되고 m3은 점수 없이 남는다
    scored_run(store, [L(3), L(2), L(1)], FakeScorer({}), monkeypatch, {"llm_calls_per_run": 1})
    unscored = [l.id for l, _ in store.listings_to_retry()]
    assert unscored == ["mercari:m3"]
    # 다음 실행: 새 매물은 없고, 남은 m3를 다시 채점해서 95점이면 알림
    scorer = FakeScorer({"mercari:m3": 95})
    stats, sent = scored_run(store, [L(3), L(2), L(1)], scorer, monkeypatch)
    assert scorer.calls == ["mercari:m3"] and sent == ["mercari:m3"]
    assert store.listings_to_retry() == []


def test_retry_baseline_does_not_notify(monkeypatch):
    store = Store(":memory:")
    # 첫 실행에서 상한에 걸려 점수 없이 남은 기준점 매물
    scored_run(store, [L(2), L(1)], FakeScorer({}), monkeypatch, {"llm_calls_per_run": 1})
    assert [b for _, b in store.listings_to_retry()] == [True]
    scorer = FakeScorer({"mercari:m2": 95, "mercari:m1": 95})
    stats, sent = scored_run(store, [L(2), L(1)], scorer, monkeypatch)
    assert len(scorer.calls) == 1 and sent == []
