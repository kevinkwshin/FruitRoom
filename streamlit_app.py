import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
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
AUTO_ASSIGN_TIME_SLOT_STR = "11:30 - 13:00"
AUTO_ASSIGN_START_TIME = time(11, 30)
AUTO_ASSIGN_END_TIME = time(13, 0)
MANUAL_RESERVATION_START_HOUR = 13
MANUAL_RESERVATION_END_HOUR = 17
RESERVATION_SHEET_HEADERS = ["날짜", "시간_시작", "시간_종료", "조", "방", "예약유형", "예약ID"]
ROTATION_SHEET_HEADER = ["next_team_index"]

# --- Google Sheets 클라이언트 및 워크시트 초기화 ---
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

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임방 예약/조회", layout="centered", initial_sidebar_state="expanded")

if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"

# --- 사이드바 ---
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

# --- 메인 화면 콘텐츠 ---
if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df = load_reservations()

if st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약":
    st.header("🗓️ 예약 시간표")
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_main_page_v8")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd', 'text-align': 'center', 'vertical-align': 'middle',
                    'min-width': '75px', 'height': '50px', 'font-size': '0.8em',
                    'line-height': '1.4'
                }).set_table_styles([
                    {'selector': 'th', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '5px'), ('color', '#333'),
                        ('vertical-align', 'middle')
                    ]},
                    {'selector': 'th.row_heading', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '5px'), ('color', '#333'),
                        ('vertical-align', 'middle')
                    ]},
                    {'selector': 'td', 'props': [('padding', '5px'), ('vertical-align', 'top')]}
                ])
                def highlight_reserved_cell(val_html):
                    bg_color = 'background-color: white;'
                    font_weight = 'normal'
                    if isinstance(val_html, str) and val_html != '':
                        if '(자동)' in val_html:
                            bg_color = 'background-color: #e0f3ff;'
                        elif '(수동)' in val_html:
                            bg_color = 'background-color: #d4edda;'
                    return f'{bg_color}; font-weight: {font_weight};'

                try:
                    styled_df = styled_df.set_table_attributes('style="border-collapse: collapse;"')
                    styled_df = styled_df.map(highlight_reserved_cell) # 수정: applymap -> map
                except AttributeError:
                    st.warning("Pandas Styler.map()을 사용할 수 없습니다. 이전 방식(applymap)을 사용합니다. Pandas 버전 업그레이드를 고려해주세요.")
                    styled_df = styled_df.applymap(highlight_reserved_cell) # Fallback
                return styled_df

            time_slots_v8 = []
            current_time_v8 = datetime.combine(date.today(), time(11, 0))
            end_of_day_v8 = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_v8 < end_of_day_v8:
                time_slots_v8.append(current_time_v8.time())
                current_time_v8 += timedelta(minutes=30)

            timetable_df_v8 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_v8], columns=ALL_ROOMS)
            timetable_df_v8 = timetable_df_v8.fillna('')

            for _, res_v8 in day_reservations.iterrows():
                start_res_dt_v8 = datetime.combine(date.today(), res_v8["시간_시작"])
                end_res_dt_v8 = datetime.combine(date.today(), res_v8["시간_종료"])
                current_slot_dt_v8 = start_res_dt_v8
                res_type_str_v8 = "(자동)" if res_v8['예약유형'] == '자동' else "(수동)"
                cell_content_v8 = f"<b>{res_v8['조']}</b><br><small style='color: #555;'>{res_type_str_v8}</small>"

                while current_slot_dt_v8 < end_res_dt_v8:
                    slot_str_v8 = current_slot_dt_v8.strftime("%H:%M")
                    if slot_str_v8 in timetable_df_v8.index and res_v8["방"] in timetable_df_v8.columns:
                        if timetable_df_v8.loc[slot_str_v8, res_v8["방"]] == '':
                             timetable_df_v8.loc[slot_str_v8, res_v8["방"]] = cell_content_v8
                    current_slot_dt_v8 += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_v8).to_html(escape=False))
        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    st.markdown("---")
    st.header("✍️ 조모임방 예약/취소")
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지.
        - 최소 예약 시간은 30분, 예약 단위는 30분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.markdown("##### 📝 새 예약 등록")
    manual_date_default_v8 = max(timetable_date, date.today())
    manual_date_main_reserve_v8 = st.date_input(
        "예약 날짜", value=manual_date_default_v8, min_value=date.today(),
        key="manual_date_main_page_reserve_v8"
    )

    cols_main_reserve_v8 = st.columns(2)
    with cols_main_reserve_v8[0]:
        selected_team_main_reserve_v8 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve_v8")
        _today_v8 = date.today() # 날짜와 무관하게 시간 범위 계산을 위해 사용

        # 시작 시간 기본값 설정 (요청: 13:00)
        start_time_default_val_v8 = time(MANUAL_RESERVATION_START_HOUR, 0) # 13:00
        
        # 실제 예약 가능한 최대 시작 시간 (종료 시간 - 30분)
        # 이 값은 UI에서 사용자가 선택할 수 있는 범위를 암시적으로 제한하거나, 유효성 검사에 사용됨
        max_possible_start_time_dt_v8 = datetime.combine(_today_v8, time(MANUAL_RESERVATION_END_HOUR, 0)) - timedelta(minutes=30)
        max_possible_start_time_val_v8 = max_possible_start_time_dt_v8.time() # 예: 16:30

        # 만약 기본 시작 시간이 가능한 최대 시작 시간보다 늦다면 조정 (13:00은 16:30보다 이르므로 조정 안됨)
        if start_time_default_val_v8 > max_possible_start_time_val_v8:
            start_time_default_val_v8 = max_possible_start_time_val_v8

        manual_start_time_main_reserve_v8 = st.time_input(
            "시작 시간",
            value=start_time_default_val_v8, # 수정: 기본값 13:00
            # min_value, max_value 인자 제거
            step=timedelta(minutes=30),
            key="manual_start_time_main_page_reserve_v8"
        )

    with cols_main_reserve_v8[1]:
        selected_room_main_reserve_v8 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve_v8")
        
        # 종료 시간 기본값 설정 (요청: 17:00)
        end_time_default_val_v8 = time(MANUAL_RESERVATION_END_HOUR, 0) # 17:00

        # 실제 예약 가능한 최소 종료 시간 (선택된 시작 시간 + 30분)
        min_possible_end_time_dt_v8 = datetime.combine(_today_v8, manual_start_time_main_reserve_v8) + timedelta(minutes=30)
        min_possible_end_time_val_v8 = min_possible_end_time_dt_v8.time()

        # 실제 예약 가능한 최대 종료 시간
        max_possible_end_time_val_v8 = time(MANUAL_RESERVATION_END_HOUR, 0) # 17:00

        # 만약 기본 종료 시간이 가능한 최소 종료 시간보다 이르면 조정
        if end_time_default_val_v8 < min_possible_end_time_val_v8:
            end_time_default_val_v8 = min_possible_end_time_val_v8
        # 만약 기본 종료 시간이 가능한 최대 종료 시간보다 늦다면 조정 (17:00은 17:00이므로 조정 안됨)
        if end_time_default_val_v8 > max_possible_end_time_val_v8:
            end_time_default_val_v8 = max_possible_end_time_val_v8
            
        manual_end_time_main_reserve_v8 = st.time_input(
            "종료 시간",
            value=end_time_default_val_v8, # 수정: 기본값 17:00 (또는 조정된 값)
            # min_value, max_value 인자 제거
            step=timedelta(minutes=30),
            key="manual_end_time_main_page_reserve_v8"
        )

    time_valid_main_reserve_v8 = True
    # 유효성 검사: 시작 시간은 MANUAL_RESERVATION_START_HOUR (13:00) 이상이어야 함
    if manual_start_time_main_reserve_v8 < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"시작 시간은 {time(MANUAL_RESERVATION_START_HOUR, 0).strftime('%H:%M')} 이후여야 합니다."); time_valid_main_reserve_v8 = False
    # 유효성 검사: 시작 시간은 max_possible_start_time_val_v8 (예: 16:30) 이하여야 함
    if manual_start_time_main_reserve_v8 > max_possible_start_time_val_v8:
        st.error(f"시작 시간은 {max_possible_start_time_val_v8.strftime('%H:%M')} 이전이어야 합니다 (최소 30분 예약 필요)."); time_valid_main_reserve_v8 = False
    
    if manual_start_time_main_reserve_v8 >= manual_end_time_main_reserve_v8:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v8 = False
    
    # 유효성 검사: 종료 시간은 min_possible_end_time_val_v8 (시작시간 + 30분) 이상이어야 함 (위의 로직과 중복될 수 있으나 명시)
    # 위에서 manual_start_time_main_reserve_v8 >= manual_end_time_main_reserve_v8로 이미 커버됨
    # if manual_end_time_main_reserve_v8 < min_possible_end_time_val_v8:
    #     st.error(f"종료 시간은 시작 시간으로부터 최소 30분 이후여야 합니다."); time_valid_main_reserve_v8 = False
        
    # 유효성 검사: 종료 시간은 MANUAL_RESERVATION_END_HOUR (17:00) 이하여야 함
    if manual_end_time_main_reserve_v8 > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"종료 시간은 {time(MANUAL_RESERVATION_END_HOUR, 0).strftime('%H:%M')} 이전이어야 합니다."); time_valid_main_reserve_v8 = False

    min_duration_main_reserve_v8 = timedelta(minutes=30)
    # datetime.min 대신 date.today() 사용 (날짜 영향 없으나 일관성)
    current_duration_v8 = datetime.combine(date.today(), manual_end_time_main_reserve_v8) - datetime.combine(date.today(), manual_start_time_main_reserve_v8)
    if current_duration_v8 < min_duration_main_reserve_v8 and time_valid_main_reserve_v8: # 유효성 검사가 통과한 경우에만 기간 체크
        st.error(f"최소 예약 시간은 {min_duration_main_reserve_v8.seconds // 60}분입니다."); time_valid_main_reserve_v8 = False


    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v8", type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v8):
        if time_valid_main_reserve_v8: # 최종 유효성 검사 한 번 더
            current_reservations_main_reserve_v8 = load_reservations()
            is_overlap_main_reserve_v8 = False
            room_res_check_v8 = current_reservations_main_reserve_v8[
                (current_reservations_main_reserve_v8["날짜"] == manual_date_main_reserve_v8) &
                (current_reservations_main_reserve_v8["방"] == selected_room_main_reserve_v8)
            ]
            for _, ex_res_check_v8 in room_res_check_v8.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v8, manual_end_time_main_reserve_v8, ex_res_check_v8["시간_시작"], ex_res_check_v8["시간_종료"]):
                    st.error(f"⚠️ {selected_room_main_reserve_v8}은(는) 해당 시간에 일부 또는 전체가 이미 예약되어 있습니다."); is_overlap_main_reserve_v8=True; break
            
            if not is_overlap_main_reserve_v8: # 방 중복이 없을 때만 조 중복 체크
                team_res_check_v8 = current_reservations_main_reserve_v8[
                    (current_reservations_main_reserve_v8["날짜"] == manual_date_main_reserve_v8) &
                    (current_reservations_main_reserve_v8["조"] == selected_team_main_reserve_v8)
                ]
                for _, ex_res_check_v8 in team_res_check_v8.iterrows():
                    if check_time_overlap(manual_start_time_main_reserve_v8, manual_end_time_main_reserve_v8, ex_res_check_v8["시간_시작"], ex_res_check_v8["시간_종료"]):
                        st.error(f"⚠️ {selected_team_main_reserve_v8}은(는) 해당 시간에 이미 다른 방을 예약했습니다."); is_overlap_main_reserve_v8=True; break
            
            if not is_overlap_main_reserve_v8:
                new_item_main_reserve_v8 = {
                    "날짜": manual_date_main_reserve_v8, "시간_시작": manual_start_time_main_reserve_v8, "시간_종료": manual_end_time_main_reserve_v8,
                    "조": selected_team_main_reserve_v8, "방": selected_room_main_reserve_v8, "예약유형": "수동", "예약ID": str(uuid.uuid4())
                }
                updated_df_main_reserve_v8 = pd.concat([current_reservations_main_reserve_v8, pd.DataFrame([new_item_main_reserve_v8])], ignore_index=True)
                save_reservations(updated_df_main_reserve_v8)
                st.success(f"🎉 예약 완료!")
                st.rerun()
            # else: 이미 st.error가 호출됨

    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_display_cancel_v8 = reservations_df[
        (reservations_df["날짜"] == manual_date_main_reserve_v8) & # 조회 중인 날짜의
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_cancel_v8.empty:
        my_manual_res_display_cancel_v8 = my_manual_res_display_cancel_v8.sort_values(by=["시간_시작", "조"])
        for _, row_main_cancel_v8 in my_manual_res_display_cancel_v8.iterrows():
            res_id_main_cancel_v8 = row_main_cancel_v8["예약ID"]
            time_str_main_cancel_v8 = f"{row_main_cancel_v8['시간_시작'].strftime('%H:%M')} - {row_main_cancel_v8['시간_종료'].strftime('%H:%M')}"
            item_cols_main_cancel_v8 = st.columns([3,1])
            with item_cols_main_cancel_v8[0]: st.markdown(f"**{time_str_main_cancel_v8}** / **{row_main_cancel_v8['조']}** / `{row_main_cancel_v8['방']}`")
            with item_cols_main_cancel_v8[1]:
                if st.button("취소", key=f"cancel_{res_id_main_cancel_v8}_main_page_reserve_v8", use_container_width=True):
                    current_on_cancel_main_reserve_v8 = load_reservations()
                    updated_on_cancel_main_reserve_v8 = current_on_cancel_main_reserve_v8[current_on_cancel_main_reserve_v8["예약ID"] != res_id_main_cancel_v8]
                    save_reservations(updated_on_cancel_main_reserve_v8)
                    st.success(f"🗑️ 예약 취소됨")
                    st.rerun()
    else:
        st.info(f"{manual_date_main_reserve_v8.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


elif st.session_state.current_page == "🔄 자동 배정 (관리자)":
    st.header("🔄 자동 배정 ⚠️ 관리자 전용")
    st.warning("이 기능은 관리자만 사용해주세요. 잘못된 조작은 전체 예약에 영향을 줄 수 있습니다.")
    
    # 사이드바에서 test_mode가 정의되지만, 이 페이지 로드 시점에 항상 접근 가능하도록 st.session_state 사용 고려 가능
    # 여기서는 사이드바가 먼저 실행된다고 가정하고 'test_mode' 변수를 사용합니다.
    # 만약 test_mode가 정의되지 않은 경우를 대비 (페이지 직접 접근 등)
    current_test_mode_admin = False
    if 'test_mode' in locals() and isinstance(test_mode, bool):
         current_test_mode_admin = test_mode
    elif "test_mode_checkbox_admin_v8" in st.session_state: # 사이드바 체크박스 값 사용
         current_test_mode_admin = st.session_state.test_mode_checkbox_admin_v8
    
    if current_test_mode_admin:
        st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else:
        st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT_STR}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** `{', '.join(AUTO_ASSIGN_EXCLUDE_TEAMS)}` 조는 제외. 나머지 조는 로테이션.
        """)

    auto_assign_date_admin_page_v8 = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_page_final_v8")
    weekday_admin_page_v8 = auto_assign_date_admin_page_v8.weekday()
    can_auto_assign_admin_page_v8 = current_test_mode_admin or (weekday_admin_page_v8 in [2, 6]) # 2: 수요일, 6: 일요일

    if not can_auto_assign_admin_page_v8:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page_final_v8", type="primary", disabled=not can_auto_assign_admin_page_v8):
        # if can_auto_assign_admin_page_v8: # 버튼 disabled로 이미 처리
        current_reservations_admin_page_v8 = load_reservations()
        existing_auto_admin_page_v8 = current_reservations_admin_page_v8[
            (current_reservations_admin_page_v8["날짜"] == auto_assign_date_admin_page_v8) &
            (current_reservations_admin_page_v8["시간_시작"] == AUTO_ASSIGN_START_TIME) &
            (current_reservations_admin_page_v8["예약유형"] == "자동")
        ]
        if not existing_auto_admin_page_v8.empty:
            st.warning(f"이미 {auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
        else:
            new_auto_list_admin_page_v8 = []
            assigned_info_admin_page_v8 = []
            if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                new_auto_list_admin_page_v8.append({
                    "날짜": auto_assign_date_admin_page_v8, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                    "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                })
                assigned_info_admin_page_v8.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
            
            next_idx_admin_page_v8 = load_rotation_state()
            num_rotation_teams_admin_page_v8 = len(ROTATION_TEAMS)
            num_rotation_rooms_admin_page_v8 = len(ROTATION_ROOMS)
            
            # 배정 가능한 로테이션 팀/방 수 (둘 중 작은 값만큼만 배정 가능)
            available_slots_for_rotation = min(num_rotation_teams_admin_page_v8, num_rotation_rooms_admin_page_v8)

            for i in range(available_slots_for_rotation):
                # num_rotation_teams_admin_page_v8 == 0 이면 이 루프는 실행되지 않음 (available_slots_for_rotation이 0)
                team_idx_list_admin_page_v8 = (next_idx_admin_page_v8 + i) % num_rotation_teams_admin_page_v8
                team_assign_admin_page_v8 = ROTATION_TEAMS[team_idx_list_admin_page_v8]
                room_assign_admin_page_v8 = ROTATION_ROOMS[i] # 방은 순서대로 할당
                new_auto_list_admin_page_v8.append({
                    "날짜": auto_assign_date_admin_page_v8, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                    "조": team_assign_admin_page_v8, "방": room_assign_admin_page_v8, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                })
                assigned_info_admin_page_v8.append(f"🔄 **{team_assign_admin_page_v8}** → **{room_assign_admin_page_v8}** (로테이션)")

            if new_auto_list_admin_page_v8:
                new_df_admin_page_v8 = pd.DataFrame(new_auto_list_admin_page_v8)
                updated_df_admin_page_v8 = pd.concat([current_reservations_admin_page_v8, new_df_admin_page_v8], ignore_index=True)
                save_reservations(updated_df_admin_page_v8)
                
                new_next_idx_admin_page_v8 = 0 # 기본값
                if num_rotation_teams_admin_page_v8 > 0:
                    new_next_idx_admin_page_v8 = (next_idx_admin_page_v8 + available_slots_for_rotation) % num_rotation_teams_admin_page_v8
                save_rotation_state(new_next_idx_admin_page_v8)
                
                st.success(f"🎉 {auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')} 자동 배정 완료!")
                for info in assigned_info_admin_page_v8: st.markdown(f"- {info}")
                if num_rotation_teams_admin_page_v8 > 0: 
                    st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin_page_v8]}'")
                st.rerun()
            else: 
                st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 배정은 가능할 수 있음, 로테이션 대상 없음).")
        # else: # 이미 배정된 경우, 위에서 st.warning 처리

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin_page_v8 = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_page_v8) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_page_v8.empty:
        st.dataframe(auto_today_display_admin_page_v8[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")


elif st.session_state.current_page == "📖 관리자 매뉴얼":
    st.header("📖 관리자 매뉴얼")
    st.markdown("""
    이 예약 시스템은 조모임방 예약을 효율적으로 관리하기 위해 만들어졌습니다.
    데이터는 **Google Sheets와 연동**되어 실시간으로 저장 및 업데이트됩니다.

    ### 주요 기능:

    1.  **예약 시간표 및 수동 예약 (기본 페이지):**
        *   **시간표 조회:** 특정 날짜를 선택하여 해당 날짜의 전체 예약 현황을 시간표 형태로 한눈에 볼 수 있습니다.
            *   시간표에는 자동 배정된 예약과 수동으로 예약된 내용이 모두 표시됩니다.
            *   각 예약 셀에는 조 이름과 예약 유형(자동/수동)이 표시됩니다.
        *   **수동 예약 등록:**
            *   시간표 아래 섹션에서 원하는 날짜, 조, 방, 시작 시간, 종료 시간을 선택하여 직접 예약할 수 있습니다.
            *   예약 가능 시간: 매일 13:00부터 17:00까지입니다. (기본 선택 시간: 시작 13:00, 종료 17:00)
            *   최소 예약 시간은 30분이며, 예약은 30분 단위로 가능합니다.
            *   이미 예약된 시간이나 방, 또는 해당 시간에 이미 다른 예약을 한 조는 중복 예약할 수 없습니다.
        *   **수동 예약 취소:**
            *   예약 등록 폼 아래에, 선택된 날짜에 본인이 한 수동 예약 목록이 나타납니다.
            *   각 예약 항목 옆의 "취소" 버튼을 눌러 예약을 취소할 수 있습니다.

    2.  **자동 배정 (관리자 전용):**
        *   이 페이지는 **관리자만 사용**해야 합니다. 사이드바의 "👑 관리자" 섹션을 통해 접근할 수 있습니다.
        *   **실행 요일:** 기본적으로 매주 **수요일**과 **일요일**의 예약이 자동으로 배정됩니다.
            *   사이드바의 "🧪 테스트 모드 활성화"를 체크하면 요일 제한 없이 아무 날짜나 자동 배정을 실행하여 테스트할 수 있습니다.
        *   **배정 시간:** 자동 배정은 항상 **11:30 - 13:00** 시간대로 이루어집니다.
        *   **고정 배정:**
            *   `시니어조`는 항상 `9F-1` 방에 고정적으로 배정됩니다.
        *   **로테이션 배정:**
            *   `시니어조`와 `9F-1` 방을 제외한 나머지 조들과 방들을 대상으로 로테이션 방식이 적용됩니다.
            *   `대면A`, `대면B`, `대면C` 조는 자동 배정 대상에서 제외됩니다.
            *   이전 자동 배정 시 마지막으로 배정된 조 다음 순서부터 공평하게 방이 할당됩니다.
        *   **실행 방법:**
            1.  자동 배정을 실행할 날짜를 선택합니다.
            2.  "선택 날짜 자동 배정 실행" 버튼을 클릭합니다. (실행 가능한 요일/모드일 때만 활성화)
            3.  이미 해당 날짜에 자동 배정 내역이 있다면 경고 메시지가 표시되며, 중복 실행되지 않습니다.
            4.  배정이 완료되면 결과와 함께 다음 로테이션 시작 조 정보가 표시됩니다.

    ### 데이터 관리:

    *   **Google Sheets 연동:** 모든 예약 데이터와 자동 배정 로테이션 상태는 지정된 Google 스프레드시트에 안전하게 저장됩니다.
        *   `reservations` 시트: 모든 예약 내역 (날짜, 시작/종료 시간, 조, 방, 예약 유형, 고유 예약 ID)
        *   `rotation_state` 시트: 다음 자동 배정 로테이션 시작 조의 인덱스
    *   **데이터 캐싱:** API 요청을 줄이고 앱 성능을 향상시키기 위해 데이터는 일정 시간(현재 3분) 동안 캐시됩니다.
        *   사이드바의 "🔄 데이터 캐시 새로고침" 버튼을 사용하여 언제든지 캐시를 수동으로 초기화하고 최신 데이터를 불러올 수 있습니다.

    ### 주의사항:

    *   **자동 배정 실행:** 자동 배정은 신중하게 실행해야 합니다. 이미 수동 예약이 있는 시간과 겹치지 않도록 설계되었지만, 실행 전 해당 날짜의 시간표를 한번 확인하는 것이 좋습니다.
    *   **Google Sheets 접근 권한:** 이 앱이 Google Sheets에 정상적으로 접근하려면 초기 설정 시 서비스 계정의 인증 정보(Secrets)와 스프레드시트 공유 설정이 올바르게 되어 있어야 합니다.
    *   **API 사용량:** 빈번한 새로고침이나 과도한 동시 사용은 Google Sheets API 사용량 제한에 도달할 수 있습니다. 현재 캐싱 기능으로 이를 완화하고 있습니다.

    궁금한 점이나 문제가 발생하면 관리자에게 문의해주세요.
    """)
