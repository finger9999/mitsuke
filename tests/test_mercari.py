import json
from pathlib import Path

from finder.sources import mercari

FIXTURE = Path(__file__).parent / "fixtures" / "mercari_search.json"


def load():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_items_basic_fields():
    listings = mercari.parse_items(load(), "ツモリチサト")
    assert listings, "픽스처에서 매물을 하나도 못 읽음"
    for l in listings:
        assert l.id.startswith("mercari:m")
        assert l.search == "ツモリチサト"
        assert l.category_id
        assert l.title
        assert l.price_jpy > 0
        assert l.url == f"https://jp.mercari.com/item/{l.id.removeprefix('mercari:')}"
        assert l.image_url and l.image_url.startswith("https://")


def test_parse_items_skips_shops():
    data = load()
    data["items"].append({"id": "2JZWMQEReMQqWsmEKeUhog", "name": "shop", "price": "100", "itemType": "ITEM_TYPE_BEYOND"})
    shops = [i for i in data["items"] if i["itemType"] != "ITEM_TYPE_MERCARI"]
    listings = mercari.parse_items(data, "x")
    assert len(listings) == len(data["items"]) - len(shops)


def test_parse_items_skips_sold():
    data = {"items": [{"id": "m1", "name": "a", "price": "100", "status": "ITEM_STATUS_SOLD_OUT"}]}
    assert mercari.parse_items(data, "x") == []


def test_parse_empty_response():
    assert mercari.parse_items({}, "x") == []


def test_dpop_token_shape():
    token = mercari._DPoP().token(mercari.SEARCH_URL, "POST")
    assert token.count(".") == 2
