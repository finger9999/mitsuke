"""규칙 필터: 가격·카테고리·사이즈·제외 키워드."""

import unicodedata
from dataclasses import dataclass, field

from finder.models import Listing
from finder.sources import categories


@dataclass
class Rules:
    price_min: int = 0
    price_max: int | None = None
    # 카테고리별 예산. 위 단계 카테고리(예: 12 레디스 아우터)를 적으면 그 아래 전부에 적용된다
    category_price_max: dict[int, int] = field(default_factory=dict)
    exclude_categories: list[int] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)  # 비어 있으면 사이즈 검사 안 함


def _norm(text: str) -> str:
    # 전각/반각, 대소문자 차이를 없앤다 (ＸＬ → xl, ｼﾞｬﾝｸ → ジャンク)
    return unicodedata.normalize("NFKC", text).casefold()


def budget(listing: Listing, rules: Rules) -> int | None:
    """이 매물에 적용할 예산. 가장 구체적인(아래 단계) 카테고리 규칙이 이긴다."""
    for cat in categories.lineage(listing.category_id):
        if cat in rules.category_price_max:
            return rules.category_price_max[cat]
    return rules.price_max


def check(listing: Listing, rules: Rules) -> str | None:
    """통과하면 None, 탈락하면 이유를 돌려준다."""
    lineage = categories.lineage(listing.category_id)
    for cat in rules.exclude_categories:
        if cat in lineage:
            return f"제외 카테고리: {categories.name(cat)}"

    if listing.price_jpy < rules.price_min:
        return f"가격 ¥{listing.price_jpy:,} < 최저 ¥{rules.price_min:,}"
    limit = budget(listing, rules)
    if limit is not None and listing.price_jpy > limit:
        return f"가격 ¥{listing.price_jpy:,} > 예산 ¥{limit:,}"

    title = _norm(listing.title)
    for kw in rules.exclude_keywords:
        if _norm(kw) in title:
            return f"제외 키워드: {kw}"

    if rules.sizes and not any(_norm(s) in title for s in rules.sizes):
        return f"사이즈 불일치 (원하는 사이즈: {', '.join(rules.sizes)})"

    return None
