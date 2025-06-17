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
# DEFAULT_AUTO_ASSIGN_SLOT_STR 은 아래에서 동적으로 생성

DEFAULT_MANUAL_RESERVATION_START_HOUR = 13
DEFAULT_MANUAL_RESERVATION_END_HOUR = 17

WEDNESDAY_AUTO_ASSIGN_START_TIME = time(21, 0)
WEDNESDAY_AUTO_ASSIGN_END_TIME = time(23, 59) # 24:00 대신 23:59로 당일 종료
# WEDNESDAY_AUTO_ASSIGN_SLOT_STR 은 아래에서 동적으로 생성

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
    st.header("🗓️ 예약 시간표")
    timetable_date = st.date_input("시간표 조회 날짜", value=today_kst, key="timetable_date_main_page_v8")

    selected_weekday = timetable_date.weekday()
    is_wednesday_selected_timetable = (selected_weekday == 2)

    timetable_display_start_hour = DEFAULT_AUTO_ASSIGN_START_TIME.hour
    timetable_display_end_hour = DEFAULT_MANUAL_RESERVATION_END_HOUR
    if is_wednesday_selected_timetable:
        # 수요일 시간표는 21:00 ~ 23:00 슬롯까지, 그리고 자동배정 11시도 포함하도록
        timetable_display_start_hour = min(DEFAULT_AUTO_ASSIGN_START_TIME.hour, WEDNESDAY_AUTO_ASSIGN_START_TIME.hour) # 11시
        timetable_display_end_hour = WEDNESDAY_AUTO_ASSIGN_END_TIME.hour + 1 # 23:59의 다음 시간은 24 (다음날 0시)

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        # 시간표 생성 로직은 day_reservations 유무와 관계없이 실행되도록 밖으로 뺌
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
        # current_dt_v8의 날짜 부분은 중요하지 않음, time 객체만 사용
        current_dt_for_slot_generation = datetime.combine(date(2000,1,1), time(timetable_display_start_hour, 0))
        
        # end_hour_for_loop는 루프의 종료 조건으로 사용될 시간(hour) 값
        end_hour_for_loop = timetable_display_end_hour
        if timetable_display_end_hour == 24: # 24시까지면 23시 슬롯까지 생성
            end_hour_for_loop = 24 # 루프는 < 24 로 돌아서 23시까지만

        # time_slots_v8 생성
        hour_iter = timetable_display_start_hour
        while hour_iter < end_hour_for_loop:
            time_slots_v8.append(time(hour_iter,0))
            hour_iter +=1

        timetable_df_v8 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_v8], columns=ALL_ROOMS).fillna('')

        if not day_reservations.empty:
            for _, res_v8 in day_reservations.iterrows():
                res_start_time = res_v8["시간_시작"]
                res_end_time = res_v8["시간_종료"]
                res_type_str_v8 = "(자동)" if res_v8['예약유형'] == '자동' else "(수동)"
                team_name_color = "#333333" 
                cell_content_v8 = f"<b style='color: {team_name_color};'>{res_v8['조']}</b><br><small style='color: #555;'>{res_type_str_v8}</small>"

                for slot_start_time_obj in time_slots_v8:
                    # 날짜 부분은 동일하게 하여 시간만 비교 (dummy date 사용)
                    slot_start_dt = datetime.combine(date.min, slot_start_time_obj)
                    slot_end_dt = slot_start_dt + timedelta(hours=1)
                    
                    res_start_dt_combined = datetime.combine(date.min, res_start_time)
                    
                    # 수요일 자정 예약(23:59 종료)은 다음날 00:00으로 간주되지 않도록 처리
                    if res_end_time == time(0,0) and res_start_time > time(12,0): # 시작이 오후고 종료가 00:00이면 다음날 자정
                         res_end_dt_combined = datetime.combine(date.min + timedelta(days=1), time(0,0))
                    elif res_end_time == time(23,59) and is_wednesday_selected_timetable: # 수요일 23:59 예약
                        # 이 경우 slot_end_dt가 다음날 00:00이 될 수 있으므로, 23:59를 정확히 표현
                         res_end_dt_combined = datetime.combine(date.min, time(23,59,59)) # 초까지 명시하여 비교 정확도 향상
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

    else: # reservations_df.empty
        st.info("등록된 예약이 없습니다.")


    st.markdown("---")
    st.header("✍️ 조모임방 예약/취소")

    manual_date_default_v8 = today_kst
    manual_date_main_reserve_v8 = st.date_input(
        "예약 날짜", value=manual_date_default_v8, min_value=today_kst,
        key="manual_date_main_page_reserve_v8"
    )
    
    manual_selected_weekday = manual_date_main_reserve_v8.weekday()
    is_wednesday_manual = (manual_selected_weekday == 2)

    current_manual_start_hour = WEDNESDAY_MANUAL_RESERVATION_START_HOUR if is_wednesday_manual else DEFAULT_MANUAL_RESERVATION_START_HOUR
    current_manual_end_hour = WEDNESDAY_MANUAL_RESERVATION_END_HOUR if is_wednesday_manual else DEFAULT_MANUAL_RESERVATION_END_HOUR

    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **선택된 날짜 ({manual_date_main_reserve_v8.strftime('%Y-%m-%d')}, {'수요일' if is_wednesday_manual else '수요일 아님'})**
        - **예약 가능 시간:** 매일 `{current_manual_start_hour}:00` 부터 `{current_manual_end_hour}:00` 까지.
        - 최소 예약 시간은 1시간, 예약 단위는 1시간입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.markdown("##### 📝 새 예약 등록")
    
    cols_main_reserve_v8 = st.columns(2)
    # 위젯 key에 is_wednesday_manual을 추가하여 요일 변경 시 위젯이 다시 그려지도록 함
    key_suffix = "_wed" if is_wednesday_manual else "_other"

    with cols_main_reserve_v8[0]:
        selected_team_main_reserve_v8 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve_v8" + key_suffix)
        _today_for_time_calc_v8 = today_kst

        start_time_default_val_v8 = time(current_manual_start_hour, 0)
        
        max_possible_start_time_dt_v8 = datetime.combine(_today_for_time_calc_v8, time(current_manual_end_hour, 0)) - timedelta(hours=1)
        max_possible_start_time_val_v8 = max_possible_start_time_dt_v8.time()

        if start_time_default_val_v8 > max_possible_start_time_val_v8 :
             start_time_default_val_v8 = max_possible_start_time_val_v8
        if start_time_default_val_v8 < time(current_manual_start_hour,0): # 최소 시작시간 보장
             start_time_default_val_v8 = time(current_manual_start_hour,0)


        manual_start_time_main_reserve_v8 = st.time_input(
            "시작 시간",
            value=start_time_default_val_v8,
            step=timedelta(hours=1),
            key="manual_start_time_main_page_reserve_v8" + key_suffix
        )

    with cols_main_reserve_v8[1]:
        selected_room_main_reserve_v8 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve_v8" + key_suffix)
        
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
            key="manual_end_time_main_page_reserve_v8" + key_suffix
        )

    time_valid_main_reserve_v8 = True
    if manual_start_time_main_reserve_v8 < time(current_manual_start_hour, 0):
        st.error(f"시작 시간은 {time(current_manual_start_hour, 0).strftime('%H:%M')} 이후여야 합니다."); time_valid_main_reserve_v8 = False
    
    if manual_start_time_main_reserve_v8 >= time(current_manual_end_hour, 0):
         st.error(f"시작 시간은 {time(current_manual_end_hour-1, 0).strftime('%H:%M')} 이전이어야 합니다."); time_valid_main_reserve_v8 = False
    elif manual_start_time_main_reserve_v8 > max_possible_start_time_val_v8:
        st.error(f"시작 시간은 {max_possible_start_time_val_v8.strftime('%H:%M')} 이전이어야 합니다 (최소 1시간 예약 필요)."); time_valid_main_reserve_v8 = False
    
    if manual_start_time_main_reserve_v8 >= manual_end_time_main_reserve_v8:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v8 = False
        
    if manual_end_time_main_reserve_v8 > time(current_manual_end_hour, 0):
        st.error(f"종료 시간은 {time(current_manual_end_hour, 0).strftime('%H:%M')} 이전이어야 합니다."); time_valid_main_reserve_v8 = False

    min_duration_main_reserve_v8 = timedelta(hours=1)
    current_duration_v8 = datetime.combine(today_kst, manual_end_time_main_reserve_v8) - datetime.combine(today_kst, manual_start_time_main_reserve_v8)
    if current_duration_v8 < min_duration_main_reserve_v8 and time_valid_main_reserve_v8 :
        st.error(f"최소 예약 시간은 {min_duration_main_reserve_v8.seconds // 3600}시간입니다."); time_valid_main_reserve_v8 = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v8"  + key_suffix, type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v8):
        current_reservations_main_reserve_v8 = load_reservations()
        is_overlap_main_reserve_v8 = False
        room_res_check_v8 = current_reservations_main_reserve_v8[
            (current_reservations_main_reserve_v8["날짜"] == manual_date_main_reserve_v8) &
            (current_reservations_main_reserve_v8["방"] == selected_room_main_reserve_v8)
        ]
        for _, ex_res_check_v8 in room_res_check_v8.iterrows():
            if check_time_overlap(manual_start_time_main_reserve_v8, manual_end_time_main_reserve_v8, ex_res_check_v8["시간_시작"], ex_res_check_v8["시간_종료"]):
                st.error(f"⚠️ {selected_room_main_reserve_v8}은(는) 해당 시간에 일부 또는 전체가 이미 예약되어 있습니다."); is_overlap_main_reserve_v8=True; break
        if not is_overlap_main_reserve_v8:
            team_res_check_v8 = current_reservations_main_reserve_v8[
                (current_reservations_main_reserve_v8["날짜"] == manual_date_main_reserve_v8) &
                (current_reservations_main_reserve_v8["조"] == selected_team_main_reserve_v8)
            ]
            for _, ex_res_check_v8 in team_res_check_v8.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v8, manual_end_time_main_reserve_v8, ex_res_check_v8["시간_시작"], ex_res_check_v8["시간_종료"]):
                    st.error(f"⚠️ {selected_team_main_reserve_v8}은(는) 해당 시간에 이미 다른 방을 예약했습니다."); is_overlap_main_reserve_v8=True; break
        if not is_overlap_main_reserve_v8:
            new_item_main_reserve_v8 = {"날짜": manual_date_main_reserve_v8, "시간_시작": manual_start_time_main_reserve_v8, "시간_종료": manual_end_time_main_reserve_v8, "조": selected_team_main_reserve_v8, "방": selected_room_main_reserve_v8, "예약유형": "수동", "예약ID": str(uuid.uuid4())}
            updated_df_main_reserve_v8 = pd.concat([current_reservations_main_reserve_v8, pd.DataFrame([new_item_main_reserve_v8])], ignore_index=True)
            save_reservations(updated_df_main_reserve_v8)
            st.success(f"🎉 예약 완료!"); st.rerun()

    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_display_cancel_v8 = reservations_df[(reservations_df["날짜"] == manual_date_main_reserve_v8) & (reservations_df["예약유형"] == "수동")].copy()
    if not my_manual_res_display_cancel_v8.empty:
        my_manual_res_display_cancel_v8 = my_manual_res_display_cancel_v8.sort_values(by=["시간_시작", "조"])
        for _, row_main_cancel_v8 in my_manual_res_display_cancel_v8.iterrows():
            res_id_main_cancel_v8 = row_main_cancel_v8["예약ID"]
            time_str_main_cancel_v8 = f"{row_main_cancel_v8['시간_시작'].strftime('%H:%M')} - {row_main_cancel_v8['시간_종료'].strftime('%H:%M')}"
            item_cols_main_cancel_v8 = st.columns([3,1])
            with item_cols_main_cancel_v8[0]: st.markdown(f"**{time_str_main_cancel_v8}** / **{row_main_cancel_v8['조']}** / `{row_main_cancel_v8['방']}`")
            with item_cols_main_cancel_v8[1]:
                if st.button("취소", key=f"cancel_{res_id_main_cancel_v8}_main_page_reserve_v8" + key_suffix, use_container_width=True):
                    current_on_cancel_main_reserve_v8 = load_reservations()
                    updated_on_cancel_main_reserve_v8 = current_on_cancel_main_reserve_v8[current_on_cancel_main_reserve_v8["예약ID"] != res_id_main_cancel_v8]
                    save_reservations(updated_on_cancel_main_reserve_v8)
                    st.success(f"🗑️ 예약 취소됨"); st.rerun()
    else: st.info(f"{manual_date_main_reserve_v8.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")

