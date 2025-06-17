네, 좋은 제안입니다! UI 개선을 위해 요청하신 두 가지 사항을 반영하겠습니다.

변경 사항:

"예약 날짜" 통합:
수동 예약 섹션의 "예약 날짜" st.date_input을 제거합니다.
대신, 페이지 상단의 "시간표 조회 날짜" (timetable_date)를 수동 예약 및 예약 취소의 기준 날짜로 사용합니다.
이렇게 하면 사용자는 하나의 날짜 선택기로 시간표 조회와 수동 예약/취소를 모두 관리할 수 있습니다.
"방 선택" 위치 변경:
수동 예약 섹션에서 "조 선택" 바로 다음에 "방 선택" st.selectbox를 위치시키고, 그 아래에 "시작 시간"과 "종료 시간" st.time_input이 나란히 오도록 레이아웃을 조정합니다.
수정된 코드:

아래는 위 변경 사항을 적용한 전체 코드입니다. st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약": 블록 내부의 UI 구성과 로직이 주로 변경됩니다.

Generated python
import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
import uuid
import json

# --- 초기 설정 ---
AUTO_ASSIGN_EXCLUDE_TEAMS = ["대면A", "대면B", "대면C"]
SENIOR_TEAM = "시니어조"
SENIOR_ROOM = "9F-1"
ALL_TEAMS = [f"{i}조" for i in range(1, 14)] + ["대면A", "대면B", "대면C","대면D", "청년", "중고등", SENIOR_TEAM]
ROTATION_TEAMS = [team for team in ALL_TEAMS if team not in AUTO_ASSIGN_EXCLUDE_TEAMS and team != SENIOR_TEAM]
ALL_ROOMS = [f"9F-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
ROTATION_ROOMS = [room for room in ALL_ROOMS if room != SENIOR_ROOM]

RESERVATION_SHEET_HEADERS = ["날짜", "시간_시작", "시간_종료", "조", "방", "예약유형", "예약ID"]
ROTATION_SHEET_HEADER = ["next_team_index"]
TIME_STEP_MINUTES = 60

DEFAULT_AUTO_ASSIGN_START_TIME = time(11, 0)
DEFAULT_AUTO_ASSIGN_END_TIME = time(13, 0)

DEFAULT_MANUAL_RESERVATION_START_HOUR = 13
DEFAULT_MANUAL_RESERVATION_END_HOUR = 17

WEDNESDAY_AUTO_ASSIGN_START_TIME = time(21, 0)
WEDNESDAY_AUTO_ASSIGN_END_TIME = time(23, 59)

WEDNESDAY_MANUAL_RESERVATION_START_HOUR = 16
WEDNESDAY_MANUAL_RESERVATION_END_HOUR = 19

KST = timezone(timedelta(hours=9))

def get_today_kst():
    return datetime.now(KST).date()

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
    dummy_date = date.min
    new_start_dt = datetime.combine(dummy_date, new_start)
    new_end_dt = datetime.combine(dummy_date, new_end)
    existing_start_dt = datetime.combine(dummy_date, existing_start)
    existing_end_dt = datetime.combine(dummy_date, existing_end)
    return max(new_start_dt, existing_start_dt) < min(new_end_dt, existing_end_dt)

st.set_page_config(page_title="조모임방 예약/조회", layout="centered", initial_sidebar_state="expanded")

if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"

st.sidebar.title("🚀 조모임방 예약/조회")
st.sidebar.markdown("---")

if st.session_state.current_page == "🔄 자동 배정 (관리자)":
    if st.sidebar.button("🏠 시간표 및 수동 예약으로 돌아가기", key="return_to_main_from_admin_v8"):
        st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"
        st.rerun()
elif st.session_state.current_page == "📖 관리자 매뉴얼":
    if st.sidebar.button("🏠 시간표 및 수동 예약으로 돌아가기", key="return_to_main_from_manual_v8"):
        st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"
        st.rerun()
    if st.sidebar.button("⚙️ 자동 배정 설정 페이지로 이동", key="go_to_auto_assign_from_manual_v8"):
        st.session_state.current_page = "🔄 자동 배정 (관리자)"
        st.rerun()
else:
    st.sidebar.subheader("👑 관리자")
    if st.sidebar.button("⚙️ 자동 배정 설정 페이지로 이동", key="admin_auto_assign_nav_btn_main_v8"):
        st.session_state.current_page = "🔄 자동 배정 (관리자)"
        st.rerun()
    if st.sidebar.button("📖 관리자 매뉴얼 보기", key="admin_manual_nav_btn_main_v8"):
        st.session_state.current_page = "📖 관리자 매뉴얼"
        st.rerun()
    test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제", key="test_mode_checkbox_admin_v8")

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 기타 설정")
if st.sidebar.button("🔄 데이터 캐시 새로고침", key="cache_refresh_btn_admin_v8"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다.")
    st.rerun()

if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df = load_reservations()
today_kst = get_today_kst()

if st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약":
    st.header("🗓️ 예약 시간표 및 수동 예약/취소") # 헤더 변경
    # "시간표 조회 날짜"가 이제 수동 예약 및 취소의 기준 날짜도 겸함
    # min_value를 today_kst로 설정하여 과거 날짜의 수동 예약/취소는 불가능하게 함
    # 시간표 자체는 과거 날짜도 조회 가능해야 하므로, 수동 예약/취소 시 날짜 유효성 검사 추가 필요
    timetable_date = st.date_input(
        "날짜 선택 (시간표 조회, 수동 예약/취소 기준)", 
        value=today_kst, 
        # min_value=today_kst, # 시간표는 과거도 볼 수 있어야 하므로 min_value 제거. 수동 예약 시 날짜 체크.
        key="unified_date_selector_v8"
    )

    selected_weekday = timetable_date.weekday()
    is_wednesday_selected = (selected_weekday == 2)

    # 시간표 표시 범위 설정
    timetable_display_start_hour = DEFAULT_AUTO_ASSIGN_START_TIME.hour
    timetable_display_end_hour = DEFAULT_MANUAL_RESERVATION_END_HOUR
    if is_wednesday_selected:
        timetable_display_start_hour = min(DEFAULT_AUTO_ASSIGN_START_TIME.hour, WEDNESDAY_AUTO_ASSIGN_START_TIME.hour)
        timetable_display_end_hour = WEDNESDAY_AUTO_ASSIGN_END_TIME.hour + 1

    # 시간표 표시 로직 (이전과 동일)
    def style_timetable(df_in):
        styled_df = df_in.style.set_properties(**{
            'border': '1px solid #ddd', 'text-align': 'center', 'vertical-align': 'middle',
            'min-width': '85px', 'height': '60px', 'font-size': '0.9em',
            'line-height': '1.5'
        }).set_table_styles([
            {'selector': 'th', 'props': [
                ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                ('font-weight', 'bold'), ('padding', '8px'), ('color', '#333'),
                ('vertical-align', 'middle')
            ]},
            {'selector': 'th.row_heading', 'props': [
                ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                ('font-weight', 'bold'), ('padding', '8px'), ('color', '#333'),
                ('vertical-align', 'middle')
            ]},
            {'selector': 'td', 'props': [('padding', '8px'), ('vertical-align', 'top')]}
        ])
        def highlight_reserved_cell(val_html):
            bg_color = 'background-color: white;'
            if isinstance(val_html, str) and val_html != '':
                if '(자동)' in val_html: bg_color = 'background-color: #e0f3ff;'
                elif '(수동)' in val_html: bg_color = 'background-color: #d4edda;'
            return f'{bg_color};' 
        try:
            styled_df = styled_df.set_table_attributes('style="border-collapse: collapse;"').map(highlight_reserved_cell)
        except AttributeError:
            st.warning("Pandas Styler.map()을 사용할 수 없습니다. 이전 방식(applymap)을 사용합니다.")
            styled_df = styled_df.applymap(highlight_reserved_cell)
        return styled_df

    time_slots_v8 = []
    hour_iter = timetable_display_start_hour
    end_hour_for_loop = timetable_display_end_hour
    if timetable_display_end_hour == 24: end_hour_for_loop = 24
    
    current_hour = timetable_display_start_hour
    while current_hour < end_hour_for_loop : # 23시 슬롯까지 생성
        time_slots_v8.append(time(current_hour,0))
        current_hour +=1
        
    timetable_df_v8 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_v8], columns=ALL_ROOMS).fillna('')

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            for _, res_v8 in day_reservations.iterrows():
                res_start_time = res_v8["시간_시작"]
                res_end_time = res_v8["시간_종료"]
                res_type_str_v8 = "(자동)" if res_v8['예약유형'] == '자동' else "(수동)"
                team_name_color = "#333333" 
                cell_content_v8 = f"<b style='color: {team_name_color};'>{res_v8['조']}</b><br><small style='color: #555;'>{res_type_str_v8}</small>"
                for slot_start_time_obj in time_slots_v8:
                    slot_start_dt = datetime.combine(date.min, slot_start_time_obj)
                    slot_end_dt = slot_start_dt + timedelta(hours=1)
                    res_start_dt_combined = datetime.combine(date.min, res_start_time)
                    if res_end_time == time(0,0) and res_start_time > time(12,0):
                         res_end_dt_combined = datetime.combine(date.min + timedelta(days=1), time(0,0))
                    elif res_end_time == time(23,59) and is_wednesday_selected:
                         res_end_dt_combined = datetime.combine(date.min, time(23,59,59))
                    else:
                         res_end_dt_combined = datetime.combine(date.min, res_end_time)
                    if res_start_dt_combined < slot_end_dt and res_end_dt_combined > slot_start_dt:
                        slot_str_v8 = slot_start_time_obj.strftime("%H:%M")
                        if slot_str_v8 in timetable_df_v8.index and res_v8["방"] in timetable_df_v8.columns:
                            timetable_df_v8.loc[slot_str_v8, res_v8["방"]] = cell_content_v8
    
    st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황 (1시간 단위)**")
    if not timetable_df_v8.empty:
        st.html(style_timetable(timetable_df_v8).to_html(escape=False))
    else:
        st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 표시할 시간 슬롯이 없거나 예약이 없습니다.")
    
    # --- 수동 예약/취소 섹션 ---
    st.markdown("---")
    # st.header("✍️ 수동 예약/취소") # 헤더는 위에서 통합됨

    # 수동 예약은 오늘 또는 미래 날짜에만 가능하도록 체크
    can_manual_reserve_today = timetable_date >= today_kst

    current_manual_start_hour = WEDNESDAY_MANUAL_RESERVATION_START_HOUR if is_wednesday_selected else DEFAULT_MANUAL_RESERVATION_START_HOUR
    current_manual_end_hour = WEDNESDAY_MANUAL_RESERVATION_END_HOUR if is_wednesday_selected else DEFAULT_MANUAL_RESERVATION_END_HOUR

    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **선택된 날짜 ({timetable_date.strftime('%Y-%m-%d')}, {'수요일' if is_wednesday_selected else '수요일 아님'})**
        - **예약 가능 시간:** 매일 `{current_manual_start_hour}:00` 부터 `{current_manual_end_hour}:00` 까지.
        - 최소 예약 시간은 1시간, 예약 단위는 1시간입니다.
        - 중복 예약은 불가능합니다.
        - 수동 예약 및 취소는 선택된 날짜가 오늘 또는 미래인 경우에만 가능합니다.
        """)

    if not can_manual_reserve_today:
        st.warning(f"{timetable_date.strftime('%Y-%m-%d')}은(는) 과거 날짜이므로 수동 예약/취소가 불가능합니다.")
    else:
        st.markdown("##### 📝 새 예약 등록")
        
        # UI 변경: 조 선택과 방 선택을 먼저
        key_suffix_manual = "_wed" if is_wednesday_selected else "_other"
        
        selected_team_main_reserve_v8 = st.selectbox(
            "조 선택", ALL_TEAMS, 
            key="manual_team_sel_main_page_reserve_v8" + key_suffix_manual
        )
        selected_room_main_reserve_v8 = st.selectbox(
            "방 선택", ALL_ROOMS, 
            key="manual_room_sel_main_page_reserve_v8" + key_suffix_manual
        )

        cols_time_reserve_v8 = st.columns(2) # 시간 선택을 위한 컬럼
        _today_for_time_calc_v8 = today_kst # 시간 객체 생성 시 기준 날짜

        with cols_time_reserve_v8[0]:
            start_time_default_val_v8 = time(current_manual_start_hour, 0)
            max_possible_start_time_dt_v8 = datetime.combine(_today_for_time_calc_v8, time(current_manual_end_hour, 0)) - timedelta(hours=1)
            max_possible_start_time_val_v8 = max_possible_start_time_dt_v8.time()

            if start_time_default_val_v8 > max_possible_start_time_val_v8 :
                 start_time_default_val_v8 = max_possible_start_time_val_v8
            if start_time_default_val_v8 < time(current_manual_start_hour,0):
                 start_time_default_val_v8 = time(current_manual_start_hour,0)

            manual_start_time_main_reserve_v8 = st.time_input(
                "시작 시간",
                value=start_time_default_val_v8,
                step=timedelta(hours=1),
                key="manual_start_time_main_page_reserve_v8" + key_suffix_manual
            )

        with cols_time_reserve_v8[1]:
            end_time_default_val_v8 = time(current_manual_end_hour, 0)
            min_possible_end_time_dt_v8 = datetime.combine(_today_for_time_calc_v8, manual_start_time_main_reserve_v8) + timedelta(hours=1)
            min_possible_end_time_val_v8 = min_possible_end_time_dt_v8.time()
            max_possible_end_time_val_v8 = time(current_manual_end_hour, 0)

            if end_time_default_val_v8 < min_possible_end_time_val_v8:
                end_time_default_val_v8 = min_possible_end_time_val_v8
            if end_time_default_val_v8 > max_possible_end_time_val_v8:
                end_time_default_val_v8 = max_possible_end_time_val_v8
                
            manual_end_time_main_reserve_v8 = st.time_input(
                "종료 시간",
                value=end_time_default_val_v8,
                step=timedelta(hours=1),
                key="manual_end_time_main_page_reserve_v8" + key_suffix_manual
            )

        time_valid_main_reserve_v8 = True
        # 유효성 검사 로직 (이전과 동일, current_manual_start_hour/end_hour 사용)
        if manual_start_time_main_reserve_v8 < time(current_manual_start_hour, 0):
            st.error(f"시작 시간은 {time(current_manual_start_hour, 0).strftime('%H:%M')} 이후여야 합니다."); time_valid_main_reserve_v8 = False
        if manual_start_time_main_reserve_v8 >= time(current_manual_end_hour, 0):
             st.error(f"시작 시간은 {time(current_manual_end_hour-1, 0).strftime('%H:%M')} 이전이어야 합니다."); time_valid_main_reserve_v8 = False
        elif manual_start_time_main_reserve_v8 > max_possible_start_time_val_v8: # max_possible_start_time_val_v8는 이미 계산됨
            st.error(f"시작 시간은 {max_possible_start_time_val_v8.strftime('%H:%M')} 이전이어야 합니다 (최소 1시간 예약 필요)."); time_valid_main_reserve_v8 = False
        if manual_start_time_main_reserve_v8 >= manual_end_time_main_reserve_v8:
            st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v8 = False
        if manual_end_time_main_reserve_v8 > time(current_manual_end_hour, 0):
            st.error(f"종료 시간은 {time(current_manual_end_hour, 0).strftime('%H:%M')} 이전이어야 합니다."); time_valid_main_reserve_v8 = False
        min_duration_main_reserve_v8 = timedelta(hours=1)
        current_duration_v8 = datetime.combine(date.min, manual_end_time_main_reserve_v8) - datetime.combine(date.min, manual_start_time_main_reserve_v8)
        if current_duration_v8 < min_duration_main_reserve_v8 and time_valid_main_reserve_v8 :
            st.error(f"최소 예약 시간은 {min_duration_main_reserve_v8.seconds // 3600}시간입니다."); time_valid_main_reserve_v8 = False

        if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v8"  + key_suffix_manual, type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v8):
            # 예약 날짜는 timetable_date 사용
            current_reservations_main_reserve_v8 = load_reservations()
            is_overlap_main_reserve_v8 = False
            room_res_check_v8 = current_reservations_main_reserve_v8[
                (current_reservations_main_reserve_v8["날짜"] == timetable_date) & # 수정: timetable_date 사용
                (current_reservations_main_reserve_v8["방"] == selected_room_main_reserve_v8)
            ]
            for _, ex_res_check_v8 in room_res_check_v8.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v8, manual_end_time_main_reserve_v8, ex_res_check_v8["시간_시작"], ex_res_check_v8["시간_종료"]):
                    st.error(f"⚠️ {selected_room_main_reserve_v8}은(는) 해당 시간에 일부 또는 전체가 이미 예약되어 있습니다."); is_overlap_main_reserve_v8=True; break
            if not is_overlap_main_reserve_v8:
                team_res_check_v8 = current_reservations_main_reserve_v8[
                    (current_reservations_main_reserve_v8["날짜"] == timetable_date) & # 수정: timetable_date 사용
                    (current_reservations_main_reserve_v8["조"] == selected_team_main_reserve_v8)
                ]
                for _, ex_res_check_v8 in team_res_check_v8.iterrows():
                    if check_time_overlap(manual_start_time_main_reserve_v8, manual_end_time_main_reserve_v8, ex_res_check_v8["시간_시작"], ex_res_check_v8["시간_종료"]):
                        st.error(f"⚠️ {selected_team_main_reserve_v8}은(는) 해당 시간에 이미 다른 방을 예약했습니다."); is_overlap_main_reserve_v8=True; break
            if not is_overlap_main_reserve_v8:
                new_item_main_reserve_v8 = {"날짜": timetable_date, "시간_시작": manual_start_time_main_reserve_v8, "시간_종료": manual_end_time_main_reserve_v8, "조": selected_team_main_reserve_v8, "방": selected_room_main_reserve_v8, "예약유형": "수동", "예약ID": str(uuid.uuid4())} # 수정: timetable_date 사용
                updated_df_main_reserve_v8 = pd.concat([current_reservations_main_reserve_v8, pd.DataFrame([new_item_main_reserve_v8])], ignore_index=True)
                save_reservations(updated_df_main_reserve_v8)
                st.success(f"🎉 예약 완료!"); st.rerun()

        st.markdown("##### 🚫 나의 수동 예약 취소")
        # 예약 취소도 timetable_date 기준으로
        my_manual_res_display_cancel_v8 = reservations_df[(reservations_df["날짜"] == timetable_date) & (reservations_df["예약유형"] == "수동")].copy() # 수정: timetable_date 사용
        if not my_manual_res_display_cancel_v8.empty:
            my_manual_res_display_cancel_v8 = my_manual_res_display_cancel_v8.sort_values(by=["시간_시작", "조"])
            for _, row_main_cancel_v8 in my_manual_res_display_cancel_v8.iterrows():
                res_id_main_cancel_v8 = row_main_cancel_v8["예약ID"]
                time_str_main_cancel_v8 = f"{row_main_cancel_v8['시간_시작'].strftime('%H:%M')} - {row_main_cancel_v8['시간_종료'].strftime('%H:%M')}"
                item_cols_main_cancel_v8 = st.columns([3,1])
                with item_cols_main_cancel_v8[0]: st.markdown(f"**{time_str_main_cancel_v8}** / **{row_main_cancel_v8['조']}** / `{row_main_cancel_v8['방']}`")
                with item_cols_main_cancel_v8[1]:
                    if st.button("취소", key=f"cancel_{res_id_main_cancel_v8}_main_page_reserve_v8" + key_suffix_manual, use_container_width=True):
                        current_on_cancel_main_reserve_v8 = load_reservations()
                        updated_on_cancel_main_reserve_v8 = current_on_cancel_main_reserve_v8[current_on_cancel_main_reserve_v8["예약ID"] != res_id_main_cancel_v8]
                        save_reservations(updated_on_cancel_main_reserve_v8)
                        st.success(f"🗑️ 예약 취소됨"); st.rerun()
        else: st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


elif st.session_state.current_page == "🔄 자동 배정 (관리자)":
    # (자동 배정 페이지 로직은 이전과 동일하게 유지)
    st.header("🔄 자동 배정 ⚠️ 관리자 전용")
    st.warning("이 기능은 관리자만 사용해주세요. 잘못된 조작은 전체 예약에 영향을 줄 수 있습니다.")
    
    current_test_mode_admin = False
    if 'test_mode' in locals() and isinstance(test_mode, bool): current_test_mode_admin = test_mode
    elif "test_mode_checkbox_admin_v8" in st.session_state: current_test_mode_admin = st.session_state.test_mode_checkbox_admin_v8
    
    auto_assign_date_admin_page_v8 = st.date_input("자동 배정 실행할 날짜", value=today_kst, key="auto_date_admin_page_final_v8")
    weekday_admin_page_v8 = auto_assign_date_admin_page_v8.weekday()
    is_wednesday_auto_assign = (weekday_admin_page_v8 == 2)

    current_auto_assign_start_time = WEDNESDAY_AUTO_ASSIGN_START_TIME if is_wednesday_auto_assign else DEFAULT_AUTO_ASSIGN_START_TIME
    current_auto_assign_end_time = WEDNESDAY_AUTO_ASSIGN_END_TIME if is_wednesday_auto_assign else DEFAULT_AUTO_ASSIGN_END_TIME
    
    start_str_auto = current_auto_assign_start_time.strftime('%H:%M')
    end_str_auto = ""
    if is_wednesday_auto_assign and current_auto_assign_end_time == time(23, 59):
        end_str_auto = "00:00" 
    else:
        end_str_auto = current_auto_assign_end_time.strftime('%H:%M')
    current_auto_assign_slot_str = f"{start_str_auto} - {end_str_auto}"

    if current_test_mode_admin: st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else: st.info(f"🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다. (선택된 날짜: {'수요일' if is_wednesday_auto_assign else '수요일 아님'})")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **선택된 날짜 ({auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')}, {'수요일' if is_wednesday_auto_assign else '수요일 아님'})**
        - **배정 시간:** `{current_auto_assign_slot_str}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** `{', '.join(AUTO_ASSIGN_EXCLUDE_TEAMS)}` 조는 제외. 나머지 조는 로테이션.
        """)
    
    can_auto_assign_admin_page_v8 = current_test_mode_admin or (is_wednesday_auto_assign or weekday_admin_page_v8 == 6)

    if not can_auto_assign_admin_page_v8: st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page_final_v8", type="primary", disabled=not can_auto_assign_admin_page_v8):
        current_reservations_admin_page_v8 = load_reservations()
        existing_auto_admin_page_v8 = current_reservations_admin_page_v8[
            (current_reservations_admin_page_v8["날짜"] == auto_assign_date_admin_page_v8) &
            (current_reservations_admin_page_v8["시간_시작"] == current_auto_assign_start_time) &
            (current_reservations_admin_page_v8["시간_종료"] == current_auto_assign_end_time) &
            (current_reservations_admin_page_v8["예약유형"] == "자동")
        ]
        if not existing_auto_admin_page_v8.empty: st.warning(f"이미 {auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')} {current_auto_assign_slot_str}에 자동 배정 내역이 있습니다.")
        else:
            new_auto_list_admin_page_v8 = []
            assigned_info_admin_page_v8 = []
            if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                new_auto_list_admin_page_v8.append({"날짜": auto_assign_date_admin_page_v8, "시간_시작": current_auto_assign_start_time, "시간_종료": current_auto_assign_end_time, "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())})
                assigned_info_admin_page_v8.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
            next_idx_admin_page_v8 = load_rotation_state()
            num_rotation_teams_admin_page_v8 = len(ROTATION_TEAMS)
            num_rotation_rooms_admin_page_v8 = len(ROTATION_ROOMS)
            available_slots_for_rotation = min(num_rotation_teams_admin_page_v8, num_rotation_rooms_admin_page_v8)
            for i in range(available_slots_for_rotation):
                team_idx_list_admin_page_v8 = (next_idx_admin_page_v8 + i) % num_rotation_teams_admin_page_v8
                team_assign_admin_page_v8 = ROTATION_TEAMS[team_idx_list_admin_page_v8]
                room_assign_admin_page_v8 = ROTATION_ROOMS[i]
                new_auto_list_admin_page_v8.append({"날짜": auto_assign_date_admin_page_v8, "시간_시작": current_auto_assign_start_time, "시간_종료": current_auto_assign_end_time, "조": team_assign_admin_page_v8, "방": room_assign_admin_page_v8, "예약유형": "자동", "예약ID": str(uuid.uuid4())})
                assigned_info_admin_page_v8.append(f"🔄 **{team_assign_admin_page_v8}** → **{room_assign_admin_page_v8}** (로테이션)")
            if new_auto_list_admin_page_v8:
                new_df_admin_page_v8 = pd.DataFrame(new_auto_list_admin_page_v8)
                updated_df_admin_page_v8 = pd.concat([current_reservations_admin_page_v8, new_df_admin_page_v8], ignore_index=True)
                save_reservations(updated_df_admin_page_v8)
                new_next_idx_admin_page_v8 = (next_idx_admin_page_v8 + available_slots_for_rotation) % num_rotation_teams_admin_page_v8 if num_rotation_teams_admin_page_v8 > 0 else 0
                save_rotation_state(new_next_idx_admin_page_v8)
                st.success(f"🎉 {auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')} 자동 배정 완료!")
                for info in assigned_info_admin_page_v8: st.markdown(f"- {info}")
                if num_rotation_teams_admin_page_v8 > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin_page_v8]}'")
                st.rerun()
            else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 배정은 가능할 수 있음, 로테이션 대상 없음).")

    st.subheader(f"자동 배정 현황 ({current_auto_assign_slot_str})")
    auto_today_display_admin_page_v8 = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_page_v8) &
        (reservations_df["시간_시작"] == current_auto_assign_start_time) &
        (reservations_df["시간_종료"] == current_auto_assign_end_time) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_page_v8.empty: st.dataframe(auto_today_display_admin_page_v8[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else: st.info(f"{auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')} {current_auto_assign_slot_str} 시간대 자동 배정 내역이 없습니다.")


elif st.session_state.current_page == "📖 관리자 매뉴얼":
    st.header("📖 관리자 매뉴얼")
    default_slot_str_manual = f"{DEFAULT_AUTO_ASSIGN_START_TIME.strftime('%H:%M')} - {DEFAULT_AUTO_ASSIGN_END_TIME.strftime('%H:%M')}"
    wed_slot_str_manual = f"{WEDNESDAY_AUTO_ASSIGN_START_TIME.strftime('%H:%M')} - 00:00" # 23:59 종료를 00:00으로 표시

    st.markdown(f"""
    이 예약 시스템은 조모임방 예약을 효율적으로 관리하기 위해 만들어졌습니다.
    데이터는 **Google Sheets와 연동**되어 실시간으로 저장 및 업데이트됩니다.
    날짜는 **한국 표준시(KST)를 기준**으로 표시됩니다.

    ### 주요 기능:

    1.  **예약 시간표 및 수동 예약/취소 (기본 페이지):**
        *   페이지 상단의 **날짜 선택기**를 사용하여 시간표를 조회하고, 해당 날짜에 대한 수동 예약 및 취소를 진행합니다.
        *   **시간표 조회:** 선택된 날짜의 전체 예약 현황을 **1시간 단위** 시간표 형태로 볼 수 있습니다.
            *   시간표는 선택된 날짜에 따라 표시 범위가 조정될 수 있습니다.
        *   **수동 예약 등록:**
            *   선택된 날짜가 오늘 또는 미래인 경우에만 예약 가능합니다.
            *   **수요일:** 예약 가능 시간 **{WEDNESDAY_MANUAL_RESERVATION_START_HOUR}:00 ~ {WEDNESDAY_MANUAL_RESERVATION_END_HOUR}:00**
            *   **그 외 요일:** 예약 가능 시간 **{DEFAULT_MANUAL_RESERVATION_START_HOUR}:00 ~ {DEFAULT_MANUAL_RESERVATION_END_HOUR}:00**
            *   "조 선택" -> "방 선택" -> "시작/종료 시간 선택" 순으로 입력합니다.
            *   모든 예약은 **1시간 단위**이며, 최소 예약 시간도 1시간입니다.
        *   **수동 예약 취소:** 선택된 날짜의 수동 예약 목록에서 취소할 수 있습니다. (오늘 또는 미래 날짜만 가능)

    2.  **자동 배정 (관리자 전용):**
        *   **자동 배정 날짜:** 접속 시 오늘 날짜(KST)가 기본으로 선택됩니다.
        *   **배정 시간:**
            *   **수요일:** **{wed_slot_str_manual}**
            *   **그 외 요일 (일요일 포함):** **{default_slot_str_manual}**
        *   **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)

    ### 데이터 관리 / 주의사항: (기존과 동일)
    """)
content_copy
download
Use code with caution.
Python
주요 변경점 요약:

날짜 선택기 통합 (timetable_date 활용):
st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약" 블록 상단에 timetable_date라는 st.date_input 하나만 남겼습니다. 이 날짜가 시간표 조회, 수동 예약, 수동 예약 취소의 기준이 됩니다.
수동 예약/취소는 선택된 timetable_date가 오늘(today_kst) 또는 미래인 경우에만 활성화되도록 can_manual_reserve_today 변수를 사용하고, 과거 날짜일 경우 경고 메시지를 표시합니다.
수동 예약 정보 저장 시 new_item_main_reserve_v8["날짜"]에 timetable_date를 사용합니다.
수동 예약 취소 목록 필터링 시 reservations_df["날짜"] == timetable_date를 사용합니다.
수동 예약 UI 레이아웃 변경:
"새 예약 등록" 섹션에서 st.selectbox로 "조 선택"과 "방 선택"을 먼저 표시합니다.
그 아래에 st.columns(2)를 사용하여 "시작 시간"과 "종료 시간" st.time_input을 나란히 배치했습니다.
위젯 key 동적 변경 유지: 수동 예약 관련 위젯들의 key에 key_suffix_manual (요일에 따라 _wed 또는 _other)을 추가하여, timetable_date 변경으로 요일 특성이 바뀔 때 위젯들이 올바르게 리셋되고 기본값을 다시 로드하도록 했습니다.
매뉴얼 업데이트: 통합된 날짜 선택기와 변경된 수동 예약 UI 흐름을 매뉴얼에 반영했습니다.
시간표 표시 로직 미세 조정: 시간표 생성 시 time_slots_v8를 만드는 루프 조건을 좀 더 명확하게 수정했습니다.
이 변경으로 UI가 더 간결해지고 스마트폰에서의 사용성이 향상될 것으로 기대합니다. 테스트해 보시고 피드백 부탁드립니다!
