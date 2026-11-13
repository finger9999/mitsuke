# 007. 채점 LLM을 Gemini로 바꿈

2026-11-14 · 관련 파일: [finder/scorer.py](../../finder/scorer.py), [config.yaml](../../config.yaml)

## 결정

사용자가 API 키를 Gemini로 쓰겠다고 했다. 005에서 Claude Haiku 5.5로 만든 채점기를 Google Gemini로 바꿨다. 파이프라인, 비용 상한, 아우터만 채점하는 구조는 그대로다.

## 모델 고르기

Google 공식 가격표(2026-11-14 확인)에서 이미지 입력을 받고 무료 등급이 있는 싼 모델:

| 모델 | 유료 가격 (입력 / 출력, 100만 토큰당) | 비고 |
| --- | --- | --- |
| `gemini-2.5-flash-lite` | $0.10 / $0.40 | 가장 쌈. 같은 2.5 세대의 flash·pro는 이미 지원 중단(deprecated) 공지 |
| **`gemini-3.1-flash-lite`** (기본) | $0.25 / $1.50 | 현행 세대 |

둘 다 **무료 등급**이 있다. 지금 물량(채점 대상이 하루 몇 개)이면 무료 등급 안에서 끝날 가능성이 높다. 2.5 세대가 정리되는 중이라 기본값은 3.1 flash-lite로 하고, `config.yaml`의 `gemini_model`로 2.5 flash-lite를 고를 수 있게 했다.

무료 등급 데이터는 Google이 제품 개선에 쓸 수 있다는 조건이 붙는다. 매물 사진·제목·취향 기준 정도라 문제는 적다고 봤다.

## Claude 버전과 달라진 점

| | Claude (005) | Gemini (지금) |
| --- | --- | --- |
| SDK | `anthropic` | `google-genai` |
| 사진 | URL을 그대로 넘김 | URL을 못 받아서 썸네일(7KB)을 받아 바이트로 넘김 |
| JSON 출력 | `output_config.format` | `response_mime_type` + `response_json_schema` |
| 생각 줄이기 | `effort: low` | `thinking_level: MINIMAL` (모델이 거부하면 설정 없이 재시도) |
| 비용 계산 | 입력·출력 토큰 | 입력 + 출력 + 생각 토큰. 유료 가격 기준이라 무료 등급이면 실제 청구는 0 |
| 키 | 키체인 `mitsuke-anthropic` | 키체인 `mitsuke-gemini` / `GEMINI_API_KEY` |

## 확인 상태

- 단위 테스트는 가짜 채점기를 써서 그대로 통과.
- 실제 Gemini 호출은 키를 넣은 뒤 `reevaluate`로 확인한다.
