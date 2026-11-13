"""메루카리 검색 → 매물 목록.

웹 프론트엔드가 쓰는 검색 API(api.mercari.jp/v2/entities:search)를 그대로 호출한다.
이 API는 요청마다 DPoP 헤더(ES256으로 서명한 JWT)를 요구하는데, 키는 클라이언트가
임의로 만들어도 받아준다. 그래서 실행할 때마다 새 키를 만든다.
"""

import base64
import json
import logging
import time
import uuid

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from finder.models import Listing

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.mercari.jp/v2/entities:search"
CATEGORIES_URL = "https://api.mercari.jp/services/master/v1/itemCategories"
ITEM_DETAIL_URL = "https://api.mercari.jp/items/get"
ITEM_URL = "https://jp.mercari.com/item/{id}"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class _DPoP:
    def __init__(self):
        self._key = ec.generate_private_key(ec.SECP256R1())
        nums = self._key.public_key().public_numbers()
        self._jwk = {
            "crv": "P-256",
            "kty": "EC",
            "x": _b64(nums.x.to_bytes(32, "big")),
            "y": _b64(nums.y.to_bytes(32, "big")),
        }

    def token(self, url: str, method: str) -> str:
        header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": self._jwk}
        payload = {
            "iat": int(time.time()),
            "jti": str(uuid.uuid4()),
            "htu": url,
            "htm": method,
            "uuid": str(uuid.uuid4()),
        }
        signing_input = ".".join(
            _b64(json.dumps(part, separators=(",", ":")).encode()) for part in (header, payload)
        )
        r, s = decode_dss_signature(self._key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
        return signing_input + "." + _b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _search_body(keyword: str, page_size: int) -> dict:
    return {
        "userId": "",
        "pageSize": page_size,
        "pageToken": "",
        "searchSessionId": uuid.uuid4().hex,
        "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
        "thumbnailTypes": [],
        "searchCondition": {
            "keyword": keyword,
            "excludeKeyword": "",
            "sort": "SORT_CREATED_TIME",
            "order": "ORDER_DESC",
            "status": ["STATUS_ON_SALE"],
            "sizeId": [],
            "categoryId": [],
            "brandId": [],
            "sellerId": [],
            "priceMin": 0,
            "priceMax": 0,
            "itemConditionId": [],
            "shippingPayerId": [],
            "shippingFromArea": [],
            "shippingMethod": [],
            "colorId": [],
            "hasCoupon": False,
            "attributes": [],
            "itemTypes": [],
            "skuIds": [],
        },
        "defaultDatasets": ["DATASET_TYPE_MERCARI", "DATASET_TYPE_BEYOND"],
        "serviceFrom": "suruga",
        "withItemBrand": True,
        "withItemSize": False,
        "withItemPromotions": True,
        "withItemSizes": True,
        "withShopname": False,
    }


def parse_items(data: dict, search: str) -> list[Listing]:
    """검색 응답 JSON → Listing 목록.

    메루카리 Shops 상품(ITEM_TYPE_BEYOND)은 ID 체계가 달라 Buyee 링크를 만들 수 없으므로 뺀다.
    """
    listings = []
    for item in data.get("items", []):
        if item.get("itemType", "ITEM_TYPE_MERCARI") != "ITEM_TYPE_MERCARI":
            continue
        if item.get("status") not in (None, "ITEM_STATUS_ON_SALE"):
            continue
        item_id = item["id"]
        thumbs = item.get("thumbnails") or []
        created = item.get("created")
        category = item.get("categoryId")
        listings.append(
            Listing(
                id=f"mercari:{item_id}",
                search=search,
                title=item.get("name", ""),
                price_jpy=int(item.get("price", 0)),
                image_url=thumbs[0] if thumbs else None,
                url=ITEM_URL.format(id=item_id),
                created_at=int(created) if created else None,
                category_id=int(category) if category else None,
            )
        )
    return listings


def search(keyword: str, page_size: int = 60, client: httpx.Client | None = None) -> list[Listing]:
    """키워드로 판매 중인 매물을 최신순으로 가져온다."""
    dpop = _DPoP()
    headers = {
        "DPoP": dpop.token(SEARCH_URL, "POST"),
        "X-Platform": "web",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    own_client = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.post(SEARCH_URL, json=_search_body(keyword, page_size), headers=headers)
        resp.raise_for_status()
        listings = parse_items(resp.json(), keyword)
    finally:
        if own_client:
            client.close()
    if not listings:
        log.warning("메루카리 검색 결과 0개: %r (페이지 구조가 바뀌었을 수 있음)", keyword)
    return listings


def fetch_categories() -> dict[str, list]:
    """카테고리 목록 → {id: [이름, 부모 id]}. categories.py의 스냅샷을 새로 만들 때 쓴다."""
    headers = {
        "DPoP": _DPoP().token(CATEGORIES_URL, "GET"),
        "X-Platform": "web",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    resp = httpx.get(CATEGORIES_URL, headers=headers, timeout=20)
    resp.raise_for_status()
    return {c["id"]: [c["name"], c["parentId"]] for c in resp.json()["categories"]}


def fetch_category_chain(item_id: str) -> list[tuple[int, str, int]]:
    """매물 상세에서 카테고리 경로를 읽는다 → [(id, 이름, 부모 id), ...] (위 → 아래).

    카테고리 목록 API에는 새 다단계 카테고리(예: 1426 半袖)가 빠져 있어서,
    모르는 카테고리가 나오면 그 카테고리의 매물 하나로 경로를 알아낸다.
    """
    headers = {
        "DPoP": _DPoP().token(ITEM_DETAIL_URL, "GET"),
        "X-Platform": "web",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    resp = httpx.get(ITEM_DETAIL_URL, params={"id": item_id.removeprefix("mercari:")}, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()["data"]
    nodes = [(int(c["id"]), c["name"]) for c in data.get("parent_categories_ntiers", [])]
    leaf = data["item_category_ntiers"]
    nodes.append((int(leaf["id"]), leaf["name"]))
    return [(cid, name, nodes[i - 1][0] if i else 0) for i, (cid, name) in enumerate(nodes)]
