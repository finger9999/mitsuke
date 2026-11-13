# 002. 맥 알림이 안 뜬다

2026-11-14 · 관련 파일: [app/MitsukeNotifier/main.swift](../../app/MitsukeNotifier/main.swift), [finder/notifier.py](../../finder/notifier.py), [scripts/build_notifier.sh](../../scripts/build_notifier.sh)

## 목표

새 매물을 찾으면 맥 알림을 띄우고, 알림을 누르면 Buyee 구매 페이지가 열려야 한다.

## 1차 시도: terminal-notifier

파이썬에서 맥 알림을 띄우는 흔한 방법은 두 가지다.

| 방법 | 클릭하면 URL 열기 |
| --- | --- |
| `osascript -e 'display notification ...'` | 안 됨 |
| `terminal-notifier -open <URL>` | 됨 |

클릭 동작이 필요해서 terminal-notifier(brew로 이미 설치돼 있던 2.0.0)를 골랐다. 명령은 매번 성공(종료 코드 0)으로 끝났는데 **화면에는 아무것도 안 떴다.**

## 원인 찾기

### 의심 1: 알림 권한이 꺼져 있다 → 맞았지만 이것만은 아니었다

macOS 알림 설정은 `~/Library/Preferences/com.apple.ncprefs.plist`에 앱별로 저장된다. terminal-notifier 항목의 `flags` 값을 보니:

| 시점 | flags | 16진수 |
| --- | --- | --- |
| 처음 | 8396814 | `0x80200E` |
| 시스템 설정에서 허용을 켠 뒤 | 41951246 | `0x280200E` |

허용을 켜자 `0x2000000` 비트가 새로 켜졌다. 이 비트가 "알림 허용"인 것으로 보인다. (Apple이 공개한 형식이 아니라서, 켜기 전후 값을 비교해서 추정한 것이다.)

권한을 켰는데도 여전히 안 떴다.

### 의심 2: Claude Code 샌드박스가 막는다 → 아니었다

Claude Code는 명령을 샌드박스 안에서 실행한다. 샌드박스가 알림 서비스와의 연결을 막는 것일 수 있었다. 그래서 같은 명령을 사용자가 직접 VS Code 터미널에서 실행해 봤는데, **거기서도 안 떴다.** 샌드박스 문제가 아니었다.

### 결론: terminal-notifier 자체가 이 맥(macOS 15.3)에서 동작하지 않는다

terminal-notifier는 오래된 `NSUserNotification` API를 쓴다. 이 API는 macOS 11부터 폐기 예정(deprecated)이다. 최신 macOS에서 알림이 조용히 버려진 원인으로 가장 그럴듯하지만, 정확한 원인을 따로 확인하지는 않았다.

## 해결: 알림 앱을 직접 만들었다

현재 권장되는 API인 `UserNotifications`(`UNUserNotificationCenter`)로 작은 Swift 앱을 만들었다. 이 API는 **앱 번들(.app)** 안에서 실행돼야 하고 번들 ID가 있어야 한다. 알림 권한도 번들 ID 단위로 관리된다.

### 구조

```
MitsukeNotifier.app/
└── Contents/
    ├── Info.plist        # 번들 ID com.mitsuke.notifier, 이름 "미츠케", LSUIElement(독 아이콘 없음)
    └── MacOS/
        └── MitsukeNotifier   # swiftc로 컴파일한 실행 파일
```

Xcode 프로젝트 없이 `swiftc` 한 줄로 컴파일하고, 폴더를 직접 만들어 번들 모양을 갖춘 뒤 `codesign --sign -`(애드혹 서명)으로 서명한다. 이 과정이 `scripts/build_notifier.sh`다.

### 동작 방식

1. 파이썬이 실행 파일을 인자와 함께 부른다.
   ```
   MitsukeNotifier --title ... --subtitle ... --message ... --open <Buyee URL> --image <썸네일 URL>
   ```
2. 앱이 알림 권한을 확인하고(처음 한 번은 macOS가 허용 여부를 묻는다), 알림을 올린 뒤 바로 끝난다.
3. 사용자가 알림을 누르면 **macOS가 앱을 다시 실행**하고, delegate의 `didReceive`가 불린다. 알림에 넣어둔 URL(`userInfo["url"]`)을 브라우저로 열고 끝난다.

알림 내용 안에 URL을 담아 두기 때문에, 알림을 올린 앱이 이미 꺼져 있어도 클릭이 동작한다.

### 썸네일

메루카리 썸네일은 webp인데, 알림 첨부(`UNNotificationAttachment`)는 webp를 받지 않을 수 있다. 그래서 이미지를 받아 `NSImage`로 읽고 PNG로 바꿔 임시 파일로 저장한 뒤 첨부한다.

## 겪은 것

- **샌드박스에서는 권한 창이 안 뜬다.** Claude Code가 실행하면 권한 창 없이 곧바로 "Notifications are not allowed for this application" 오류가 났다. 사용자가 터미널에서 직접 한 번 실행하니 허용 창이 떴고, 허용하자 알림이 떴다.
- **한 번 허용하면 그다음은 그냥 된다.** 권한은 번들 ID에 묶여 있어서 launchd 자동 실행에서도 그대로 쓰인다.
- **다시 빌드해도 권한이 유지된다.** 애드혹 서명은 빌드할 때마다 서명이 바뀌어서 걱정했는데, 사용자가 다시 빌드한 뒤에도 알림이 떴다. 혹시 안 뜨면 시스템 설정 → 알림 → 미츠케를 확인한다.

## 정리

| 시도 | 결과 |
| --- | --- |
| terminal-notifier | 명령은 성공, 화면에 안 뜸 |
| 알림 권한 켜기 | 여전히 안 뜸 |
| 사용자 터미널에서 직접 실행 | 여전히 안 뜸 → 샌드박스 탓 아님 |
| Swift + UserNotifications 앱 | **뜸**, 클릭하면 Buyee 페이지가 열림 (사용자 확인) |

이 알림 앱은 2단계 메뉴바 앱(SwiftUI)으로 합칠 수 있다. 같은 번들 ID를 쓰면 권한도 이어질 것으로 예상한다.
