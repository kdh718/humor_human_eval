from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from supabase import Client, create_client

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "sampled_combined_600.csv"
PAGE_SIZE = 12

SCORE_OPTIONS = [
    "Very low",
    "Low",
    "Neutral",
    "High",
    "Very high",
]

TYPE_OPTIONS = [
    "Homonym / Polysemy",
    "Similar pronunciation",
    "Cultural / Social meme",
    "Situational incongruity / unexpected interpretation"
    "Other / Not sure",
]

TYPE_VISIBLE_SCORES = {"Neutral", "High", "Very high"}

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


def load_saved_responses(supabase: Client, evaluator_id: str) -> dict[int, dict]:
    res = (
        supabase.table("responses")
        .select("item_id, humor_score, humor_type")
        .eq("evaluator_id", evaluator_id)
        .execute()
    )

    saved = {}
    for row in res.data or []:
        saved[int(row["item_id"])] = {
            "humor_score": row.get("humor_score"),
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


def init_session_for_item(item_id: int, saved: dict) -> None:
    score_key = f"humor_score_{item_id}"
    type_key = f"humor_type_{item_id}"

    if score_key not in st.session_state:
        saved_score = saved.get("humor_score", "Neutral")
        if saved_score not in SCORE_OPTIONS:
            saved_score = "Neutral"
        st.session_state[score_key] = saved_score

    if type_key not in st.session_state:
        saved_type = saved.get("humor_type", "Other / Not sure")
        if saved_type not in TYPE_OPTIONS:
            saved_type = "Other / Not sure"
        st.session_state[type_key] = saved_type


def collect_rows_to_save(
    page_df: pd.DataFrame,
    evaluator_id: str,
) -> list[dict]:
    rows_to_save = []

    for idx, row in page_df.iterrows():
        item_id = int(idx)
        sentence = row["sentence"]

        humor_score = st.session_state.get(f"humor_score_{item_id}", "Neutral")

        if humor_score in TYPE_VISIBLE_SCORES:
            humor_type = st.session_state.get(
                f"humor_type_{item_id}",
                "Other / Not sure",
            )
            if humor_type not in TYPE_OPTIONS:
                humor_type = "Other / Not sure"
        else:
            humor_type = "Other / Not sure"

        rows_to_save.append({
            "evaluator_id": evaluator_id,
            "item_id": item_id,
            "sentence": sentence,
            "humor_score": humor_score,
            "humor_type": humor_type,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })

    return rows_to_save


supabase = get_supabase_client()

if not DATA_PATH.exists():
    st.error(f"데이터 파일이 없습니다: {DATA_PATH}")
    st.stop()

df = load_data(str(DATA_PATH))

st.title("Humor Human Evaluation")

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

if page_num == 0:
    st.caption("현재 첫 페이지입니다.")
if page_num == max_page:
    st.caption("현재 마지막 페이지입니다.")

for idx, row in page_df.iterrows():
    item_id = int(idx)
    sentence = row["sentence"]
    saved = saved_responses.get(item_id, {})

    init_session_for_item(item_id, saved)

    st.markdown("---")
    st.markdown(f"### Item {item_id}")
    st.info(sentence)

    humor_score = st.radio(
        f"[{item_id}] 이 문장이 얼마나 유머로 보이나요?",
        options=SCORE_OPTIONS,
        key=f"humor_score_{item_id}",
        horizontal=True,
    )

    if humor_score in TYPE_VISIBLE_SCORES:
        st.radio(
            f"[{item_id}] 왜 그렇게 판단했나요?",
            options=TYPE_OPTIONS,
            key=f"humor_type_{item_id}",
        )
    else:
        st.caption("유머성이 낮다고 선택하셨습니다. 유형 문항은 자동 처리됩니다.")
        st.session_state[f"humor_type_{item_id}"] = "Other / Not sure"

st.markdown("---")

rows_to_save = collect_rows_to_save(page_df, evaluator_id)

col1, col2, col3 = st.columns(3)
prev_btn = col1.button("⬅️ 이전 페이지", use_container_width=True)
save_only = col2.button("💾 임시저장", use_container_width=True)
next_btn = col3.button("➡️ 다음 페이지", use_container_width=True)

if prev_btn or save_only or next_btn:
    try:
        save_responses(supabase, rows_to_save)

        if prev_btn:
            next_page = max(page_num - 1, 0)
        elif next_btn:
            next_page = min(page_num + 1, max_page)
        else:
            next_page = page_num

        save_page_progress(supabase, evaluator_id, next_page)
        st.session_state.page_num = next_page

        if next_btn and page_num == max_page:
            st.success("마지막 페이지까지 저장되었습니다.")
        else:
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
