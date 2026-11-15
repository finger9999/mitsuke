"""취향 기준 자동 개선 (설계 문서 6단계).

1. 라벨(👍👎) 매물을 반으로 나눈다: 제안용 / 검증용 (매물 ID로 고정해서 실행마다 같게).
2. 제안용 절반에서 AI와 사용자가 어긋난 매물(높은 점수인데 👎, 낮은 점수인데 👍)을 사진과 함께 Gemini에 보여주고
   취향 기준 글을 고쳐 쓰게 한다.
3. 검증용 절반을 지금 기준과 새 기준으로 각각 채점해 분리도(AUC)를 비교한다.
4. 새 기준이 margin 이상 나을 때만 반영한다. 결과는 기록(settings.taste_history)과 보고서로 남긴다.

검증에 쓰는 매물은 제안을 만들 때 보여주지 않는다. 같은 매물로 고치고 재면 점수가 부풀기 때문이다.
"""

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime

from google import genai
from google.genai import types

from finder import images
from finder.metrics import metrics
from finder.models import Listing
from finder.scorer import DEFAULT_MODEL, PRICES, Scorer
from finder.sources import categories, mercari
from finder.store import Store

log = logging.getLogger(__name__)

PROPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "taste": {"type": "string", "description": "고쳐 쓴 취향 기준 전문"},
        "changes": {"type": "array", "items": {"type": "string"}, "description": "무엇을 왜 바꿨는지, 항목당 한 문장"},
    },
    "required": ["taste", "changes"],
}

PROPOSE_PROMPT = """너는 쇼핑 비서의 채점 기준을 다듬는 역할이다.
채점 AI는 아래 "지금 취향 기준"을 읽고 메루카리 매물에 0~100점을 매긴다.
[알림 받고 싶은 것]에 맞으면 90점 이상(알림), [관심 있는 것]에 맞으면 60~89점이다.

그런데 아래 매물들에서 채점 AI와 사용자의 판단이 어긋났다. 사진과 함께 보고,
사용자가 실제로 무엇을 좋아하고 싫어하는지 디테일 단위(깃, 무늬, 장식, 실루엣, 소재감, 색 조합 등)로 파악해서
취향 기준 글을 고쳐 써라.

지켜야 할 것:
- 형식은 그대로: [알림 받고 싶은 것] / [관심 있는 것] 두 칸. 필요하면 [싫어하는 것] 칸을 추가해도 된다.
- 사용자가 "무조건", "반드시"라고 쓴 조건은 지운다는 강한 근거가 없으면 유지한다.
- 브랜드 이름으로 판단하게 만들지 않는다. 사용자는 디자인만 본다.
- 매물 하나에만 맞춘 규칙(특정 상품명 등)은 쓰지 않는다. 여러 매물에 공통된 경향만 쓴다.
- 한국어로, 지금 글보다 너무 길어지지 않게 (최대 두 배).

지금 취향 기준:
{taste}
"""


@dataclass
class TuneResult:
    current_taste: str
    proposed_taste: str
    changes: list[str]
    before: dict
    after: dict
    accepted: bool
    margin: float
    cost_usd: float
    n_mismatches: int
    notes: list[str] = field(default_factory=list)


def split(listing_id: str) -> str:
    """매물 ID로 정해지는 고정 분할. 실행마다 같은 매물이 같은 쪽에 간다."""
    return "validate" if int(hashlib.sha1(listing_id.encode()).hexdigest(), 16) % 2 else "propose"


def _to_listing(r: dict) -> Listing:
    return Listing(r["id"], r["search"], r["title"], r["price_jpy"], r["image_url"], r["url"],
                   r["created_at"], r["category_id"])


def _mismatches(rows: list[dict], notify_score: int, limit: int = 8) -> list[dict]:
    """높은 점수인데 👎 (점수 높은 순) + 알림 점수에 못 미친 👍 (점수 낮은 순)."""
    false_pos = sorted([r for r in rows if r["feedback"] < 0 and (r["score"] or 0) >= 60],
                       key=lambda r: -r["score"])[:limit]
    missed = sorted([r for r in rows if r["feedback"] > 0 and r["score"] is not None and r["score"] < notify_score],
                    key=lambda r: r["score"])[:limit]
    return false_pos + missed


def propose(client: genai.Client, model: str, taste: str, mismatches: list[dict]) -> tuple[str, list[str], float]:
    contents: list = []
    for i, r in enumerate(mismatches, 1):
        verdict = "👍 좋아함" if r["feedback"] > 0 else "👎 싫어함"
        contents.append(
            f"[매물 {i}] AI {r['score']}점, 사용자 {verdict}\n제목: {r['title']}\n"
            f"카테고리: {categories.path(r['category_id']) or '모름'}\nAI 이유: {r['score_reason'] or '-'}")
        if thumb := images.thumb(r["id"], r["image_url"]):
            contents.append(types.Part.from_bytes(data=thumb[0], mime_type=thumb[1]))
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=PROPOSE_PROMPT.format(taste=taste),
            response_mime_type="application/json",
            response_json_schema=PROPOSE_SCHEMA,
            max_output_tokens=4000,
        ),
    )
    usage = response.usage_metadata
    price_in, price_out = PRICES.get(model, PRICES[DEFAULT_MODEL])
    cost = ((usage.prompt_token_count or 0) * price_in
            + ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) * price_out) / 1_000_000
    data = json.loads(response.text)
    return data["taste"].strip(), [c.strip() for c in data["changes"]], cost


