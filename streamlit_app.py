import streamlit as st
import pandas as pd
from datetime import datetime, date, time
import gspread
from google.oauth2.service_account import Credentials
import uuid # 고유 ID 생성을 위해 추가
import json # JSON 파싱을 위해 추가

# --- Google Sheets 설정 ---
try:
    # Streamlit Cloud Secrets에서 정보 가져오기
    creds_json_str = st.secrets["GOOGLE_SHEETS_CREDENTIALS"] # 문자열로 가져옴
    SPREADSHEET_NAME = st.secrets["GOOGLE_SHEET_NAME"]

    # 문자열로 된 JSON을 파이썬 딕셔너리로 변환
    creds_dict = json.loads(creds_json_str)

    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes) # 딕셔너리 전달
    gc = gspread.authorize(creds)
    spreadsheet = gc.open(SPREADSHEET_NAME)
    reservations_ws = spreadsheet.worksheet("reservations")
    rotation_ws = spreadsheet.worksheet("rotation_state")
    GSHEET_AVAILABLE = True
except KeyError as e: # Secrets에 키가 없는 경우
    GSHEET_AVAILABLE = False
    st.error(f"Streamlit Secrets 설정 오류: '{e}' 키를 찾을 수 없습니다. 'GOOGLE_SHEETS_CREDENTIALS'와 'GOOGLE_SHEET_NAME'이 올바르게 설정되었는지 확인해주세요.")
    st.stop()
except json.JSONDecodeError: # JSON 파싱 오류
    GSHEET_AVAILABLE = False
    st.error("Google Sheets 인증 정보(GOOGLE_SHEETS_CREDENTIALS)가 올바른 JSON 형식이 아닙니다. Secrets 설정을 확인해주세요.")
    st.stop()
except Exception as e: # 그 외 gspread 또는 API 오류
    GSHEET_AVAILABLE = False
    st.error(f"Google Sheets 연결에 실패했습니다: {e}")
    st.info("GCP에서 Google Sheets API 및 Drive API가 활성화되었는지, 서비스 계정에 스프레드시트 공유 권한이 부여되었는지 확인해주세요.")
    st.stop()

# --- 초기 설정 ---
TEAMS = [f"조 {i}" for i in range(1, 12)] + ["대면A", "대면B", "대면C", "시니어조"]
ROOMS = [f"9-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
AUTO_ASSIGN_TIME_SLOT = "11:30 - 13:00"
MANUAL_TIME_SLOTS = ["13:00 - 14:00", "14:00 - 15:00", "15:00 - 16:00", "16:00 - 17:00"]
RESERVATION_SHEET_HEADERS = ["날짜", "시간", "조", "방", "예약유형", "예약ID"]
ROTATION_SHEET_HEADER = ["next_team_index"]

# --- 데이터 로드 및 저장 함수 (Google Sheets) ---
def get_all_records_as_df(worksheet):
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)
    if df.empty and list(df.columns) != RESERVATION_SHEET_HEADERS and worksheet.title == "reservations":
        df = pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
    elif df.empty and list(df.columns) != ROTATION_SHEET_HEADER and worksheet.title == "rotation_state":
        df = pd.DataFrame(columns=ROTATION_SHEET_HEADER)

    # 날짜 열을 datetime.date 객체로 변환 (reservations 시트만 해당)
    if "날짜" in df.columns:
        df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
        df = df.dropna(subset=['날짜']) # 변환 실패한 행 제거
    return df

def update_worksheet_from_df(worksheet, df, headers):
    # 헤더를 포함하여 DataFrame을 리스트의 리스트로 변환
    df_values = [headers] + df.astype(str).values.tolist()
    worksheet.clear() # 기존 내용 모두 삭제
    worksheet.update(df_values, value_input_option='USER_ENTERED') # 새 내용으로 업데이트

def load_reservations():
    if not GSHEET_AVAILABLE: return pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
    df = get_all_records_as_df(reservations_ws)
    # 예약ID가 없는 경우를 대비 (기존 데이터 호환)
    if "예약ID" not in df.columns and not df.empty:
        df["예약ID"] = [str(uuid.uuid4()) for _ in range(len(df))]
        # 만약 ID가 추가되었다면, 시트 업데이트 (선택적)
        # update_worksheet_from_df(reservations_ws, df, RESERVATION_SHEET_HEADERS)
    elif "예약ID" not in df.columns and df.empty:
        df["예약ID"] = []

    # 날짜 열 형식 통일
    if "날짜" in df.columns:
         df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
         df = df.dropna(subset=['날짜'])
    return df

