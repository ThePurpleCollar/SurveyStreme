import fitz  # PyMuPDF
from docx import Document


def read_pdf(file):
    """PDF 파일에서 텍스트를 추출"""
    doc = fitz.open(stream=file.read(), filetype="pdf")
    texts = []
    for page in doc:
        texts.append(page.get_text("text"))
    return texts


def read_docx_without_strikethrough(file):
    """DOCX 파일에서 취소선 텍스트를 제외하고 추출"""
    doc = Document(file)
    texts_without_strikethrough = []
    for paragraph in doc.paragraphs:
        text_runs = [run.text for run in paragraph.runs if not run.font.strike]
        paragraph_text = ''.join(text_runs)
        if paragraph_text:
            texts_without_strikethrough.append(paragraph_text)
    return texts_without_strikethrough
