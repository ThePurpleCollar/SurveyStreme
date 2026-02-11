# Survey Stream (questvoyager)

설문지(PDF/DOCX) 자동 분석 및 Table Guide 생성 Streamlit 웹앱.

## Tech Stack
- Python 3.11+, Streamlit, Poetry
- LLM: Gemini 2.5 Pro (문항 추출), GPT-5 (Title/Grammar/Quality), GPT-4.1-mini (Length/Checklist)
- LLM 프록시: LiteLLM (Ipsos 내부)
- 주요 라이브러리: python-docx, PyMuPDF, pandas, openai, openpyxl

## Project Structure
```
app.py                    # 메인 진입점 + 사이드바 + 페이지 라우팅
pages/                    # UI 페이지 (doc_analyzer, table_guide, quality_checker 등)
services/                 # 비즈니스 로직 (llm_client, llm_extractor, docx_parser 등)
models/                   # 데이터 모델 (SurveyQuestion, SurveyDocument)
ui/                       # UI 컴포넌트 (tree_view, spreadsheet, download)
```

## Coding Conventions
- 함수/변수: snake_case, 클래스: PascalCase
- private 함수: `_` 접두사 (예: `_parse_paragraph`)
- docstring: 한국어 또는 영어 (기존 파일의 언어를 따름)
- 타입 힌트: 모든 함수 시그니처에 사용
- import 순서: stdlib → third-party → local
- Streamlit 세션 상태 키: snake_case 문자열 (예: `"survey_document"`, `"edited_df"`)

## Critical Rules
- `st.session_state`에 저장되는 핵심 객체는 반드시 `SurveyDocument` 타입을 사용할 것
- LLM 호출은 반드시 `services/llm_client.py`의 `call_llm()` 또는 `call_llm_json()`을 경유할 것
- 새 LLM 프롬프트 작성 시 한국어/영어 양쪽 버전 모두 작성할 것
- UI 코드에 비즈니스 로직을 넣지 말 것 (pages/ → services/ 호출 구조 유지)
- `.env` 파일에 있는 API 키를 코드에 하드코딩하지 말 것

## Verification (Definition of Done)
모든 변경 작업 완료 후 아래를 반드시 실행:
1. `python -c "from app import *; print('import OK')"` — 전체 import 체인 확인
2. `python -m pytest tests/ -v` — 테스트 존재 시 실행
3. 변경된 파일에 대해 `python -m py_compile <file>` — 문법 오류 확인
4. 관련 함수에 대해 간단한 smoke test 스크립트 작성 후 실행

## Task Workflow
작업 흐름은 `docs/roadmap.md`에서 관리. 자세한 내용은 @docs/roadmap.md 참조.
개별 작업의 상세 스펙은 @docs/tasks/ 폴더의 파일 참조.
