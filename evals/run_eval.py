"""채점 평가: 사용자의 👍👎를 정답으로, 점수가 얼마나 잘 맞는지 잰다.

  python evals/run_eval.py                       DB에 저장된 점수로 바로 측정 (공짜)
  python evals/run_eval.py --fresh               라벨 달린 매물을 지금 설정으로 다시 채점해서 측정
  python evals/run_eval.py --fresh --variants refs,norefs
                                                 참고 사진 비교 채점(refs)과 글 기준만(norefs) 비교

지표
- 분리도(AUC): 무작위로 고른 👍 매물이 무작위로 고른 👎 매물보다 점수가 높을 확률. 0.5 = 동전 던지기, 1.0 = 완벽
- 90점 기준 정밀도: 알림(90점 이상) 중 실제 👍 비율 / 재현율: 👍 중 알림까지 간 비율
- 규칙 탈락 👍: 규칙(예산 등)에서 떨어졌는데 사용자가 👍한 매물. LLM이 아니라 규칙이 놓친 것

결과는 evals/reports/에 마크다운으로 남긴다 (집계 숫자만, 매물 정보 없음).
라벨 스냅샷은 evals/datasets/에 저장한다 (매물 제목이 들어 있어 저장소에는 올리지 않음).
"""

import argparse
import functools
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

import main  # noqa: E402
from finder import scorer as scorer_mod  # noqa: E402
from finder.metrics import auc, metrics  # noqa: E402,F401
from finder.models import Listing  # noqa: E402
from finder.sources import mercari  # noqa: E402
from finder.store import Store  # noqa: E402

# 백그라운드로 돌려 파일로 받을 때도 진행 상황이 바로 보이게
print = functools.partial(print, flush=True)  # noqa: A001

REPORTS = ROOT / "evals" / "reports"
DATASETS = ROOT / "evals" / "datasets"


def labeled(store: Store) -> list[dict]:
    return [dict(r) for r in store.conn.execute(
        "SELECT * FROM listings WHERE feedback IS NOT NULL ORDER BY feedback_at")]


def to_listing(r: dict) -> Listing:
    return Listing(r["id"], r["search"], r["title"], r["price_jpy"], r["image_url"], r["url"],
                   r["created_at"], r["category_id"])


def fresh_scores(store: Store, options: dict, rows: list[dict], variant: str) -> tuple[list[dict], float, int]:
    """라벨 달린 매물을 지금 설정으로 다시 채점한다. DB에는 쓰지 않는다."""
    taste, key = store.settings()["taste"], scorer_mod.api_key()
    if not key or not taste.strip():
        sys.exit("API 키나 취향 기준이 없어 다시 채점할 수 없습니다.")
    refs = options.get("reference_likes", 3), options.get("reference_dislikes", 2)
    reference_fn = None
    if variant == "refs":
        # 자기 자신은 참고 사진에서 뺀다 (정답을 보여주는 셈이라)
        reference_fn = lambda l: store.feedback_references(l.category_id, *refs, exclude_id=l.id)  # noqa: E731
    examples = [] if variant == "norefs" else store.feedback_examples()
    sc = scorer_mod.Scorer(taste, key, examples, model=options.get("gemini_model", scorer_mod.DEFAULT_MODEL),
                           reference_fn=reference_fn)
    interval = options.get("llm_min_interval_seconds", 5)
    out, cost, failed = [], 0.0, 0
    for i, r in enumerate(rows, 1):
        try:
            result = sc.score(to_listing(r), mercari.fetch_description(r["id"]))
        except Exception as e:  # 팔린 매물(403), 일시 오류(503) 등은 빼고 센다
            failed += 1
            print(f"  [{i}/{len(rows)}] 실패 {r['id']}: {str(e)[:80]}")
        else:
            out.append({"id": r["id"], "feedback": r["feedback"], "score": result.score})
            cost += result.cost_usd
            print(f"  [{i}/{len(rows)}] {'👍' if r['feedback'] > 0 else '👎'} {result.score}점")
        time.sleep(interval)
    # 피드백 예시 문장에 자기 자신이 들어 있을 수 있다 (최근 12개). 작은 누수라 보고서에 적어 둔다
    return out, cost, failed


