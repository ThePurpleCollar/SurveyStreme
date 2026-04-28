import os
import json
import sys
import streamlit as st
from streamlit_option_menu import option_menu
import logging

from pages.doc_analyzer import page_document_processing
from pages.table_guide import page_table_guide_builder
from pages.survey_qa import page_survey_qa
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


def _setup_hub_llm_logging():
    """Enable Ipsos AI Hub LLM usage logging when the Hub module is available."""
    hub_services_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "services")
    )
    if os.path.isdir(hub_services_dir) and hub_services_dir not in sys.path:
        sys.path.insert(0, hub_services_dir)

    try:
        import hub_llm_logger
        from hub_llm_logger import setup_llm_logging
    except Exception as e:
        logging.warning("Hub LLM logging unavailable: %s", e)
        return

    if getattr(hub_llm_logger, "_survey_stream_logging_configured", False):
        return

    # LLM 사용량 자동 로깅 — 서비스 업데이트 시 유지 필수
    setup_llm_logging(
        service_id=1,
        service_name="Survey Stream",
        get_user_id=lambda: st.session_state.get("auth_user", {}).get("id", "anonymous"),
    )
    setattr(hub_llm_logger, "_survey_stream_logging_configured", True)


# --- 페이지 설정 ---
st.set_page_config(
    page_title="Survey Stream",
    page_icon="🌊",
    layout="wide"
)

_setup_hub_llm_logging()
logging.info("User accessed the application.")


def init_gemini():
    """Legacy no-op; LLM clients initialize lazily in call sites."""
    return None

# --- 클라이언트 초기화 ---
init_gemini()  # Vertex AI SDK 초기화 (Gemini 모델 사용)


# --- User Guide 다이얼로그 ---
@st.dialog("User Guide", width="large")
def _show_user_guide():
    page_user_reference()


@st.dialog("⚠️ Overwrite Session?", width="small")
def _confirm_overwrite(filename: str, question_count: int):
    st.warning(
        f"현재 세션 **{filename}** ({question_count}개 문항)이 대체됩니다. "
        "저장하지 않은 변경사항은 사라집니다."
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("취소", use_container_width=True):
            st.rerun()
    with col2:
        if st.button("계속 진행", type="primary", use_container_width=True):
            st.session_state['_overwrite_confirmed'] = True
            st.rerun()


# --- 네비게이션 상수 ---
_PAGES = [
    "Questionnaire Analyzer",   # 0
    "Table Guide Builder",      # 1  (needs edited_df)
    "Logic Checker",             # 2  (needs survey_doc)
]

_ICONS_UNLOCKED = [
    'bi bi-magic',              # 0  Questionnaire Analyzer
    'bi bi-table',              # 1  Table Guide Builder
    'bi bi-shield-check',       # 2  Logic Checker
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
        "파일 업로드 (.docx / .json)",
        type=["docx", "json"],
    )

    if raw_upload is not None:
        # ── 세션 덮어쓰기 확인 ──
        _new_upload_key = f"{raw_upload.name}_{raw_upload.size}"
        _has_existing = 'survey_document' in st.session_state
        _is_same_file = (st.session_state.get('_loaded_session_key') == _new_upload_key)

        if _has_existing and not _is_same_file and not st.session_state.pop('_overwrite_confirmed', False):
            doc = st.session_state['survey_document']
            _confirm_overwrite(doc.filename, len(doc.questions))
            st.stop()

        ext = os.path.splitext(raw_upload.name)[1].lower()

        if ext == '.json':
            # ── JSON → 세션 복원 (최초 1회만) ──
            if st.session_state.get('_loaded_session_key') != _new_upload_key:
                try:
                    data = json.loads(raw_upload.getvalue().decode("utf-8"))
                    doc = SurveyDocument.from_json_dict(data)
                    st.session_state['survey_document'] = doc
                    st.session_state['edited_df'] = doc.to_dataframe()
                    st.session_state['uploaded_file_name'] = os.path.splitext(doc.filename)[0]
                    st.session_state['_loaded_session_key'] = _new_upload_key
                except Exception as e:
                    st.error(f"세션 복원 실패: {e}")
        else:
            # ── PDF/DOCX → 설문지 업로드 ──
            uploaded_file = raw_upload
            st.session_state['uploaded_file_name'] = os.path.splitext(raw_upload.name)[0]
            st.session_state['_loaded_session_key'] = _new_upload_key
            output_folder = 'output'
            if not os.path.exists(output_folder):
                os.makedirs(output_folder)
            output_path = os.path.join(output_folder, raw_upload.name)
            with open(output_path, 'wb') as f:
                f.write(raw_upload.getbuffer())

    # ── 문서 상태 뱃지 + Save Session ──
    if 'survey_document' in st.session_state:
        doc = st.session_state['survey_document']
        st.success(f"**{doc.filename}** — {len(doc.questions)}개 문항")
        st.download_button(
            label="세션 저장",
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
        icons[1] = 'bi bi-lock'       # Table Guide Builder
    if not has_survey_doc:
        icons[2] = 'bi bi-lock'       # Survey QA

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
    if st.button("도움말 & 사용자 가이드", use_container_width=True):
        _show_user_guide()

# ============================================================
# 페이지 라우팅
# ============================================================
if page == 'Questionnaire Analyzer':
    page_document_processing(uploaded_file)
    render_download_buttons("Questionnaire Analyzer", include_excel=True)

elif page == 'Table Guide Builder':
    page_table_guide_builder()

elif page == 'Logic Checker':
    page_survey_qa()
