import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import gspread
from google.oauth2.service_account import Credentials
import uuid
import json

# --- 초기 설정 (이전과 동일) ---
AUTO_ASSIGN_EXCLUDE_TEAMS = ["대면A", "대면B", "대면C"]
SENIOR_TEAM = "시니어"
SENIOR_ROOM = "9F-1"
ALL_TEAMS = [f"{i}조" for i in range(1, 13)] + ["대면A", "대면B", "대면C", "대면D", "청년", "중고등", SENIOR_TEAM]
ROTATION_TEAMS = [team for team in ALL_TEAMS if team not in AUTO_ASSIGN_EXCLUDE_TEAMS and team != SENIOR_TEAM]
ALL_ROOMS = [f"9F-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
ROTATION_ROOMS = [room for room in ALL_ROOMS if room != SENIOR_ROOM]
AUTO_ASSIGN_TIME_SLOT_STR = "11:30 - 13:00"
AUTO_ASSIGN_START_TIME = time(11, 30)
AUTO_ASSIGN_END_TIME = time(13, 0)
MANUAL_RESERVATION_START_HOUR = 13
MANUAL_RESERVATION_END_HOUR = 17
RESERVATION_SHEET_HEADERS = ["날짜", "시간_시작", "시간_종료", "조", "방", "예약유형", "예약ID"]
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


# --- 데이터 로드 및 저장 함수 (이전 캐싱 로직과 동일) ---
@st.cache_data(ttl=180)
def get_all_records_as_df_cached(_ws, expected_headers, _cache_key_prefix):
    if not GSHEET_AVAILABLE or _ws is None: return pd.DataFrame(columns=expected_headers)
    try:
        records = _ws.get_all_records()
        df = pd.DataFrame(records)
        if df.empty or not all(h in df.columns for h in expected_headers):
            return pd.DataFrame(columns=expected_headers)
        if "날짜" in df.columns and _ws.title == "reservations":
            df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
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
        if "시간_시작" in df_to_save.columns:
            df_to_save['시간_시작'] = df_to_save['시간_시작'].apply(lambda t: t.strftime('%H:%M') if isinstance(t, time) else t)
        if "시간_종료" in df_to_save.columns:
            df_to_save['시간_종료'] = df_to_save['시간_종료'].apply(lambda t: t.strftime('%H:%M') if isinstance(t, time) else t)
        df_values = [headers] + df_to_save.astype(str).values.tolist()
        _ws.clear()
        _ws.update(df_values, value_input_option='USER_ENTERED')
        if _ws.title == "reservations": get_all_records_as_df_cached.clear()
        elif _ws.title == "rotation_state": load_rotation_state_cached.clear()
    except Exception as e:
        st.error(f"'{_ws.title}' 시트 업데이트 중 오류: {e}")

def load_reservations():
    return get_all_records_as_df_cached(reservations_ws, RESERVATION_SHEET_HEADERS, "reservations_cache")

@st.cache_data(ttl=180)
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

def check_time_overlap(new_start, new_end, existing_start, existing_end):
    return max(new_start, existing_start) < min(new_end, existing_end)

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임방 예약/조회", layout="centered", initial_sidebar_state="expanded")

if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"

# --- 사이드바 ---
st.sidebar.title("🚀 조모임방 예약/조회")
st.sidebar.markdown("---")

if st.session_state.current_page == "🔄 자동 배정 (관리자)":
    if st.sidebar.button("🏠 시간표 및 수동 예약으로 돌아가기", key="return_to_main_btn_v3"):
        st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"
        st.rerun()
    st.sidebar.markdown("---")

st.sidebar.subheader("👑 관리자")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제", key="test_mode_checkbox_admin_v3")

if st.sidebar.button("⚙️ 자동 배정 설정 페이지로 이동", key="admin_auto_assign_nav_btn_admin_v3"):
    st.session_state.current_page = "🔄 자동 배정 (관리자)"
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 기타 설정")
if st.sidebar.button("🔄 데이터 캐시 새로고침", key="cache_refresh_btn_admin_v3"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다.")
    st.rerun()

if st.session_state.current_page not in ["🔄 자동 배정 (관리자)"]:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"

# --- 메인 화면 콘텐츠 ---
if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df = load_reservations()

if st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약":
    st.header("🗓️ 예약 시간표")
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_main_page_v3")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                # (스타일링 함수 이전과 동일)
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd', 'text-align': 'center',
                    'min-width': '70px', 'height': '38px', 'font-size': '0.85em',
                }).set_table_styles([
                    {'selector': 'th', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '5px'), ('color', '#333')
                    ]},
                    {'selector': 'th.row_heading', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '5px'), ('color', '#333')
                    ]},
                    {'selector': 'td', 'props': [('padding', '5px')]}
                ])
                def highlight_reserved_cell(val):
                    bg_color = 'background-color: white;'
                    font_weight = 'normal'
                    text_color = 'color: #212529;'
                    if isinstance(val, str) and val != '':
                        if '(자동)' in val:
                            bg_color = 'background-color: #e0f3ff;'
                            text_color = 'color: #004085;'
                        elif '(수동)' in val:
                            bg_color = 'background-color: #d4edda;'
                            text_color = 'color: #155724;'
                        font_weight = 'bold'
                    return f'{bg_color} {text_color} font-weight: {font_weight};'
                try: styled_df = styled_df.applymap(highlight_reserved_cell)
                except AttributeError: styled_df = styled_df.apply(lambda col: col.map(highlight_reserved_cell))
                return styled_df

            time_slots_main_v3 = []
            current_time_main_v3 = datetime.combine(date.today(), time(11, 0))
            end_of_day_main_v3 = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_main_v3 < end_of_day_main_v3:
                time_slots_main_v3.append(current_time_main_v3.time())
                current_time_main_v3 += timedelta(minutes=30)

            timetable_df_main_v3 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_main_v3], columns=ALL_ROOMS)
            timetable_df_main_v3 = timetable_df_main_v3.fillna('')

            for _, res_main_v3 in day_reservations.iterrows():
                start_res_dt_main_v3 = datetime.combine(date.today(), res_main_v3["시간_시작"])
                end_res_dt_main_v3 = datetime.combine(date.today(), res_main_v3["시간_종료"])
                current_slot_dt_main_v3 = start_res_dt_main_v3
                res_type_str_v3 = "(자동)" if res_main_v3['예약유형'] == '자동' else "(수동)"
                while current_slot_dt_main_v3 < end_res_dt_main_v3:
                    slot_str_main_v3 = current_slot_dt_main_v3.strftime("%H:%M")
                    if slot_str_main_v3 in timetable_df_main_v3.index and res_main_v3["방"] in timetable_df_main_v3.columns:
                        if timetable_df_main_v3.loc[slot_str_main_v3, res_main_v3["방"]] == '':
                             timetable_df_main_v3.loc[slot_str_main_v3, res_main_v3["방"]] = f"{res_main_v3['조']} {res_type_str_v3}"
                    current_slot_dt_main_v3 += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_main_v3).to_html(escape=False))
            st.caption("표시형식: 조이름 (예약유형)")
        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    st.markdown("---")
    st.header("✍️ 조모임방 예약/취소")
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지.
        - 최소 예약 시간은 30분, 예약 단위는 15분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.markdown("##### 📝 새 예약 등록")
    # "예약 날짜"의 value를 timetable_date와 date.today() 중 더 나중 날짜로 설정
    manual_date_default = max(timetable_date, date.today())
    manual_date_main_reserve_v3 = st.date_input(
        "예약 날짜",
        value=manual_date_default, # 수정된 기본값
        min_value=date.today(), # 최소값은 오늘
        key="manual_date_main_page_reserve_v3"
    )

    cols_main_reserve_v3 = st.columns(2)
    with cols_main_reserve_v3[0]:
        selected_team_main_reserve_v3 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve_v3")
        manual_start_time_main_reserve_v3 = st.time_input(
            "시작 시간",
            value=time(MANUAL_RESERVATION_START_HOUR, 0),
            min_value=time(MANUAL_RESERVATION_START_HOUR, 0), # 시작 시간 최소값
            max_value=time(MANUAL_RESERVATION_END_HOUR -1, 45), # 종료 시간 고려 (최소 15분 전)
            step=timedelta(minutes=15),
            key="manual_start_time_main_page_reserve_v3"
        )
    with cols_main_reserve_v3[1]:
        selected_room_main_reserve_v3 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve_v3")
        # 종료 시간 기본값: 시작 시간 + 3시간, 단 17:00를 넘지 않도록
        default_end_hour = manual_start_time_main_reserve_v3.hour + 3
        default_end_minute = manual_start_time_main_reserve_v3.minute
        if default_end_hour >= MANUAL_RESERVATION_END_HOUR:
            default_end_time_val = time(MANUAL_RESERVATION_END_HOUR, 0)
        else:
            default_end_time_val = time(default_end_hour, default_end_minute)

        manual_end_time_main_reserve_v3 = st.time_input(
            "종료 시간",
            value=default_end_time_val, # 기본값 수정
            min_value= (datetime.combine(date.today(), manual_start_time_main_reserve_v3) + timedelta(minutes=30)).time(), # 시작 시간 + 30분 부터
            max_value=time(MANUAL_RESERVATION_END_HOUR, 0), # 최대 17:00
            step=timedelta(minutes=15),
            key="manual_end_time_main_page_reserve_v3"
        )

    time_valid_main_reserve_v3 = True
    if manual_start_time_main_reserve_v3 >= manual_end_time_main_reserve_v3:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v3 = False
    # 시작 시간 범위는 time_input의 min_value/max_value로 어느정도 제어됨
    # elif manual_start_time_main_reserve_v3 < time(MANUAL_RESERVATION_START_HOUR, 0):
    #     st.error(f"시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 이후여야 합니다."); time_valid_main_reserve_v3 = False
    # elif manual_end_time_main_reserve_v3 > time(MANUAL_RESERVATION_END_HOUR, 0): # max_value로 제어
    #     st.error(f"종료 시간은 {MANUAL_RESERVATION_END_HOUR}:00 이전이어야 합니다."); time_valid_main_reserve_v3 = False

    min_duration_main_reserve_v3 = timedelta(minutes=30)
    current_duration = datetime.combine(date.min, manual_end_time_main_reserve_v3) - datetime.combine(date.min, manual_start_time_main_reserve_v3)
    if current_duration < min_duration_main_reserve_v3:
        st.error(f"최소 예약 시간은 {min_duration_main_reserve_v3.seconds // 60}분입니다."); time_valid_main_reserve_v3 = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v3", type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v3):
        # (예약 로직 이전과 동일)
        if time_valid_main_reserve_v3: # 버튼이 활성화 되었더라도 한번 더 체크
            current_reservations_main_reserve_v3 = load_reservations()
            is_overlap_main_reserve_v3 = False
            room_res_check_v3 = current_reservations_main_reserve_v3[
                (current_reservations_main_reserve_v3["날짜"] == manual_date_main_reserve_v3) &
                (current_reservations_main_reserve_v3["방"] == selected_room_main_reserve_v3)
            ]
            for _, ex_res_check_v3 in room_res_check_v3.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v3, manual_end_time_main_reserve_v3, ex_res_check_v3["시간_시작"], ex_res_check_v3["시간_종료"]):
                    st.error(f"⚠️ {selected_room_main_reserve_v3}은(는) 해당 시간에 일부 또는 전체가 이미 예약되어 있습니다."); is_overlap_main_reserve_v3=True; break
            if is_overlap_main_reserve_v3: st.stop()

            team_res_check_v3 = current_reservations_main_reserve_v3[
                (current_reservations_main_reserve_v3["날짜"] == manual_date_main_reserve_v3) &
                (current_reservations_main_reserve_v3["조"] == selected_team_main_reserve_v3)
            ]
            for _, ex_res_check_v3 in team_res_check_v3.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v3, manual_end_time_main_reserve_v3, ex_res_check_v3["시간_시작"], ex_res_check_v3["시간_종료"]):
                    st.error(f"⚠️ {selected_team_main_reserve_v3}은(는) 해당 시간에 이미 다른 방을 예약했습니다."); is_overlap_main_reserve_v3=True; break
            if is_overlap_main_reserve_v3: st.stop()


            new_item_main_reserve_v3 = {
                "날짜": manual_date_main_reserve_v3, "시간_시작": manual_start_time_main_reserve_v3, "시간_종료": manual_end_time_main_reserve_v3,
                "조": selected_team_main_reserve_v3, "방": selected_room_main_reserve_v3, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_main_reserve_v3 = pd.concat([current_reservations_main_reserve_v3, pd.DataFrame([new_item_main_reserve_v3])], ignore_index=True)
            save_reservations(updated_df_main_reserve_v3)
            st.success(f"🎉 예약 완료!")
            st.rerun()


    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_display_cancel_v3 = reservations_df[
        (reservations_df["날짜"] == manual_date_main_reserve_v3) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_cancel_v3.empty:
        my_manual_res_display_cancel_v3 = my_manual_res_display_cancel_v3.sort_values(by=["시간_시작", "조"])
        for _, row_main_cancel_v3 in my_manual_res_display_cancel_v3.iterrows():
            res_id_main_cancel_v3 = row_main_cancel_v3["예약ID"]
            time_str_main_cancel_v3 = f"{row_main_cancel_v3['시간_시작'].strftime('%H:%M')} - {row_main_cancel_v3['시간_종료'].strftime('%H:%M')}"
            item_cols_main_cancel_v3 = st.columns([3,1])
            with item_cols_main_cancel_v3[0]: st.markdown(f"**{time_str_main_cancel_v3}** / **{row_main_cancel_v3['조']}** / `{row_main_cancel_v3['방']}`")
            with item_cols_main_cancel_v3[1]:
                if st.button("취소", key=f"cancel_{res_id_main_cancel_v3}_main_page_reserve_v3", use_container_width=True):
                    current_on_cancel_main_reserve_v3 = load_reservations()
                    updated_on_cancel_main_reserve_v3 = current_on_cancel_main_reserve_v3[current_on_cancel_main_reserve_v3["예약ID"] != res_id_main_cancel_v3]
                    save_reservations(updated_on_cancel_main_reserve_v3)
                    st.success(f"🗑️ 예약 취소됨")
                    st.rerun()
    else:
        st.info(f"{manual_date_main_reserve_v3.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


elif st.session_state.current_page == "🔄 자동 배정 (관리자)":
    st.header("🔄 자동 배정 ⚠️ 관리자 전용")
    st.warning("이 기능은 관리자만 사용해주세요. 잘못된 조작은 전체 예약에 영향을 줄 수 있습니다.")
    # (자동 배정 페이지 내용, 이전과 동일)
    # ... (생략) ...
    if test_mode: st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else: st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT_STR}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** (이하 설명 동일)
        """)

    auto_assign_date_admin_page_v3 = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_page_final_v3")
    weekday_admin_page_v3 = auto_assign_date_admin_page_v3.weekday()
    can_auto_assign_admin_page_v3 = test_mode or (weekday_admin_page_v3 in [2, 6])

    if not can_auto_assign_admin_page_v3:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page_final_v3", type="primary"):
        if can_auto_assign_admin_page_v3:
            current_reservations_admin_page_v3 = load_reservations()
            existing_auto_admin_page_v3 = current_reservations_admin_page_v3[
                (current_reservations_admin_page_v3["날짜"] == auto_assign_date_admin_page_v3) &
                (current_reservations_admin_page_v3["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_admin_page_v3["예약유형"] == "자동")
            ]
            if not existing_auto_admin_page_v3.empty:
                st.warning(f"이미 {auto_assign_date_admin_page_v3.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_admin_page_v3 = []
                assigned_info_admin_page_v3 = []
                # 시니어조
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_admin_page_v3.append({
                        "날짜": auto_assign_date_admin_page_v3, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page_v3.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션
                next_idx_admin_page_v3 = load_rotation_state()
                num_rotation_teams_admin_page_v3 = len(ROTATION_TEAMS)
                num_rotation_rooms_admin_page_v3 = len(ROTATION_ROOMS)
                available_rooms_admin_page_v3 = min(num_rotation_teams_admin_page_v3, num_rotation_rooms_admin_page_v3)

                for i in range(available_rooms_admin_page_v3):
                    if num_rotation_teams_admin_page_v3 == 0: break
                    team_idx_list_admin_page_v3 = (next_idx_admin_page_v3 + i) % num_rotation_teams_admin_page_v3
                    team_assign_admin_page_v3 = ROTATION_TEAMS[team_idx_list_admin_page_v3]
                    room_assign_admin_page_v3 = ROTATION_ROOMS[i]
                    new_auto_list_admin_page_v3.append({
                        "날짜": auto_assign_date_admin_page_v3, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign_admin_page_v3, "방": room_assign_admin_page_v3, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page_v3.append(f"🔄 **{team_assign_admin_page_v3}** → **{room_assign_admin_page_v3}** (로테이션)")

                if new_auto_list_admin_page_v3:
                    new_df_admin_page_v3 = pd.DataFrame(new_auto_list_admin_page_v3)
                    updated_df_admin_page_v3 = pd.concat([current_reservations_admin_page_v3, new_df_admin_page_v3], ignore_index=True)
                    save_reservations(updated_df_admin_page_v3)
                    new_next_idx_admin_page_v3 = (next_idx_admin_page_v3 + available_rooms_admin_page_v3) % num_rotation_teams_admin_page_v3 if num_rotation_teams_admin_page_v3 > 0 else 0
                    save_rotation_state(new_next_idx_admin_page_v3)
                    st.success(f"🎉 {auto_assign_date_admin_page_v3.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_admin_page_v3: st.markdown(f"- {info}")
                    if num_rotation_teams_admin_page_v3 > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin_page_v3]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin_page_v3 = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_page_v3) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_page_v3.empty:
        st.dataframe(auto_today_display_admin_page_v3[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin_page_v3.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")
