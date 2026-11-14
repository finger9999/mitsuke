"""클라우드 LLM 채점: 사진 + 제목 + 설명 + 취향 기준 → 0~100점과 한 줄 이유.

Google Gemini를 쓴다. 기본 모델은 gemini-3.1-flash-lite (무료 등급이 있고, 유료여도 입력 $0.25 / 출력 $1.50 per 1M).
더 싼 gemini-2.5-flash-lite($0.10 / $0.40)도 config.yaml의 gemini_model로 고를 수 있다.
생각(thinking)은 최소로 둔다. 채점할 매물은 원본 사진, 비교용 👍👎 매물은 썸네일을 보낸다 (docs/devlog/008).

API 키는 환경 변수 GEMINI_API_KEY, 없으면 macOS 키체인(서비스 이름 mitsuke-gemini)에서 읽는다.
launchd로 돌 때는 셸 환경 변수가 없어서 키체인이 필요하다.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass

from google import genai
from google.genai import errors, types

from finder import images
from finder.models import Listing
from finder.sources import categories

log = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.1-flash-lite"
# 유료 등급 기준 달러 / 100만 토큰 (입력, 출력). 무료 등급 안에서는 실제로 청구되지 않는다
PRICES = {
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}
KEYCHAIN_SERVICE = "mitsuke-gemini"

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "0~100"},
        "reason": {"type": "string", "description": "한국어 한 문장"},
    },
    "required": ["score", "reason"],
}

SYSTEM = """너는 일본 메루카리 중고 매물을 사용자의 취향에 맞춰 채점하는 쇼핑 비서다.
매물 사진, 제목, 설명, 카테고리를 보고 이 사용자가 사고 싶어 할 정도를 0~100점으로 매긴다.

옷 취향은 작은 디테일(깃 모양, 무늬의 결, 단추·자수 같은 장식, 실루엣, 소재감, 색 조합)로 갈린다.
사용자가 직접 👍/👎한 매물 사진이 함께 주어지면, 그것이 글로 된 취향 기준보다 정확한 근거다.
채점할 매물을 그 사진들과 디테일 단위로 비교해서, 좋아한 쪽과 싫어한 쪽 중 어디에 가까운지 판단한다.

점수 기준:
- 90~100: 취향 기준의 "알림 받고 싶은 것"에 확실히 맞는다. 사용자에게 바로 알림이 간다.
- 60~89: "관심 있는 것"에 맞는다. 또는 "알림 받고 싶은 것"에 가깝지만 조건을 다 확인할 수 없다.
  관심 있는 것끼리도 취향에 잘 맞을수록 높게 준다 (목록에서 점수순으로 보기 때문).
- 30~59: 브랜드는 맞지만 관심 밖이다.
- 0~29: 검색한 브랜드의 상품이 아니다 (제목에 브랜드명만 언급한 다른 브랜드 상품, 콜라보가 아닌 "~풍" 상품 등).

규칙:
- "알림 받고 싶은 것"에 "무조건"이나 "반드시"로 적힌 조건은 확인될 때만 90점 이상을 준다.
  제목·설명·사진으로 확인할 수 없으면 89점 이하로 주고, 이유에 무엇이 불확실한지 적는다.
- 일본어 소재 표기: ウール·wool·毛·メリノ·ラムウール = 울. カシミヤ(캐시미어)·アンゴラ·モヘア는 울과 다른 동물 섬유다.
- 이유는 한국어 한 문장으로, 점수를 정한 핵심 근거만 쓴다. 참고 사진과 비교했다면 어떤 디테일이 닮았거나 다른지 쓴다.

