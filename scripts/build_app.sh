#!/bin/bash
# 맥 앱을 빌드해 ~/Applications/Mitsuke.app 에 설치한다 (Spotlight·Launchpad에서 "미츠케"로 찾을 수 있음).
#   ./scripts/build_app.sh          빌드
#   ./scripts/build_app.sh --open   빌드하고 실행 (이미 떠 있으면 다시 띄움)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/app/Mitsuke"
APP="$SRC/build/Mitsuke.app"

swift build -c release --package-path "$SRC"
BIN="$(swift build -c release --package-path "$SRC" --show-bin-path)/Mitsuke"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN" "$APP/Contents/MacOS/Mitsuke"
# 앱이 DB를 찾을 수 있게 저장소 경로를 Info.plist에 박는다
sed "s|__MITSUKE_ROOT__|$ROOT|" "$SRC/Info.plist" > "$APP/Contents/Info.plist"
# 애드혹 서명(-)은 빌드할 때마다 앱 신원이 바뀌어 알림 권한이 풀릴 수 있다.
# Apple Development 인증서가 있으면 그걸로 서명해서 다시 빌드해도 같은 앱으로 인식되게 한다.
IDENTITY="$(security find-identity -v -p codesigning | awk '/Apple Development/ {print $2; exit}')"
if [[ -n "$IDENTITY" ]]; then
  codesign --force --sign "$IDENTITY" "$APP"
else
  echo "Apple Development 인증서가 없어 애드혹 서명 (다시 빌드하면 알림 권한을 다시 허용해야 할 수 있음)"
  codesign --force --sign - "$APP"
fi

INSTALLED="$HOME/Applications/Mitsuke.app"
pkill -x Mitsuke 2>/dev/null || true
mkdir -p "$HOME/Applications"
rm -rf "$INSTALLED"
cp -R "$APP" "$INSTALLED"
echo "설치 완료: $INSTALLED"

if [[ "${1:-}" == "--open" ]]; then
  open "$INSTALLED"
fi
