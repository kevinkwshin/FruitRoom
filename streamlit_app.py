import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import gspread
from google.oauth2.service_account import Credentials
import uuid
import json

# --- 초기 설정 ---
# 자동 배정에서 제외될 조
AUTO_ASSIGN_EXCLUDE_TEAMS = ["대면A", "대면B", "대면C"]
# 시니어조와 고정 배정 방
SENIOR_TEAM = "시니어조"
SENIOR_ROOM = "9-1"

ALL_TEAMS = [f"조 {i}" for i in range(1, 12)] + ["대면A", "대면B", "대면C", SENIOR_TEAM]
# 로테이션 대상 조 (시니어조 및 제외 조 제외)
ROTATION_TEAMS = [team for team in ALL_TEAMS if team not in AUTO_ASSIGN_EXCLUDE_TEAMS and team != SENIOR_TEAM]

ALL_ROOMS = [f"9-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
# 로테이션 대상 방 (시니어조 고정 방 제외)
ROTATION_ROOMS = [room for room in ALL_ROOMS if room != SENIOR_ROOM]


AUTO_ASSIGN_TIME_SLOT = "11:30 - 13:00"
MANUAL_TIME_SLOTS = ["13:00 - 14:00", "14:00 - 15:00", "15:00 - 16:00", "16:00 - 17:00"]
RESERVATION_SHEET_HEADERS = ["날짜", "시간", "조", "방", "예약유형", "예약ID"]
ROTATION_SHEET_HEADER = ["next_team_index"] # ROTATION_TEAMS에 대한 인덱스

# --- Google Sheets 설정 (이전과 동일) ---
try:
    creds_json_str = st.secrets["GOOGLE_SHEETS_CREDENTIALS"]
    SPREADSHEET_NAME = st.secrets["GOOGLE_SHEET_NAME"]
    creds_dict = json.loads(creds_json_str)
    if 'private_key' in creds_dict and isinstance(creds_dict.get('private_key'), str):
        creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open(SPREADSHEET_NAME)
    reservations_ws = spreadsheet.worksheet("reservations")
    rotation_ws = spreadsheet.worksheet("rotation_state")
    GSHEET_AVAILABLE = True
except Exception as e:
    GSHEET_AVAILABLE = False
    st.error(f"Google Sheets 연결에 심각한 오류가 발생했습니다: {e}")
    st.info("Secrets 및 GCP API 설정을 다시 확인해주세요.")
    st.stop()

# --- 데이터 로드 및 저장 함수 (Google Sheets - 이전과 동일) ---
def get_all_records_as_df(worksheet, expected_headers):
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)
    # 헤더가 없거나, 예상과 다를 경우 빈 DataFrame 반환 (헤더 포함)
    if df.empty or not all(h in df.columns for h in expected_headers):
        return pd.DataFrame(columns=expected_headers)

    if "날짜" in df.columns and worksheet.title == "reservations":
        df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
        df = df.dropna(subset=['날짜'])
    return df

def update_worksheet_from_df(worksheet, df, headers):
    df_values = [headers] + df.astype(str).values.tolist()
    worksheet.clear()
    worksheet.update(df_values, value_input_option='USER_ENTERED')

def load_reservations():
    if not GSHEET_AVAILABLE: return pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
    df = get_all_records_as_df(reservations_ws, RESERVATION_SHEET_HEADERS)
    if "예약ID" not in df.columns: # 이전 데이터 호환
        df["예약ID"] = [str(uuid.uuid4()) for _ in range(len(df))] if not df.empty else []
    return df

def save_reservations(df):
    if not GSHEET_AVAILABLE: return
    df_to_save = df.copy()
    if '날짜' in df_to_save.columns:
        df_to_save['날짜'] = pd.to_datetime(df_to_save['날짜']).dt.strftime('%Y-%m-%d')
    update_worksheet_from_df(reservations_ws, df_to_save, RESERVATION_SHEET_HEADERS)

def load_rotation_state():
    if not GSHEET_AVAILABLE: return 0
    df_state = get_all_records_as_df(rotation_ws, ROTATION_SHEET_HEADER)
    if not df_state.empty and "next_team_index" in df_state.columns:
        try:
            return int(df_state.iloc[0]["next_team_index"])
        except (ValueError, TypeError): return 0
    return 0

def save_rotation_state(next_team_index):
    if not GSHEET_AVAILABLE: return
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    update_worksheet_from_df(rotation_ws, df_state, ROTATION_SHEET_HEADER)


# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약", layout="centered", initial_sidebar_state="collapsed") # centered로 변경

st.title("🚀 조모임 스터디룸 예약")
st.caption("Google Sheets 연동 | 자동 배정은 수, 일요일에만")
st.markdown("---")

if not GSHEET_AVAILABLE: # 시작 시 한번 더 체크
    st.stop()

reservations_df = load_reservations()

tab1, tab2, tab3 = st.tabs(["🔄 자동 배정", "✍️ 수동 예약", "🗓️ 예약 현황"])

