from dataclasses import dataclass


@dataclass
class Listing:
    id: str  # "mercari:m123..."
    search: str
    title: str
    price_jpy: int
    image_url: str | None
    url: str
    created_at: int | None = None  # 판매자가 올린 시각 (unix)
    category_id: int | None = None  # 메루카리 카테고리 (가장 아래 단계)
