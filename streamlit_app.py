import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import gspread
from google.oauth2.service_account import Credentials
import uuid
import json

AUTO_ASSIGN_EXCLUDE_TEAMS = ["대면A", "대면B", "대면C"]
SENIOR_TEAM = "시니어"
SENIOR_ROOM = "9F-1"
ALL_TEAMS = [f"{i}조" for i in range(1, 13)] + ["대면A", "대면B", "대면C", "대면D", "청년", "중고등", SENIOR_TEAM]
ROTATION_TEAMS = [team for team in ALL_TEAMS if team not in AUTO_ASSIGN_EXCLUDE_TEAMS and team != SENIOR_TEAM]
ALL_ROOMS = [f"9F-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
ROTATION_ROOMS = [room for room in ALL_ROOMS if room != SENIOR_ROOM]

AUTO_ASSIGN_TIME_SLOT_STR = "11:30 - 13:00" # 문자열 표시용
# 자동 배정 시간 객체 (비교용)
AUTO_ASSIGN_START_TIME = time(11, 30)
AUTO_ASSIGN_END_TIME = time(13, 0)

# 수동 예약 가능 시간 범위
MANUAL_RESERVATION_START_HOUR = 13
MANUAL_RESERVATION_END_HOUR = 17 # 17:00 전까지 예약 가능 (즉, 16:xx 시작 가능)

RESERVATION_SHEET_HEADERS = ["날짜", "시간_시작", "시간_종료", "조", "방", "예약유형", "예약ID"] # 시간 열 변경
ROTATION_SHEET_HEADER = ["next_team_index"]

# --- Google Sheets 클라이언트 및 워크시트 초기화 (이전 캐싱 로직과 동일) ---
@st.cache_resource
def init_gspread_client():
    try:
        creds_json_str = st.secrets["GOOGLE_SHEETS_CREDENTIALS"]
        creds_dict = json.loads(creds_json_str)
        if 'private_key' in creds_dict and isinstance(creds_dict.get('private_key'), str):
            creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
        scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        st.error(f"Google Sheets 클라이언트 초기화 실패: {e}")
        return None

@st.cache_resource
def get_worksheets(_gc_client):
    if _gc_client is None: return None, None, False
    try:
        SPREADSHEET_NAME = st.secrets["GOOGLE_SHEET_NAME"]
        spreadsheet = _gc_client.open(SPREADSHEET_NAME)
        reservations_ws = spreadsheet.worksheet("reservations")
        rotation_ws = spreadsheet.worksheet("rotation_state")
        return reservations_ws, rotation_ws, True
    except Exception as e:
        st.error(f"Google Sheets 워크시트 가져오기 실패: {e}")
        return None, None, False

gc_client = init_gspread_client()
reservations_ws, rotation_ws, GSHEET_AVAILABLE = get_worksheets(gc_client)

# --- 데이터 로드 및 저장 함수 ---
@st.cache_data(ttl=300) # 캐시 시간 5분으로 줄임 (더 빠른 반영 위해)
def get_all_records_as_df_cached(_ws, expected_headers, _cache_key_prefix):
    if not GSHEET_AVAILABLE or _ws is None: return pd.DataFrame(columns=expected_headers)
    try:
        records = _ws.get_all_records()
        df = pd.DataFrame(records)
        if df.empty or not all(h in df.columns for h in expected_headers):
            return pd.DataFrame(columns=expected_headers)

        if "날짜" in df.columns and _ws.title == "reservations":
            df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
            # 시간 열을 time 객체로 변환 (오류 발생 시 NaT 처리 후 제거)
            if "시간_시작" in df.columns:
                df['시간_시작'] = pd.to_datetime(df['시간_시작'], format='%H:%M', errors='coerce').dt.time
            if "시간_종료" in df.columns:
                df['시간_종료'] = pd.to_datetime(df['시간_종료'], format='%H:%M', errors='coerce').dt.time
            df = df.dropna(subset=['날짜', '시간_시작', '시간_종료'])
        return df
    except Exception as e:
        st.warning(f"'{_ws.title}' 시트 로드 중 오류 (캐시 사용 시도): {e}")
        return pd.DataFrame(columns=expected_headers)

def update_worksheet_from_df(_ws, df, headers):
    if not GSHEET_AVAILABLE or _ws is None: return
    try:
        df_to_save = df.copy()
        # 시간 객체를 문자열로 변환하여 저장
        if "시간_시작" in df_to_save.columns:
            df_to_save['시간_시작'] = df_to_save['시간_시작'].apply(lambda t: t.strftime('%H:%M') if isinstance(t, time) else t)
        if "시간_종료" in df_to_save.columns:
            df_to_save['시간_종료'] = df_to_save['시간_종료'].apply(lambda t: t.strftime('%H:%M') if isinstance(t, time) else t)

        df_values = [headers] + df_to_save.astype(str).values.tolist()
        _ws.clear()
        _ws.update(df_values, value_input_option='USER_ENTERED')
        # 캐시 무효화
        if _ws.title == "reservations": get_all_records_as_df_cached.clear()
        elif _ws.title == "rotation_state": load_rotation_state_cached.clear()
    except Exception as e:
        st.error(f"'{_ws.title}' 시트 업데이트 중 오류: {e}")

def load_reservations():
    return get_all_records_as_df_cached(reservations_ws, RESERVATION_SHEET_HEADERS, "reservations_cache")

@st.cache_data(ttl=300)
def load_rotation_state_cached(_rotation_ws, _cache_key_prefix):
    if not GSHEET_AVAILABLE or _rotation_ws is None: return 0
    df_state = get_all_records_as_df_cached(_rotation_ws, ROTATION_SHEET_HEADER, _cache_key_prefix)
    if not df_state.empty and "next_team_index" in df_state.columns:
        try: return int(df_state.iloc[0]["next_team_index"])
        except (ValueError, TypeError): return 0
    return 0

def load_rotation_state():
    return load_rotation_state_cached(rotation_ws, "rotation_state_cache")

def save_reservations(df):
    update_worksheet_from_df(reservations_ws, df, RESERVATION_SHEET_HEADERS)

def save_rotation_state(next_team_index):
    if not GSHEET_AVAILABLE or rotation_ws is None: return
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    update_worksheet_from_df(rotation_ws, df_state, ROTATION_SHEET_HEADER)

# 시간 중복 확인 함수
def check_time_overlap(new_start, new_end, existing_start, existing_end):
    return max(new_start, existing_start) < min(new_end, existing_end)

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약", layout="centered", initial_sidebar_state="auto")

# 탭 상태 유지를 위한 세션 상태 초기화
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "🔄 자동 배정" # 기본 탭

# --- 사이드바 (이전과 동일) ---
st.sidebar.title("⚙️ 설정 및 관리")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제")
if st.sidebar.button("🔄 데이터 캐시 새로고침"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다. 페이지가 새로고침됩니다.")
    st.rerun()
st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ 관리자 메뉴")
# (이하 관리자 메뉴 동일)
if st.sidebar.button("⚠️ 모든 예약 기록 및 로테이션 초기화", key="reset_all_data_main"):
    if st.sidebar.checkbox("정말로 모든 기록을 삭제하고 로테이션 상태를 초기화하시겠습니까?", key="confirm_delete_main"):
        # ... (초기화 로직)
        try:
            if GSHEET_AVAILABLE:
                empty_reservations_df = pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
                update_worksheet_from_df(reservations_ws, empty_reservations_df, RESERVATION_SHEET_HEADERS)
                save_rotation_state(0)
                st.sidebar.success("모든 예약 기록 및 로테이션 상태가 Google Sheets에서 초기화되었습니다.")
                st.rerun()
            else:
                st.sidebar.error("Google Sheets에 연결되지 않아 초기화할 수 없습니다.")
        except Exception as e:
            st.sidebar.error(f"초기화 중 오류 발생: {e}")


# --- 메인 화면 ---
st.title("🚀 조모임 스터디룸 예약")
# (캡션 동일)
if test_mode:
    st.caption("Google Sheets 연동 | 🧪 **테스트 모드 실행 중**")
else:
    st.caption("Google Sheets 연동 | 자동 배정은 수, 일요일에만")
st.markdown("---")

if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df_main = load_reservations() # 전역적으로 사용할 예약 데이터

# 탭 생성 및 선택 상태 관리
tab_titles = ["🔄 자동 배정", "✍️ 수동 예약", "🗓️ 예약 시간표"]
# active_tab_index = tab_titles.index(st.session_state.active_tab) # 이렇게 하면 오류 가능성
try:
    active_tab_index = tab_titles.index(st.session_state.get("active_tab", tab_titles[0]))
except ValueError:
    active_tab_index = 0 # st.session_state.active_tab에 없는 값이면 기본값

tabs = st.tabs(tab_titles)

# 탭 1: 자동 배정
with tabs[0]:
    st.session_state.active_tab = tab_titles[0] # 현재 탭 저장
    st.header("🔄 자동 배정")
    # (자동 배정 탭 내용, 이전 코드와 유사하게 구성, reservations_df_main 사용)
    # ... (생략 - 이전 자동 배정 탭 로직과 동일하게 next_rotation_idx 로드 등 포함)
    if test_mode: st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else: st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT_STR}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** (이하 설명 동일)
        """)

    auto_assign_date_tab1 = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_tab1_cached")
    weekday_tab1 = auto_assign_date_tab1.weekday()
    can_auto_assign_tab1 = test_mode or (weekday_tab1 in [2, 6])

    if not can_auto_assign_tab1:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_tab1_cached", type="primary"):
        if can_auto_assign_tab1:
            current_reservations_tab1 = load_reservations() # 최신 데이터
            existing_auto_tab1 = current_reservations_tab1[
                (current_reservations_tab1["날짜"] == auto_assign_date_tab1) &
                (current_reservations_tab1["시간_시작"] == AUTO_ASSIGN_START_TIME) & # 시간 객체로 비교
                (current_reservations_tab1["예약유형"] == "자동")
            ]

            if not existing_auto_tab1.empty:
                st.warning(f"이미 {auto_assign_date_tab1.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_tab1 = []
                assigned_info_tab1 = []
                # 시니어조 배정
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_tab1.append({
                        "날짜": auto_assign_date_tab1, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_tab1.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션 배정
                next_idx_tab1 = load_rotation_state()
                # ... (이전 로테이션 배정 로직과 동일, new_auto_list_tab1에 추가) ...
                num_rotation_teams_tab1 = len(ROTATION_TEAMS)
                num_rotation_rooms_tab1 = len(ROTATION_ROOMS)
                available_rooms_for_rotation_tab1 = min(num_rotation_teams_tab1, num_rotation_rooms_tab1)

                for i in range(available_rooms_for_rotation_tab1):
                    if num_rotation_teams_tab1 == 0: break
                    team_idx_in_list = (next_idx_tab1 + i) % num_rotation_teams_tab1
                    team_assign = ROTATION_TEAMS[team_idx_in_list]
                    room_assign = ROTATION_ROOMS[i]
                    new_auto_list_tab1.append({
                        "날짜": auto_assign_date_tab1, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign, "방": room_assign, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_tab1.append(f"🔄 **{team_assign}** → **{room_assign}** (로테이션)")


                if new_auto_list_tab1:
                    new_df_tab1 = pd.DataFrame(new_auto_list_tab1)
                    updated_df_tab1 = pd.concat([current_reservations_tab1, new_df_tab1], ignore_index=True)
                    save_reservations(updated_df_tab1)
                    new_next_idx_tab1 = (next_idx_tab1 + available_rooms_for_rotation_tab1) % num_rotation_teams_tab1 if num_rotation_teams_tab1 > 0 else 0
                    save_rotation_state(new_next_idx_tab1)
                    st.success(f"🎉 {auto_assign_date_tab1.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_tab1: st.markdown(f"- {info}")
                    if num_rotation_teams_tab1 > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_tab1]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_tab1 = reservations_df_main[
        (reservations_df_main["날짜"] == auto_assign_date_tab1) &
        (reservations_df_main["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df_main["예약유형"] == "자동")
    ]
    if not auto_today_display_tab1.empty:
        st.dataframe(auto_today_display_tab1[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_tab1.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")


# 탭 2: 수동 예약
with tabs[1]:
    st.session_state.active_tab = tab_titles[1] # 현재 탭 저장
    st.header("✍️ 수동 예약 및 취소")
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지 자유롭게 시간 설정.
        - 최소 예약 시간은 30분, 예약 단위는 15분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.subheader("📝 새 예약 등록")
    manual_date_tab2 = st.date_input("예약 날짜", value=date.today(), min_value=date.today(), key="manual_date_tab2_time")

    cols_t2_details = st.columns(2)
    with cols_t2_details[0]:
        selected_team_tab2 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_time")
        # 시작 시간 선택
        manual_start_time_input = st.time_input(
            "시작 시간",
            value=time(MANUAL_RESERVATION_START_HOUR, 0),
            step=timedelta(minutes=15), # 15분 간격
            key="manual_start_time"
        )
    with cols_t2_details[1]:
        selected_room_tab2 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_time")
        # 종료 시간 선택
        manual_end_time_input = st.time_input(
            "종료 시간",
            value=time(MANUAL_RESERVATION_START_HOUR + 1, 0), # 기본 1시간 뒤
            step=timedelta(minutes=15),
            key="manual_end_time"
        )

    time_valid = True
    if manual_start_time_input >= manual_end_time_input:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다.")
        time_valid = False
    elif manual_start_time_input < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"예약 시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 이후여야 합니다.")
        time_valid = False
    elif manual_end_time_input > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"예약 종료 시간은 {MANUAL_RESERVATION_END_HOUR}:00 이전이어야 합니다.")
        time_valid = False
    # 최소 예약 시간 (예: 30분)
    min_duration = timedelta(minutes=30)
    if datetime.combine(date.min, manual_end_time_input) - datetime.combine(date.min, manual_start_time_input) < min_duration:
        st.error(f"최소 예약 시간은 {min_duration.seconds // 60}분입니다.")
        time_valid = False


    if st.button("✅ 예약하기", key="manual_reserve_btn_tab2_time", type="primary", use_container_width=True, disabled=not time_valid):
        if time_valid:
            current_reservations_tab2 = load_reservations()
            is_overlap = False
            # 1. 해당 방의 시간 중복 체크
            room_reservations = current_reservations_tab2[
                (current_reservations_tab2["날짜"] == manual_date_tab2) &
                (current_reservations_tab2["방"] == selected_room_tab2)
            ]
            for _, existing_res in room_reservations.iterrows():
                if check_time_overlap(manual_start_time_input, manual_end_time_input,
                                      existing_res["시간_시작"], existing_res["시간_종료"]):
                    st.error(f"⚠️ {selected_room_tab2}은(는) 해당 시간에 이미 예약(또는 일부 겹침)이 있습니다: {existing_res['시간_시작'].strftime('%H:%M')}-{existing_res['시간_종료'].strftime('%H:%M')}")
                    is_overlap = True
                    break
            if is_overlap: st.stop() # 중복 시 더 이상 진행 안 함

            # 2. 해당 조의 시간 중복 체크
            team_reservations = current_reservations_tab2[
                (current_reservations_tab2["날짜"] == manual_date_tab2) &
                (current_reservations_tab2["조"] == selected_team_tab2)
            ]
            for _, existing_res in team_reservations.iterrows():
                 if check_time_overlap(manual_start_time_input, manual_end_time_input,
                                      existing_res["시간_시작"], existing_res["시간_종료"]):
                    st.error(f"⚠️ {selected_team_tab2}은(는) 해당 시간에 이미 다른 예약(또는 일부 겹침)이 있습니다: {existing_res['방']} ({existing_res['시간_시작'].strftime('%H:%M')}-{existing_res['시간_종료'].strftime('%H:%M')})")
                    is_overlap = True
                    break
            if is_overlap: st.stop()

            # 예약 진행
            new_manual_res_item = {
                "날짜": manual_date_tab2, "시간_시작": manual_start_time_input, "시간_종료": manual_end_time_input,
                "조": selected_team_tab2, "방": selected_room_tab2, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_tab2 = pd.concat([current_reservations_tab2, pd.DataFrame([new_manual_res_item])], ignore_index=True)
            save_reservations(updated_df_tab2)
            st.success(f"🎉 예약 완료: {manual_date_tab2.strftime('%Y-%m-%d')} / {selected_team_tab2} / {selected_room_tab2} / {manual_start_time_input.strftime('%H:%M')}-{manual_end_time_input.strftime('%H:%M')}")
            st.rerun() # 탭 상태 유지를 위해 st.session_state.active_tab이 설정된 후 rerun

    st.markdown("---")
    st.subheader(f"🚫 나의 수동 예약 취소 ({manual_date_tab2.strftime('%Y-%m-%d')})")
    # (수동 예약 취소 로직, reservations_df_main 사용, 시간 표시를 HH:MM - HH:MM 형식으로)
    my_manual_res_display_tab2 = reservations_df_main[
        (reservations_df_main["날짜"] == manual_date_tab2) &
        (reservations_df_main["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_tab2.empty:
        # 시간_시작을 기준으로 정렬
        my_manual_res_display_tab2 = my_manual_res_display_tab2.sort_values(by=["시간_시작", "조"])

        for index, row in my_manual_res_display_tab2.iterrows():
            res_id_tab2 = row["예약ID"]
            time_str_tab2 = f"{row['시간_시작'].strftime('%H:%M')} - {row['시간_종료'].strftime('%H:%M')}"
            item_cols_tab2_cancel = st.columns([3,1])
            with item_cols_tab2_cancel[0]:
                st.markdown(f"**{time_str_tab2}** / **{row['조']}** / `{row['방']}`")
            with item_cols_tab2_cancel[1]:
                if st.button("취소", key=f"cancel_{res_id_tab2}_time", use_container_width=True):
                    current_on_cancel_tab2 = load_reservations()
                    updated_on_cancel_tab2 = current_on_cancel_tab2[current_on_cancel_tab2["예약ID"] != res_id_tab2]
                    save_reservations(updated_on_cancel_tab2)
                    st.success(f"🗑️ 예약 취소됨: {row['조']} / {row['방']} ({time_str_tab2})")
                    st.rerun()
    else:
        st.info(f"{manual_date_tab2.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


# 탭 3: 예약 시간표
with tabs[2]:
    st.session_state.active_tab = tab_titles[2] # 현재 탭 저장
    st.header("🗓️ 예약 시간표")
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date")

    if not reservations_df_main.empty:
        day_reservations = reservations_df_main[reservations_df_main["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            # 시간표 생성을 위한 시간 슬롯 (30분 단위)
            time_slots = []
            current_time = datetime.combine(date.today(), time(11, 0)) # 11:00 부터 시작
            end_of_day = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0)) # 17:00 까지

            while current_time < end_of_day:
                time_slots.append(current_time.time())
                current_time += timedelta(minutes=30)

            timetable_df = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots], columns=ALL_ROOMS)
            timetable_df = timetable_df.fillna('') # 빈 칸으로 초기화

            for _, res in day_reservations.iterrows():
                start_res_dt = datetime.combine(date.today(), res["시간_시작"])
                end_res_dt = datetime.combine(date.today(), res["시간_종료"])

                # 예약된 시간에 해당하는 모든 30분 슬롯에 조 이름 표시
                current_slot_dt = start_res_dt
                while current_slot_dt < end_res_dt:
                    slot_str = current_slot_dt.strftime("%H:%M")
                    if slot_str in timetable_df.index and res["방"] in timetable_df.columns:
                        # 이미 다른 예약이 같은 슬롯에 있다면 (일부 겹침), 줄바꿈으로 추가 (간단히)
                        if timetable_df.loc[slot_str, res["방"]] == '':
                            timetable_df.loc[slot_str, res["방"]] = f"{res['조']} ({res['예약유형'][0]})" # 자동(A)/수동(S)
                        else: # 더 복잡한 중첩 표시는 어려움, 여기서는 덮어쓰거나 간단히 추가
                             timetable_df.loc[slot_str, res["방"]] += f"\n{res['조']} ({res['예약유형'][0]})" # \n은 dataframe에서 잘 안보임
                    current_slot_dt += timedelta(minutes=30) # 다음 30분 슬롯으로 이동

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            # st.dataframe(timetable_df, use_container_width=True) # 기본 dataframe
            # 좀 더 보기 좋게 HTML 테이블로 표시 (스타일링은 제한적)
            st.markdown(timetable_df.to_html(escape=False, classes='table table-bordered table-striped', justify='center'), unsafe_allow_html=True)
            st.caption("표시형식: 조이름 (예약유형 첫글자 A:자동, S:수동)")

        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")
