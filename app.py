import os
import json
import streamlit as st
from streamlit_option_menu import option_menu
import logging

from services.llm_client import init_client, init_gemini
from pages.doc_analyzer import page_document_processing
from pages.table_guide import page_table_guide_builder
from pages.quality_checker import page_quality_checker
from pages.length_estimator import page_length_estimator
from pages.skip_logic_visualizer import page_skip_logic_visualizer
from pages.path_simulator import page_path_simulator
from pages.checklist_generator import page_checklist_generator
from pages.user_guide import page_user_reference
from models.survey import SurveyDocument
from ui.download import render_download_buttons

# --- 로깅 설정 ---
LOG_FILE = "access.log"
if not os.path.exists('output'):
    os.makedirs('output')
log_file_path = os.path.join('output', LOG_FILE)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, mode='a', encoding='utf-8'),
    ]
)

# --- 페이지 설정 ---
st.set_page_config(
    page_title="Survey Stream",
    page_icon="🌊",
    layout="wide"
)

logging.info("User accessed the application.")

# --- 클라이언트 초기화 ---
client = init_client()
init_gemini()  # Vertex AI SDK 초기화 (Gemini 모델 사용)


# --- User Guide 다이얼로그 ---
@st.dialog("User Guide", width="large")
def _show_user_guide():
    page_user_reference()


# --- 네비게이션 상수 ---
# 그룹 1: 문항 추출
# 그룹 2: Table Guide (단독)
# 그룹 3: 내용 검토 (Quality + Grammar 통합 → Length)
# 그룹 4: 구조 분석 & 검수 (Skip Logic → Path Simulator → Checklist)
_PAGES = [
    "Questionnaire Analyzer",   # 0
    "---",                      # 1
    "Table Guide Builder",      # 2  (needs edited_df)
    "---",                      # 3
    "Quality Checker",          # 4  (needs survey_doc; Grammar 포함)
    "Length Estimator",         # 5  (needs survey_doc)
    "---",                      # 6
    "Skip Logic",               # 7  (needs survey_doc)
    "Path Simulator",           # 8  (needs survey_doc)
    "Checklist",                # 9  (needs survey_doc)
]

_ICONS_UNLOCKED = [
    'bi bi-magic',              # 0  Questionnaire Analyzer
    None,                       # 1  ---
    'bi bi-table',              # 2  Table Guide Builder
    None,                       # 3  ---
    'bi bi-shield-check',       # 4  Quality Checker
    'bi bi-stopwatch',          # 5  Length Estimator
    None,                       # 6  ---
    'bi bi-diagram-3',          # 7  Skip Logic
    'bi bi-signpost-split',     # 8  Path Simulator
    'bi bi-list-check',         # 9  Checklist
]

# ============================================================
# 사이드바
# ============================================================
uploaded_file = None  # 페이지 라우팅에서 사용 (PDF/DOCX만 해당)

with st.sidebar:
    # ── 타이틀 ──
    st.markdown(
        "<h2 style='margin-bottom:0;'>🌊 Survey Stream</h2>",
        unsafe_allow_html=True,
    )

    # ── 파일 업로드 (단일: 설문지 + 세션 통합) ──
    raw_upload = st.file_uploader(
        "Upload file (.pdf / .docx / .json)",
        type=["pdf", "docx", "json"],
    )

    if raw_upload is not None:
        ext = os.path.splitext(raw_upload.name)[1].lower()

        if ext == '.json':
            # ── JSON → 세션 복원 (최초 1회만) ──
            _load_key = f"{raw_upload.name}_{raw_upload.size}"
            if st.session_state.get('_loaded_session_key') != _load_key:
                try:
                    data = json.loads(raw_upload.getvalue().decode("utf-8"))
                    doc = SurveyDocument.from_json_dict(data)
                    st.session_state['survey_document'] = doc
                    st.session_state['edited_df'] = doc.to_dataframe()
                    st.session_state['uploaded_file_name'] = os.path.splitext(doc.filename)[0]
                    st.session_state['_loaded_session_key'] = _load_key
                except Exception as e:
                    st.error(f"Failed to load session: {e}")
        else:
            # ── PDF/DOCX → 설문지 업로드 ──
            uploaded_file = raw_upload
            st.session_state['uploaded_file_name'] = os.path.splitext(raw_upload.name)[0]
            output_folder = 'output'
            if not os.path.exists(output_folder):
                os.makedirs(output_folder)
            output_path = os.path.join(output_folder, raw_upload.name)
            with open(output_path, 'wb') as f:
                f.write(raw_upload.getbuffer())

    # ── 문서 상태 뱃지 + Save Session ──
    if 'survey_document' in st.session_state:
        doc = st.session_state['survey_document']
        st.success(f"**{doc.filename}** — {len(doc.questions)} questions")
        st.download_button(
            label="Save Session",
            data=doc.to_json_bytes(),
            file_name=f"{os.path.splitext(doc.filename)[0]}_session.json",
            mime='application/json',
            use_container_width=True,
        )

    st.divider()

    # ── 네비게이션 메뉴 ──
    has_edited_df = 'edited_df' in st.session_state
    has_survey_doc = 'survey_document' in st.session_state

    icons = list(_ICONS_UNLOCKED)
    if not has_edited_df:
        icons[2] = 'bi bi-lock'       # Table Guide Builder
    if not has_survey_doc and not has_edited_df:
        icons[4] = 'bi bi-lock'       # Quality Checker (어느 한쪽이라도 있으면 탭 일부 사용 가능)
    if not has_survey_doc:
        icons[5] = 'bi bi-lock'       # Length Estimator
        icons[7] = 'bi bi-lock'       # Skip Logic
        icons[8] = 'bi bi-lock'       # Path Simulator
        icons[9] = 'bi bi-lock'       # Checklist

    page = option_menu(
        None,
        _PAGES,
        icons=icons,
        default_index=0,
        styles={
            "container": {"padding": "4!important", "background-color": "#fafafa"},
            "icon": {"color": "black", "font-size": "20px"},
            "nav-link": {
                "font-size": "15px",
                "text-align": "left",
                "margin": "0px",
                "--hover-color": "#fafafa",
            },
            "nav-link-selected": {"background-color": "#08c7b4"},
        },
    )

    # "---" 선택 방어
    if page == "---":
        page = st.session_state.get('last_valid_page', 'Questionnaire Analyzer')
    else:
        st.session_state['last_valid_page'] = page

    st.divider()

    # ── 하단 도움말 ──
    if st.button("Help & User Guide", use_container_width=True):
        _show_user_guide()

# ============================================================
# 페이지 라우팅
# ============================================================
if page == 'Questionnaire Analyzer':
    page_document_processing(uploaded_file, client)
    render_download_buttons("Questionnaire Analyzer", include_excel=True)

elif page == 'Table Guide Builder':
    page_table_guide_builder()

elif page == 'Quality Checker':
    page_quality_checker()

elif page == 'Length Estimator':
    page_length_estimator()

elif page == 'Skip Logic':
    page_skip_logic_visualizer()

elif page == 'Path Simulator':
    page_path_simulator()

elif page == 'Checklist':
    page_checklist_generator()