elif st.session_state.current_page == "🔄 자동 배정 (관리자)":
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
    # 수요일과 다른 요일의 자동 배정 시간 문자열을 생성
    default_slot_str_manual = f"{DEFAULT_AUTO_ASSIGN_START_TIME.strftime('%H:%M')} - {DEFAULT_AUTO_ASSIGN_END_TIME.strftime('%H:%M')}"
    wed_slot_str_manual = f"{WEDNESDAY_AUTO_ASSIGN_START_TIME.strftime('%H:%M')} - 00:00"

    st.markdown(f"""
    이 예약 시스템은 조모임방 예약을 효율적으로 관리하기 위해 만들어졌습니다.
    데이터는 **Google Sheets와 연동**되어 실시간으로 저장 및 업데이트됩니다.
    날짜는 **한국 표준시(KST)를 기준**으로 표시됩니다.

    ### 주요 기능:

    1.  **예약 시간표 및 수동 예약 (기본 페이지):**
        *   **시간표 조회:** 접속 시 오늘 날짜(KST)가 기본으로 선택되며, 시간표는 선택된 날짜에 따라 표시 범위가 조정됩니다.
            *   (예: 수요일은 11:00 ~ 23:00 슬롯까지, 다른 요일은 11:00 ~ 16:00 슬롯까지 표시)
        *   **수동 예약 등록:**
            *   접속 시 예약 날짜가 오늘(KST)로 기본 선택됩니다. (과거 날짜 선택 불가)
            *   **수요일:** 예약 가능 시간 **{WEDNESDAY_MANUAL_RESERVATION_START_HOUR}:00 ~ {WEDNESDAY_MANUAL_RESERVATION_END_HOUR}:00**
            *   **그 외 요일:** 예약 가능 시간 **{DEFAULT_MANUAL_RESERVATION_START_HOUR}:00 ~ {DEFAULT_MANUAL_RESERVATION_END_HOUR}:00**
            *   모든 예약은 **1시간 단위**이며, 최소 예약 시간도 1시간입니다.
        *   **수동 예약 취소:** (기존과 동일)

    2.  **자동 배정 (관리자 전용):**
        *   **자동 배정 날짜:** 접속 시 오늘 날짜(KST)가 기본으로 선택됩니다.
        *   **배정 시간:**
            *   **수요일:** **{wed_slot_str_manual}**
            *   **그 외 요일 (일요일 포함):** **{default_slot_str_manual}**
        *   **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)

    ### 데이터 관리 / 주의사항: (기존과 동일)
    """)
