# Survey Stream

Survey Stream은 마케팅 리서치 설문지(DOCX)를 분석해 문항 정보를 추출하고, Table Guide와 Banner Spec을 생성하며, Script 구현/링크 테스트 전에 로직 리스크를 점검하는 Streamlit 앱입니다.

## 주요 기능

| 메뉴 | 목적 | 주요 산출물 |
| --- | --- | --- |
| Questionnaire Analyzer | DOCX 설문지 구조 파싱, AI 문항 추출, 추출 커버리지 점검 | 편집 가능한 문항 테이블, Analyzer Excel, 세션 JSON |
| Table Guide Builder | Study Brief 기반 Table Title/Banner 생성, DP 전달 명세 작성 | 내부 리뷰용 Table Guide Excel, DP Handoff Excel, CSV, Session JSON |
| Logic Checker | 스킵/필터/분기 로직과 Script/링크 테스트 확인 항목 점검 | 로직 시각화, 분기 테스트, 응답자 경로, 체크리스트 Excel |

## 사용자 워크플로우

1. 사이드바에서 `.docx` 설문지 또는 저장된 `.json` 세션 파일을 업로드합니다.
2. Questionnaire Analyzer에서 `AI로 문항 추출 시작`을 실행합니다.
3. DOCX Preflight와 추출 결과 점검을 확인하고, Spreadsheet에서 필요한 값을 수정합니다.
4. Table Guide Builder에서 Study Brief를 확인하고 Table Title 또는 Banner를 생성합니다.
5. 다운로드 탭에서 내부 리뷰용 Excel 또는 DP Handoff Excel을 내려받습니다.
6. Logic Checker에서 `QA 분석 실행` 후 Script 구현/링크 테스트 확인 항목을 Excel로 전달합니다.

## 핵심 처리 흐름

### Questionnaire Analyzer

- DOCX 섹션, 단락, 표, 병합 셀, 취소선, 텍스트박스, 표 유형을 파싱합니다.
- DOCX Preflight로 문항 후보, 문항유형 표기율, 보기표/매트릭스/일반표 리스크를 먼저 보여줍니다.
- 패턴 스캔과 AI 추출을 결합해 QuestionNumber, SourceVariable, QuestionText, QuestionType, AnswerOptions, Filter, SkipLogic, Instructions 등을 추출합니다.
- 추출 커버리지 리포트는 문항/보기/필터/스킵 로직/지시문 누락 가능성을 사용자 관점에서 요약합니다.
- Survey Intelligence가 조사 유형, 조사 목적, 주요 세그먼트를 추정해 후속 생성 단계에 전달합니다.

### Table Guide Builder

- Study Brief를 AI 추정값으로 프리필하고 사용자가 확정/수정할 수 있습니다.
- Table Title은 질문문만 요약하지 않고 SourceVariable, 문항 역할, 문항유형, 보기, 필터, 스킵/지시문, Survey Intelligence를 함께 사용합니다.
- Key Buying Factors, Purchase Intent, Aided Brand Awareness, Brand Consideration 같은 마케팅 리서치 표준 표현을 우선합니다.
- Banner 생성은 기본 인구통계와 조사 목적에 맞는 행동/태도/브랜드 세그먼트를 함께 제안합니다.
- DP Handoff Excel은 `Table Guide`, `Banner Spec` 2개 시트로 구성됩니다.
- 내부 리뷰용 Table Guide Excel은 Cover, Table Guide, Banner Spec, Banner Layout, Net Recode Spec, Answer Options 등을 포함합니다.

### Logic Checker

- LLM 없이 알고리즘으로 경로 시뮬레이션, 스킵 로직 그래프, 분기 테스트, 대표 응답자 경로, 체크리스트를 생성합니다.
- 확인 항목은 `설문지 수정 필요`, `Script 구현 확인`, `링크 테스트 확인` 업무 구분으로 정리됩니다.
- Excel 다운로드에는 Summary, Logic Map, Branch Test, Respondent Paths, Checklist, Unparsed 시트가 포함됩니다.

## 설치 및 실행

```bash
git clone <repository-url>
cd surveystreme

uv sync
cp .env.example .env
streamlit run app.py
```

## 환경 변수

```env
LITELLM_API_KEY=sk-your-litellm-api-key
LITELLM_BASE_URL=https://ipsos.litellm-prod.ai
```

## 프로젝트 구조

```text
app.py                    # Streamlit entry point, sidebar upload/session/navigation
models/
  survey.py               # SurveyQuestion, SurveyDocument, Banner, TableGuideDocument
pages/
  doc_analyzer.py         # Questionnaire Analyzer UI
  table_guide.py          # Table Guide Builder UI
  survey_qa.py            # Logic Checker UI
  user_guide.py           # Help & user guide dialog content
services/
  docx_parser.py          # DOCX structure parser
  docx_preflight.py       # DOCX readiness/preflight checks
  docx_renderer.py        # Annotated text renderer for extraction
  llm_extractor.py        # AI extraction pipeline
  postprocessor.py        # SummaryType/TableNumber post-processing
  coverage_checker.py     # Extraction coverage diagnostics
  coverage_user_summary.py # User-facing coverage summary
  survey_context.py       # Study context builder
  table_guide_service.py  # Table Guide/Banner/export services
  skip_logic_service.py   # Skip logic parser/graph helpers
  path_simulator.py       # Path simulation and branch scenarios
  prescripting_checker.py # Structural QA checks
  checklist_generator.py  # Link-test checklist generation
ui/
  spreadsheet.py          # Editable question table
  tree_view.py            # Optional detailed question cards
  download.py             # Analyzer CSV/Excel downloads
tests/
  smoke_test_*.py         # Smoke/regression tests
docs/
  *.md                    # Roadmap, quality notes, validation report
```

## 개발 검증

```powershell
.\.venv\Scripts\python.exe -B -c "import app; print('import OK')"

$tests = Get-ChildItem tests -Filter 'smoke_test_*.py' | Sort-Object Name
foreach ($t in $tests) { .\.venv\Scripts\python.exe -B $t.FullName }
```
