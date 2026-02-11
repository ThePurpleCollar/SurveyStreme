# QuestVoyager (Survey Stream)

Streamlit-based survey questionnaire analysis platform for automated question extraction, Table Guide generation, and quality assurance.

## Features

| Feature | Description | LLM |
|---------|-------------|-----|
| **Questionnaire Analyzer** | PDF/DOCX question extraction with 5-phase pipeline | Gemini 2.5 Pro |
| **Intelligence Dashboard** | Survey overview metrics, flow diagrams, distributions | None (algorithmic) |
| **Table Guide Builder** | 6-tab cross-tabulation guide with expert consensus banners | GPT-5 |
| **Quality Checker** | 6-category issue detection + grammar correction | GPT-5 |
| **Length Estimator** | Cognitive-load-based survey completion time estimation | GPT-4.1-mini |
| **Translation Helper** | Multi-language translation (14 languages) preserving MR terminology | GPT-5 |
| **Skip Logic Visualizer** | Graphviz flow diagram of skip/branch logic | None (algorithmic) |
| **Path Simulator** | DFS path enumeration, test scenarios, interactive tracer | None (algorithmic) |
| **Checklist Generator** | Link-test checklist (5 algorithmic + 1 LLM check) | GPT-4.1-mini |
| **Piping Intelligence** | Piping/filter dependency detection with bottleneck analysis | GPT-5 (optional) |

## Tech Stack

- **Runtime**: Python 3.11+
- **UI Framework**: Streamlit 1.44+
- **Package Manager**: Poetry
- **LLM**: Gemini 2.5 Pro (extraction), GPT-5 (enrichment), GPT-4.1-mini (utilities)
- **LLM Proxy**: LiteLLM (Ipsos internal)
- **Key Libraries**: python-docx, PyMuPDF, pandas, openai, openpyxl, google-cloud-aiplatform

## Installation

```bash
# Clone repository
git clone <repository-url>
cd questvoyager

# Install dependencies
poetry install

# Configure environment
cp .env.example .env
# Edit .env with your API credentials

# Run application
streamlit run app.py
```

## Configuration

Create a `.env` file (see `.env.example`):

```
LITELLM_API_KEY=sk-your-litellm-api-key
LITELLM_BASE_URL=https://ipsos.litellm-prod.ai
```

## Project Structure

```
app.py                  # Main entry point + sidebar navigation + session management
models/
  survey.py             # Data models (SurveyQuestion, SurveyDocument, Banner, etc.)
services/
  llm_client.py         # Unified LLM gateway (Gemini + GPT dispatch)
  llm_extractor.py      # LLM-first question extraction pipeline
  table_guide_service.py # Table Guide generation (6 phases + expert consensus)
  quality_checker.py    # 6-category survey quality analysis
  grammar_checker.py    # Batch grammar correction
  length_estimator.py   # Cognitive-load LOI estimation
  translation_service.py # Multi-language translation
  skip_logic_service.py # Skip logic graph building
  path_simulator.py     # DFS path enumeration + test scenarios
  checklist_generator.py # Link-test checklist (algorithmic + LLM)
  piping_service.py     # Piping/filter dependency analysis
  survey_context.py     # Shared survey context builder
  docx_parser.py        # DOCX parsing with format metadata
  docx_renderer.py      # DOCX-to-annotated-text for LLM
  pdf_parser.py         # PDF text extraction (PyMuPDF)
  postprocessor.py      # SummaryType, TableNumber assignment
  chunker.py            # Document chunking (question-boundary)
pages/
  doc_analyzer.py       # Questionnaire Analyzer UI
  intelligence_dashboard.py # Intelligence Dashboard UI
  table_guide.py        # Table Guide Builder UI (6 tabs)
  quality_checker.py    # Quality Checker UI (2 tabs)
  length_estimator.py   # Length Estimator UI
  translation_helper.py # Translation Helper UI
  skip_logic_visualizer.py # Skip Logic Visualizer UI
  path_simulator.py     # Path Simulator UI (3 tabs)
  checklist_generator.py # Checklist Generator UI
  piping_intelligence.py # Piping Intelligence UI
  user_guide.py         # User Guide documentation page
ui/
  tree_view.py          # Hierarchical question tree view
  spreadsheet.py        # Editable data editor view
  download.py           # CSV/Excel download + multi-sheet export
tests/                  # Smoke tests
docs/                   # Roadmap + task specs
```

## Development

- See `CLAUDE.md` for coding conventions
- See `docs/roadmap.md` for task tracking
- Run verification: `python -c "from app import *; print('import OK')"`
- Run tests: `python -m pytest tests/ -v`

## Development Status

**Completed**: Phase 1-6 (18/21 tasks)
**In Progress**: Phase 3 partial (TASK-09, TASK-10)
**Planned**: Phase 4 (architecture), Phase 7 (reliability)

See `docs/roadmap.md` for detailed status.
