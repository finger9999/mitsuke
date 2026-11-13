# 미츠케 (Mitsuke)

메루카리에 새로 올라온 매물 중 취향에 맞는 것만 골라 맥 알림으로 알려주고, Buyee 구매 페이지로 바로 연결해주는 개인용 직구 비서. 자세한 설계는 [docs/DESIGN.md](docs/DESIGN.md).

현재 **0단계 (기본 파이프라인)**: 메루카리 검색 → 신규 감지 → 규칙 필터 → Buyee 링크 → 맥 알림.

## 설치

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/build_notifier.sh       # 알림 도우미 앱 빌드 (Xcode 필요)
```

처음 알림을 보낼 때 macOS가 "미츠케" 알림 허용 여부를 묻는다. 허용해야 알림이 뜬다.

## 사용

1. `config.yaml`에 검색어(일본어), 예산, 사이즈, 제외 키워드를 적는다.
2. 실행해 본다.

```bash
.venv/bin/python main.py run          # 한 번 실행
.venv/bin/python main.py recent       # 알림 간 매물 보기
.venv/bin/python main.py recent --all # 기준점·탈락 매물까지
```

검색어별 첫 실행은 이미 올라와 있던 매물을 기준점으로만 저장하고 알림을 보내지 않는다. 그다음 실행부터 새로 올라온 매물이 알림으로 온다.

3. 1시간마다 자동 실행:

```bash
./scripts/install_launchd.sh            # 등록
./scripts/install_launchd.sh uninstall  # 해제
```

## 테스트

```bash
.venv/bin/python -m pytest
```

파서 테스트는 `tests/fixtures/`에 저장해둔 실제 메루카리 응답으로 돈다.
