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
    feedback_at    INTEGER
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

-- 전체 설정. 값은 JSON (price_max, outer_price_max, exclude_keywords, exclude_categories)
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

    def add(self, listing: Listing, status: str, filter_reason: str | None = None, buyee_url: str | None = None):
        self.conn.execute(
            """INSERT OR IGNORE INTO listings
               (id, search, title, price_jpy, image_url, url, created_at, category_id,
                first_seen, status, filter_reason, buyee_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )
        self.conn.commit()

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

    # ── 실행 기록 ────────────────────────────────────────────

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (int(time.time()),))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, fetched: int, new: int, notified: int, errors: list[str]):
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, fetched = ?, new = ?, notified = ?, errors = ? WHERE id = ?",
            (int(time.time()), fetched, new, notified, json.dumps(errors, ensure_ascii=False), run_id),
        )
        self.conn.commit()


def _outer(price: int | None) -> dict[int, int]:
    return {c: price for c in OUTER_CATEGORIES} if price is not None else {}
