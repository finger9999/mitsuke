# 004. 매물 확인과 검색어 설정을 맥 앱으로

2026-11-14 · 관련 파일: [app/Mitsuke/](../../app/Mitsuke/), [finder/store.py](../../finder/store.py), [scripts/build_app.sh](../../scripts/build_app.sh)

## 요구사항

- 1시간마다 쌓인 매물을 메루카리 사이트가 아니라 맥에서 따로 보고 싶다
- 검색어 설정을 `config.yaml` 파일 말고 UI에서 하고 싶다

## 형태 고르기

| 방식 | 장점 | 단점 |
| --- | --- | --- |
| **SwiftUI 맥 앱 (선택)** | 메뉴바에서 바로 보임, 알림 앱과 합칠 수 있음, 설계 문서 2단계와 같은 방향 | 만드는 데 조금 더 걸림 |
| 로컬 웹페이지 (Python 서버) | 빨리 만듦 | 서버를 계속 켜 둬야 함, 메뉴바 없음 |

설계 문서 로드맵의 2단계(메뉴바 앱)를 앞당긴 셈이다.

## 구조 변경: 설정을 파일에서 DB로

앱이 검색어를 편집하려면 앱과 파이썬이 같은 곳을 봐야 한다. Swift에서 YAML을 고쳐 쓰는 건 번거롭고 주석도 날아가서, 원래 둘의 연결고리인 SQLite에 테이블을 추가했다.

```
searches  검색어마다 한 줄: keyword, enabled, price_max, outer_price_max, exclude_keywords
settings  공통 설정 (key → JSON): price_max, outer_price_max, exclude_keywords, exclude_categories
runs      실행 기록: 시작·끝 시각, 새 매물 수, 알림 수, 오류  → 앱의 "마지막 확인" 표시
```

- 파이프라인 코드(`pipeline.run`)는 그대로 두고, `Store.search_config()`가 DB 내용을 예전 `config.yaml`과 같은 모양으로 만들어 넘긴다.
- "아우터 예산" 하나를 카테고리 규칙 `{12: 금액, 31: 금액}`으로 바꿔준다. 003에서 만든 카테고리 규칙을 UI에 그대로 노출하면 카테고리 번호를 알아야 해서, UI에는 "기본 예산 / 아우터 예산" 두 칸만 둔다.
- 처음 실행할 때 `config.yaml`에 있던 검색어·설정을 DB로 한 번 옮긴다(`Store.import_config`). DB에 검색어가 이미 있으면 다시 하지 않는다.
- `config.yaml`에는 요청 간격, 페이지 크기 같은 동작 설정만 남겼다.

## 앱 구성

Xcode 프로젝트 파일(`.xcodeproj`) 대신 **Swift 패키지**로 만들었다. `Package.swift`를 Xcode로 열면 프로젝트처럼 편집할 수 있고, 명령줄에서는 `swift build`로 빌드된다. `.xcodeproj`는 사람이 손으로 쓰기 어려운 형식이라 이쪽이 관리하기 쉽다.

`swift build`가 만드는 건 실행 파일 하나라서, `scripts/build_app.sh`가 002 때처럼 `.app` 번들 모양을 만들고 애드혹 서명을 한다. 이때 저장소 경로를 Info.plist(`MitsukeRoot`)에 넣어서 앱이 `data/mitsuke.db`를 찾게 한다.

| 파일 | 역할 |
| --- | --- |
| `main.swift` | `--notify`가 있으면 알림만 보내고 끝, 없으면 메뉴바 앱 실행 |
| `Notifier.swift` | 002의 알림 도우미를 옮겨온 것 + 앱 모드에서 알림 클릭 처리 |
| `Database.swift` | SQLite C API(`import SQLite3`)로 직접 읽고 쓰기. 외부 라이브러리 없음 |
| `AppModel.swift` | 30초마다 DB를 다시 읽음, "지금 확인"(launchd 작업을 `launchctl kickstart`로 바로 실행) |
| `MenuBarView.swift` | 메뉴바 창: 최근 통과 매물 8개, 마지막 확인 시각 |
| `ListingsView.swift` | 전체 매물 사진 그리드, 검색어·제목으로 거르기, 탈락·기준점 포함 보기 |
| `SettingsView.swift` | 검색어 추가·삭제·켜고 끄기, 공통·검색어별 예산, 제외 키워드 |

### 알림 앱을 합친 방식

예전에는 알림 전용 앱(`MitsukeNotifier.app`)이 따로 있었다. 이제 같은 실행 파일이 두 가지로 동작한다.

- 파이썬이 `Mitsuke --notify --title ... --open <Buyee URL>`로 부르면 알림만 올리고 바로 끝난다. 메뉴바 앱이 이미 떠 있어도 별도 프로세스라 상관없다.
- 알림을 누르면 macOS가 같은 번들 ID(`com.mitsuke.app`)의 앱으로 클릭을 보낸다. 메뉴바 앱이 받아서 Buyee 페이지를 연다.

번들 ID가 `com.mitsuke.notifier`에서 `com.mitsuke.app`으로 바뀌었기 때문에 **알림 권한을 한 번 다시 허용해야 한다.**

### "새 매물" 표시

메뉴바 창이나 전체 보기 창을 마지막으로 닫은 시각을 앱 설정(UserDefaults)에 저장하고, 그 뒤에 들어온 통과 매물에 NEW를 붙인다. 메뉴바 아이콘 옆 숫자도 이 개수다. DB에 따로 "읽음" 컬럼을 두지 않아서 파이썬 쪽은 바뀐 게 없다.

## 확인한 것 / 아직 안 한 것

- 빌드는 경고 없이 한 번에 통과했다. 앱이 실행되는 것까지 확인했다.
- 화면이 제대로 보이는지, 설정 저장이 파이프라인에 반영되는지, 알림 클릭이 떠 있는 앱으로 전달되는지는 사용자가 직접 확인해야 한다. (Claude Code 쪽에서는 화면을 볼 수 없고, 샌드박스 때문에 알림도 보낼 수 없다 → 002)
