"""Translation Helper UI 페이지.

추출된 설문지를 다국어로 번역. 마케팅 리서치 용어 보존.
"""

import streamlit as st

from services.llm_client import MODEL_TITLE_GENERATOR
from services.translation_service import (
    SUPPORTED_LANGUAGES,
    TranslationResult,
    TranslatedQuestion,
    detect_source_language,
    translate_questions,
    export_translation_excel,
)


def page_translation_helper() -> None:
    """Translation Helper 메인 진입점."""
    st.title("Translation Helper")

    # Guard clause
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            'Please process a document in "Questionnaire Analyzer" first.'
        )
        return

    doc = st.session_state["survey_document"]
    questions = doc.questions

    if not questions:
        st.warning("No questions found in the document.")
        return

    st.info(
        f"Found **{len(questions)}** questions in **{doc.filename}**. "
        "Select target language and translate."
    )

    # Auto-detect source language
    detected_lang = detect_source_language(questions)
    if "translation_source_lang" not in st.session_state:
        st.session_state["translation_source_lang"] = detected_lang

    # Controls
    lang_codes = list(SUPPORTED_LANGUAGES.keys())
    lang_labels = list(SUPPORTED_LANGUAGES.values())

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 2])

    with ctrl_col1:
        source_idx = lang_codes.index(st.session_state["translation_source_lang"]) \
            if st.session_state["translation_source_lang"] in lang_codes else 0
        source_lang = st.selectbox(
            "Source Language",
            options=lang_codes,
            index=source_idx,
            format_func=lambda x: f"{SUPPORTED_LANGUAGES[x]} (auto-detected)" if x == detected_lang else SUPPORTED_LANGUAGES[x],
            key="translation_source_selectbox",
        )
        st.session_state["translation_source_lang"] = source_lang

    with ctrl_col2:
        # 타겟 언어: 소스와 다른 언어만 선택 가능
        target_options = [c for c in lang_codes if c != source_lang]
        default_target = "en" if source_lang != "en" else "ko"
        if default_target not in target_options:
            default_target = target_options[0] if target_options else "en"

        saved_target = st.session_state.get("translation_target_lang", default_target)
        if saved_target not in target_options:
            saved_target = default_target

        target_lang = st.selectbox(
            "Target Language",
            options=target_options,
            index=target_options.index(saved_target) if saved_target in target_options else 0,
            format_func=lambda x: SUPPORTED_LANGUAGES.get(x, x),
            key="translation_target_selectbox",
        )
        st.session_state["translation_target_lang"] = target_lang

    with ctrl_col3:
        st.write("")
        st.write("")
        translate_clicked = st.button("Translate", type="primary")

    # Run translation
    if translate_clicked:
        with st.status("Translating...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()
            batch_done = [0]
            total_batches_ref = [1]

            def _progress_callback(event: str, data: dict):
                if event == "batch_start":
                    total_batches_ref[0] = data["total_batches"]
                    log_area.text(
                        f"Batch {data['batch_index'] + 1}/{data['total_batches']} "
                        f"({data['question_count']} questions)..."
                    )
                elif event == "batch_done":
                    batch_done[0] += 1
                    progress = batch_done[0] / total_batches_ref[0]
                    progress_bar.progress(min(progress, 1.0))

            result = translate_questions(
                questions=questions,
                source_language=source_lang,
                target_language=target_lang,
                model=MODEL_TITLE_GENERATOR,
                progress_callback=_progress_callback,
            )
            st.session_state["translation_result"] = result

            status.update(
                label=f"Done! Translated {len(result.translated_questions)} questions.",
                state="complete",
            )

    # Results
    if "translation_result" not in st.session_state:
        return

    result: TranslationResult = st.session_state["translation_result"]

    if not result.translated_questions:
        st.warning("No translation results available.")
        return

    st.divider()

    # Summary
    source_name = SUPPORTED_LANGUAGES.get(result.source_language, result.source_language)
    target_name = SUPPORTED_LANGUAGES.get(result.target_language, result.target_language)
    st.subheader(f"Translation: {source_name} → {target_name}")
    st.caption(f"{len(result.translated_questions)} questions translated")

    # Comparison view
    _render_comparison_view(result)

    st.divider()

    # Download
    _render_download(result)


# ---------------------------------------------------------------------------
# 렌더링 함수
# ---------------------------------------------------------------------------


def _render_comparison_view(result: TranslationResult) -> None:
    """문항별 원문/번역 비교 뷰."""
    for i, tq in enumerate(result.translated_questions):
        edited_marker = " (edited)" if tq.is_edited else ""
        with st.expander(
            f"**{tq.question_number}**{edited_marker} — {tq.original_text[:60]}...",
            expanded=False,
        ):
            col_orig, col_trans = st.columns(2)

            with col_orig:
                st.markdown("**Original**")
                st.text_area(
                    "Original Text",
                    value=tq.original_text,
                    height=100,
                    disabled=True,
                    key=f"trans_orig_text_{i}",
                    label_visibility="collapsed",
                )

                # 원문 보기
                if tq.original_options:
                    st.markdown("**Options (Original)**")
                    for opt in tq.original_options:
                        st.caption(f"{opt.code}. {opt.label}")

                if tq.original_instructions:
                    st.markdown("**Instructions (Original)**")
                    st.caption(tq.original_instructions)

            with col_trans:
                st.markdown("**Translated**")
                new_text = st.text_area(
                    "Translated Text",
                    value=tq.translated_text,
                    height=100,
                    key=f"trans_new_text_{i}",
                    label_visibility="collapsed",
                )

                # 편집 감지
                if new_text != tq.translated_text:
                    tq.translated_text = new_text
                    tq.is_edited = True

                # 번역 보기
                if tq.translated_options:
                    st.markdown("**Options (Translated)**")
                    for opt in tq.translated_options:
                        st.caption(f"{opt.code}. {opt.label}")

                if tq.translated_instructions:
                    st.markdown("**Instructions (Translated)**")
                    st.caption(tq.translated_instructions)


def _render_download(result: TranslationResult) -> None:
    """Excel 다운로드."""
    source_name = SUPPORTED_LANGUAGES.get(result.source_language, result.source_language)
    target_name = SUPPORTED_LANGUAGES.get(result.target_language, result.target_language)

    excel_bytes = export_translation_excel(result)

    st.download_button(
        label=f"Download Translation ({source_name} → {target_name}) — Excel",
        data=excel_bytes,
        file_name=f"translation_{result.source_language}_to_{result.target_language}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
