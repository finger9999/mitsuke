#!/bin/bash
# 맥 앱을 빌드해 app/Mitsuke/build/미츠케.app 에 만든다.
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
echo "빌드 완료: $APP"

if [[ "${1:-}" == "--open" ]]; then
  pkill -x Mitsuke 2>/dev/null || true
  open "$APP"
fi
