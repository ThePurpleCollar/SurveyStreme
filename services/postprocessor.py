import re
import pandas as pd


def extract_question_type(text, question_type_keywords1, question_type_keywords2):
    """문항 텍스트에서 괄호 안의 문항 유형을 추출"""
    pattern = re.compile(r'(\[\s*(.*?)\s*\]|\(\s*(.*?)\s*\))')
    cleaned_text = text
    question_type = None
    for match in pattern.finditer(text):
        potential_type = match.group(2) or match.group(3)
        if potential_type:
            potential_type_lower = potential_type.lower()
            for keyword in question_type_keywords1:
                if potential_type_lower == keyword.lower():
                    question_type = potential_type.strip()
                    cleaned_text = text[:match.start()].strip()
                    return cleaned_text, question_type
    for match in pattern.finditer(text):
        potential_type = match.group(2) or match.group(3)
        if potential_type and any(keyword.lower() in potential_type.lower() for keyword in question_type_keywords2):
            question_type = potential_type.strip()
            cleaned_text = text[:match.start()].strip()
            break
    return cleaned_text, question_type


def extract_question_data(texts):
    """텍스트에서 문항 번호, 텍스트, 유형을 추출"""
    pattern = r'^([A-Za-z]+[a-z]*\d+[a-z]?(?:-\d+)*|[A-Za-z]+\d+[A-Za-z])\.\s*(.*)'

    question_type_keywords1 = ['SA', '단수', 'SELECT ONE', 'MA', '복수', 'SELECT ALL', 'OE', 'OPEN', '오픈', 'OPEN/SA', 'NUMERIC']
    question_type_keywords2 = ['SCALE', 'PT', '척도', 'TOP', 'RANK', '순위']
    question_data = []
    current_question_text = ""
    current_qn = None
    for text in texts:
        lines = text.split('\n')
        for line in lines:
            match = re.match(pattern, line)
            if match:
                if current_qn:
                    cleaned_text, current_qtype = extract_question_type(current_question_text, question_type_keywords1, question_type_keywords2)
                    question_data.append((current_qn, cleaned_text, current_qtype))
                    current_question_text = ""
                current_qn = match.group(1)
                current_question_text = match.group(2)
            else:
                current_question_text += " " + line
    if current_qn and current_question_text:
        cleaned_text, current_qtype = extract_question_type(current_question_text, question_type_keywords1, question_type_keywords2)
        question_data.append((current_qn, cleaned_text, current_qtype))
    return question_data


def duplicate_and_insert_rows(df):
    """Grid 척도형, 순위형 문항에 추가 행 생성"""
    rows_to_insert = []
    for index, row in df.iterrows():
        question_type = str(row['QuestionType']) if row['QuestionType'] is not None else ""
        top_match = re.search(r'(top|rank) ?(\d+)', question_type, re.IGNORECASE)
        top_match_ko = re.search(r'(\d+)\s*순위', question_type)
        pt_scale_match = re.search(r'(pt|척도)\s*x\s*(\d+)', question_type, re.IGNORECASE)
        match_value = None
        if top_match:
            match_value = int(top_match.group(2)) - 1
        elif top_match_ko:
            match_value = int(top_match_ko.group(1)) - 1
        if match_value is not None:
            for _ in range(match_value):
                new_row = row.copy()
                new_row['SummaryType'] = ''
                rows_to_insert.append((index, new_row))
        elif pt_scale_match:
            pt_scale_value = int(pt_scale_match.group(2)) + 1
            for _ in range(pt_scale_value):
                new_row = row.copy()
                new_row['SummaryType'] = ''
                rows_to_insert.append((index, new_row))
    rows_to_insert.sort(key=lambda x: x[0], reverse=True)
    for insert_index, row_data in rows_to_insert:
        df = pd.concat([df.iloc[:insert_index+1], pd.DataFrame([row_data]).reset_index(drop=True), df.iloc[insert_index+1:]]).reset_index(drop=True)
    return df


