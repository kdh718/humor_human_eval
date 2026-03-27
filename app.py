import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DATA_PATH = "sampled_combined_720.csv"
DB_PATH = "human_eval.db"
PAGE_SIZE = 12


st.set_page_config(
    page_title="Humor Human Evaluation",
    layout="wide",
)


@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    required_columns = {"sentence"}
    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns in CSV: {missing}")

    return df


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS responses (
            evaluator_id TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            source TEXT,
            original_label TEXT,
            sentence TEXT NOT NULL,
            humor_tf TEXT NOT NULL,
            funniness INTEGER NOT NULL,
            humor_type TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            PRIMARY KEY (evaluator_id, item_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS progress (
            evaluator_id TEXT PRIMARY KEY,
            next_page INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


def get_saved_page(evaluator_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT next_page FROM progress WHERE evaluator_id = ?",
        (evaluator_id,),
    )
    row = cur.fetchone()
    conn.close()

    if row is None:
        return 0
    return int(row[0])


def save_page_progress(evaluator_id: str, next_page: int) -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO progress (evaluator_id, next_page, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(evaluator_id) DO UPDATE SET
            next_page = excluded.next_page,
            updated_at = excluded.updated_at
        """,
        (
            evaluator_id,
            next_page,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    conn.commit()
    conn.close()


def save_responses(rows: list[dict]) -> None:
    conn = get_conn()
    cur = conn.cursor()

    for row in rows:
        cur.execute(
            """
            INSERT OR REPLACE INTO responses (
                evaluator_id,
                item_id,
                source,
                original_label,
                sentence,
                humor_tf,
                funniness,
                humor_type,
                submitted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["evaluator_id"],
                row["item_id"],
                row["source"],
                row["original_label"],
                row["sentence"],
                row["humor_tf"],
                row["funniness"],
                row["humor_type"],
                row["submitted_at"],
            ),
        )

    conn.commit()
    conn.close()


def get_completed_count(evaluator_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM responses WHERE evaluator_id = ?",
        (evaluator_id,),
    )
    count = cur.fetchone()[0]
    conn.close()
    return int(count)


def reset_instruction_state_if_user_changed(evaluator_id: str) -> None:
    last_id = st.session_state.get("last_evaluator_id")
    if last_id != evaluator_id:
        st.session_state["instruction_done"] = False
        st.session_state["page_num"] = get_saved_page(evaluator_id)
        st.session_state["last_evaluator_id"] = evaluator_id


def show_instruction_page() -> None:
    st.title("평가 안내")

    st.markdown(
        """
다음 문장들을 읽고 유머 여부를 평가해주세요.

### 평가 기준

**1. 이 문장이 유머라고 느껴지나요?**  
- 유머라고 느껴지면 `T`, 아니면 `F`를 선택하세요.

**2. (유머라고 느꼈다면) 얼마나 재미있나요?**  
- `1`은 거의 재미없음, `5`는 매우 재미있음을 의미합니다.

**3. 이 문장이 유머라고 느껴지는 주된 이유는 무엇인가요?**  
- 아래 유형 중 가장 적절한 하나를 선택해주세요.

### 유머 유형 설명

- **Homonym / Polysemy**  
  하나의 단어가 여러 의미로 해석되며 발생하는 유머

- **Similar pronunciation**  
  발음이 비슷한 단어를 활용한 유머

- **Cultural / Social meme**  
  특정 문화, 밈, 사회적 맥락을 기반으로 한 유머

- **Situational incongruity / unexpected interpretation**  
  현실과 어긋난 해석이나 예상 밖의 상황 전개에서 발생하는 유머

- **Other / Not sure**  
  위에 해당하지 않거나 판단이 어려운 경우

### 주의
- 각 문항에 대해 가장 적절한 하나의 유형만 선택해주세요.
- `F`를 선택하면 2번과 3번은 자동 처리됩니다.
        """
    )

    if st.button("평가 시작", type="primary"):
        st.session_state["instruction_done"] = True
        st.rerun()

    st.stop()


def main() -> None:
    if not Path(DATA_PATH).exists():
        st.error(f"CSV file not found: {DATA_PATH}")
        st.stop()

    init_db()
    df = load_data(DATA_PATH)

    if "instruction_done" not in st.session_state:
        st.session_state["instruction_done"] = False
    if "page_num" not in st.session_state:
        st.session_state["page_num"] = 0
    if "last_evaluator_id" not in st.session_state:
        st.session_state["last_evaluator_id"] = None

    st.title("Humor Human Evaluation")

    evaluator_id = st.text_input("Evaluator ID")

    if not evaluator_id.strip():
        st.info("Evaluator ID를 입력하세요.")
        st.stop()

    evaluator_id = evaluator_id.strip()
    reset_instruction_state_if_user_changed(evaluator_id)

    if not st.session_state["instruction_done"]:
        show_instruction_page()

    total_n = len(df)
    max_page = max((total_n - 1) // PAGE_SIZE, 0)

    saved_page = get_saved_page(evaluator_id)
    if st.session_state["page_num"] != saved_page and st.session_state["page_num"] > max_page:
        st.session_state["page_num"] = saved_page

    page_num = min(st.session_state["page_num"], max_page)

    if page_num > max_page:
        page_num = max_page

    completed_count = get_completed_count(evaluator_id)

    if completed_count >= total_n:
        st.success("모든 평가를 완료했습니다.")
        st.write(f"총 완료 문항 수: {completed_count} / {total_n}")
        return

    start_idx = page_num * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total_n)
    page_df = df.iloc[start_idx:end_idx].copy()

    st.write(f"진행 상황: **{completed_count} / {total_n}**")
    st.write(f"현재 페이지: **{page_num + 1} / {max_page + 1}**")
    st.progress(completed_count / total_n if total_n > 0 else 0.0)

    st.markdown("---")

    rows_to_save = []

    for row_idx, row in page_df.iterrows():
        item_id = int(row_idx)
        sentence = str(row["sentence"])
        source = str(row["source"]) if "source" in row and pd.notna(row["source"]) else ""
        original_label = str(row["label"]) if "label" in row and pd.notna(row["label"]) else ""

        st.markdown(f"### Sentence {item_id + 1}")
        st.info(sentence)

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
                    "Situational incongruity / unexpected interpretation",
                    "Other / Not sure",
                ],
                key=f"humor_type_{item_id}",
            )
        else:
            funniness = 0
            humor_type = "Other / Not sure"

        rows_to_save.append(
            {
                "evaluator_id": evaluator_id,
                "item_id": item_id,
                "source": source,
                "original_label": original_label,
                "sentence": sentence,
                "humor_tf": humor_tf,
                "funniness": int(funniness),
                "humor_type": humor_type,
                "submitted_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

        st.markdown("---")

    col1, col2, col3 = st.columns([1, 1.2, 1])

    with col1:
        if st.button("이전 페이지", disabled=(page_num == 0), use_container_width=True):
            st.session_state["page_num"] = max(page_num - 1, 0)
            st.rerun()

    with col2:
        submitted = st.button("이 페이지 제출", type="primary", use_container_width=True)

    with col3:
        if st.button("다음 페이지", disabled=(page_num >= max_page), use_container_width=True):
            st.session_state["page_num"] = min(page_num + 1, max_page)
            st.rerun()

    if submitted:
        save_responses(rows_to_save)

        next_page = min(page_num + 1, max_page + 1)
        save_page_progress(evaluator_id, next_page)
        st.session_state["page_num"] = next_page

        st.success("저장되었습니다. 다음 접속 시 이어서 시작됩니다.")
        st.rerun()


if __name__ == "__main__":
    main()
