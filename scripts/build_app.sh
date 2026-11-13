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
codesign --force --sign - "$APP"

INSTALLED="$HOME/Applications/Mitsuke.app"
pkill -x Mitsuke 2>/dev/null || true
mkdir -p "$HOME/Applications"
rm -rf "$INSTALLED"
cp -R "$APP" "$INSTALLED"
echo "설치 완료: $INSTALLED"

if [[ "${1:-}" == "--open" ]]; then
  open "$INSTALLED"
fi
