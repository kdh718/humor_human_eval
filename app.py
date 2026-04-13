from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from supabase import create_client, Client

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "sampled_combined_600.csv"
PAGE_SIZE = 12

st.set_page_config(page_title="Humor Human Evaluation", layout="wide")


@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    return pd.read_csv(path)


@st.cache_resource
def get_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def get_saved_page(supabase: Client, evaluator_id: str) -> int:
    res = (
        supabase.table("progress")
        .select("next_page")
        .eq("evaluator_id", evaluator_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return int(res.data[0]["next_page"])
    return 0


def save_page_progress(supabase: Client, evaluator_id: str, next_page: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "evaluator_id": evaluator_id,
        "next_page": next_page,
        "updated_at": now,
    }
    (
        supabase.table("progress")
        .upsert(payload, on_conflict="evaluator_id")
        .execute()
    )


def save_responses(supabase: Client, rows: list[dict]) -> None:
    (
        supabase.table("responses")
        .upsert(rows, on_conflict="evaluator_id,item_id")
        .execute()
    )


def get_completed_count(supabase: Client, evaluator_id: str) -> int:
    res = (
        supabase.table("responses")
        .select("item_id", count="exact")
        .eq("evaluator_id", evaluator_id)
        .execute()
    )
    return res.count or 0


def load_saved_responses(supabase: Client, evaluator_id: str) -> dict:
    res = (
        supabase.table("responses")
        .select("item_id, humor_tf, funniness, humor_type")
        .eq("evaluator_id", evaluator_id)
        .execute()
    )

    saved = {}
    for row in res.data or []:
        saved[int(row["item_id"])] = {
            "humor_tf": row.get("humor_tf"),
            "funniness": row.get("funniness"),
            "humor_type": row.get("humor_type"),
        }
    return saved


def load_all_responses_df(supabase: Client) -> pd.DataFrame:
    res = (
        supabase.table("responses")
        .select("*")
        .order("submitted_at", desc=True)
        .execute()
    )
    return pd.DataFrame(res.data or [])


supabase = get_supabase_client()
df = load_data(str(DATA_PATH))

st.title("Humor Human Evaluation")

with st.expander("Debug info"):
    st.write("data path:", str(DATA_PATH))
    st.write("total items:", len(df))

evaluator_id = st.text_input("Evaluator ID")

if not evaluator_id.strip():
    st.info("Evaluator ID를 입력하세요.")
    st.stop()

evaluator_id = evaluator_id.strip()

if "page_num" not in st.session_state:
    st.session_state.page_num = get_saved_page(supabase, evaluator_id)

if st.session_state.get("last_evaluator_id") != evaluator_id:
    st.session_state.page_num = get_saved_page(supabase, evaluator_id)
    st.session_state.last_evaluator_id = evaluator_id

saved_responses = load_saved_responses(supabase, evaluator_id)

total_n = len(df)
max_page = (total_n - 1) // PAGE_SIZE
page_num = min(st.session_state.page_num, max_page)

start_idx = page_num * PAGE_SIZE
end_idx = min(start_idx + PAGE_SIZE, total_n)
page_df = df.iloc[start_idx:end_idx].copy()

completed_count = get_completed_count(supabase, evaluator_id)

st.write(f"진행 상황: **{completed_count} / {total_n}**")
st.write(f"현재 페이지: **{page_num + 1} / {max_page + 1}**")
st.progress(completed_count / total_n if total_n > 0 else 0)

type_options = [
    "Homonym / Polysemy",
    "Similar pronunciation",
    "Cultural / Social meme",
    "Other / Not sure",
]

rows_to_save = []

for idx, row in page_df.iterrows():
    item_id = int(idx)
    sentence = row["sentence"]

    st.markdown("---")
    st.markdown(f"### Item {item_id}")
    st.info(sentence)

    humor_tf = st.radio(
        f"[{item_id}] 이 문장이 유머라고 느껴지나요?",
        options=["T", "F"],
        key=f"humor_tf_{item_id}",
        horizontal=True
    )

    if humor_tf == "T":
        funniness = st.radio(
            f"[{item_id}] (유머라고 느꼈다면) 얼마나 재미있나요?",
            options=[1, 2, 3, 4, 5],
            key=f"funniness_{item_id}",
            horizontal=True
        )

        humor_type = st.radio(
            f"[{item_id}] 이 문장이 유머라고 느껴지는 주된 이유는 무엇인가요?",
            options=[
                "Homonym / Polysemy",
                "Similar pronunciation",
                "Cultural / Social meme",
                "Other / Not sure"
            ],
            key=f"humor_type_{item_id}"
        )
    else:
        st.caption("유머가 아니라고 선택하셨습니다. 나머지 문항은 자동 처리됩니다.")
        funniness = 0
        humor_type = "Other / Not sure"

    rows_to_save.append({
        "evaluator_id": evaluator_id,
        "item_id": item_id,
        "sentence": sentence,
        "humor_tf": humor_tf,
        "funniness": funniness,
        "humor_type": humor_type,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    })

col1, col2 = st.columns(2)
submitted = col1.button("이 페이지 제출")
save_only = col2.button("현재 페이지 임시저장")

if submitted or save_only:
    try:
        save_responses(supabase, rows_to_save)

        if submitted:
            next_page = min(page_num + 1, max_page + 1)
        else:
            next_page = page_num

        save_page_progress(supabase, evaluator_id, next_page)
        st.session_state.page_num = next_page

        st.success("저장되었습니다.")
        st.rerun()

    except Exception as e:
        st.error(f"저장 실패: {e}")

st.markdown("---")
st.subheader("관리자 확인용")

if st.checkbox("전체 응답 보기"):
    try:
        result_df = load_all_responses_df(supabase)
        st.dataframe(result_df, use_container_width=True)

        if not result_df.empty:
            csv = result_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "CSV 다운로드",
                data=csv,
                file_name="human_eval_responses.csv",
                mime="text/csv",
            )
    except Exception as e:
        st.error(f"응답 조회 실패: {e}")