def save_reservations(df):
    if not GSHEET_AVAILABLE: return
    df_to_save = df.copy()
    if '날짜' in df_to_save.columns: # 날짜를 YYYY-MM-DD 문자열로
        df_to_save['날짜'] = pd.to_datetime(df_to_save['날짜']).dt.strftime('%Y-%m-%d')
    update_worksheet_from_df(reservations_ws, df_to_save, RESERVATION_SHEET_HEADERS)

def load_rotation_state():
    if not GSHEET_AVAILABLE: return 0
    df_state = get_all_records_as_df(rotation_ws)
    if not df_state.empty and "next_team_index" in df_state.columns:
        try:
            return int(df_state.iloc[0]["next_team_index"])
        except ValueError: # 값이 숫자가 아닐 경우
            return 0
    return 0

def save_rotation_state(next_team_index):
    if not GSHEET_AVAILABLE: return
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    update_worksheet_from_df(rotation_ws, df_state, ROTATION_SHEET_HEADER)

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약 시스템", layout="wide", initial_sidebar_state="collapsed")

if not GSHEET_AVAILABLE:
    st.stop() # Google Sheets 연결 실패 시 앱 중단

st.title("🚀 조모임 스터디룸 예약 시스템")
st.caption("Google Sheets를 사용하여 데이터가 안전하게 보관됩니다.")
st.markdown("---")

reservations_df = load_reservations()

tab1, tab2, tab3 = st.tabs(["🔄 자동 배정 (11:30-13:00)", "✍️ 수동 예약 및 취소", "🗓️ 전체 예약 현황"])

