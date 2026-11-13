"""규칙 필터: 가격·사이즈·제외 키워드."""

import unicodedata
from dataclasses import dataclass, field

from finder.models import Listing


@dataclass
class Rules:
    price_min: int = 0
    price_max: int | None = None
    exclude_keywords: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)  # 비어 있으면 사이즈 검사 안 함


def _norm(text: str) -> str:
    # 전각/반각, 대소문자 차이를 없앤다 (ＸＬ → xl, ｼﾞｬﾝｸ → ジャンク)
    return unicodedata.normalize("NFKC", text).casefold()


def check(listing: Listing, rules: Rules) -> str | None:
    """통과하면 None, 탈락하면 이유를 돌려준다."""
    if listing.price_jpy < rules.price_min:
        return f"가격 ¥{listing.price_jpy:,} < 최저 ¥{rules.price_min:,}"
    if rules.price_max is not None and listing.price_jpy > rules.price_max:
        return f"가격 ¥{listing.price_jpy:,} > 예산 ¥{rules.price_max:,}"

    title = _norm(listing.title)
    for kw in rules.exclude_keywords:
        if _norm(kw) in title:
            return f"제외 키워드: {kw}"

    if rules.sizes and not any(_norm(s) in title for s in rules.sizes):
        return f"사이즈 불일치 (원하는 사이즈: {', '.join(rules.sizes)})"

    return None
