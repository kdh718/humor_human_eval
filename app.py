import sqlite3
from datetime import datetime
import pandas as pd
import streamlit as st

DATA_PATH = "sampled_combined_720.csv"
DB_PATH = "human_eval.db"
PAGE_SIZE = 12

st.set_page_config(page_title="Humor Human Evaluation", layout="wide")


@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        evaluator_id TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        sentence TEXT,
        humor_tf TEXT,
        funniness INTEGER,
        humor_type TEXT,
        submitted_at TEXT,
        PRIMARY KEY (evaluator_id, item_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS progress (
        evaluator_id TEXT PRIMARY KEY,
        next_page INTEGER NOT NULL,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_saved_page(evaluator_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT next_page FROM progress WHERE evaluator_id = ?",
        (evaluator_id,)
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def save_page_progress(evaluator_id: str, next_page: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO progress (evaluator_id, next_page, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(evaluator_id) DO UPDATE SET
        next_page = excluded.next_page,
        updated_at = excluded.updated_at
    """, (evaluator_id, next_page, datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def save_responses(rows: list[dict]):
    conn = get_conn()
    cur = conn.cursor()

    for row in rows:
        cur.execute("""
        INSERT OR REPLACE INTO responses
        (evaluator_id, item_id, sentence, humor_tf, funniness, humor_type, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            row["evaluator_id"],
            row["item_id"],
            row["sentence"],
            row["humor_tf"],
            row["funniness"],
            row["humor_type"],
            row["submitted_at"]
        ))

    conn.commit()
    conn.close()


def get_completed_count(evaluator_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM responses WHERE evaluator_id = ?",
        (evaluator_id,)
    )
    count = cur.fetchone()[0]
    conn.close()
    return count


init_db()
df = load_data(DATA_PATH)

st.title("Humor Human Evaluation")

evaluator_id = st.text_input("Evaluator ID")

if not evaluator_id.strip():
    st.info("Evaluator ID를 입력하세요.")
    st.stop()

if "last_evaluator_id" not in st.session_state:
    st.session_state.last_evaluator_id = None

if "page_num" not in st.session_state:
    st.session_state.page_num = 0

if st.session_state.last_evaluator_id != evaluator_id:
    st.session_state.page_num = get_saved_page(evaluator_id)
    st.session_state.last_evaluator_id = evaluator_id

total_n = len(df)
max_page = (total_n - 1) // PAGE_SIZE
page_num = min(st.session_state.page_num, max_page)

start_idx = page_num * PAGE_SIZE
end_idx = min(start_idx + PAGE_SIZE, total_n)
page_df = df.iloc[start_idx:end_idx].copy()

completed_count = get_completed_count(evaluator_id)

st.write(f"진행 상황: **{completed_count} / {total_n}**")
st.write(f"현재 페이지: **{page_num + 1} / {max_page + 1}**")
st.progress(completed_count / total_n if total_n > 0 else 0.0)

rows_to_save = []

for idx, row in page_df.iterrows():
    item_id = int(idx)
    sentence = row["sentence"]

    st.markdown("---")
    st.markdown(f"### Sentence {item_id + 1}")
    st.info(sentence)

    # 기본값 F
    humor_tf = st.radio(
        "1. 이 문장이 유머라고 느껴지나요?",
        options=["F", "T"],
        index=0,
        key=f"humor_tf_{item_id}",
        horizontal=True,
    )

    if humor_tf == "T":
        funniness = st.radio(
            "2. (유머라고 느꼈다면) 얼마나 재미있나요?",
            options=[1, 2, 3, 4, 5],
            key=f"funniness_{item_id}",
            horizontal=True,
        )

        humor_type = st.radio(
            "3. 이 문장이 유머라고 느껴지는 주된 이유는 무엇인가요?",
            options=[
                "Homonym / Polysemy",
                "Similar pronunciation",
                "Cultural / Social meme",
                "Other / Not sure",
            ],
            key=f"humor_type_{item_id}",
        )
    else:
        funniness = 0
        humor_type = "Other / Not sure"

    rows_to_save.append({
        "evaluator_id": evaluator_id,
        "item_id": item_id,
        "sentence": sentence,
        "humor_tf": humor_tf,
        "funniness": funniness,
        "humor_type": humor_type,
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
    })

st.markdown("---")

col1, col2, col3 = st.columns([1, 1, 1])

with col1:
    if st.button("이전 페이지", disabled=(page_num == 0)):
        st.session_state.page_num -= 1
        st.rerun()

with col2:
    submit_clicked = st.button("이 페이지 제출", use_container_width=True)

with col3:
    if st.button("다음 페이지", disabled=(page_num >= max_page)):
        st.session_state.page_num += 1
        st.rerun()

if submit_clicked:
    save_responses(rows_to_save)

    next_page = min(page_num + 1, max_page + 1)
    save_page_progress(evaluator_id, next_page)
    st.session_state.page_num = next_page

    st.success("저장되었습니다. 다음 접속 시 이어서 시작됩니다.")
    st.rerun()
