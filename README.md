# Survey Stream

설문지(DOCX) 자동 분석 플랫폼 — 문항 추출, Table Guide 생성, 로직 검증을 하나의 워크플로우로.

## Features

| Feature | Description | LLM |
|---------|-------------|-----|
| **Questionnaire Analyzer** | DOCX → AI 문항 추출 (5-phase pipeline) + 커버리지 리포트 | Gemini 2.5 Pro |
| **Table Guide Builder** | Table Title + Banner 생성 + DP용 엑셀 출력 | Gemini 2.5 Pro |
| **Logic Checker** | 로직 시각화 + 분기 테스트 + 체크리스트 통합 | None (algorithmic) |

## Tech Stack

- **Runtime**: Python 3.11+
- **UI Framework**: Streamlit 1.44+
- **Package Manager**: uv
- **LLM**: Gemini 2.5 Pro (extraction, titles, banners), Gemini 2.5 Flash (checklist, grammar), GPT-5 (quality)
- **LLM Proxy**: LiteLLM (Ipsos internal)
- **Key Libraries**: python-docx, pandas, openai, openpyxl, google-cloud-aiplatform

## Installation

```bash
git clone <repository-url>
cd surveystreme

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your API credentials

# Run application
streamlit run app.py
```

## Configuration

```
LITELLM_API_KEY=sk-your-litellm-api-key
LITELLM_BASE_URL=https://ipsos.litellm-prod.ai
```

## Project Structure

```
app.py                  # Main entry + 3-menu sidebar
models/
  survey.py             # SurveyQuestion, SurveyDocument, Banner, ProgrammingGuide
services/
  llm_client.py         # LLM gateway (Gemini + GPT, retry, safety filter)
  llm_extractor.py      # LLM-first extraction (concept-based prompting)
  docx_parser.py        # DOCX parsing (merged cells, strikethrough, table classifier)
  docx_renderer.py      # Annotated text with type markers
  chunker.py            # Metadata-based chunking (dual-track)
  postprocessor.py      # SummaryType, TableNumber
  coverage_checker.py   # Extraction coverage verification
  prescripting_checker.py # Structural validation (codes, skip targets, filters)
  table_guide_service.py # Table Guide (expert consensus banners)
  path_simulator.py     # Path simulation + test scenarios
  checklist_generator.py # Link-test checklist (step-by-step + negative)
  skip_logic_service.py # Skip logic graph + Graphviz DOT
  survey_context.py     # Study Brief context builder
pages/
  doc_analyzer.py       # Questionnaire Analyzer UI
  table_guide.py        # Table Guide Builder UI
  survey_qa.py          # Logic Checker UI
ui/
  tree_view.py          # Question tree view
  spreadsheet.py        # Editable data editor
  download.py           # CSV/Excel download (Banner Layout sheet)
tests/                  # Smoke tests (16)
docs/                   # Roadmap + task specs
```

## Workflow

```
1. Questionnaire Analyzer
   DOCX 업로드 → AI 문항 추출 → 커버리지 리포트 → 세션 저장

2. Table Guide Builder
   Study Brief 확인 → Table Title + Banner 생성 → DP용 엑셀 다운로드

3. Logic Checker
   QA 분석 실행 → 로직 시각화 + 분기 테스트 + 체크리스트 → 엑셀 다운로드
```

## Development

- See `CLAUDE.md` for coding conventions
- See `docs/roadmap.md` for task tracking
- Run verification: `python -c "from app import *; print('import OK')"`
- Run tests: `python -m pytest tests/ -v`