사용자 취향 기준:
{taste}"""


@dataclass
class Score:
    score: int
    reason: str
    model: str
    cost_usd: float  # 유료 등급 가격으로 계산한 값 (무료 등급이면 실제 청구는 0)


def api_key() -> str | None:
    if key := os.environ.get("GEMINI_API_KEY"):
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
        ai = f"AI {e['score']}점 → " if e.get("score") is not None else ""
        lines.append(f"- {ai}사용자 {mark}: {e['title']} (¥{e['price_jpy']:,})")
    return (
        "\n\n사용자가 최근 직접 평가한 매물. AI 점수와 사용자 평가가 어긋난 경우는 채점이 틀린 것이니, "
        "비슷한 매물을 채점할 때 사용자 평가 쪽으로 맞춘다. 단, 알림 조건의 필수 조건은 그대로 지킨다:\n"
        + "\n".join(lines)
    )


def _part(image: tuple[bytes, str] | None) -> types.Part | None:
    # Gemini는 URL을 직접 못 받아서 바이트로 넘긴다
    return types.Part.from_bytes(data=image[0], mime_type=image[1]) if image else None


def _reference_parts(refs: list[dict]) -> list:
    """👍👎 참고 매물 → [설명 글, 사진, ...]. 사진은 썸네일 (한 장 수십~수백 토큰)."""
    parts: list = []
    for i, r in enumerate(refs, 1):
        mark = "👍 좋아함" if r["feedback"] > 0 else "👎 싫어함"
        ai = f", 그때 AI 점수 {r['score']}점" if r.get("score") is not None else ""
        parts.append(f"[참고 {i}] 사용자 {mark}{ai}: {r['title']} (¥{r['price_jpy']:,}) "
                     f"/ {categories.path(r['category_id']) or '카테고리 모름'}")
        if image := _part(images.thumb(r["id"], r["image_url"])):
            parts.append(image)
    return parts


class Scorer:
    def __init__(self, taste: str, key: str, examples: list[dict] | None = None, model: str = DEFAULT_MODEL,
                 reference_fn=None):
        """reference_fn(listing) → 비교용으로 보여줄 👍👎 매물 목록 (Store.feedback_references)."""
        self.client = genai.Client(api_key=key)
        self.model = model
        self.system = SYSTEM.format(taste=taste.strip()) + _feedback_examples(examples or [])
        self.reference_fn = reference_fn

    def _config(self, thinking: bool) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=self.system,
            response_mime_type="application/json",
            response_json_schema=SCHEMA,
            max_output_tokens=2000,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL) if thinking else None,
        )

    def score(self, listing: Listing, description: str = "") -> Score:
        text = "\n".join([
            f"검색어: {listing.search}",
            f"제목: {listing.title}",
            f"가격: ¥{listing.price_jpy:,}",
            f"카테고리: {categories.path(listing.category_id) or '알 수 없음'}",
            f"설명:\n{description[:2000] or '(없음)'}",
        ])
        refs = self.reference_fn(listing) if self.reference_fn else []
        contents: list = []
        if refs:
            contents.append("사용자가 직접 평가한 비슷한 매물들:")
            contents += _reference_parts(refs)
            contents.append("─── 이제 아래 매물을 채점한다 ───")
        # 채점할 매물은 원본 사진 (디테일이 보이게). 실패하면 썸네일
        if image := _part(images.full(listing.id, listing.image_url)):
            contents.append(image)
        contents.append(text)

        try:
            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=self._config(thinking=True))
        except errors.ClientError as e:
            # 모델에 따라 생각 수준 설정을 안 받을 수 있다. 그때는 설정 없이 한 번 더
            if "thinking" not in str(e).lower():
                raise
            response = self.client.models.generate_content(
                model=self.model, contents=contents, config=self._config(thinking=False))

        usage = response.usage_metadata
        price_in, price_out = PRICES.get(self.model, PRICES[DEFAULT_MODEL])
        out_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        cost = ((usage.prompt_token_count or 0) * price_in + out_tokens * price_out) / 1_000_000
        if not response.text:
            raise RuntimeError(f"빈 응답 (finish_reason: {response.candidates[0].finish_reason if response.candidates else '?'})")
        data = json.loads(response.text)
        return Score(
            score=max(0, min(100, int(data["score"]))),
            reason=str(data["reason"]).strip(),
            model=self.model,
            cost_usd=cost,
        )
