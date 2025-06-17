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
st.set_page_config(page_title="조모임방 예약/조회", layout="centered", initial_sidebar_state="expanded") # 앱 제목 변경

# 페이지 상태 유지를 위한 세션 상태 초기화
if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"

# --- 사이드바 ---
st.sidebar.title("🚀 조모임방 예약/조회") # 사이드바 제목 변경
st.sidebar.markdown("---")

# 기본 페이지로 돌아가는 버튼 (관리자 페이지에 있을 때만 표시)
if st.session_state.current_page == "🔄 자동 배정 (관리자)":
    if st.sidebar.button("🏠 시간표 및 수동 예약으로 돌아가기", key="return_to_main_btn"):
        st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"
        st.rerun()
    st.sidebar.markdown("---")


st.sidebar.subheader("👑 관리자")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제", key="test_mode_checkbox_admin")

if st.sidebar.button("⚙️ 자동 배정 설정 페이지로 이동", key="admin_auto_assign_nav_btn_admin"):
    st.session_state.current_page = "🔄 자동 배정 (관리자)"
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 기타 설정")
if st.sidebar.button("🔄 데이터 캐시 새로고침", key="cache_refresh_btn_admin"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다.")
    st.rerun()

# --- 메인 화면 콘텐츠 ---
if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df = load_reservations()

# 선택된 페이지에 따라 콘텐츠 표시
if st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약":
    st.header("🗓️ 예약 시간표") # 페이지 헤더 변경
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_main_page_v2")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd',
                    'text-align': 'center',
                    'min-width': '70px', # 셀 너비 증가
                    'height': '38px', # 셀 높이 증가
                    'font-size': '0.85em', # 글자 크기 약간 키움
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
                    text_color = 'color: #212529;' # 더 진한 기본 글자색 (Bootstrap 기본)
                    if isinstance(val, str) and val != '':
                        if '(자동)' in val: # 텍스트 변경
                            bg_color = 'background-color: #e0f3ff;' # 약간 더 진한 하늘색
                            text_color = 'color: #004085;' # Bootstrap info text color
                        elif '(수동)' in val: # 텍스트 변경
                            bg_color = 'background-color: #d4edda;'
                            text_color = 'color: #155724;'
                        font_weight = 'bold'
                    return f'{bg_color} {text_color} font-weight: {font_weight};'
                try:
                    styled_df = styled_df.applymap(highlight_reserved_cell)
                except AttributeError:
                    styled_df = styled_df.apply(lambda col: col.map(highlight_reserved_cell))
                return styled_df

            time_slots_main_v2 = []
            current_time_main_v2 = datetime.combine(date.today(), time(11, 0))
            end_of_day_main_v2 = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_main_v2 < end_of_day_main_v2:
                time_slots_main_v2.append(current_time_main_v2.time())
                current_time_main_v2 += timedelta(minutes=30)

            timetable_df_main_v2 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_main_v2], columns=ALL_ROOMS)
            timetable_df_main_v2 = timetable_df_main_v2.fillna('')

            for _, res_main_v2 in day_reservations.iterrows():
                start_res_dt_main_v2 = datetime.combine(date.today(), res_main_v2["시간_시작"])
                end_res_dt_main_v2 = datetime.combine(date.today(), res_main_v2["시간_종료"])
                current_slot_dt_main_v2 = start_res_dt_main_v2
                res_type_str = "(자동)" if res_main_v2['예약유형'] == '자동' else "(수동)" # 표시 텍스트 변경
                while current_slot_dt_main_v2 < end_res_dt_main_v2:
                    slot_str_main_v2 = current_slot_dt_main_v2.strftime("%H:%M")
                    if slot_str_main_v2 in timetable_df_main_v2.index and res_main_v2["방"] in timetable_df_main_v2.columns:
                        if timetable_df_main_v2.loc[slot_str_main_v2, res_main_v2["방"]] == '':
                             timetable_df_main_v2.loc[slot_str_main_v2, res_main_v2["방"]] = f"{res_main_v2['조']} {res_type_str}"
                    current_slot_dt_main_v2 += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_main_v2).to_html(escape=False))
            st.caption("표시형식: 조이름 (예약유형)")
        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    st.markdown("---")
    st.header("✍️ 조모임방 예약/취소") # 제목 변경
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지 자유롭게 시간 설정.
        - 최소 예약 시간은 30분, 예약 단위는 15분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.markdown("##### 📝 새 예약 등록")
    manual_date_main_reserve_v2 = st.date_input("예약 날짜", value=timetable_date, min_value=date.today(), key="manual_date_main_page_reserve_v2")

    cols_main_reserve_v2 = st.columns(2)
    with cols_main_reserve_v2[0]:
        selected_team_main_reserve_v2 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve_v2")
        manual_start_time_main_reserve_v2 = st.time_input(
            "시작 시간", value=time(MANUAL_RESERVATION_START_HOUR, 0),
            step=timedelta(minutes=15), key="manual_start_time_main_page_reserve_v2"
        )
    with cols_main_reserve_v2[1]:
        selected_room_main_reserve_v2 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve_v2")
        manual_end_time_main_reserve_v2 = st.time_input(
            "종료 시간", value=time(MANUAL_RESERVATION_START_HOUR + 1, 0),
            step=timedelta(minutes=15), key="manual_end_time_main_page_reserve_v2"
        )

    time_valid_main_reserve_v2 = True
    if manual_start_time_main_reserve_v2 >= manual_end_time_main_reserve_v2:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v2 = False
    elif manual_start_time_main_reserve_v2 < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 이후여야 합니다."); time_valid_main_reserve_v2 = False
    elif manual_end_time_main_reserve_v2 > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"종료 시간은 {MANUAL_RESERVATION_END_HOUR}:00 이전이어야 합니다."); time_valid_main_reserve_v2 = False
    min_duration_main_reserve_v2 = timedelta(minutes=30)
    if datetime.combine(date.min, manual_end_time_main_reserve_v2) - datetime.combine(date.min, manual_start_time_main_reserve_v2) < min_duration_main_reserve_v2:
        st.error(f"최소 예약 시간은 {min_duration_main_reserve_v2.seconds // 60}분입니다."); time_valid_main_reserve_v2 = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v2", type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v2):
        if time_valid_main_reserve_v2:
            current_reservations_main_reserve_v2 = load_reservations()
            is_overlap_main_reserve_v2 = False
            room_res_check_v2 = current_reservations_main_reserve_v2[
                (current_reservations_main_reserve_v2["날짜"] == manual_date_main_reserve_v2) &
                (current_reservations_main_reserve_v2["방"] == selected_room_main_reserve_v2)
            ]
            for _, ex_res_check_v2 in room_res_check_v2.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v2, manual_end_time_main_reserve_v2, ex_res_check_v2["시간_시작"], ex_res_check_v2["시간_종료"]):
                    st.error(f"⚠️ {selected_room_main_reserve_v2} 시간 중복"); is_overlap_main_reserve_v2=True; break
            if is_overlap_main_reserve_v2: st.stop()
            team_res_check_v2 = current_reservations_main_reserve_v2[
                (current_reservations_main_reserve_v2["날짜"] == manual_date_main_reserve_v2) &
                (current_reservations_main_reserve_v2["조"] == selected_team_main_reserve_v2)
            ]
            for _, ex_res_check_v2 in team_res_check_v2.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v2, manual_end_time_main_reserve_v2, ex_res_check_v2["시간_시작"], ex_res_check_v2["시간_종료"]):
                    st.error(f"⚠️ {selected_team_main_reserve_v2} 시간 중복"); is_overlap_main_reserve_v2=True; break
            if is_overlap_main_reserve_v2: st.stop()

            new_item_main_reserve_v2 = {
                "날짜": manual_date_main_reserve_v2, "시간_시작": manual_start_time_main_reserve_v2, "시간_종료": manual_end_time_main_reserve_v2,
                "조": selected_team_main_reserve_v2, "방": selected_room_main_reserve_v2, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_main_reserve_v2 = pd.concat([current_reservations_main_reserve_v2, pd.DataFrame([new_item_main_reserve_v2])], ignore_index=True)
            save_reservations(updated_df_main_reserve_v2)
            st.success(f"🎉 예약 완료!")
            st.rerun()

    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_display_cancel_v2 = reservations_df[
        (reservations_df["날짜"] == manual_date_main_reserve_v2) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_cancel_v2.empty:
        my_manual_res_display_cancel_v2 = my_manual_res_display_cancel_v2.sort_values(by=["시간_시작", "조"])
        for _, row_main_cancel_v2 in my_manual_res_display_cancel_v2.iterrows():
            res_id_main_cancel_v2 = row_main_cancel_v2["예약ID"]
            time_str_main_cancel_v2 = f"{row_main_cancel_v2['시간_시작'].strftime('%H:%M')} - {row_main_cancel_v2['시간_종료'].strftime('%H:%M')}"
            item_cols_main_cancel_v2 = st.columns([3,1])
            with item_cols_main_cancel_v2[0]: st.markdown(f"**{time_str_main_cancel_v2}** / **{row_main_cancel_v2['조']}** / `{row_main_cancel_v2['방']}`")
            with item_cols_main_cancel_v2[1]:
                if st.button("취소", key=f"cancel_{res_id_main_cancel_v2}_main_page_reserve_v2", use_container_width=True):
                    current_on_cancel_main_reserve_v2 = load_reservations()
                    updated_on_cancel_main_reserve_v2 = current_on_cancel_main_reserve_v2[current_on_cancel_main_reserve_v2["예약ID"] != res_id_main_cancel_v2]
                    save_reservations(updated_on_cancel_main_reserve_v2)
                    st.success(f"🗑️ 예약 취소됨")
                    st.rerun()
    else:
        st.info(f"{manual_date_main_reserve_v2.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


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

    auto_assign_date_admin_page_v2 = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_page_final_v2")
    weekday_admin_page_v2 = auto_assign_date_admin_page_v2.weekday()
    can_auto_assign_admin_page_v2 = test_mode or (weekday_admin_page_v2 in [2, 6])

    if not can_auto_assign_admin_page_v2:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page_final_v2", type="primary"):
        if can_auto_assign_admin_page_v2:
            current_reservations_admin_page_v2 = load_reservations()
            existing_auto_admin_page_v2 = current_reservations_admin_page_v2[
                (current_reservations_admin_page_v2["날짜"] == auto_assign_date_admin_page_v2) &
                (current_reservations_admin_page_v2["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_admin_page_v2["예약유형"] == "자동")
            ]
            if not existing_auto_admin_page_v2.empty:
                st.warning(f"이미 {auto_assign_date_admin_page_v2.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_admin_page_v2 = []
                assigned_info_admin_page_v2 = []
                # 시니어조
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_admin_page_v2.append({
                        "날짜": auto_assign_date_admin_page_v2, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page_v2.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션
                next_idx_admin_page_v2 = load_rotation_state()
                num_rotation_teams_admin_page_v2 = len(ROTATION_TEAMS)
                num_rotation_rooms_admin_page_v2 = len(ROTATION_ROOMS)
                available_rooms_admin_page_v2 = min(num_rotation_teams_admin_page_v2, num_rotation_rooms_admin_page_v2)

                for i in range(available_rooms_admin_page_v2):
                    if num_rotation_teams_admin_page_v2 == 0: break
                    team_idx_list_admin_page_v2 = (next_idx_admin_page_v2 + i) % num_rotation_teams_admin_page_v2
                    team_assign_admin_page_v2 = ROTATION_TEAMS[team_idx_list_admin_page_v2]
                    room_assign_admin_page_v2 = ROTATION_ROOMS[i]
                    new_auto_list_admin_page_v2.append({
                        "날짜": auto_assign_date_admin_page_v2, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign_admin_page_v2, "방": room_assign_admin_page_v2, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page_v2.append(f"🔄 **{team_assign_admin_page_v2}** → **{room_assign_admin_page_v2}** (로테이션)")

                if new_auto_list_admin_page_v2:
                    new_df_admin_page_v2 = pd.DataFrame(new_auto_list_admin_page_v2)
                    updated_df_admin_page_v2 = pd.concat([current_reservations_admin_page_v2, new_df_admin_page_v2], ignore_index=True)
                    save_reservations(updated_df_admin_page_v2)
                    new_next_idx_admin_page_v2 = (next_idx_admin_page_v2 + available_rooms_admin_page_v2) % num_rotation_teams_admin_page_v2 if num_rotation_teams_admin_page_v2 > 0 else 0
                    save_rotation_state(new_next_idx_admin_page_v2)
                    st.success(f"🎉 {auto_assign_date_admin_page_v2.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_admin_page_v2: st.markdown(f"- {info}")
                    if num_rotation_teams_admin_page_v2 > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin_page_v2]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin_page_v2 = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_page_v2) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_page_v2.empty:
        st.dataframe(auto_today_display_admin_page_v2[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin_page_v2.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")
