"""매물 사진 받기 + 로컬 캐시.

채점할 때 같은 👍👎 참고 사진을 매번 다시 보내므로, 한 번 받은 사진은 data/images/에 저장해 둔다.
"""

import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

CACHE = Path(__file__).resolve().parent.parent / "data" / "images"
FULL_URL = "https://static.mercdn.net/item/detail/orig/photos/{item_id}_1.jpg"


def full_url(listing_id: str) -> str:
    """첫 번째 사진 원본 (썸네일은 240×240이라 디테일이 잘 안 보인다)."""
    return FULL_URL.format(item_id=listing_id.removeprefix("mercari:"))


def fetch(url: str, cache_key: str) -> tuple[bytes, str] | None:
    """(바이트, MIME 타입). 실패하면 None."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for path in CACHE.glob(f"{cache_key}.*"):
        mime = "image/jpeg" if path.suffix == ".jpg" else "image/webp"
        return path.read_bytes(), mime
    try:
        resp = httpx.get(url, timeout=20)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("사진 받기 실패 %s: %s", url, e)
        return None
    mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    ext = ".jpg" if mime == "image/jpeg" else ".webp"
    (CACHE / f"{cache_key}{ext}").write_bytes(resp.content)
    return resp.content, mime


def full(listing_id: str, fallback_url: str | None = None) -> tuple[bytes, str] | None:
    key = listing_id.replace(":", "_") + "_full"
    return fetch(full_url(listing_id), key) or (thumb(listing_id, fallback_url) if fallback_url else None)


def thumb(listing_id: str, url: str | None) -> tuple[bytes, str] | None:
    if not url:
        return None
    return fetch(url, listing_id.replace(":", "_") + "_thumb")


def cleanup(keep_ids: set[str], full_days: float = 1, thumb_days: float = 7) -> int:
    """오래된 캐시 사진을 지운다. 지운 파일 수를 돌려준다.

    - 원본 사진(_full): 채점할 때 한 번 쓰고 끝이라 하루 지나면 지운다 (장당 약 75KB, 용량 대부분).
    - 썸네일(_thumb): 👍👎한 매물(keep_ids)은 채점 참고 사진으로 계속 쓰니 남기고, 나머지는 7일 뒤 지운다.
    """
    if not CACHE.exists():
        return 0
    now = time.time()
    removed = 0
    for path in CACHE.iterdir():
        stem = path.stem
        listing_id = stem.rsplit("_", 1)[0].replace("_", ":", 1)
        age_days = (now - path.stat().st_mtime) / 86400
        if stem.endswith("_full"):
            expired = age_days > full_days
        else:
            expired = listing_id not in keep_ids and age_days > thumb_days
        if expired:
            path.unlink()
            removed += 1
    return removed
