"""미츠케 CLI.

  python main.py run [--no-notify]   파이프라인 한 번 실행 (launchd가 1시간마다 부름)
  python main.py recent [-n 20] [--all]   최근 매물 보기
  python main.py update-categories   메루카리 카테고리 스냅샷 새로 받기
  python main.py reevaluate   평가 없이 저장된 기준점·점수 없는 매물 다시 평가 (알림 없음)
  python main.py like|dislike|unrate <매물 ID>   피드백 기록 (m123... 또는 mercari:m123...)
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from finder import pipeline, scorer
from finder.sources import categories, mercari
from finder.store import Store

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "mitsuke.db"
LOG_PATH = ROOT / "logs" / "mitsuke.log"


def setup_logging():
    LOG_PATH.parent.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cmd_run(args):
    options = load_config(args.config)
    store = Store(DB_PATH)
    try:
        if store.import_config(options):
            logging.info("config.yaml의 검색어·설정을 DB로 옮겼습니다. 이제 맥 앱에서 편집하세요")
        # 검색어·예산은 DB(맥 앱에서 편집), 요청 간격 같은 동작 설정은 config.yaml
        config = options | store.search_config()
        run_id = store.start_run()
        stats = pipeline.run(config, store, notify=not args.no_notify, scorer=make_scorer(store, options))
        store.finish_run(run_id, stats.fetched, stats.new, stats.notified, stats.errors, stats.scored, stats.cost_usd)
    finally:
        store.close()
    logging.info(
        "완료: 가져옴 %d, 신규 %d, 기준점 %d, 탈락 %d, 채점 %d ($%.4f), 알림 %d, 오류 %d",
        stats.fetched, stats.new, stats.seeded, stats.filtered, stats.scored, stats.cost_usd, stats.notified,
        len(stats.errors),
    )
    return 1 if stats.errors and stats.fetched == 0 else 0


def make_scorer(store: Store, options: dict):
    """API 키와 취향 기준이 둘 다 있을 때만 채점한다. 없으면 규칙 통과 매물을 모두 알림 (0단계 방식)."""
    taste = store.settings()["taste"]
    key = scorer.api_key()
    if not key:
        logging.warning("API 키가 없어 채점 없이 실행 (키체인 %s 또는 GEMINI_API_KEY)", scorer.KEYCHAIN_SERVICE)
        return None
    if not taste.strip():
        logging.warning("취향 기준이 비어 있어 채점 없이 실행 (맥 앱 설정에서 입력)")
        return None
    return scorer.Scorer(taste, key, store.feedback_examples(), model=options.get("gemini_model", scorer.DEFAULT_MODEL))


def cmd_reevaluate(args):
    options = load_config(args.config)
    store = Store(DB_PATH)
    try:
        config = options | store.search_config()
        stats = pipeline.reevaluate(config, store, scorer=make_scorer(store, options), llm_limit=args.limit)
    finally:
        store.close()
    print(f"다시 평가: {stats.new}개 → 탈락 {stats.filtered}, 채점 {stats.scored} (${stats.cost_usd:.4f}), "
          f"나머지 통과 {stats.new - stats.filtered - stats.scored}")
    return 0


def cmd_feedback(args):
    value = {"like": 1, "dislike": -1, "unrate": None}[args.cmd]
    listing_id = args.id if args.id.startswith("mercari:") else f"mercari:{args.id}"
    store = Store(DB_PATH)
    try:
        ok = store.set_feedback(listing_id, value)
    finally:
        store.close()
    print("기록했습니다." if ok else f"DB에 없는 매물: {listing_id}")
    return 0 if ok else 1


def cmd_recent(args):
    store = Store(DB_PATH)
    try:
        rows = store.recent(args.n, include_filtered=args.all)
    finally:
        store.close()
    if not rows:
        print("아직 매물이 없습니다.")
        return 0
    for r in rows:
        seen = datetime.fromtimestamp(r["first_seen"]).strftime("%m-%d %H:%M")
        score = f"{r['score']:>3}점" if r["score"] is not None else "  - "
        mark = {1: "👍", -1: "👎"}.get(r["feedback"], "  ")
        line = f"{seen}  [{r['status']:<8}] {score} {mark} ¥{r['price_jpy']:>7,}  {r['title'][:50]}"
        print(line)
        if r["score_reason"]:
            print(f"{'':16}{r['score_reason']}")
        if r["category_id"]:
            print(f"{'':16}{categories.path(r['category_id'])}")
        if r["filter_reason"]:
            print(f"{'':16}탈락: {r['filter_reason']}")
        print(f"{'':16}{r['buyee_url'] or r['url']}")
    return 0


def cmd_update_categories(args):
    tree = mercari.fetch_categories()
    categories.save_snapshot(tree)
    print(f"카테고리 {len(tree)}개 저장: {categories.SNAPSHOT}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mitsuke")
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="파이프라인 한 번 실행")
    p_run.add_argument("--no-notify", action="store_true", help="알림 없이 저장만")
    p_run.set_defaults(func=cmd_run)

    p_recent = sub.add_parser("recent", help="최근 매물 보기")
    p_recent.add_argument("-n", type=int, default=20)
    p_recent.add_argument("--all", action="store_true", help="기준점·탈락 매물도 보기")
    p_recent.set_defaults(func=cmd_recent)

    p_cats = sub.add_parser("update-categories", help="메루카리 카테고리 스냅샷 새로 받기")
    p_cats.set_defaults(func=cmd_update_categories)

    p_re = sub.add_parser("reevaluate", help="기준점·점수 없는 매물 다시 평가 (알림 없음)")
    p_re.add_argument("--limit", type=int, default=100, help="이번에 채점할 최대 매물 수 (기본 100)")
    p_re.set_defaults(func=cmd_reevaluate)

    for name, help_ in (("like", "👍 기록"), ("dislike", "👎 기록"), ("unrate", "피드백 지우기")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("id", help="매물 ID (m123... 또는 mercari:m123...)")
        p.set_defaults(func=cmd_feedback)

    args = parser.parse_args(argv)
    setup_logging()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
