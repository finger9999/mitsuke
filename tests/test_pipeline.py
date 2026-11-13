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


def test_first_run_only_seeds(monkeypatch):
    store = Store(":memory:")
    stats, sent = run(store, [L(1), L(2)], monkeypatch)
    assert stats.seeded == 2 and sent == []


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


def test_rules_for_merges_defaults():
    rules = pipeline.rules_for(
        {"keyword": "k", "exclude_keywords": ["b"], "category_price_max": {"31": 50000}},
        {"price_max": 30000, "exclude_keywords": ["a"], "category_price_max": {12: 70000}, "exclude_categories": [186]},
    )
    assert rules.price_max == 30000
    assert rules.exclude_keywords == ["a", "b"]
    assert rules.category_price_max == {12: 70000, 31: 50000}
    assert rules.exclude_categories == [186]