def assign_summary_type(df):
    """문항 유형에 따라 SummaryType 자동 생성"""
    percent_type = ['SA', '단수', 'Select one', 'MA', '복수', 'Select all', 'OE', 'OPEN', 'Open', '오픈', 'OPEN/SA']
    mean_type = ['NUMERIC', 'Numeric']
    scale_type = ['SCALE', 'Scale']
    df.loc[df['QuestionType'].isin(percent_type), 'SummaryType'] = '%'
    df.loc[df['QuestionType'].isin(mean_type), 'SummaryType'] = '%, mean'
    df.loc[df['QuestionType'].isin(scale_type), 'SummaryType'] = '%/Top2/Bot2/Mean'
    grouped = df.groupby('QuestionNumber')
    for name, group in grouped:
        pt_scale_rows = group['QuestionType'].str.contains(r'(pt|척도)\s*x\s*\d+', regex=True, case=False)
        if pt_scale_rows.any():
            first_row_index = group.index[0]
            second_row_index = group.index[1]
            df.at[first_row_index, 'SummaryType'] = 'Summary Top2%'
            df.at[second_row_index, 'SummaryType'] = 'Summary Mean'

    def ordinal(n):
        return "%d%s" % (n, "tsnrhtdd"[(n//10%10!=1)*(n%10<4)*n%10::4])

    def generate_summary_type(n):
        return ['+'.join(ordinal(x+1) for x in range(i+1)) for i in range(n)]

    filtered_indices = df['QuestionType'].str.contains(r'(top\s*\d+|rank\s*\d+|\d+\s*순위)', case=False, na=False)
    df_filtered = df[filtered_indices].copy()
    df_filtered['SummaryType'] = df_filtered.groupby('QuestionNumber').cumcount() + 1
    df_filtered['SummaryType'] = df_filtered.groupby('QuestionNumber')['SummaryType'].transform(lambda x: generate_summary_type(len(x)))
    df.update(df_filtered['SummaryType'])
    return df


def add_table_number_column(df):
    """TableNumber 컬럼 추가 (중복 시 _1, _2 등 부여)"""
    df['TableNumber'] = df['QuestionNumber']
    for qn in df['QuestionNumber'].unique():
        indices = df.index[df['QuestionNumber'] == qn].tolist()
        if len(indices) > 1:
            for i, idx in enumerate(indices, start=1):
                df.at[idx, 'TableNumber'] = f"{df.at[idx, 'TableNumber']}_{i}"
    return df


def update_summary_type(df):
    """척도형 문항의 SummaryType을 점수에 따라 세분화"""
    pattern = re.compile(r'(\d+)\s*점?\s*(pt|척도)', re.IGNORECASE)
    for index, row in df.iterrows():
        if pd.notnull(row['QuestionType']) and ('pt' in row['QuestionType'].lower() or '척도' in row['QuestionType']) and not row['SummaryType']:
            match = pattern.search(row['QuestionType'])
            if match:
                num = int(match.group(1))
                if num == 4:
                    df.at[index, 'SummaryType'] = '%/Top2(3+4)/Bot2(1+2)/Mean'
                elif num == 5:
                    df.at[index, 'SummaryType'] = '%/Top2(4+5)/Mid(3)/Bot2(1+2)/Mean'
                elif num == 6:
                    df.at[index, 'SummaryType'] = '%/Top2(5+6)/Mid(3+4)/Bot2(1+2)/Mean'
                elif num == 7:
                    df.at[index, 'SummaryType'] = '%/Top2(6+7)/Mid(3+4+5)/Bot2(1+2)/Top3(5+6+7)/Mid(4)/Bot3(1+2+3)/Mean'
                elif num == 10:
                    df.at[index, 'SummaryType'] = '%/Top2(9+10)/Bot2(1+2)/Top3(8+9+10)/Bot3(1+2+3)/Mean'
    return df
