"""Checklist Generator UI 페이지.

설문지 문항을 분석하여 링크테스트 체크리스트를 생성한다.
알고리즘 검사(즉시) + LLM 검사(배치 처리).
"""

import io
import pandas as pd
import streamlit as st

from services.llm_client import MODEL_CHECKLIST_GENERATOR
from services.checklist_generator import (
    generate_checklist,
    ChecklistResult,
    ChecklistItem,
    CATEGORIES,
    PRIORITIES,
    CATEGORY_LABELS,
    PRIORITY_LABELS,
)
from typing import List


def page_checklist_generator():
    st.title("Checklist")

    # Guard clause
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            '먼저 Questionnaire Analyzer에서 문서를 처리해주세요.',
        )
        return

    survey_doc = st.session_state["survey_document"]
    questions = survey_doc.questions
    if not questions:
        st.warning("문서에서 문항을 찾을 수 없습니다.")
        return

    st.info(
        f"**{survey_doc.filename}**에서 **{len(questions)}**개 문항을 발견했습니다. "
        "언어를 선택하고 **체크리스트 생성** 버튼을 클릭하세요.",
    )

    # Controls
    ctrl_col1, ctrl_col2 = st.columns([1, 3])
    with ctrl_col1:
        language = st.selectbox(
            "언어",
            options=["ko", "en"],
            format_func=lambda x: "한국어" if x == "ko" else "English",
            key="checklist_language",
        )
    with ctrl_col2:
        st.write("")
        st.write("")
        generate_clicked = st.button("체크리스트 생성", type="primary")

    # Generate
    if generate_clicked:
        with st.status("체크리스트 생성 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()
            batch_done = [0]
            total_batches = [1]

            def _progress_callback(event: str, data: dict):
                if event == "phase":
                    if data["status"] == "start":
                        if data["name"] == "algorithmic":
                            log_area.text("알고리즘 검사 실행 중...")
                        elif data["name"] == "llm":
                            log_area.text("LLM 분석 실행 중 (파이핑 & 척도)...")
                            progress_bar.progress(0.3)
                    elif data["status"] == "done":
                        if data["name"] == "algorithmic":
                            log_area.text(f"알고리즘 검사 완료 ({data['count']}건)")
                            progress_bar.progress(0.3)
                        elif data["name"] == "llm":
                            progress_bar.progress(1.0)
                elif event == "batch_start":
                    total_batches[0] = data["total_batches"]
                    log_area.text(
                        f"LLM 배치 {data['batch_index'] + 1}/{data['total_batches']} "
                        f"({data['question_count']}개 문항)..."
                    )
                elif event == "batch_done":
                    batch_done[0] += 1
                    progress = 0.3 + (batch_done[0] / total_batches[0]) * 0.7
                    progress_bar.progress(min(progress, 1.0))

            result = generate_checklist(
                questions=questions,
                language=language,
                model=MODEL_CHECKLIST_GENERATOR,
                progress_callback=_progress_callback,
            )
            st.session_state["checklist_result"] = result

            status.update(
                label=f"완료! {len(result.items)}건의 체크리스트 항목 생성됨.",
                state="complete",
            )

    # Results
    if "checklist_result" not in st.session_state:
        return

    result: ChecklistResult = st.session_state["checklist_result"]
    lang = result.language

    if not result.items:
        st.success("체크리스트 분석 완료 — 설문에서 이슈가 감지되지 않았습니다.")
        return

    st.divider()

    # Dashboard
    _render_dashboard(result, lang)

    st.divider()

    # Category distribution chart
    _render_category_chart(result, lang)

    st.divider()

    # Filters
    filtered_items = _render_filters(result, lang)

    # Detail table
    _render_detail_table(filtered_items, lang)

    # Excel download
    _render_download(result)


def _render_dashboard(result: ChecklistResult, lang: str):
    """요약 메트릭 4칸."""
    priority_counts = result.count_by_priority()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 항목", len(result.items))
    with col2:
        st.metric(
            PRIORITY_LABELS[lang].get("HIGH", "High"),
            priority_counts.get("HIGH", 0),
        )
    with col3:
        st.metric(
            PRIORITY_LABELS[lang].get("MEDIUM", "Medium"),
            priority_counts.get("MEDIUM", 0),
        )
    with col4:
        st.metric(
            PRIORITY_LABELS[lang].get("LOW", "Low"),
            priority_counts.get("LOW", 0),
        )


def _render_category_chart(result: ChecklistResult, lang: str):
    """카테고리별 분포 막대 차트."""
    st.subheader("카테고리 분포")

    cat_counts = result.count_by_category()
    cat_labels = CATEGORY_LABELS.get(lang, CATEGORY_LABELS["en"])

    max_count = max(cat_counts.values()) if cat_counts else 1
    has_items = False

    for cat in CATEGORIES:
        count = cat_counts.get(cat, 0)
        if count == 0:
            continue
        has_items = True
        label = cat_labels.get(cat, cat)
        col_label, col_bar, col_count = st.columns([2, 6, 1])
        with col_label:
            st.text(label)
        with col_bar:
            st.progress(count / max_count if max_count > 0 else 0)
        with col_count:
            st.text(str(count))

    if not has_items:
        st.caption("표시할 항목이 없습니다.")


def _render_filters(result: ChecklistResult, lang: str) -> List[ChecklistItem]:
    """필터 UI + 필터 적용."""
    cat_labels = CATEGORY_LABELS.get(lang, CATEGORY_LABELS["en"])
    pri_labels = PRIORITY_LABELS.get(lang, PRIORITY_LABELS["en"])

    col1, col2 = st.columns(2)
    with col1:
        selected_priorities = st.multiselect(
            "우선순위 필터",
            options=PRIORITIES,
            default=PRIORITIES,
            format_func=lambda x: pri_labels.get(x, x),
            key="checklist_filter_priority",
        )
    with col2:
        # 실제 존재하는 카테고리만 표시
        existing_cats = [cat for cat in CATEGORIES
                         if any(i.category == cat for i in result.items)]
        selected_categories = st.multiselect(
            "카테고리 필터",
            options=existing_cats,
            default=existing_cats,
            format_func=lambda x: cat_labels.get(x, x),
            key="checklist_filter_category",
        )

    filtered = [
        item for item in result.items
        if item.priority in selected_priorities and item.category in selected_categories
    ]
    return filtered


def _render_detail_table(items: List[ChecklistItem], lang: str):
    """체크리스트 상세 테이블."""
    st.subheader(f"체크리스트 항목 ({len(items)}건)")

    if not items:
        st.info("현재 필터에 해당하는 항목이 없습니다.")
        return

    cat_labels = CATEGORY_LABELS.get(lang, CATEGORY_LABELS["en"])
    pri_labels = PRIORITY_LABELS.get(lang, PRIORITY_LABELS["en"])

    rows = []
    for item in items:
        rows.append({
            "#": item.item_id,
            "Category": cat_labels.get(item.category, item.category),
            "Priority": pri_labels.get(item.priority, item.priority),
            "Q#": item.question_number,
            "Title": item.title,
            "Detail": item.detail,
            "Expected Behavior": item.expected_behavior,
            "Source": item.source,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "#": st.column_config.NumberColumn("#", width="small"),
            "Category": st.column_config.TextColumn("Category", width="small"),
            "Priority": st.column_config.TextColumn("Priority", width="small"),
            "Q#": st.column_config.TextColumn("Q#", width="small"),
            "Title": st.column_config.TextColumn("Title", width="medium"),
            "Detail": st.column_config.TextColumn("Detail", width="large"),
            "Expected Behavior": st.column_config.TextColumn("Expected", width="large"),
            "Source": st.column_config.TextColumn("Source", width="small"),
        },
    )


def _render_download(result: ChecklistResult):
    """Excel 다운로드."""
    cat_labels = CATEGORY_LABELS.get(result.language, CATEGORY_LABELS["en"])
    pri_labels = PRIORITY_LABELS.get(result.language, PRIORITY_LABELS["en"])

    rows = []
    for item in result.items:
        rows.append({
            "#": item.item_id,
            "Category": cat_labels.get(item.category, item.category),
            "Priority": pri_labels.get(item.priority, item.priority),
            "Question": item.question_number,
            "Title": item.title,
            "Detail": item.detail,
            "Expected Behavior": item.expected_behavior,
            "Source": item.source,
        })

    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name="Checklist")
    buffer.seek(0)

    st.download_button(
        label="체크리스트 다운로드 (Excel)",
        data=buffer,
        file_name="link_test_checklist.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
