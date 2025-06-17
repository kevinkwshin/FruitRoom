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
@st.cache_data(ttl=180) # 캐시 시간 3분
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
st.set_page_config(page_title="조모임 예약", layout="centered", initial_sidebar_state="expanded")

# 페이지 상태 유지를 위한 세션 상태 초기화
if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약" # 기본 페이지 변경

# --- 사이드바 ---
st.sidebar.title("🚀 조모임 스터디룸")

# 페이지 네비게이션
page_options_sidebar = ["🗓️ 예약 시간표 및 수동 예약"] # 관리자 메뉴는 별도 섹션
# 현재 선택된 페이지 (관리자 메뉴를 제외한 일반 메뉴용)
# st.session_state.current_page가 page_options_sidebar에 없으면 기본값 사용
try:
    current_page_index_sidebar = page_options_sidebar.index(st.session_state.current_page)
except ValueError:
    # 현재 페이지가 관리자 메뉴 중 하나일 수 있으므로, 일반 메뉴의 기본값으로 설정
    if st.session_state.current_page not in ["🔄 자동 배정 (관리자)"]:
         st.session_state.current_page = page_options_sidebar[0] # 일반 메뉴 기본값
    current_page_index_sidebar = 0 # st.radio에는 항상 유효한 index 필요


selected_page_main_menu = st.sidebar.radio(
    "메인 메뉴",
    page_options_sidebar,
    index=page_options_sidebar.index(st.session_state.current_page) if st.session_state.current_page in page_options_sidebar else 0,
    key="main_menu_radio"
)
if selected_page_main_menu != st.session_state.current_page : # 메인메뉴에서 선택이 바뀌면 current_page 업데이트
    st.session_state.current_page = selected_page_main_menu


st.sidebar.markdown("---")
st.sidebar.title("👑 관리자")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제")

# 관리자 메뉴 선택 (버튼처럼 동작)
if st.sidebar.button("🔄 자동 배정 (관리자 전용)", key="admin_auto_assign_btn"):
    st.session_state.current_page = "🔄 자동 배정 (관리자)"
    st.rerun() # 페이지 변경을 위해 rerun