def _score_all(store: Store, key: str, model: str, taste: str, rows: list[dict], interval: float,
               sleep=time.sleep) -> tuple[list[dict], float]:
    scorer = Scorer(taste, key, store.feedback_examples(), model=model,
                    reference_fn=lambda l: store.feedback_references(l.category_id, exclude_id=l.id))
    out, cost = [], 0.0
    for r in rows:
        try:
            result = scorer.score(_to_listing(r), mercari.fetch_description(r["id"]))
        except Exception as e:  # 팔린 매물, 일시 오류는 빼고 잰다
            log.warning("검증 채점 실패 %s: %s", r["id"], str(e)[:100])
        else:
            out.append({"id": r["id"], "feedback": r["feedback"], "score": result.score})
            cost += result.cost_usd
        sleep(interval)
    return out, cost


def tune(store: Store, key: str, options: dict, sample: int = 40, margin: float = 0.03,
         apply: bool = True, sleep=time.sleep) -> TuneResult:
    model = options.get("gemini_model", DEFAULT_MODEL)
    notify_score = options.get("notify_score", 90)
    interval = options.get("llm_min_interval_seconds", 5)
    taste = store.settings()["taste"]
    rows = [dict(r) for r in store.conn.execute("SELECT * FROM listings WHERE feedback IS NOT NULL")]
    propose_rows = [r for r in rows if split(r["id"]) == "propose"]
    validate_rows = [r for r in rows if split(r["id"]) == "validate"]
    notes = []

    mism = _mismatches(propose_rows, notify_score)
    if not mism:
        raise RuntimeError("제안용 매물 중 AI와 어긋난 게 없어 고칠 근거가 없습니다")
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=120_000))
    proposed, changes, cost = propose(client, model, taste, mism)

    # 검증: 👍는 전부, 👎는 무작위로 채워 sample개 (👍가 적어서 다 쓴다)
    likes = [r for r in validate_rows if r["feedback"] > 0]
    dislikes = [r for r in validate_rows if r["feedback"] < 0]
    random.Random(0).shuffle(dislikes)
    target = likes + dislikes[:max(0, sample - len(likes))]
    if len(likes) < 10:
        notes.append(f"검증용 👍가 {len(likes)}개뿐이라 분리도가 크게 흔들린다. 반영 여부는 참고만.")

    before_rows, c1 = _score_all(store, key, model, taste, target, interval, sleep)
    after_rows, c2 = _score_all(store, key, model, proposed, target, interval, sleep)
    before, after = metrics(before_rows, notify_score), metrics(after_rows, notify_score)
    cost += c1 + c2

    accepted = (before["auc"] is not None and after["auc"] is not None and after["auc"] >= before["auc"] + margin)
    history = store.settings().get("taste_history") or []
    history.append({
        "at": datetime.now().isoformat(timespec="minutes"),
        "previous": taste, "proposed": proposed, "changes": changes,
        "auc_before": before["auc"], "auc_after": after["auc"], "accepted": accepted and apply,
    })
    store.set_setting("taste_history", history[-20:])
    if accepted and apply:
        store.set_setting("taste", proposed)
    return TuneResult(taste, proposed, changes, before, after, accepted and apply, margin, cost, len(mism), notes)


def report(r: TuneResult) -> str:
    def row(name, m):
        f = lambda v, pct=False: "-" if v is None else (f"{v:.0%}" if pct else f"{v:.3f}" if v <= 1 else f"{v:.0f}")  # noqa: E731
        return (f"| {name} | {m['n']} | {m['likes']} / {m['dislikes']} | {f(m['auc'])} | {f(m['mean_like'])} | "
                f"{f(m['mean_dislike'])} | {f(m['precision'], True)} | {f(m['recall'], True)} |")

    verdict = "반영함" if r.accepted else f"반영 안 함 (분리도가 {r.margin:+.2f} 이상 오르지 않음)"
    return "\n".join([
        f"# 취향 기준 자동 개선 {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"결과: **{verdict}**. 어긋난 매물 {r.n_mismatches}개로 제안, 검증은 제안에 안 쓴 매물로. "
        f"비용 ${r.cost_usd:.4f} (유료 가격 기준 추정).",
        *[f"\n> {n}" for n in r.notes],
        "",
        "| 기준 | 매물 | 👍 / 👎 | 분리도(AUC) | 👍 평균 | 👎 평균 | 90점 정밀도 | 90점 재현율 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        row("지금 기준", r.before),
        row("제안 기준", r.after),
        "",
        "## 바뀐 점",
        *[f"- {c}" for c in r.changes],
        "",
        "## 제안 기준 전문",
        "",
        "```",
        r.proposed_taste,
        "```",
        "",
    ])
