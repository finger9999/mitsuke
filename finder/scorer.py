"""클라우드 LLM 채점: 사진 + 제목 + 설명 + 취향 기준 → 0~100점과 한 줄 이유.

가장 싼 Claude 모델(Haiku 5.5)을 쓴다. 비용을 줄이려고 effort는 low, 사진은 썸네일 한 장만 보낸다.
API 키는 환경 변수 ANTHROPIC_API_KEY, 없으면 macOS 키체인(서비스 이름 mitsuke-anthropic)에서 읽는다.
launchd로 돌 때는 셸 환경 변수가 없어서 키체인이 필요하다.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass

import anthropic

from finder.models import Listing
from finder.sources import categories

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
# 달러 / 토큰 (프롬프트 10만 토큰 이하 기준)
PRICE_IN = 0.10 / 1_000_000
PRICE_OUT = 0.50 / 1_000_000
KEYCHAIN_SERVICE = "mitsuke-anthropic"

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "0~100"},
        "reason": {"type": "string", "description": "한국어 한 문장"},
    },
    "required": ["score", "reason"],
    "additionalProperties": False,
}

SYSTEM = """너는 일본 메루카리 중고 매물을 사용자의 취향에 맞춰 채점하는 쇼핑 비서다.
매물 사진 한 장, 제목, 설명, 카테고리를 보고 이 사용자가 사고 싶어 할 정도를 0~100점으로 매긴다.

점수 기준:
- 90~100: 지금 찾고 있는 조건에 확실히 맞는다. 알림을 보낼 만하다.
- 60~89: 취향에는 맞지만 지금 찾는 조건이 아니거나, 맞는지 확신할 수 없다.
- 30~59: 브랜드는 맞지만 관심 밖이다.
- 0~29: 검색한 브랜드의 상품이 아니다 (제목에 브랜드명만 언급한 다른 브랜드 상품, 콜라보가 아닌 "~풍" 상품 등).

규칙:
- 사용자 취향 기준에 "무조건"이나 "반드시"로 적힌 조건은 확인될 때만 90점 이상을 준다.
  제목·설명·사진으로 확인할 수 없으면 89점 이하로 주고, 이유에 무엇이 불확실한지 적는다.
- 일본어 소재 표기: ウール·wool·毛·メリノ·ラムウール = 울. カシミヤ(캐시미어)·アンゴラ·モヘア는 울과 다른 동물 섬유다.
- 이유는 한국어 한 문장으로, 점수를 정한 핵심 근거만 쓴다.

사용자 취향 기준:
{taste}"""


@dataclass
class Score:
    score: int
    reason: str
    model: str
    cost_usd: float


def api_key() -> str | None:
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return key
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _feedback_examples(examples: list[dict]) -> str:
    if not examples:
        return ""
    lines = []
    for e in examples:
        mark = "👍 좋아함" if e["feedback"] > 0 else "👎 싫어함"
        lines.append(f"- {mark}: {e['title']} (¥{e['price_jpy']:,})")
    return "\n\n사용자가 최근 직접 평가한 매물 (참고용):\n" + "\n".join(lines)


class Scorer:
    def __init__(self, taste: str, key: str, examples: list[dict] | None = None):
        self.client = anthropic.Anthropic(api_key=key, max_retries=2, timeout=60)
        self.system = SYSTEM.format(taste=taste.strip()) + _feedback_examples(examples or [])

    def score(self, listing: Listing, description: str = "") -> Score:
        text = "\n".join([
            f"검색어: {listing.search}",
            f"제목: {listing.title}",
            f"가격: ¥{listing.price_jpy:,}",
            f"카테고리: {categories.path(listing.category_id) or '알 수 없음'}",
            f"설명:\n{description[:2000] or '(없음)'}",
        ])
        content = [{"type": "text", "text": text}]
        if listing.image_url:
            content.insert(0, {"type": "image", "source": {"type": "url", "url": listing.image_url}})

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=self.system,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
        cost = response.usage.input_tokens * PRICE_IN + response.usage.output_tokens * PRICE_OUT
        if response.stop_reason == "refusal":
            raise RuntimeError("모델이 채점을 거절함")
        data = json.loads(next(b.text for b in response.content if b.type == "text"))
        return Score(
            score=max(0, min(100, int(data["score"]))),
            reason=data["reason"].strip(),
            model=MODEL,
            cost_usd=cost,
        )
