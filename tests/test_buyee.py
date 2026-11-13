import pytest

from finder.checkout import buyee


def test_item_url():
    assert buyee.item_url("mercari:m123") == "https://buyee.jp/mercari/item/m123"
    assert buyee.item_url("m123") == "https://buyee.jp/mercari/item/m123"


def test_rejects_other_sources():
    with pytest.raises(ValueError):
        buyee.item_url("rakuma:abc")