with tab1:
    st.header("🔄 오늘의 자동 배정 (로테이션)")
    st.markdown(f"매일 **{AUTO_ASSIGN_TIME_SLOT}** 시간에 조별 방이 자동으로 배정됩니다.")
    # (탭1 설명 부분은 이전 코드와 유사하게 유지 가능)

    auto_assign_date = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date")

    if st.button("✨ 자동 배정 실행하기", key="auto_assign_btn", type="primary"):
        reservations_df = load_reservations() # 항상 최신 데이터로 시작
        existing_auto = reservations_df[
            (reservations_df["날짜"] == auto_assign_date) &
            (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
            (reservations_df["예약유형"] == "자동")
        ]

        if not existing_auto.empty:
            st.warning(f"⚠️ {auto_assign_date.strftime('%Y-%m-%d')}에 이미 자동 배정 내역이 있습니다.")
        else:
            next_idx = load_rotation_state()
            num_teams = len(TEAMS)
            new_auto_reservations = []
            assigned_info = []

            for i in range(len(ROOMS)):
                if num_teams == 0: break
                team_idx = (next_idx + i) % num_teams
                team = TEAMS[team_idx]
                room = ROOMS[i]
                reservation_id = str(uuid.uuid4())

                new_auto_reservations.append({
                    "날짜": auto_assign_date, "시간": AUTO_ASSIGN_TIME_SLOT,
                    "조": team, "방": room, "예약유형": "자동", "예약ID": reservation_id
                })
                assigned_info.append(f"✅ **{team}** → **{room}**")

            if new_auto_reservations:
                new_df = pd.DataFrame(new_auto_reservations)
                reservations_df = pd.concat([reservations_df, new_df], ignore_index=True)
                save_reservations(reservations_df)
                save_rotation_state((next_idx + len(ROOMS)) % num_teams if num_teams > 0 else 0)
                st.success("🎉 자동 배정 완료!")
                for info in assigned_info: st.markdown(f"- {info}")
                st.rerun()
            else:
                st.error("자동 배정할 조 또는 방이 없습니다.")

    st.subheader(f"오늘의 자동 배정 현황 ({auto_assign_date.strftime('%Y-%m-%d')})")
    auto_today = reservations_df[
        (reservations_df["날짜"] == auto_assign_date) &
        (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today.empty:
        st.dataframe(auto_today[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info("자동 배정 내역이 없습니다.")


with tab2:
    st.header("✍️ 수동 예약 및 취소")
    st.markdown("원하는 시간과 방을 직접 선택하여 예약하거나, 기존 예약을 취소할 수 있습니다.")

    st.subheader("📝 새 예약 등록")
    manual_date = st.date_input("예약 날짜", value=date.today(), min_value=date.today(), key="manual_date_input")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        selected_team = st.selectbox("조 선택", TEAMS, key="manual_team_select")
    with col2:
        selected_time_slot = st.selectbox("시간 선택", MANUAL_TIME_SLOTS, key="manual_time_select")
    with col3:
        selected_room = st.selectbox("방 선택", ROOMS, key="manual_room_select")

    if st.button("✅ 예약하기", key="manual_reserve_btn", type="primary"):
        reservations_df = load_reservations() # 최신 데이터
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
            reservation_id = str(uuid.uuid4())
            new_manual_res = pd.DataFrame([{
                "날짜": manual_date, "시간": selected_time_slot, "조": selected_team,
                "방": selected_room, "예약유형": "수동", "예약ID": reservation_id
            }])
            reservations_df = pd.concat([reservations_df, new_manual_res], ignore_index=True)
            save_reservations(reservations_df)
            st.success(f"🎉 예약 완료: {selected_team} / {selected_room} / {selected_time_slot}")
            st.rerun()

    st.markdown("---")
    st.subheader(f"🚫 나의 수동 예약 취소 ({manual_date.strftime('%Y-%m-%d')})")
    
    # 선택된 날짜의 "수동" 예약만 필터링
    my_manual_reservations = reservations_df[
        (reservations_df["날짜"] == manual_date) &
        (reservations_df["예약유형"] == "수동")
    ].copy() # SettingWithCopyWarning 방지

    if not my_manual_reservations.empty:
        my_manual_reservations['시간'] = pd.Categorical(my_manual_reservations['시간'], categories=MANUAL_TIME_SLOTS, ordered=True)
        my_manual_reservations = my_manual_reservations.sort_values(by=["시간", "방"])

        for index, row in my_manual_reservations.iterrows():
            res_id = row["예약ID"]
            # 예약 정보 표시와 취소 버튼을 한 줄에
            cols = st.columns([0.2, 0.2, 0.2, 0.2, 0.2]) # 비율 조정 가능
            cols[0].write(f"{row['시간']}")
            cols[1].write(f"{row['조']}")
            cols[2].write(f"{row['방']}")
            cols[3].caption(f"ID: {str(res_id)[:8]}...") # ID 일부만 표시
            
            # 취소 버튼의 key를 고유하게 만듦
            if cols[4].button("취소", key=f"cancel_{res_id}", help=f"{row['조']}의 {row['방']} ({row['시간']}) 예약을 취소합니다."):
                reservations_df = load_reservations() # 최신 데이터 로드
                reservations_df = reservations_df[reservations_df["예약ID"] != res_id]
                save_reservations(reservations_df)
                st.success(f"🗑️ 예약 취소됨: {row['조']} / {row['방']} ({row['시간']})")
                st.rerun()
        if my_manual_reservations.empty: # 취소 후 비었을 경우
             st.info(f"{manual_date.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")

    else:
        st.info(f"{manual_date.strftime('%Y-%m-%d')}에 수동 예약 내역이 없습니다.")


with tab3:
    st.header("🗓️ 전체 예약 현황")
    view_date_all = st.date_input("조회할 날짜", value=date.today(), key="view_date_all_tab3")

    reservations_df_display = load_reservations()
    if not reservations_df_display.empty:
        display_df = reservations_df_display[reservations_df_display["날짜"] == view_date_all].copy()

        if not display_df.empty:
            st.subheader(f"{view_date_all.strftime('%Y-%m-%d')} 예약 내역")
            time_order = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            display_df['시간'] = pd.Categorical(display_df['시간'], categories=time_order, ordered=True)
            display_df_sorted = display_df.sort_values(by=["시간", "방"])
            st.dataframe(display_df_sorted[["시간", "조", "방", "예약유형"]], use_container_width=True)
        else:
            st.info(f"{view_date_all.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    if st.checkbox("🔍 전체 기간 모든 예약 보기", key="show_all_data_tab3"):
        if not reservations_df_display.empty:
            st.subheader("모든 예약 기록")
            # 전체 데이터 표시 시에도 시간 정렬 및 날짜 정렬
            df_all_copy = reservations_df_display.copy()
            time_order_all = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            df_all_copy['시간'] = pd.Categorical(df_all_copy['시간'], categories=time_order_all, ordered=True)
            st.dataframe(df_all_copy.sort_values(by=["날짜", "시간", "방"])[["날짜", "시간", "조", "방", "예약유형"]], use_container_width=True)
        else:
            st.info("등록된 예약이 없습니다.")

# 관리자 기능 (사이드바)
st.sidebar.title("🛠️ 관리자 메뉴")
if st.sidebar.button("⚠️ 모든 예약 기록 및 로테이션 초기화", key="reset_all_data_g_sheets"):
    if st.sidebar.checkbox("정말로 모든 기록을 삭제하고 로테이션 상태를 초기화하시겠습니까? (Google Sheets 데이터가 삭제됩니다)", key="confirm_delete_g_sheets"):
        try:
            # reservations 시트 비우기 (헤더는 남김)
            empty_reservations_df = pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
            update_worksheet_from_df(reservations_ws, empty_reservations_df, RESERVATION_SHEET_HEADERS)

            # rotation_state 시트 초기화 (헤더는 남김)
            save_rotation_state(0) # next_team_index를 0으로

            st.sidebar.success("모든 예약 기록 및 로테이션 상태가 Google Sheets에서 초기화되었습니다.")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"초기화 중 오류 발생: {e}")
