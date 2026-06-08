"""
학점은행제 학점 계산기 프로토타입
Streamlit 기반 단일 파일 앱

실행 방법:
1. 의존성 설치: pip install streamlit pandas
2. 앱 실행: streamlit run /root/creditbank-calculator/app.py

현재 버전은 실제 DB 연동 대신 샘플 데이터를 사용합니다.
"""

import os
import io
import json
import re
import pandas as pd
import streamlit as st

# 기본 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")

# 샘플 데이터 경로
SAMPLE_COMPLETED = os.path.join(DATA_DIR, "sample_completed.csv")
MAJORS_JSON = os.path.join(DATA_DIR, "majors.json")
QUALIFICATION_JSON = os.path.join(DATA_DIR, "qualification_credits.json")


@st.cache_data
def load_majors() -> dict:
    if not os.path.exists(MAJORS_JSON):
        st.error("전공 요건 파일(majors.json)이 없습니다.")
        st.stop()
    with open(MAJORS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)["requirements"]


@st.cache_data
def load_qualifications() -> dict:
    if not os.path.exists(QUALIFICATION_JSON):
        return {"meta": {}, "grades": [], "qualifications": []}
    with open(QUALIFICATION_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data
def load_sample_completed() -> pd.DataFrame:
    if not os.path.exists(SAMPLE_COMPLETED):
        st.error("샘플 이수과목 파일(sample_completed.csv)이 없습니다.")
        st.stop()
    return pd.read_csv(SAMPLE_COMPLETED)


def normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    expected = ["type", "category", "institution", "subject", "credits", "year"]
    if list(df.columns) != expected:
        st.warning(
            "업로드한 파일의 컬럼이 예상과 다릅니다.\n"
            "필수 컬럼: type, category, institution, subject, credits, year"
        )
    df = df.copy()
    df["credits"] = pd.to_numeric(df["credits"], errors="coerce").fillna(0).astype(int)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").fillna(0).astype(int)
    return df


def aggregate_completed(df: pd.DataFrame) -> dict:
    total_credits = int(df["credits"].sum())
    by_category = (
        df.groupby("category", as_index=False)["credits"].sum()
        .set_index("category")["credits"]
        .to_dict()
    )
    return {
        "총학점": total_credits,
        "전공필수": int(by_category.get("전공필수", 0)),
        "전공선택": int(by_category.get("전공선택", 0)),
        "교양": int(by_category.get("교양", 0)),
        "일반": int(by_category.get("일반", 0)),
        "기타": int(by_category.get("기타", 0)),
    }


def compute_remaining(completed: dict, required: dict) -> dict:
    keys = ["총학점", "전공필수", "전공선택", "교양", "일반"]
    if not keys:
        return {}
    return {k: max(0, required[k] - completed.get(k, 0)) for k in keys}


def render_progress(completed: dict, required: dict, label: str) -> None:
    remaining = compute_remaining(completed, required)[label]
    done = required[label] - remaining
    st.metric(
        label=f"{label} 이수 현황",
        value=f"{done} / {required[label]}",
        delta=f"남은 {remaining}학점",
    )
    st.progress(min(1.0, done / max(1, required[label])))


def parse_credit_tokens(raw: str):
    """Return the primary credit and a list of note flags from tokens like '20 (30)' or '25 45*'."""
    text = (raw or "").replace("\n", " ")
    current = None
    legacy = None

    m = re.search(r"(\d+)", text)
    if m:
        current = int(m.group(1))

    m2 = re.search(r"\((\d+)\)", text)
    if m2:
        legacy = int(m2.group(1))
    else:
        m3 = re.search(r"(\d+)\s+(\d+)", text)
        if m3:
            current = int(m3.group(1))
            legacy = int(m3.group(2))

    notes = []
    if "*" in text:
        notes.append("취득시기별 학점 변동 있음")
    if legacy is not None:
        notes.append(f"2009.3 이전 취득자 적용학점: {legacy}학점")
    return current, legacy, notes


def render_qualification_search(qual_db: dict):
    st.subheader("🎓 자격증별 학점인정 조회")
    q = qual_db.get("qualifications", [])
    if not q:
        st.info("자격증 DB가 비어 있습니다. 데이터를 확인해 주세요.")
        return

    df = pd.DataFrame(q)
    df.columns = [c for c in df.columns]
    search_cols = [c for c in df.columns if c != "source_page"]
    with st.form("qualification_search_form"):
        col1, col2 = st.columns([2, 1])
        with col1:
            keyword = st.text_input("자격명 검색", placeholder="예) 경영지도사, 컴퓨터활용능력")
        with col2:
            category_filter = st.selectbox(
                "대분류",
                ["전체"] + sorted(df["대분류"].dropna().unique().tolist()),
            )
        submitted = st.form_submit_button("검색")

    if not submitted:
        st.caption("검색어를 입력하면 해당 자격증의 인정학점과 연계 정보를 조회합니다.")
        st.dataframe(
            df[["대분류", "중분류", "자격명", "인정학점_현행"]].head(50),
            use_container_width=True,
        )
        return

    mask = pd.Series([True] * len(df))
    if keyword:
        mask = mask & df["자격명"].str.contains(keyword, na=False)
    if category_filter != "전체":
        mask = mask & (df["대분류"] == category_filter)
    result = df[mask].copy()
    if result.empty:
        st.warning("검색 결과가 없습니다.")
        return

    st.success(f"검색 결과 {len(result)}건")
    for _, row in result.iterrows():
        credits_raw = row.get("인정학점_현행", "") or ""
        current, legacy, notes = parse_credit_tokens(credits_raw)
        st.markdown(
            f"**{row.get('자격명', '')}**\n"
            f"- 대분류: {row.get('대분류', '-')}\n"
            f"- 인정학점: {credits_raw or '-'}\n"
            f"- 전문학사 전공 연계: {row.get('전문학사_전공') or '-'}"
        )
        if notes:
            st.caption(" / ".join(notes))


def main():
    st.set_page_config(page_title="학점은행제 학점 계산기", page_icon="🎓", layout="wide")
    st.title("🎓 학점은행제 학점 계산기 (프로토타입)")
    st.caption("전적대/자격증/독학사 이수 내역을 기준으로 남은 학점을 계산합니다.")

    majors = load_majors()
    degree_options = list(majors.keys())
    major_map: dict = {}
    for d in degree_options:
        for m in majors[d].keys():
            major_map[f"{d} - {m}"] = (d, m)

    degree = st.sidebar.selectbox("목표 학위", degree_options)
    available_majors = list(majors[degree].keys())
    major_label = st.sidebar.selectbox("목표 전공", available_majors)
    selected_degree, selected_major = degree, major_label
    requirements = majors[selected_degree][selected_major]

    st.sidebar.header("이수 과목 입력")
    input_mode = st.sidebar.radio("입력 방식", ["파일 업로드", "직접 입력", "샘플 데이터 사용"])

    if input_mode == "파일 업로드":
        uploaded_file = st.sidebar.file_uploader(
            "CSV 파일 업로드",
            type=["csv"],
            help=(
                "필수 컬럼: type, category, institution, subject, credits, year\n"
                "예) 전적대, 교양, 서울대학교, 대학영어, 3, 2020"
            ),
        )
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            df = normalize_df(df)
            completed = aggregate_completed(df)
        else:
            st.sidebar.info("CSV 파일을 업로드하면 자동으로 반영됩니다.")
            completed = {
                "총학점": 0,
                "전공필수": 0,
                "전공선택": 0,
                "교양": 0,
                "일반": 0,
                "기타": 0,
            }
    elif input_mode == "직접 입력":
        st.sidebar.subheader("과목 직접 입력")
        with st.sidebar.form("manual_input_form"):
            input_type = st.selectbox("구분", ["전적대", "자격증", "독학사"])
            category = st.selectbox("분류", ["전공필수", "전공선택", "교양", "일반", "기타"])
            institution = st.text_input("기관명", placeholder="예) 서울대학교")
            subject = st.text_input("과목명", placeholder="예) 영어글쓰기")
            credits = st.number_input("이수학점", min_value=0, max_value=20, value=3, step=1)
            year = st.number_input("이수연도", min_value=1950, max_value=2100, value=2024, step=1)
            add = st.form_submit_button("과목 추가")
        if "records" not in st.session_state:
            st.session_state["records"] = []
        if add:
            r = st.session_state["records"]
            st.session_state["records"] = r + [
                {
                    "type": input_type,
                    "category": category,
                    "institution": institution,
                    "subject": subject,
                    "credits": int(credits),
                    "year": int(year),
                }
            ]
        rows = st.session_state.get("records", [])
        if rows:
            st.sidebar.dataframe(pd.DataFrame(rows), use_container_width=True)
        df = pd.DataFrame(rows) if rows else pd.DataFrame(
            columns=["type", "category", "institution", "subject", "credits", "year"]
        )
        if not df.empty:
            df = normalize_df(df)
            completed = aggregate_completed(df)
        else:
            completed = {
                "총학점": 0,
                "전공필수": 0,
                "전공선택": 0,
                "교양": 0,
                "일반": 0,
                "기타": 0,
            }
    else:
        df = load_sample_completed()
        df = normalize_df(df)
        completed = aggregate_completed(df)
        st.sidebar.success(f"샘플 데이터 {len(df)}건을 사용합니다.")

    qual_db = load_qualifications()

    # 메인 화면
    tab1, tab2, tab3, tab4 = st.tabs(["요건 비교", "이수 내역", "자격증 조회", "프로토타입 안내"])

    with tab1:
        remaining = compute_remaining(completed, requirements)
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("기준 요건")
            st.json(requirements)
        with col2:
            st.subheader("현재 이수")
            st.json(completed)

        st.subheader("요건 이수 현황")
        cols = st.columns(len(remaining))
        for c, (k, v) in zip(cols, remaining.items()):
            with c:
                render_progress(completed, requirements, k)

        st.subheader("상세 요약")
        summary_rows = []
        for k in ["총학점", "전공필수", "전공선택", "교양", "일반"]:
            done = requirements[k] - remaining[k]
            summary_rows.append(
                {
                    "구분": k,
                    "필요학점": requirements[k],
                    "이수학점": done,
                    "남은학점": remaining[k],
                }
            )
        st.table(pd.DataFrame(summary_rows))

    with tab2:
        if input_mode == "파일 업로드":
            if "uploaded_file" in locals() and uploaded_file is not None:
                st.dataframe(df, use_container_width=True)
            else:
                st.info("왼쪽에서 CSV 파일을 업로드해 주세요.")
        elif input_mode == "직접 입력":
            if not df.empty:
                st.dataframe(df, use_container_width=True)
            else:
                st.info("왼쪽에서 과목을 추가해 주세요.")
        else:
            st.dataframe(df, use_container_width=True)

    with tab3:
        render_qualification_search(qual_db)

    with tab4:
        st.markdown(
            """
            ## 사용 방법 (프로토타입)
            1. 왼쪽 메뉴에서 목표 **학위**와 **전공**을 선택합니다.
            2. 이수 과목을 **파일 업로드**, **직접 입력**, 또는 **샘플 데이터** 중 하나로 입력합니다.
            3. 요건 비교 탭에서 현재 이수 현황과 남은 학점을 확인합니다.
            4. **자격증 조회** 탭에서 자격증별 인정학점과 연계 전공을 확인할 수 있습니다.

            ## 참고
            - 실제 운영 환경에서는 학점은행제 공식 데이터와 연동해야 합니다.
            - 자격증, 독학사, 군대, 전공심화 등의 반영 기준은 새롭게 검증이 필요합니다.
            - 자격 학점인정 기준은 제28차 기준(2025-12-15 시행)을 적용했습니다.
            """
        )


if __name__ == "__main__":
    main()
