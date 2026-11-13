from finder.sources import categories


def test_lineage_goes_up_to_root():
    assert categories.lineage(149) == [149, 12, 1]
    assert categories.path(149) == "レディース > ジャケット/アウター > ロングコート"


def test_unknown_and_missing():
    assert categories.lineage(None) == []
    assert categories.lineage(99999999) == [99999999]


def test_learn_unknown_category(tmp_path, monkeypatch):
    from finder import pipeline
    from finder.models import Listing

    monkeypatch.setattr(categories, "LEARNED", tmp_path / "learned.json")
    categories._tree.cache_clear()
    calls = []

    def chain_fn(listing_id):
        calls.append(listing_id)
        return [(3088, "ファッション", 0), (1, "レディース", 3088), (12, "ジャケット/アウター", 1), (99001, "新コート", 12)]

    items = [Listing(f"mercari:m{i}", "s", "t", 1, None, "u", category_id=99001) for i in range(3)]
    pipeline.learn_categories(items, chain_fn=chain_fn, sleep=lambda s: None)

    assert calls == ["mercari:m0"]  # 카테고리당 한 번
    assert categories.lineage(99001) == [99001, 12, 1]  # 이미 아는 1, 12의 부모는 그대로
    pipeline.learn_categories(items, chain_fn=chain_fn, sleep=lambda s: None)
    assert len(calls) == 1
    categories._tree.cache_clear()
