"""맥 알림. 클릭하면 Buyee 구매 페이지가 열린다.

알림은 맥 앱(app/Mitsuke, scripts/build_app.sh로 빌드)을 `--notify` 모드로 불러서 보낸다.
terminal-notifier는 macOS 15에서 알림이 조용히 버려지는 경우가 있어 쓰지 않는다 (docs/devlog/002).
앱이 없으면 osascript로 알림만 띄운다 (클릭 동작 없음).
"""

import logging
import subprocess
from pathlib import Path

from finder.models import Listing

log = logging.getLogger(__name__)

NOTIFIER_BIN = Path.home() / "Applications/Mitsuke.app/Contents/MacOS/Mitsuke"


def notify(listing: Listing, buyee_url: str, score: int | None = None, reason: str | None = None) -> bool:
    title = f"미츠케 · {score}점" if score is not None else "미츠케 · 찾았다"
    subtitle = f"¥{listing.price_jpy:,} · {listing.search}"
    message = f"{listing.title}\n{reason}" if reason else listing.title

    if NOTIFIER_BIN.exists():
        cmd = [str(NOTIFIER_BIN), "--notify", "--title", title, "--subtitle", subtitle, "--message", message,
               "--open", buyee_url, "--group", listing.id]
        if listing.image_url:
            cmd += ["--image", listing.image_url]
    else:
        log.warning("맥 앱이 없어 osascript로 보냄 (scripts/build_app.sh로 빌드)")
        script = f"display notification {_q(message)} with title {_q(title)} subtitle {_q(subtitle)}"
        cmd = ["osascript", "-e", script]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        return True
    except subprocess.CalledProcessError as e:
        log.error("알림 실패 %s: %s", listing.id, (e.stderr or "").strip() or e)
        return False
    except (subprocess.SubprocessError, OSError) as e:
        log.error("알림 실패 %s: %s", listing.id, e)
        return False


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
