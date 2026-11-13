from finder.store import Store


def test_import_config_and_search_config():
    store = Store(":memory:")
    config = {
        "defaults": {"price_max": 3000, "category_price_max": {12: 7000, 31: 7000},
                     "exclude_categories": [186], "exclude_keywords": ["パジャマ"]},
        "searches": [{"keyword": "ツモリチサト"}, {"keyword": "センソユニコ", "price_max": 5000}],
    }
    assert store.import_config(config) is True
    assert store.import_config(config) is False  # 두 번째는 안 함

    cfg = store.search_config()
    assert cfg["defaults"] == {"price_max": 3000, "category_price_max": {12: 7000, 31: 7000},
                               "exclude_keywords": ["パジャマ"], "exclude_categories": [186]}
    assert cfg["searches"] == [
        {"keyword": "ツモリチサト", "exclude_keywords": []},
        {"keyword": "センソユニコ", "exclude_keywords": [], "price_max": 5000},
    ]


def test_disabled_search_is_skipped():
    store = Store(":memory:")
    store.add_search("a")
    store.add_search("b", enabled=False, outer_price_max=9000)
    assert [s["keyword"] for s in store.search_config()["searches"]] == ["a"]
    assert len(store.searches(enabled_only=False)) == 2


def test_runs():
    store = Store(":memory:")
    run_id = store.start_run()
    store.finish_run(run_id, 10, 2, 1, [])
    row = store.conn.execute("SELECT * FROM runs").fetchone()
    assert row["finished_at"] and row["new"] == 2
