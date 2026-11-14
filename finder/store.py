"""SQLite 읽기·쓰기. Python 파이프라인과 맥 앱(Swift)의 유일한 연결고리.

검색어와 예산 설정도 여기 있다. 맥 앱이 쓰고 파이프라인이 읽는다.
"""

import json
import sqlite3
import time
from pathlib import Path

from finder.models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id             TEXT PRIMARY KEY,          -- mercari:m123...
    search         TEXT NOT NULL,
    title          TEXT NOT NULL,
    price_jpy      INTEGER NOT NULL,
    image_url      TEXT,
    url            TEXT NOT NULL,
    created_at     INTEGER,                   -- 판매자가 올린 시각
    category_id    INTEGER,                   -- 메루카리 카테고리 (가장 아래 단계)
    first_seen     INTEGER NOT NULL,          -- 미츠케가 처음 본 시각
    status         TEXT NOT NULL,             -- seeded / filtered / passed / scored / notified
    filter_reason  TEXT,
    similarity     REAL,
    score          INTEGER,
    score_reason   TEXT,
    score_model    TEXT,
    score_cost_usd REAL,
    buyee_url      TEXT,
    est_total_krw  INTEGER,
    feedback       INTEGER,                   -- 1 = 👍, -1 = 👎, NULL = 없음
    feedback_at    INTEGER,
    baseline       INTEGER NOT NULL DEFAULT 0 -- 검색어 첫 실행 때 이미 있던 매물 (알림 안 보냄)
);
CREATE INDEX IF NOT EXISTS idx_listings_search ON listings(search);
CREATE INDEX IF NOT EXISTS idx_listings_first_seen ON listings(first_seen);

CREATE TABLE IF NOT EXISTS embeddings (
    listing_id TEXT NOT NULL REFERENCES listings(id),
    model      TEXT NOT NULL,
    vector     BLOB NOT NULL,
    PRIMARY KEY (listing_id, model)
);

-- 검색어. 맥 앱 설정 화면에서 편집한다
CREATE TABLE IF NOT EXISTS searches (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword          TEXT NOT NULL UNIQUE,
    enabled          INTEGER NOT NULL DEFAULT 1,
    price_max        INTEGER,                 -- NULL이면 전체 기본 예산
    outer_price_max  INTEGER,                 -- NULL이면 전체 아우터 예산
    exclude_keywords TEXT NOT NULL DEFAULT '[]',  -- JSON 배열
    sort_order       INTEGER NOT NULL DEFAULT 0,
    created_at       INTEGER NOT NULL
);

-- 전체 설정. 값은 JSON (taste, price_max, outer_price_max, exclude_keywords, exclude_categories)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 실행 기록. 맥 앱이 "마지막 확인" 시각을 보여준다
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    fetched     INTEGER,
    new         INTEGER,
    notified    INTEGER,
    scored      INTEGER,
    cost_usd    REAL,
    errors      TEXT
);