st.sidebar.markdown("---")
if st.sidebar.button("🔄 데이터 캐시 새로고침"):
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
    st.header("🗓️ 예약 시간표")
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_page_unified")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd', # 연한 테두리
                    'text-align': 'center',
                    'min-width': '65px',
                    'height': '35px',
                    'font-size': '0.8em', # 글자 크기 약간 줄임
                    'color': '#333' # 기본 글자색
                }).set_table_styles([
                    {'selector': 'th', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '4px')
                    ]},
                    {'selector': 'td', 'props': [('padding', '4px')]},
                    {'selector': '.index_name', 'props': [('font-weight', 'bold')]} # 시간축 이름 굵게
                ])

                def highlight_reserved_cell(val):
                    color = 'background-color: white;' # 기본 배경 흰색
                    font_weight = 'normal'
                    text_color = 'color: #333;' # 기본 글자색
                    if isinstance(val, str) and val != '':
                        if '(A)' in val:
                            color = 'background-color: #d1ecf1;' # 연한 하늘색 (정보색)
                            text_color = 'color: #0c5460;'
                        elif '(S)' in val:
                            color = 'background-color: #d4edda;' # 연한 연두색 (성공색)
                            text_color = 'color: #155724;'
                        font_weight = 'bold'
                    return f'{color} {text_color} font-weight: {font_weight};'

                styled_df = styled_df.apply(lambda x: x.map(highlight_reserved_cell), axis=None)
                return styled_df

            time_slots_unified = []
            current_time_unified = datetime.combine(date.today(), time(11, 0))
            end_of_day_unified = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_unified < end_of_day_unified:
                time_slots_unified.append(current_time_unified.time())
                current_time_unified += timedelta(minutes=30)

            timetable_df_unified = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_unified], columns=ALL_ROOMS)
            timetable_df_unified = timetable_df_unified.fillna('')

            for _, res_unified in day_reservations.iterrows():
                start_res_dt_unified = datetime.combine(date.today(), res_unified["시간_시작"])
                end_res_dt_unified = datetime.combine(date.today(), res_unified["시간_종료"])
                current_slot_dt_unified = start_res_dt_unified
                while current_slot_dt_unified < end_res_dt_unified:
                    slot_str_unified = current_slot_dt_unified.strftime("%H:%M")
                    if slot_str_unified in timetable_df_unified.index and res_unified["방"] in timetable_df_unified.columns:
                        if timetable_df_unified.loc[slot_str_unified, res_unified["방"]] == '':
                             timetable_df_unified.loc[slot_str_unified, res_unified["방"]] = f"{res_unified['조']} ({res_unified['예약유형'][0]})"
                    current_slot_dt_unified += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_unified).to_html(escape=False)) # escape=False 추가
            st.caption("표시형식: 조이름 (A:자동, S:수동)")
        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    st.markdown("---")
    st.header("✍️ 수동 예약 등록 및 취소")
    # (수동 예약 및 취소 로직, 이전 "수동 예약" 탭의 내용과 동일)
    # ... (생략 - 이전 수동 예약 로직을 여기에 통합) ...
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지 자유롭게 시간 설정.
        - 최소 예약 시간은 30분, 예약 단위는 15분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.subheader("📝 새 예약 등록")
    # 수동 예약 날짜는 시간표에서 선택된 날짜를 기본값으로 사용하거나, 별도 선택 가능
    manual_date_unified = st.date_input("예약 날짜", value=timetable_date, min_value=date.today(), key="manual_date_unified_page")

    cols_manual_unified = st.columns(2)
    with cols_manual_unified[0]:
        selected_team_unified = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_unified_page")
        manual_start_time_unified = st.time_input(
            "시작 시간", value=time(MANUAL_RESERVATION_START_HOUR, 0),
            step=timedelta(minutes=15), key="manual_start_time_unified_page"
        )
    with cols_manual_unified[1]:
        selected_room_unified = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_unified_page")
        manual_end_time_unified = st.time_input(
            "종료 시간", value=time(MANUAL_RESERVATION_START_HOUR + 1, 0),
            step=timedelta(minutes=15), key="manual_end_time_unified_page"
        )

    time_valid_unified = True
    if manual_start_time_unified >= manual_end_time_unified:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_unified = False
    elif manual_start_time_unified < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 이후여야 합니다."); time_valid_unified = False
    elif manual_end_time_unified > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"종료 시간은 {MANUAL_RESERVATION_END_HOUR}:00 이전이어야 합니다."); time_valid_unified = False
    min_duration_unified = timedelta(minutes=30)
    if datetime.combine(date.min, manual_end_time_unified) - datetime.combine(date.min, manual_start_time_unified) < min_duration_unified:
        st.error(f"최소 예약 시간은 {min_duration_unified.seconds // 60}분입니다."); time_valid_unified = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_unified_page", type="primary", use_container_width=True, disabled=not time_valid_unified):
        if time_valid_unified:
            current_reservations_unified = load_reservations()
            is_overlap_unified = False
            # 방 중복 체크
            room_res_unified_check = current_reservations_unified[
                (current_reservations_unified["날짜"] == manual_date_unified) &
                (current_reservations_unified["방"] == selected_room_unified)
            ]
            for _, ex_res_unified in room_res_unified_check.iterrows():
                if check_time_overlap(manual_start_time_unified, manual_end_time_unified, ex_res_unified["시간_시작"], ex_res_unified["시간_종료"]):
                    st.error(f"⚠️ {selected_room_unified} 시간 중복: {ex_res_unified['시간_시작'].strftime('%H:%M')}-{ex_res_unified['시간_종료'].strftime('%H:%M')}"); is_overlap_unified=True; break
            if is_overlap_unified: st.stop()
            # 조 중복 체크
            team_res_unified_check = current_reservations_unified[
                (current_reservations_unified["날짜"] == manual_date_unified) &
                (current_reservations_unified["조"] == selected_team_unified)
            ]
            for _, ex_res_unified in team_res_unified_check.iterrows():
                if check_time_overlap(manual_start_time_unified, manual_end_time_unified, ex_res_unified["시간_시작"], ex_res_unified["시간_종료"]):
                    st.error(f"⚠️ {selected_team_unified} 시간 중복: {ex_res_unified['방']} ({ex_res_unified['시간_시작'].strftime('%H:%M')}-{ex_res_unified['시간_종료'].strftime('%H:%M')})"); is_overlap_unified=True; break
            if is_overlap_unified: st.stop()

            new_item_unified = {
                "날짜": manual_date_unified, "시간_시작": manual_start_time_unified, "시간_종료": manual_end_time_unified,
                "조": selected_team_unified, "방": selected_room_unified, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_unified = pd.concat([current_reservations_unified, pd.DataFrame([new_item_unified])], ignore_index=True)
            save_reservations(updated_df_unified)
            st.success(f"🎉 예약 완료: {selected_team_unified} / {selected_room_unified} / {manual_start_time_unified.strftime('%H:%M')}-{manual_end_time_unified.strftime('%H:%M')}")
            st.rerun()

    st.markdown("---")
    st.subheader(f"🚫 나의 수동 예약 취소 ({manual_date_unified.strftime('%Y-%m-%d')})")
    my_manual_res_display_unified = reservations_df[
        (reservations_df["날짜"] == manual_date_unified) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_unified.empty:
        my_manual_res_display_unified = my_manual_res_display_unified.sort_values(by=["시간_시작", "조"])
        for _, row_unified_cancel in my_manual_res_display_unified.iterrows():
            res_id_unified_cancel = row_unified_cancel["예약ID"]
            time_str_unified_cancel = f"{row_unified_cancel['시간_시작'].strftime('%H:%M')} - {row_unified_cancel['시간_종료'].strftime('%H:%M')}"
            item_cols_unified_cancel = st.columns([3,1])
            with item_cols_unified_cancel[0]: st.markdown(f"**{time_str_unified_cancel}** / **{row_unified_cancel['조']}** / `{row_unified_cancel['방']}`")
            with item_cols_unified_cancel[1]:
                if st.button("취소", key=f"cancel_{res_id_unified_cancel}_unified_page", use_container_width=True):
                    current_on_cancel_unified = load_reservations()
                    updated_on_cancel_unified = current_on_cancel_unified[current_on_cancel_unified["예약ID"] != res_id_unified_cancel]
                    save_reservations(updated_on_cancel_unified)
                    st.success(f"🗑️ 예약 취소됨: {row_unified_cancel['조']} / {row_unified_cancel['방']} ({time_str_unified_cancel})")
                    st.rerun()
    else: st.info(f"{manual_date_unified.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


elif st.session_state.current_page == "🔄 자동 배정 (관리자)":
    st.header("🔄 자동 배정 ⚠️ 관리자 전용")
    st.warning("이 기능은 관리자만 사용해주세요. 잘못된 조작은 전체 예약에 영향을 줄 수 있습니다.")
    # (자동 배정 페이지 내용, 이전과 동일하게 구성)
    # ... (생략 - 이전 자동 배정 페이지 로직과 동일) ...
    if test_mode: st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else: st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT_STR}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** (이하 설명 동일)
        """)

    auto_assign_date_admin = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_page")
    weekday_admin = auto_assign_date_admin.weekday()
    can_auto_assign_admin = test_mode or (weekday_admin in [2, 6])

    if not can_auto_assign_admin:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page", type="primary"):
        if can_auto_assign_admin:
            current_reservations_admin = load_reservations()
            existing_auto_admin = current_reservations_admin[
                (current_reservations_admin["날짜"] == auto_assign_date_admin) &
                (current_reservations_admin["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_admin["예약유형"] == "자동")
            ]
            if not existing_auto_admin.empty:
                st.warning(f"이미 {auto_assign_date_admin.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_admin = []
                assigned_info_admin = []
                # 시니어조
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_admin.append({
                        "날짜": auto_assign_date_admin, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션
                next_idx_admin = load_rotation_state()
                num_rotation_teams_admin = len(ROTATION_TEAMS)
                num_rotation_rooms_admin = len(ROTATION_ROOMS)
                available_rooms_admin = min(num_rotation_teams_admin, num_rotation_rooms_admin)

                for i in range(available_rooms_admin):
                    if num_rotation_teams_admin == 0: break
                    team_idx_list_admin = (next_idx_admin + i) % num_rotation_teams_admin
                    team_assign_admin = ROTATION_TEAMS[team_idx_list_admin]
                    room_assign_admin = ROTATION_ROOMS[i]
                    new_auto_list_admin.append({
                        "날짜": auto_assign_date_admin, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign_admin, "방": room_assign_admin, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin.append(f"🔄 **{team_assign_admin}** → **{room_assign_admin}** (로테이션)")

                if new_auto_list_admin:
                    new_df_admin = pd.DataFrame(new_auto_list_admin)
                    updated_df_admin = pd.concat([current_reservations_admin, new_df_admin], ignore_index=True)
                    save_reservations(updated_df_admin)
                    new_next_idx_admin = (next_idx_admin + available_rooms_admin) % num_rotation_teams_admin if num_rotation_teams_admin > 0 else 0
                    save_rotation_state(new_next_idx_admin)
                    st.success(f"🎉 {auto_assign_date_admin.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_admin: st.markdown(f"- {info}")
                    if num_rotation_teams_admin > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin.empty:
        st.dataframe(auto_today_display_admin[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")
