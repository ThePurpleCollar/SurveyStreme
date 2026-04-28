"""Survey Length Estimator UI 페이지.

Questionnaire Analyzer에서 추출된 SurveyDocument의 문항들을
LLM으로 분석하여 소요 시간 대시보드 + 상세 테이블로 표시한다.
"""

import streamlit as st
import pandas as pd

from services.llm_client import MODEL_LENGTH_ESTIMATOR
from services.length_estimator import (
    estimate_survey_length,
    SurveyLengthResult,
    COGNITIVE_TASK_LABELS,
)


def page_length_estimator():
    st.title("Length Estimator")

    # Guard clause: survey_document 없으면 안내
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            '먼저 Questionnaire Analyzer에서 문서를 처리해주세요.',
            icon="⚠️",
        )
        return

    survey_doc = st.session_state["survey_document"]
    questions = survey_doc.questions
    if not questions:
        st.warning("문서에서 문항을 찾을 수 없습니다.", icon="⚠️")
        return

    st.info(
        f"**{survey_doc.filename}**에서 **{len(questions)}**개 문항을 발견했습니다. "
        "언어를 선택하고 **소요 시간 추정** 버튼을 클릭하세요.",
        icon="ℹ️",
    )

    # ── 컨트롤 영역 ──
    ctrl_col1, ctrl_col2 = st.columns([1, 3])
    with ctrl_col1:
        language = st.selectbox(
            "분석 언어",
            options=["ko", "en"],
            format_func=lambda x: "한국어" if x == "ko" else "English",
            key="length_language_select",
        )
    with ctrl_col2:
        st.write("")  # spacing
        st.write("")
        estimate_clicked = st.button("소요 시간 추정", type="primary")

    # ── 분석 실행 ──
    if estimate_clicked:
        with st.status("설문 소요 시간 추정 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()
            batch_done_count = [0]
            total_batches = [1]

            def _progress_callback(event: str, data: dict):
                if event == "batch_start":
                    total_batches[0] = data["total_batches"]
                    log_area.text(
                        f"배치 {data['batch_index'] + 1}/{data['total_batches']} 처리 중 "
                        f"({data['question_count']}개 문항)..."
                    )
                elif event == "batch_done":
                    total_batches[0] = data["total_batches"]
                    batch_done_count[0] += 1
                    progress = batch_done_count[0] / total_batches[0]
                    progress_bar.progress(progress)
                    log_area.text(
                        f"배치 {data['batch_index'] + 1}/{data['total_batches']} 완료"
                    )

            result = estimate_survey_length(
                questions=questions,
                model=MODEL_LENGTH_ESTIMATOR,
                language=language,
                progress_callback=_progress_callback,
            )
            st.session_state["length_result"] = result
            st.session_state["length_language"] = language

            total_min = result.total_seconds // 60
            total_sec = result.total_seconds % 60
            status.update(
                label=f"추정 완료! 총 소요 시간: {total_min}:{total_sec:02d}",
                state="complete",
            )

    # ── 결과 표시 ──
    if "length_result" not in st.session_state:
        return

    result: SurveyLengthResult = st.session_state["length_result"]
    if not result.question_estimates:
        return

    lang = st.session_state.get("length_language", "ko")

    st.divider()
    _render_dashboard(result)
    st.divider()
    _render_type_breakdown(result)
    st.divider()
    _render_cognitive_breakdown(result, lang)
    st.divider()
    _render_detail_table(result, lang)


def _render_dashboard(result: SurveyLengthResult):
    """요약 대시보드 메트릭 4칸."""
    total_min = result.total_seconds // 60
    total_sec = result.total_seconds % 60
    complexity_counts = result.count_by_complexity()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("총 예상 시간", f"{total_min}:{total_sec:02d}")
    with col2:
        st.metric("전체 문항", result.total_questions)
    with col3:
        st.metric("문항당 평균", f"{result.avg_seconds_per_question:.1f}초")
    with col4:
        st.metric("높은 복잡도", complexity_counts.get("high", 0))


def _render_type_breakdown(result: SurveyLengthResult):
    """유형별 분포: 바 차트 + 통계 테이블."""
    st.subheader("문항 유형별 소요 시간")

    time_by_type = result.time_by_type()
    count_by_type = result.count_by_type()

    if not time_by_type:
        return

    # 테이블 데이터 구성
    rows = []
    for qtype in sorted(time_by_type.keys(), key=lambda t: time_by_type[t], reverse=True):
        total_sec = time_by_type[qtype]
        count = count_by_type[qtype]
        avg_sec = total_sec / count if count > 0 else 0
        rows.append({
            "Type": qtype,
            "Questions": count,
            "Total (sec)": total_sec,
            "Avg (sec)": round(avg_sec, 1),
        })

    df = pd.DataFrame(rows)

    col_chart, col_table = st.columns(2)

    with col_chart:
        # 바 차트 (유형별 소요 시간)
        chart_df = df.set_index("Type")[["Total (sec)"]]
        st.bar_chart(chart_df, horizontal=True)

    with col_table:
        st.dataframe(df, use_container_width=True, hide_index=True)


def _render_cognitive_breakdown(result: SurveyLengthResult, lang: str):
    """인지 태스크별 분포."""
    st.subheader("인지 태스크별 소요 시간")

    time_by_task = result.time_by_cognitive_task()
    count_by_task = result.count_by_cognitive_task()
    task_labels = COGNITIVE_TASK_LABELS.get(lang, COGNITIVE_TASK_LABELS["en"])

    if not time_by_task:
        return

    rows = []
    for task in sorted(time_by_task.keys(), key=lambda t: time_by_task[t], reverse=True):
        total_sec = time_by_task[task]
        count = count_by_task[task]
        avg_sec = total_sec / count if count > 0 else 0
        rows.append({
            "Cognitive Task": task_labels.get(task, task),
            "Questions": count,
            "Total (sec)": total_sec,
            "Avg (sec)": round(avg_sec, 1),
        })

    df = pd.DataFrame(rows)

    col_chart, col_table = st.columns(2)

    with col_chart:
        chart_df = df.set_index("Cognitive Task")[["Total (sec)"]]
        st.bar_chart(chart_df, horizontal=True)

    with col_table:
        st.dataframe(df, use_container_width=True, hide_index=True)


def _render_detail_table(result: SurveyLengthResult, lang: str = "ko"):
    """문항별 상세 테이블."""
    st.subheader("문항 상세")

    if not result.question_estimates:
        st.info("문항 추정 결과가 없습니다.")
        return
    max_time = max(e.estimated_seconds for e in result.question_estimates)
    task_labels = COGNITIVE_TASK_LABELS.get(lang, COGNITIVE_TASK_LABELS["en"])

    rows = []
    for e in result.question_estimates:
        q_text = e.question_text
        if len(q_text) > 100:
            q_text = q_text[:100] + "..."
        rows.append({
            "Q#": e.question_number,
            "Question": q_text,
            "Type": e.question_type,
            "Options": e.option_count,
            "Cognitive": task_labels.get(e.cognitive_task, e.cognitive_task),
            "Time (sec)": e.estimated_seconds,
            "Complexity": e.complexity,
            "Reasoning": e.reasoning,
        })

    df = pd.DataFrame(rows)

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Q#": st.column_config.TextColumn("Q#", width="small"),
            "Question": st.column_config.TextColumn("Question", width="large"),
            "Type": st.column_config.TextColumn("Type", width="small"),
            "Options": st.column_config.NumberColumn("Options", width="small"),
            "Cognitive": st.column_config.TextColumn("Cognitive", width="small"),
            "Time (sec)": st.column_config.ProgressColumn(
                "Time (sec)",
                min_value=0,
                max_value=max_time,
                format="%d sec",
            ),
            "Complexity": st.column_config.TextColumn("Complexity", width="small"),
            "Reasoning": st.column_config.TextColumn("Reasoning", width="large"),
        },
    )
