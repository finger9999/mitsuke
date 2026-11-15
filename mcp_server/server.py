"""미츠케 MCP 서버. 같은 SQLite DB를 AI 에이전트(Claude 등)에게 도구로 열어준다.

  .venv/bin/python mcp_server/server.py      (stdio)

맥 앱이 사람용 화면이라면, 이건 에이전트용 인터페이스다. DB 위에 얹기만 하고 파이프라인 로직은 건드리지 않는다.
저장소 루트의 .mcp.json에 등록돼 있어서, 이 폴더에서 Claude Code를 열면 바로 쓸 수 있다.
"""

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from finder.sources import categories  # noqa: E402
from finder.store import Store  # noqa: E402

DB_PATH = ROOT / "data" / "mitsuke.db"
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

server = MCPServer(
    name="mitsuke",
    title="미츠케",
    instructions=(
        "메루카리 새 매물을 사용자 취향으로 채점해 모아 둔 DB다. 점수는 0~100이고 90점 이상은 사용자에게 알림이 간다. "
        "피드백(like/dislike)은 사용자의 취향 정답이므로, 사용자가 명시적으로 원할 때만 기록한다. "
        "구매는 Buyee 링크(buyee_url)로 사용자가 직접 한다. 결제를 대신하지 않는다."
    ),
)


def _store() -> Store:
    return Store(DB_PATH)


def _listing(r) -> dict:
    return {
        "id": r["id"],
        "title": r["title"],
        "price_jpy": r["price_jpy"],
        "score": r["score"],
        "score_reason": r["score_reason"],
        "status": r["status"],
        "filter_reason": r["filter_reason"],
        "feedback": {1: "like", -1: "dislike"}.get(r["feedback"]),
        "search": r["search"],
        "category": categories.path(r["category_id"]) or None,
        "first_seen": datetime.fromtimestamp(r["first_seen"]).isoformat(timespec="minutes"),
        "buyee_url": r["buyee_url"] or f"https://buyee.jp/mercari/item/{r['id'].removeprefix('mercari:')}",
        "mercari_url": r["url"],
        "image_url": r["image_url"],
    }


@server.tool(annotations=READ)
def get_new_matches(min_score: int = 60, hours: int = 24, limit: int = 20, include_disliked: bool = False) -> list[dict]:
    """최근 들어온 매물 중 점수가 min_score 이상인 것을 점수 높은 순으로 돌려준다.

    hours: 몇 시간 안에 처음 본 매물까지 볼지. limit: 최대 개수 (최대 100).
    """
    since = int(datetime.now().timestamp()) - hours * 3600
    disliked = "" if include_disliked else "AND (feedback IS NULL OR feedback != -1)"
    with_store = _store()
    try:
        rows = with_store.conn.execute(
            f"""SELECT * FROM listings WHERE score >= ? AND first_seen >= ? {disliked}
                ORDER BY score DESC, first_seen DESC LIMIT ?""",
            (min_score, since, min(limit, 100)),
        ).fetchall()
        return [_listing(r) for r in rows]
    finally:
        with_store.close()


@server.tool(annotations=READ)
def search_listings(query: str, limit: int = 20) -> list[dict]:
    """저장된 매물을 제목으로 찾는다 (일본어 그대로 검색, 예: "ウール", "ショートコート"). 최신순."""
    store = _store()
    try:
        rows = store.conn.execute(
            "SELECT * FROM listings WHERE title LIKE ? ORDER BY first_seen DESC LIMIT ?",
            (f"%{query}%", min(limit, 100)),
        ).fetchall()
        return [_listing(r) for r in rows]
    finally:
        store.close()


@server.tool(annotations=WRITE)
def give_feedback(listing_id: str, value: str) -> str:
    """매물에 사용자 피드백을 기록한다. value: "like"(👍), "dislike"(👎), "clear"(지우기).

    피드백은 다음 채점부터 비교 사진으로 쓰이고 평가셋 정답이 된다. 사용자가 원할 때만 기록할 것.
    """
    mapping = {"like": 1, "dislike": -1, "clear": None}
    if value not in mapping:
        return f"value는 like, dislike, clear 중 하나여야 합니다 (받은 값: {value})"
    listing_id = listing_id if listing_id.startswith("mercari:") else f"mercari:{listing_id}"
    store = _store()
    try:
        ok = store.set_feedback(listing_id, mapping[value])
    finally:
        store.close()
    return f"{listing_id}: {value} 기록함" if ok else f"DB에 없는 매물: {listing_id}"


