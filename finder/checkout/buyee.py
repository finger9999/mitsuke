"""메루카리 ID → Buyee 구매 URL."""

BUYEE_ITEM_URL = "https://buyee.jp/mercari/item/{item_id}"


def item_url(listing_id: str) -> str:
    """'mercari:m123' 또는 'm123' → Buyee 상품 페이지."""
    source, _, item_id = listing_id.rpartition(":")
    if source not in ("", "mercari"):
        raise ValueError(f"Buyee 메루카리 링크를 만들 수 없는 매물: {listing_id}")
    return BUYEE_ITEM_URL.format(item_id=item_id)