CREATE TABLE IF NOT EXISTS purchases (
    listing_id        TEXT PRIMARY KEY REFERENCES listings(id),
    est_shipping_krw  INTEGER,
    real_shipping_krw INTEGER,
    purchased_at      INTEGER
);
"""


# 메루카리 아우터 카테고리. "아우터 예산"은 이 둘과 그 아래 전부에 적용된다
OUTER_CATEGORIES = (12, 31)  # レディース / メンズ > ジャケット/アウター

DEFAULT_SETTINGS = {
    "taste": "",  # 취향 기준 (자유 서술). 비어 있으면 채점하지 않는다
    "price_max": None,
    "outer_price_max": None,
    "exclude_keywords": [],
    "exclude_categories": [],
}


class Store:
    def __init__(self, path: str | Path):
        path = Path(path)
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        # 메뉴바 앱이 읽는 동안에도 쓸 수 있게 WAL 모드
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        """예전 DB에 없는 컬럼을 추가한다."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(listings)")}
        if "category_id" not in cols:
            self.conn.execute("ALTER TABLE listings ADD COLUMN category_id INTEGER")
        if "baseline" not in cols:
            self.conn.execute("ALTER TABLE listings ADD COLUMN baseline INTEGER NOT NULL DEFAULT 0")
        run_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(runs)")}
        for col, kind in (("scored", "INTEGER"), ("cost_usd", "REAL")):
            if col not in run_cols:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {kind}")
        self.conn.commit()

    def close(self):
        self.conn.close()

    def has_search(self, search: str) -> bool:
        """이 검색어로 저장된 매물이 하나라도 있는지. 없으면 첫 실행이다."""
        row = self.conn.execute("SELECT 1 FROM listings WHERE search = ? LIMIT 1", (search,)).fetchone()
        return row is not None

    def new_only(self, listings: list[Listing]) -> list[Listing]:
        """DB에 없는 매물만 남긴다. 같은 실행 안에서 겹치는 매물도 하나로 친다."""
        seen = set()
        fresh = []
        for listing in listings:
            if listing.id in seen:
                continue
            seen.add(listing.id)
            if self.conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing.id,)).fetchone() is None:
                fresh.append(listing)
        return fresh

    def add(self, listing: Listing, status: str, filter_reason: str | None = None, buyee_url: str | None = None,
            score: int | None = None, score_reason: str | None = None, score_model: str | None = None,
            score_cost_usd: float | None = None, baseline: bool | None = None):
        # 이미 있는 매물(다시 평가)이면 평가 결과만 바꾸고 first_seen·피드백은 그대로 둔다
        self.conn.execute(
            """INSERT INTO listings
               (id, search, title, price_jpy, image_url, url, created_at, category_id,
                first_seen, status, filter_reason, buyee_url, score, score_reason, score_model, score_cost_usd,
                baseline)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 category_id = excluded.category_id, status = excluded.status,
                 filter_reason = excluded.filter_reason, buyee_url = excluded.buyee_url,
                 score = excluded.score, score_reason = excluded.score_reason,
                 score_model = excluded.score_model, score_cost_usd = excluded.score_cost_usd""",
            (
                listing.id,
                listing.search,
                listing.title,
                listing.price_jpy,
                listing.image_url,
                listing.url,
                listing.created_at,
                listing.category_id,
                int(time.time()),
                status,
                filter_reason,
                buyee_url,
                score,
                score_reason,
                score_model,
                score_cost_usd,
                int(bool(baseline)),
            ),
        )
        self.conn.commit()

    def set_feedback(self, listing_id: str, value: int | None) -> bool:
        """1 = 👍, -1 = 👎, None = 지우기. 해당 매물이 있으면 True."""
        cur = self.conn.execute(
            "UPDATE listings SET feedback = ?, feedback_at = ? WHERE id = ?",
            (value, int(time.time()) if value is not None else None, listing_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def feedback_references(self, category_id: int | None, likes: int = 3, dislikes: int = 2,
                            exclude_id: str | None = None) -> list[dict]:
        """채점할 매물과 비교해 보여줄 👍👎 매물. 카테고리가 가까운 것 → 최근 평가한 것 순서.

        나중에 온디바이스 사진 임베딩(4단계)이 생기면 정렬 기준만 사진 유사도로 바꾸면 된다.
        """
        from finder.sources import categories  # 순환 import 방지

        target = categories.lineage(category_id)

        def closeness(row) -> int:
            # 공통 조상이 깊을수록 가깝다 (같은 소분류 > 같은 중분류 > 같은 대분류)
            mine = categories.lineage(row["category_id"])
            return len(set(target) & set(mine))

        rows = self.conn.execute(
            """SELECT id, title, price_jpy, image_url, category_id, score, feedback, feedback_at
               FROM listings WHERE feedback IS NOT NULL AND id != ? ORDER BY feedback_at DESC""",
            (exclude_id or "",),
        ).fetchall()
        rows = sorted(rows, key=closeness, reverse=True)  # 안정 정렬이라 같은 거리면 최근 평가 순
        liked = [dict(r) for r in rows if r["feedback"] > 0][:likes]
        disliked = [dict(r) for r in rows if r["feedback"] < 0][:dislikes]
        return liked + disliked

    def feedback_ids(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT id FROM listings WHERE feedback IS NOT NULL")}

    def feedback_examples(self, limit: int = 12) -> list[dict]:
        """채점 프롬프트에 넣을 최근 피드백. 👍와 👎를 반씩 섞는다."""
        half = limit // 2
        rows = []
        for sign in (1, -1):
            rows += self.conn.execute(
                "SELECT title, price_jpy, score, feedback FROM listings WHERE feedback = ? ORDER BY feedback_at DESC LIMIT ?",
                (sign, half),
            ).fetchall()
        return [dict(r) for r in rows]

    def listings_to_reevaluate(self, include_unscored: bool, rescore: bool = False) -> list[Listing]:
        where = "status = 'seeded'"
        if rescore:
            where += " OR status IN ('passed', 'scored', 'notified')"
        elif include_unscored:
            where += " OR (status = 'passed' AND score IS NULL)"
        rows = self.conn.execute(f"SELECT * FROM listings WHERE {where} ORDER BY first_seen, rowid").fetchall()
        return [
            Listing(r["id"], r["search"], r["title"], r["price_jpy"], r["image_url"], r["url"],
                    r["created_at"], r["category_id"])
            for r in rows
        ]

    def listings_to_retry(self, max_age_hours: int = 48) -> list[tuple[Listing, bool]]:
        """채점을 시도했지만 점수를 못 받은 최근 매물 (상한 초과, API 오류, 채점 중단) → (매물, 기준점 여부).

        채점 대상이 아니라서 건너뛴 매물은 score_reason이 비어 있어서 여기 안 잡힌다.
        """
        since = int(time.time()) - max_age_hours * 3600
        rows = self.conn.execute(
            """SELECT * FROM listings
               WHERE status = 'passed' AND score IS NULL AND score_reason IS NOT NULL AND first_seen >= ?
               ORDER BY first_seen""",
            (since,),
        ).fetchall()
        return [
            (Listing(r["id"], r["search"], r["title"], r["price_jpy"], r["image_url"], r["url"],
                     r["created_at"], r["category_id"]), bool(r["baseline"]))
            for r in rows
        ]

    def set_status(self, listing_id: str, status: str):
        self.conn.execute("UPDATE listings SET status = ? WHERE id = ?", (status, listing_id))
        self.conn.commit()

    def recent(self, limit: int = 20, include_filtered: bool = False) -> list[sqlite3.Row]:
        where = "" if include_filtered else "WHERE status NOT IN ('seeded', 'filtered')"
        return self.conn.execute(
            f"SELECT * FROM listings {where} ORDER BY first_seen DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()

    # ── 검색어·설정 ──────────────────────────────────────────

    def settings(self) -> dict:
        result = dict(DEFAULT_SETTINGS)
        for row in self.conn.execute("SELECT key, value FROM settings"):
            result[row["key"]] = json.loads(row["value"])
        return result

    def set_setting(self, key: str, value):
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.conn.commit()

    def searches(self, enabled_only: bool = True) -> list[dict]:
        where = "WHERE enabled = 1" if enabled_only else ""
        rows = self.conn.execute(f"SELECT * FROM searches {where} ORDER BY sort_order, id").fetchall()
        return [dict(r) | {"exclude_keywords": json.loads(r["exclude_keywords"])} for r in rows]

    def add_search(self, keyword: str, price_max: int | None = None, outer_price_max: int | None = None,
                   exclude_keywords: list[str] | None = None, enabled: bool = True):
        next_order = self.conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM searches").fetchone()[0]
        self.conn.execute(
            """INSERT INTO searches (keyword, enabled, price_max, outer_price_max, exclude_keywords, sort_order, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (keyword, int(enabled), price_max, outer_price_max,
             json.dumps(exclude_keywords or [], ensure_ascii=False), next_order, int(time.time())),
        )
        self.conn.commit()

    def search_config(self) -> dict:
        """DB 설정 → pipeline.run이 받는 {"searches": [...], "defaults": {...}} 모양."""
        s = self.settings()
        defaults = {
            "price_max": s["price_max"],
            "category_price_max": _outer(s["outer_price_max"]),
            "exclude_keywords": s["exclude_keywords"],
            "exclude_categories": s["exclude_categories"],
        }
        searches = []
        for row in self.searches():
            cfg = {"keyword": row["keyword"], "exclude_keywords": row["exclude_keywords"]}
            if row["price_max"] is not None:
                cfg["price_max"] = row["price_max"]
            if row["outer_price_max"] is not None:
                cfg["category_price_max"] = _outer(row["outer_price_max"])
            searches.append(cfg)
        return {"searches": searches, "defaults": defaults}

    def import_config(self, config: dict) -> bool:
        """config.yaml에 있던 검색어·설정을 DB로 옮긴다. DB에 검색어가 이미 있으면 아무것도 안 한다."""
        if self.conn.execute("SELECT 1 FROM searches LIMIT 1").fetchone() or not config.get("searches"):
            return False
        d = config.get("defaults", {})
        outer = {int(k): v for k, v in (d.get("category_price_max") or {}).items()}
        self.set_setting("price_max", d.get("price_max"))
        self.set_setting("outer_price_max", next((outer[c] for c in OUTER_CATEGORIES if c in outer), None))
        self.set_setting("exclude_keywords", d.get("exclude_keywords", []))
        self.set_setting("exclude_categories", d.get("exclude_categories", []))
        for sc in config["searches"]:
            sc_outer = {int(k): v for k, v in (sc.get("category_price_max") or {}).items()}
            self.add_search(
                sc["keyword"],
                price_max=sc.get("price_max"),
                outer_price_max=next((sc_outer[c] for c in OUTER_CATEGORIES if c in sc_outer), None),
                exclude_keywords=sc.get("exclude_keywords", []),
            )
        return True

    def month_cost_usd(self) -> float:
        """이번 달 채점에 쓴 비용 (달러)."""
        start = time.mktime(time.localtime()[:2] + (1, 0, 0, 0, 0, 0, -1))
        row = self.conn.execute(
            "SELECT COALESCE(SUM(score_cost_usd), 0) FROM listings WHERE first_seen >= ?", (int(start),)
        ).fetchone()
        return row[0]

    # ── 실행 기록 ────────────────────────────────────────────

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (int(time.time()),))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, fetched: int, new: int, notified: int, errors: list[str],
                   scored: int = 0, cost_usd: float = 0.0):
        self.conn.execute(
            """UPDATE runs SET finished_at = ?, fetched = ?, new = ?, notified = ?, scored = ?, cost_usd = ?, errors = ?
               WHERE id = ?""",
            (int(time.time()), fetched, new, notified, scored, cost_usd, json.dumps(errors, ensure_ascii=False), run_id),
        )
        self.conn.commit()


def _outer(price: int | None) -> dict[int, int]:
    return {c: price for c in OUTER_CATEGORIES} if price is not None else {}
