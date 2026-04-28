# Survey Stream

설문지(DOCX) 자동 분석, Table Guide 생성, 로직 검증 Streamlit 웹앱.
입소스 한국 리서처를 위한 MR 워크플로우 효율화 도구.

## Tech Stack
- Python 3.11+, Streamlit, uv
- LLM: Gemini 2.5 Pro (문항 추출, Title, Banner), Gemini 2.5 Flash (체크리스트, 문법), GPT-5 (품질 분석)
- LLM 프록시: LiteLLM (Ipsos 내부)
- 주요 라이브러리: python-docx, pandas, openai, openpyxl, google-cloud-aiplatform
- DOCX-only 파이프라인 (PDF 스코프 제외, 2026-03)

## App Structure (3 메뉴)
```
Questionnaire Analyzer    # 설문지 업로드 → AI 문항 추출 → 커버리지 리포트
Table Guide Builder       # Table Title + Banner 생성 → DP용 엑셀 출력
Logic Checker             # 로직 시각화 + 분기 테스트 + 체크리스트 통합
```

## Project Structure
```
app.py                    # 메인 진입점 + 사이드바 (3메뉴) + 페이지 라우팅
pages/
  doc_analyzer.py         # Questionnaire Analyzer UI
  table_guide.py          # Table Guide Builder UI (Title + Banner + Export)
  survey_qa.py            # Logic Checker UI (시각화 + 분기 + 체크리스트)
legacy_pages/             # 라우팅 제외된 참고/실험 페이지
services/
  llm_client.py           # LLM 게이트웨이 (Gemini/GPT, 재시도, Safety Filter 해제)
  llm_extractor.py        # LLM 문항 추출 파이프라인 (Concept-based Prompting)
  docx_parser.py          # DOCX 파싱 (병합 셀, 취소선, 표 분류, 텍스트 박스)
  docx_renderer.py        # 어노테이션 텍스트 변환 (타입별 마커)
  chunker.py              # 메타데이터 기반 청킹 (Dual-Track)
  postprocessor.py        # SummaryType, TableNumber 계산
  coverage_checker.py     # 추출 커버리지 검증 (원본 vs 추출 비교)
  prescripting_checker.py # 구조 검증 (코드 중복, 스킵 대상, 필터 참조)
  table_guide_service.py  # Table Guide 생성 (전문가 합의 배너)
  path_simulator.py       # 경로 시뮬레이션 + 테스트 시나리오
  checklist_generator.py  # 체크리스트 생성 (step-by-step + Negative)
  skip_logic_service.py   # 스킵 로직 그래프 + Graphviz DOT
  survey_context.py       # Study Brief 컨텍스트 빌더
models/
  survey.py               # SurveyQuestion, SurveyDocument, Banner, ProgrammingGuide
ui/
  tree_view.py            # 문항 트리뷰
  spreadsheet.py          # 편집 테이블
  download.py             # CSV/Excel 다운로드 (Banner Layout 포함)
ground_truth/             # 사람이 검수한 추출 정답셋
scripts/
  evaluate_extraction.py  # Ground Truth vs 추출 세션 품질 평가
  promote_ground_truth.py # 세션 JSON → Ground Truth 후보 생성
  run_smoke_tests.py      # pytest 없이 smoke_test_*.py 실행
```

## Coding Conventions
- 함수/변수: snake_case, 클래스: PascalCase
- private 함수: `_` 접두사
- UI 메시지: 한국어 (메뉴명/기능명은 영어 유지)
- 타입 힌트: 모든 함수 시그니처에 사용
- import 순서: stdlib → third-party → local
- UI 코드에 비즈니스 로직을 넣지 말 것 (pages/ → services/ 호출 구조 유지)

## Critical Rules
- `st.session_state`에 저장되는 핵심 객체는 반드시 `SurveyDocument` 타입
- LLM 호출은 반드시 `services/llm_client.py`의 `call_llm()` 또는 `call_llm_json()` 경유
- `.env` 파일의 API 키를 코드에 하드코딩 금지
- Gemini Safety Filter는 BLOCK_NONE으로 해제 (NDA/PII 설문지 지원)

## Verification
1. `python -c "from app import *; print('import OK')"` — import 체인 확인
2. `python -m pytest tests/ -v` — 테스트 실행
3. `python -m py_compile <file>` — 문법 오류 확인
