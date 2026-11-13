"""맥 알림. 클릭하면 Buyee 구매 페이지가 열린다.

클릭 동작은 terminal-notifier(brew install terminal-notifier)가 있어야 된다.
없으면 osascript로 알림만 띄운다.
"""

import logging
import os
import shutil
import subprocess

from finder.models import Listing

log = logging.getLogger(__name__)


def notify(listing: Listing, buyee_url: str) -> bool:
    title = "미츠케 · 찾았다"
    subtitle = f"¥{listing.price_jpy:,} · {listing.search}"
    message = listing.title

    tn = _terminal_notifier()
    if tn:
        cmd = [tn, "-title", title, "-subtitle", subtitle, "-message", message,
               "-open", buyee_url, "-group", listing.id, "-sound", "default"]
        if listing.image_url:
            cmd += ["-contentImage", listing.image_url]
    else:
        script = f"display notification {_q(message)} with title {_q(title)} subtitle {_q(subtitle)}"
        cmd = ["osascript", "-e", script]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=15)
        return True
    except (subprocess.SubprocessError, OSError) as e:
        log.error("알림 실패 %s: %s", listing.id, e)
        return False


def _terminal_notifier() -> str | None:
    # launchd는 PATH가 짧아서 brew 경로를 따로 찾아본다
    found = shutil.which("terminal-notifier")
    if found:
        return found
    for path in ("/opt/homebrew/bin/terminal-notifier", "/usr/local/bin/terminal-notifier"):
        if os.path.exists(path):
            return path
    return None


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
