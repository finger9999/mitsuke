"""미츠케 CLI.

  python main.py run [--no-notify]   파이프라인 한 번 실행 (launchd가 1시간마다 부름)
  python main.py recent [-n 20] [--all]   최근 매물 보기
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from finder import pipeline
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
    config = load_config(args.config)
    store = Store(DB_PATH)
    try:
        stats = pipeline.run(config, store, notify=not args.no_notify)
    finally:
        store.close()
    logging.info(
        "완료: 가져옴 %d, 신규 %d, 기준점 %d, 탈락 %d, 알림 %d, 오류 %d",
        stats.fetched, stats.new, stats.seeded, stats.filtered, stats.notified, len(stats.errors),
    )
    return 1 if stats.errors and stats.fetched == 0 else 0


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
        line = f"{seen}  [{r['status']:<8}] ¥{r['price_jpy']:>7,}  {r['title'][:50]}"
        print(line)
        if r["filter_reason"]:
            print(f"{'':16}탈락: {r['filter_reason']}")
        print(f"{'':16}{r['buyee_url'] or r['url']}")
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

    args = parser.parse_args(argv)
    setup_logging()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
