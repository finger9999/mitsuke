"""SQLite 읽기·쓰기. Python 파이프라인과 메뉴바 앱(Swift)의 유일한 연결고리."""

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

CREATE TABLE IF NOT EXISTS purchases (
    listing_id        TEXT PRIMARY KEY REFERENCES listings(id),
    est_shipping_krw  INTEGER,
    real_shipping_krw INTEGER,
    purchased_at      INTEGER
);
"""


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
               (id, search, title, price_jpy, image_url, url, created_at, first_seen, status, filter_reason, buyee_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                listing.id,
                listing.search,
                listing.title,
                listing.price_jpy,
                listing.image_url,
                listing.url,
                listing.created_at,
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
