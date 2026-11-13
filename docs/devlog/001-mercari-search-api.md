# 001. 메루카리 검색을 어떻게 가져올까

2026-11-14 · 관련 파일: [finder/sources/mercari.py](../../finder/sources/mercari.py)

## 문제

설계 문서에서 가장 불확실하다고 적어둔 부분이다. 메루카리는 공개 API가 없고, 웹페이지(jp.mercari.com)는 자바스크립트로 그려져서 HTML만 받아서는 매물 목록이 안 나온다.

## 확인한 것

메루카리 웹사이트는 화면을 그릴 때 내부 검색 API를 부른다.

```
POST https://api.mercari.jp/v2/entities:search
```

이 API는 요청마다 `DPoP` 헤더를 요구한다. DPoP는 클라이언트가 만든 키로 서명한 JWT(ES256)다. 서버가 키를 미리 알 필요가 없어서, 실행할 때마다 새 키를 만들어 서명해도 받아준다.

헤더에 들어가는 JWT 구성:

- 헤더: `{"typ": "dpop+jwt", "alg": "ES256", "jwk": <공개키>}`
- 본문: `iat`(현재 시각), `jti`(임의 UUID), `htu`(요청 URL), `htm`("POST"), `uuid`(임의 UUID)
- 서명: P-256 키로 ECDSA 서명. 서명값은 DER이 아니라 r, s를 32바이트씩 이어 붙인 형식이어야 한다

여기에 `X-Platform: web` 헤더를 붙이고, 검색 조건에 `sort: SORT_CREATED_TIME`, `order: ORDER_DESC`, `status: [STATUS_ON_SALE]`을 주면 판매 중인 매물이 최신순으로 온다.

## 시험 결과

「ポーター タンカー」로 검색하니 200 응답과 함께 ID, 제목, 가격, 등록 시각, 썸네일 URL이 왔다.

## 겪은 것

- **메루카리 Shops 상품이 섞여 온다.** `itemType`이 `ITEM_TYPE_BEYOND`인 것들은 ID 형식이 `m123...`이 아니라 `2JZWMQ...` 같은 형태라서 Buyee 링크(`buyee.jp/mercari/item/{ID}`)를 만들 수 없다. 일단 걸러냈다.
- **최신순인데 순서가 살짝 섞인다.** 몇 주 전에 올라온 매물이 위쪽에 끼어 있었다. 순서를 믿지 않고, DB에 없는 ID인지로 신규를 판단하게 했다.
- **썸네일이 webp다.** URL 끝은 `.jpg`인데 실제 형식은 webp라서, 알림에 붙일 때 변환이 필요했다 ([002](002-mac-notification.md)).

## 남겨둔 대비책

- 실제 응답을 줄여서 `tests/fixtures/mercari_search.json`에 저장하고 파서 테스트를 돌린다. 판매자 정보는 빼고 매물 정보만 남겼다.
- 검색 결과가 0개면 로그에 경고를 남긴다. API가 바뀌었다는 신호일 수 있다.
- 비공식 API라 언제든 바뀔 수 있다. 바뀌면 `mercari.py`만 고치면 되도록 나눠뒀다.