@server.tool(annotations=READ)
def get_taste() -> str:
    """채점에 쓰는 취향 기준 글 ([알림 받고 싶은 것] / [관심 있는 것])."""
    store = _store()
    try:
        return store.settings()["taste"]
    finally:
        store.close()


@server.tool(annotations=READ)
def get_taste_history(limit: int = 5) -> list[dict]:
    """취향 기준 자동 개선(python main.py tune) 기록: 제안, 바뀐 점, 검증 분리도 전후, 반영 여부. 최근 것부터."""
    store = _store()
    try:
        history = store.settings().get("taste_history") or []
    finally:
        store.close()
    return list(reversed(history))[:limit]


@server.tool(annotations=WRITE)
def set_taste(text: str) -> str:
    """취향 기준 글을 바꾼다. 다음 채점부터 적용된다. 사용자가 원할 때만 쓸 것.

    [알림 받고 싶은 것]에 맞으면 90점 이상(알림), [관심 있는 것]에 맞으면 60~89점이 된다.
    """
    if not text.strip():
        return "빈 글로는 바꿀 수 없습니다 (비우면 채점이 꺼집니다)"
    store = _store()
    try:
        store.set_setting("taste", text.strip())
    finally:
        store.close()
    return "취향 기준을 바꿨습니다. 다음 실행부터 적용됩니다."


@server.tool(annotations=READ)
def list_searches() -> list[dict]:
    """메루카리 검색어 목록과 켜짐 여부, 검색어별 예산."""
    store = _store()
    try:
        return [
            {"keyword": s["keyword"], "enabled": bool(s["enabled"]), "price_max": s["price_max"],
             "outer_price_max": s["outer_price_max"], "exclude_keywords": s["exclude_keywords"]}
            for s in store.searches(enabled_only=False)
        ]
    finally:
        store.close()


@server.tool(annotations=WRITE)
def add_search(keyword: str) -> str:
    """검색어를 추가한다. 메루카리에서 쓰는 일본어 표기로 (예: "ウール ショートコート").

    첫 실행 때 이미 올라와 있던 매물은 평가만 하고 알림은 보내지 않는다.
    """
    keyword = keyword.strip()
    store = _store()
    try:
        if any(s["keyword"] == keyword for s in store.searches(enabled_only=False)):
            return f"이미 있는 검색어: {keyword}"
        store.add_search(keyword)
    finally:
        store.close()
    return f"검색어 추가: {keyword} (다음 실행부터)"


@server.tool(annotations=WRITE)
def set_search_enabled(keyword: str, enabled: bool) -> str:
    """검색어를 켜거나 끈다. 지우지는 않는다."""
    store = _store()
    try:
        cur = store.conn.execute("UPDATE searches SET enabled = ? WHERE keyword = ?", (int(enabled), keyword))
        store.conn.commit()
    finally:
        store.close()
    return f"{keyword}: {'켬' if enabled else '끔'}" if cur.rowcount else f"없는 검색어: {keyword}"


@server.tool(annotations=READ)
def get_status() -> dict:
    """마지막 실행, 이번 달 채점 비용(유료 가격 기준 추정), 매물·피드백 수."""
    store = _store()
    try:
        run = store.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        counts = dict(store.conn.execute("SELECT status, COUNT(*) FROM listings GROUP BY status").fetchall())
        fb = dict(store.conn.execute(
            "SELECT feedback, COUNT(*) FROM listings WHERE feedback IS NOT NULL GROUP BY feedback").fetchall())
        return {
            "last_run": None if not run else {
                "started_at": datetime.fromtimestamp(run["started_at"]).isoformat(timespec="minutes"),
                "finished_at": datetime.fromtimestamp(run["finished_at"]).isoformat(timespec="minutes")
                if run["finished_at"] else None,
                "new": run["new"], "scored": run["scored"], "notified": run["notified"],
            },
            "month_cost_usd_estimate": round(store.month_cost_usd(), 4),
            "listings_by_status": counts,
            "feedback": {"like": fb.get(1, 0), "dislike": fb.get(-1, 0)},
        }
    finally:
        store.close()


if __name__ == "__main__":
    server.run("stdio")