def fmt(v, pct=False):
    if v is None:
        return "-"
    return f"{v:.0%}" if pct else f"{v:.3f}" if isinstance(v, float) and v <= 1 else f"{v:.0f}"


def report(results: dict[str, dict], extra: dict, threshold: int, note: str) -> str:
    lines = [
        f"# 채점 평가 {datetime.now():%Y-%m-%d %H:%M}",
        "",
        note,
        "",
        f"| 방식 | 매물 | 👍 / 👎 | 분리도(AUC) | 👍 평균 | 👎 평균 | {threshold}점 이상 | 정밀도 | 재현율 | 비용(유료 기준) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, m in results.items():
        lines.append(
            f"| {name} | {m['n']} | {m['likes']} / {m['dislikes']} | {fmt(m['auc'])} | {fmt(m['mean_like'])} | "
            f"{fmt(m['mean_dislike'])} | {m['alerts']} | {fmt(m['precision'], True)} | {fmt(m['recall'], True)} | "
            f"{'$%.4f' % m['cost'] if m.get('cost') is not None else '-'} |"
        )
    lines += ["", "| 그 밖에 | 값 |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in extra.items()]
    return "\n".join(lines) + "\n"


def main_(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--fresh", action="store_true", help="라벨 달린 매물을 지금 설정으로 다시 채점")
    ap.add_argument("--variants", default="refs", help="--fresh일 때 비교할 방식: refs, norefs (쉼표로)")
    ap.add_argument("--limit", type=int, default=0, help="--fresh일 때 매물 수 제한 (👍👎 비율 유지하며 무작위)")
    args = ap.parse_args(argv)

    options = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    threshold = options.get("notify_score", 90)
    store = Store(main.DB_PATH)
    rows = labeled(store)

    DATASETS.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M}"
    (DATASETS / f"labels-{stamp}.json").write_text(json.dumps(
        [{k: r[k] for k in ("id", "search", "title", "price_jpy", "category_id", "status", "score", "feedback")}
         for r in rows], ensure_ascii=False, indent=1), encoding="utf-8")

    rule_missed = sum(r["status"] == "filtered" and r["feedback"] > 0 for r in rows)
    extra = {
        "라벨 전체 (👍 / 👎)": f"{sum(r['feedback'] > 0 for r in rows)} / {sum(r['feedback'] < 0 for r in rows)}",
        "규칙에서 탈락했는데 👍": rule_missed,
        "규칙에서 탈락해 점수가 없는 라벨": sum(r["score"] is None for r in rows),
    }

    results = {}
    if not args.fresh:
        scored = [r for r in rows if r["score"] is not None]
        results["저장된 점수"] = metrics(scored, threshold)
        note = ("DB에 저장된 점수로 쟀다. 점수마다 매긴 시점의 설정이 달라 섞여 있고, 일부는 라벨이 달리기 전에 "
                "매겨졌다. 방식 비교는 `--fresh`로 한다.")
    else:
        targets = rows  # LLM 성능은 규칙 통과 여부와 상관없이 전부로 잰다
        if args.limit and len(targets) > args.limit:
            random.seed(0)
            likes = [r for r in targets if r["feedback"] > 0]
            dislikes = [r for r in targets if r["feedback"] < 0]
            k = max(1, round(args.limit * len(likes) / len(targets)))
            targets = random.sample(likes, min(k, len(likes))) + random.sample(dislikes, min(args.limit - k, len(dislikes)))
        for variant in args.variants.split(","):
            print(f"{variant}: {len(targets)}개 채점")
            out, cost, failed = fresh_scores(store, options, targets, variant)
            m = metrics(out, threshold)
            m["cost"] = cost
            results[{"refs": "사진 비교 (refs)", "norefs": "글 기준만 (norefs)"}.get(variant, variant)] = m
            extra[f"{variant} 실패"] = failed
        note = (f"라벨 달린 매물 {len(targets)}개를 지금 설정({options.get('gemini_model')})으로 다시 채점했다. "
                "자기 자신은 참고 사진에서 뺐다. 단, 글로 된 최근 피드백 예시(12개)에 자기 자신이 들어 있을 수 있다. "
                "LLM 응답은 매번 조금씩 달라 같은 설정으로 다시 돌려도 숫자가 흔들린다.")

    text = report(results, extra, threshold, note)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{stamp}{'-fresh' if args.fresh else ''}.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"저장: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main_()