with tab1:
    st.header("🔄 자동 배정 (수, 일)")
    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT}`
        - **실행 요일:** 수요일, 일요일에만 실행 가능합니다.
        - **고정 배정:**
            - `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:**
            - `{SENIOR_TEAM}`과 `{SENIOR_ROOM}`을 제외한 나머지 조와 방으로 로테이션 배정됩니다.
            - 제외 조: `{', '.join(AUTO_ASSIGN_EXCLUDE_TEAMS)}`
            - 로테이션 대상 조: `{', '.join(ROTATION_TEAMS)}`
            - 로테이션 대상 방: `{', '.join(ROTATION_ROOMS)}`
        - 이전 자동 배정 기록을 바탕으로 순서대로 배정됩니다.
        """)

    auto_assign_date_input = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date")
    weekday = auto_assign_date_input.weekday() # 0:월, 1:화, 2:수, 3:목, 4:금, 5:토, 6:일

    if weekday not in [2, 6]: # 수요일(2) 또는 일요일(6)이 아닌 경우
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다.")
    else:
        if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn", type="primary"):
            reservations_df = load_reservations() # 최신 데이터
            existing_auto = reservations_df[
                (reservations_df["날짜"] == auto_assign_date_input) &
                (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
                (reservations_df["예약유형"] == "자동")
            ]

            if not existing_auto.empty:
                st.warning(f"이미 {auto_assign_date_input.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_reservations_list = []
                assigned_info_display = []

                # 1. 시니어조 고정 배정
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_reservations_list.append({
                        "날짜": auto_assign_date_input, "시간": AUTO_ASSIGN_TIME_SLOT,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_display.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")

                # 2. 나머지 조 로테이션 배정
                next_rotation_idx = load_rotation_state()
                num_rotation_teams = len(ROTATION_TEAMS)
                num_rotation_rooms = len(ROTATION_ROOMS)

                available_rooms_for_rotation = min(num_rotation_teams, num_rotation_rooms)

                for i in range(available_rooms_for_rotation):
                    if num_rotation_teams == 0: break # 배정할 조가 없으면 중단

                    team_idx_in_rotation_list = (next_rotation_idx + i) % num_rotation_teams
                    team_to_assign = ROTATION_TEAMS[team_idx_in_rotation_list]
                    room_to_assign = ROTATION_ROOMS[i] # 방은 순서대로

                    new_auto_reservations_list.append({
                        "날짜": auto_assign_date_input, "시간": AUTO_ASSIGN_TIME_SLOT,
                        "조": team_to_assign, "방": room_to_assign, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_display.append(f"🔄 **{team_to_assign}** → **{room_to_assign}** (로테이션)")

                if new_auto_reservations_list:
                    new_df = pd.DataFrame(new_auto_reservations_list)
                    reservations_df = pd.concat([reservations_df, new_df], ignore_index=True)
                    save_reservations(reservations_df)
                    # 로테이션 인덱스 업데이트 (실제 배정된 로테이션 조/방 수만큼)
                    new_next_rotation_idx = (next_rotation_idx + available_rooms_for_rotation) % num_rotation_teams if num_rotation_teams > 0 else 0
                    save_rotation_state(new_next_rotation_idx)

                    st.success(f"🎉 {auto_assign_date_input.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_display: st.markdown(f"- {info}")
                    if num_rotation_teams > 0 :
                        st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_rotation_idx]}'")
                    st.rerun()
                else:
                    st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT})")
    auto_today = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_input) & # 선택된 날짜 기준
        (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today.empty:
        st.dataframe(auto_today[["조", "방"]].sort_values(by="방"), use_container_width=True, height=len(auto_today)*38 + 38) # 높이 동적 조절
    else:
        st.info(f"{auto_assign_date_input.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")


with tab2:
    st.header("✍️ 수동 예약 및 취소")
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{', '.join(MANUAL_TIME_SLOTS)}` (1시간 단위)
        - 원하는 날짜, 조, 시간, 방을 선택하여 예약합니다.
        - 중복 예약은 불가능합니다.
        - 아래 '나의 수동 예약 취소' 섹션에서 예약을 취소할 수 있습니다.
        """)

    st.subheader("📝 새 예약 등록")
    manual_date = st.date_input("예약 날짜", value=date.today(), min_value=date.today(), key="manual_date_tab2")

    col1, col2 = st.columns(2)
    with col1:
        selected_team = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel") # 모든 조 선택 가능
    with col2:
        selected_room = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel") # 모든 방 선택 가능

    selected_time_slot = st.selectbox("시간 선택", MANUAL_TIME_SLOTS, key="manual_time_sel")

    if st.button("✅ 예약하기", key="manual_reserve_btn_tab2", type="primary", use_container_width=True):
        reservations_df = load_reservations() # 최신 데이터
        # 중복 예약 확인 (이전 로직과 유사)
        conflict_room = reservations_df[
            (reservations_df["날짜"] == manual_date) &
            (reservations_df["시간"] == selected_time_slot) &
            (reservations_df["방"] == selected_room)
        ]
        conflict_team = reservations_df[
            (reservations_df["날짜"] == manual_date) &
            (reservations_df["시간"] == selected_time_slot) &
            (reservations_df["조"] == selected_team)
        ]

        if not conflict_room.empty:
            st.error(f"⚠️ {selected_room}은(는) 해당 시간에 이미 예약되어 있습니다.")
        elif not conflict_team.empty:
            st.error(f"⚠️ {selected_team}은(는) 해당 시간에 이미 다른 예약을 했습니다.")
        else:
            new_manual_res = pd.DataFrame([{
                "날짜": manual_date, "시간": selected_time_slot, "조": selected_team,
                "방": selected_room, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }])
            reservations_df = pd.concat([reservations_df, new_manual_res], ignore_index=True)
            save_reservations(reservations_df)
            st.success(f"🎉 예약 완료: {manual_date.strftime('%Y-%m-%d')} / {selected_team} / {selected_room} / {selected_time_slot}")
            st.rerun()

    st.markdown("---")
    st.subheader(f"🚫 나의 수동 예약 취소 ({manual_date.strftime('%Y-%m-%d')})")
    my_manual_reservations = reservations_df[
        (reservations_df["날짜"] == manual_date) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_reservations.empty:
        my_manual_reservations['시간'] = pd.Categorical(my_manual_reservations['시간'], categories=MANUAL_TIME_SLOTS, ordered=True)
        my_manual_reservations = my_manual_reservations.sort_values(by=["시간", "조"])

        for index, row in my_manual_reservations.iterrows():
            res_id = row["예약ID"]
            # 예약 정보와 취소 버튼을 한 줄에 표시
            item_cols = st.columns([3, 1]) # 정보, 버튼 비율
            with item_cols[0]:
                st.markdown(f"**{row['시간']}** / **{row['조']}** / `{row['방']}`")
            with item_cols[1]:
                if st.button("취소", key=f"cancel_{res_id}", use_container_width=True):
                    reservations_df = load_reservations()
                    reservations_df = reservations_df[reservations_df["예약ID"] != res_id]
                    save_reservations(reservations_df)
                    st.success(f"🗑️ 예약 취소됨: {row['조']} / {row['방']} ({row['시간']})")
                    st.rerun()
        if my_manual_reservations.empty: # 취소 후 비었을 경우 (이 코드는 도달하기 어려움)
             st.info(f"{manual_date.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")
    else:
        st.info(f"{manual_date.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")

with tab3:
    st.header("🗓️ 전체 예약 현황")
    view_date_all = st.date_input("조회할 날짜", value=date.today(), key="view_date_all_tab3_input")

    reservations_df_display = load_reservations()
    if not reservations_df_display.empty:
        display_df = reservations_df_display[reservations_df_display["날짜"] == view_date_all].copy()

        if not display_df.empty:
            st.subheader(f"{view_date_all.strftime('%Y-%m-%d')} 예약 내역")
            time_order = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            display_df['시간'] = pd.Categorical(display_df['시간'], categories=time_order, ordered=True)
            display_df_sorted = display_df.sort_values(by=["시간", "방"])
            st.dataframe(display_df_sorted[["시간", "조", "방", "예약유형"]], use_container_width=True, height=len(display_df_sorted)*38 + 38)
        else:
            st.info(f"{view_date_all.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    with st.expander("🔍 전체 기간 모든 예약 보기 (클릭)", expanded=False):
        if not reservations_df_display.empty:
            st.subheader("모든 예약 기록")
            df_all_copy = reservations_df_display.copy()
            time_order_all = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            df_all_copy['시간'] = pd.Categorical(df_all_copy['시간'], categories=time_order_all, ordered=True)
            st.dataframe(df_all_copy.sort_values(by=["날짜","시간", "방"])[["날짜", "시간", "조", "방", "예약유형"]], use_container_width=True)
        else:
            st.info("등록된 예약이 없습니다.")

# 사이드바 관리자 메뉴 (이전과 동일, layout="centered"에 맞춰 내용이 중앙에 옴)
st.sidebar.title("🛠️ 관리자 메뉴")
if st.sidebar.button("⚠️ 모든 예약 기록 및 로테이션 초기화", key="reset_all_data_g_sheets_sidebar"):
    if st.sidebar.checkbox("정말로 모든 기록을 삭제하고 로테이션 상태를 초기화하시겠습니까? (Google Sheets 데이터가 삭제됩니다)", key="confirm_delete_g_sheets_sidebar"):
        try:
            empty_reservations_df = pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
            update_worksheet_from_df(reservations_ws, empty_reservations_df, RESERVATION_SHEET_HEADERS)
            save_rotation_state(0)
            st.sidebar.success("모든 예약 기록 및 로테이션 상태가 Google Sheets에서 초기화되었습니다.")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"초기화 중 오류 발생: {e}")
