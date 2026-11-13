#!/bin/bash
# 알림 도우미 앱을 빌드해 app/MitsukeNotifier/build/MitsukeNotifier.app 에 만든다.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/app/MitsukeNotifier"
APP="$SRC/build/MitsukeNotifier.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$SRC/Info.plist" "$APP/Contents/Info.plist"
swiftc -O -o "$APP/Contents/MacOS/MitsukeNotifier" "$SRC/main.swift"
codesign --force --sign - "$APP"
echo "빌드 완료: $APP"
