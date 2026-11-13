# 미츠케 (Mitsuke)

메루카리에 새로 올라온 매물 중 취향에 맞는 것만 골라 맥 알림으로 알려주고, Buyee 구매 페이지로 바로 연결해주는 개인용 직구 비서. 자세한 설계는 [docs/DESIGN.md](docs/DESIGN.md), 만들면서 겪은 일은 [docs/devlog/](docs/devlog/).

현재: 메루카리 검색 → 신규 감지 → 규칙 필터(예산·카테고리·제외 키워드) → Buyee 링크 → 맥 알림, 그리고 매물을 보고 검색어를 편집하는 맥 앱.

## 설치

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/build_app.sh --open        # 맥 앱 빌드 → ~/Applications 설치 → 실행 (Xcode 필요)
./scripts/install_launchd.sh         # 1시간마다 자동 실행 등록
```

처음 알림을 보낼 때 macOS가 "미츠케" 알림 허용 여부를 묻는다. 허용해야 알림이 뜬다.

## 맥 앱

Spotlight나 Launchpad에서 "미츠케"(Mitsuke)로 연다. 실행하면 매물 창이 열리고 Dock 아이콘이 생긴다.

메뉴바의 **見** 아이콘을 누르면 최근 통과 매물이 뜬다. 새 매물이 있으면 아이콘 옆에 개수가 붙는다.

- **전체 보기**: 쌓인 매물을 사진 그리드로 본다. 검색어별로 거르거나 탈락·기준점 매물까지 볼 수 있다. 카드를 누르면 Buyee, 우클릭하면 메루카리
- **설정**: 검색어 추가·삭제·켜고 끄기, 공통 예산·아우터 예산·제외 키워드, 검색어별 예산
- **지금 확인**: 1시간을 기다리지 않고 바로 한 번 실행

검색어와 예산은 DB(`data/mitsuke.db`)에 저장되고, 파이프라인이 실행될 때마다 읽는다. `config.yaml`에는 요청 간격 같은 동작 설정만 남아 있다.

앱 코드는 Swift 패키지라서 Xcode에서 `app/Mitsuke/Package.swift`를 열어 편집할 수 있다.

## 명령줄

```bash
.venv/bin/python main.py run          # 한 번 실행
.venv/bin/python main.py recent       # 통과 매물 보기
.venv/bin/python main.py recent --all # 기준점·탈락 매물까지
./scripts/install_launchd.sh uninstall  # 자동 실행 해제
```

검색어별 첫 실행은 이미 올라와 있던 매물을 기준점으로만 저장하고 알림을 보내지 않는다. 그다음 실행부터 새로 올라온 매물이 알림으로 온다.

## 테스트

```bash
.venv/bin/python -m pytest
```

파서 테스트는 `tests/fixtures/`에 저장해둔 실제 메루카리 응답으로 돈다.
