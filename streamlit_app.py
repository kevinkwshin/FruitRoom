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

# 수정: 자동 배정 시간 및 시간 단위 변경
AUTO_ASSIGN_TIME_SLOT_STR = "11:00 - 13:00" # 1시간 단위, 2시간 지속
AUTO_ASSIGN_START_TIME = time(11, 0)
AUTO_ASSIGN_END_TIME = time(13, 0)

MANUAL_RESERVATION_START_HOUR = 13 # 수동 예약 시작 시간은 그대로 유지 (13시)
MANUAL_RESERVATION_END_HOUR = 17   # 수동 예약 종료 시간은 그대로 유지 (17시)
RESERVATION_SHEET_HEADERS = ["날짜", "시간_시작", "시간_종료", "조", "방", "예약유형", "예약ID"]
ROTATION_SHEET_HEADER = ["next_team_index"]
TIME_STEP_MINUTES = 60 # 예약 및 표시 단위를 60분(1시간)으로 설정

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
                    'min-width': '85px', 'height': '60px', 'font-size': '0.9em', # 셀 크기 약간 조정
                    'line-height': '1.5'
                }).set_table_styles([
                    {'selector': 'th', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '8px'), ('color', '#333'), # 패딩 약간 조정
                        ('vertical-align', 'middle')
                    ]},
                    {'selector': 'th.row_heading', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '8px'), ('color', '#333'),
                        ('vertical-align', 'middle')
                    ]},
                    {'selector': 'td', 'props': [('padding', '8px'), ('vertical-align', 'top')]}
                ])
                def highlight_reserved_cell(val_html): # 함수 이름은 그대로 두되, 내부 로직은 val_html을 처리
                    bg_color = 'background-color: white;' # 기본 배경 흰색
                    # val_html은 이미 HTML 문자열이므로, 내부 콘텐츠에 따라 배경색만 변경
                    if isinstance(val_html, str) and val_html != '':
                        if '(자동)' in val_html:
                            bg_color = 'background-color: #e0f3ff;' # 하늘색 계열
                        elif '(수동)' in val_html:
                            bg_color = 'background-color: #d4edda;' # 연두색 계열
                    # font-weight는 HTML 태그(<b>)에서 이미 처리되므로 여기서는 제거
                    return f'{bg_color};' 

                try:
                    styled_df = styled_df.set_table_attributes('style="border-collapse: collapse;"')
                    styled_df = styled_df.map(highlight_reserved_cell)
                except AttributeError:
                    st.warning("Pandas Styler.map()을 사용할 수 없습니다. 이전 방식(applymap)을 사용합니다. Pandas 버전 업그레이드를 고려해주세요.")
                    styled_df = styled_df.applymap(highlight_reserved_cell) # Fallback
                return styled_df

            # 수정: 시간표 슬롯을 1시간 단위로 생성 (예: 11:00, 12:00, 13:00, ..., 16:00)
            # 자동 배정 시작 시간(11:00)부터 수동 예약 종료 시간(17:00)까지
            time_slots_v8 = []
            current_dt_v8 = datetime.combine(date.today(), time(AUTO_ASSIGN_START_TIME.hour, 0)) # 11:00 부터 시작
            end_of_day_dt_v8 = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0)) # 17:00 까지

            while current_dt_v8 < end_of_day_dt_v8:
                time_slots_v8.append(current_dt_v8.time())
                current_dt_v8 += timedelta(hours=1)

            timetable_df_v8 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_v8], columns=ALL_ROOMS)
            timetable_df_v8 = timetable_df_v8.fillna('')

            for _, res_v8 in day_reservations.iterrows():
                res_start_time = res_v8["시간_시작"]
                res_end_time = res_v8["시간_종료"]
                res_type_str_v8 = "(자동)" if res_v8['예약유형'] == '자동' else "(수동)"
                
                # 수정: 조 이름 색상 변경 및 스타일 적용
                team_name_color = "#333333" # 어두운 회색 또는 검정색
                cell_content_v8 = f"<b style='color: {team_name_color};'>{res_v8['조']}</b><br><small style='color: #555;'>{res_type_str_v8}</small>"

                # 시간표의 각 1시간 슬롯에 대해 예약이 걸쳐있는지 확인
                for slot_start_time_obj in time_slots_v8:
                    slot_start_dt = datetime.combine(date.today(), slot_start_time_obj)
                    slot_end_dt = slot_start_dt + timedelta(hours=1)
                    
                    # 예약 시간과 슬롯 시간이 겹치는지 확인
                    # (res_start < slot_end) and (res_end > slot_start)
                    res_start_dt_combined = datetime.combine(date.today(), res_start_time)
                    res_end_dt_combined = datetime.combine(date.today(), res_end_time)

                    if res_start_dt_combined < slot_end_dt and res_end_dt_combined > slot_start_dt:
                        slot_str_v8 = slot_start_time_obj.strftime("%H:%M")
                        if slot_str_v8 in timetable_df_v8.index and res_v8["방"] in timetable_df_v8.columns:
                            # 이미 내용이 있으면 덮어쓰지 않거나, 다른 방식으로 병합 (여기서는 덮어씀)
                            timetable_df_v8.loc[slot_str_v8, res_v8["방"]] = cell_content_v8
            
            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황 (1시간 단위)**")
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
        - 최소 예약 시간은 1시간, 예약 단위는 1시간입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.markdown("##### 📝 새 예약 등록")
    manual_date_default_v8 = date.today()
    manual_date_main_reserve_v8 = st.date_input(
        "예약 날짜", value=manual_date_default_v8, min_value=date.today(),
        key="manual_date_main_page_reserve_v8"
    )

    cols_main_reserve_v8 = st.columns(2)
    with cols_main_reserve_v8[0]:
        selected_team_main_reserve_v8 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve_v8")
        _today_for_time_calc_v8 = date.today() 

        start_time_default_val_v8 = time(MANUAL_RESERVATION_START_HOUR, 0) # 13:00
        
        # 가능한 최대 시작 시간 (종료 시간 - 1시간)
        max_possible_start_time_dt_v8 = datetime.combine(_today_for_time_calc_v8, time(MANUAL_RESERVATION_END_HOUR, 0)) - timedelta(hours=1)
        max_possible_start_time_val_v8 = max_possible_start_time_dt_v8.time() # 예: 16:00

        if start_time_default_val_v8 > max_possible_start_time_val_v8:
            start_time_default_val_v8 = max_possible_start_time_val_v8

        manual_start_time_main_reserve_v8 = st.time_input(
            "시작 시간",
            value=start_time_default_val_v8,
            step=timedelta(hours=1), # 수정: 1시간 단위
            key="manual_start_time_main_page_reserve_v8"
        )

    with cols_main_reserve_v8[1]:
        selected_room_main_reserve_v8 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve_v8")
        
        end_time_default_val_v8 = time(MANUAL_RESERVATION_END_HOUR, 0) # 17:00

        # 가능한 최소 종료 시간 (선택된 시작 시간 + 1시간)
        min_possible_end_time_dt_v8 = datetime.combine(_today_for_time_calc_v8, manual_start_time_main_reserve_v8) + timedelta(hours=1)
        min_possible_end_time_val_v8 = min_possible_end_time_dt_v8.time()

        max_possible_end_time_val_v8 = time(MANUAL_RESERVATION_END_HOUR, 0) # 17:00

        if end_time_default_val_v8 < min_possible_end_time_val_v8:
            end_time_default_val_v8 = min_possible_end_time_val_v8
        if end_time_default_val_v8 > max_possible_end_time_val_v8:
            end_time_default_val_v8 = max_possible_end_time_val_v8
            
        manual_end_time_main_reserve_v8 = st.time_input(
            "종료 시간",
            value=end_time_default_val_v8,
            step=timedelta(hours=1), # 수정: 1시간 단위
            key="manual_end_time_main_page_reserve_v8"
        )

    time_valid_main_reserve_v8 = True
    if manual_start_time_main_reserve_v8 < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"시작 시간은 {time(MANUAL_RESERVATION_START_HOUR, 0).strftime('%H:%M')} 이후여야 합니다."); time_valid_main_reserve_v8 = False
    
    # 1시간 단위이므로, 최대 시작 시간은 16:00 (17:00 종료 - 1시간)
    if manual_start_time_main_reserve_v8 >= time(MANUAL_RESERVATION_END_HOUR, 0): # 시작이 종료시간과 같거나 늦으면 안됨
         st.error(f"시작 시간은 {time(MANUAL_RESERVATION_END_HOUR-1, 0).strftime('%H:%M')} 이전이어야 합니다."); time_valid_main_reserve_v8 = False
    elif manual_start_time_main_reserve_v8 > max_possible_start_time_val_v8:
        st.error(f"시작 시간은 {max_possible_start_time_val_v8.strftime('%H:%M')} 이전이어야 합니다 (최소 1시간 예약 필요)."); time_valid_main_reserve_v8 = False
    
    if manual_start_time_main_reserve_v8 >= manual_end_time_main_reserve_v8:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v8 = False
        
    if manual_end_time_main_reserve_v8 > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"종료 시간은 {time(MANUAL_RESERVATION_END_HOUR, 0).strftime('%H:%M')} 이전이어야 합니다."); time_valid_main_reserve_v8 = False

    min_duration_main_reserve_v8 = timedelta(hours=1) # 수정: 최소 예약 시간 1시간
    current_duration_v8 = datetime.combine(date.today(), manual_end_time_main_reserve_v8) - datetime.combine(date.today(), manual_start_time_main_reserve_v8)
    if current_duration_v8 < min_duration_main_reserve_v8 and time_valid_main_reserve_v8 :
        st.error(f"최소 예약 시간은 {min_duration_main_reserve_v8.seconds // 3600}시간입니다."); time_valid_main_reserve_v8 = False


    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v8", type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v8):
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
            new_item_main_reserve_v8 = {
                "날짜": manual_date_main_reserve_v8, "시간_시작": manual_start_time_main_reserve_v8, "시간_종료": manual_end_time_main_reserve_v8,
                "조": selected_team_main_reserve_v8, "방": selected_room_main_reserve_v8, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_main_reserve_v8 = pd.concat([current_reservations_main_reserve_v8, pd.DataFrame([new_item_main_reserve_v8])], ignore_index=True)
            save_reservations(updated_df_main_reserve_v8)
            st.success(f"🎉 예약 완료!")
            st.rerun()

    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_display_cancel_v8 = reservations_df[
        (reservations_df["날짜"] == manual_date_main_reserve_v8) &
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
    
    current_test_mode_admin = False
    if 'test_mode' in locals() and isinstance(test_mode, bool):
         current_test_mode_admin = test_mode
    elif "test_mode_checkbox_admin_v8" in st.session_state:
         current_test_mode_admin = st.session_state.test_mode_checkbox_admin_v8
    
    if current_test_mode_admin:
        st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else:
        st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT_STR}` (11:00 ~ 13:00, 2시간)
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** `{', '.join(AUTO_ASSIGN_EXCLUDE_TEAMS)}` 조는 제외. 나머지 조는 로테이션.
        """)

    auto_assign_date_admin_page_v8 = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_page_final_v8")
    weekday_admin_page_v8 = auto_assign_date_admin_page_v8.weekday()
    can_auto_assign_admin_page_v8 = current_test_mode_admin or (weekday_admin_page_v8 in [2, 6])

    if not can_auto_assign_admin_page_v8:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page_final_v8", type="primary", disabled=not can_auto_assign_admin_page_v8):
        current_reservations_admin_page_v8 = load_reservations()
        existing_auto_admin_page_v8 = current_reservations_admin_page_v8[
            (current_reservations_admin_page_v8["날짜"] == auto_assign_date_admin_page_v8) &
            (current_reservations_admin_page_v8["시간_시작"] == AUTO_ASSIGN_START_TIME) & # 11:00
            (current_reservations_admin_page_v8["시간_종료"] == AUTO_ASSIGN_END_TIME) & # 13:00
            (current_reservations_admin_page_v8["예약유형"] == "자동")
        ]
        if not existing_auto_admin_page_v8.empty:
            st.warning(f"이미 {auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT_STR}에 자동 배정 내역이 있습니다.")
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
            
            available_slots_for_rotation = min(num_rotation_teams_admin_page_v8, num_rotation_rooms_admin_page_v8)

            for i in range(available_slots_for_rotation):
                team_idx_list_admin_page_v8 = (next_idx_admin_page_v8 + i) % num_rotation_teams_admin_page_v8
                team_assign_admin_page_v8 = ROTATION_TEAMS[team_idx_list_admin_page_v8]
                room_assign_admin_page_v8 = ROTATION_ROOMS[i]
                new_auto_list_admin_page_v8.append({
                    "날짜": auto_assign_date_admin_page_v8, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                    "조": team_assign_admin_page_v8, "방": room_assign_admin_page_v8, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                })
                assigned_info_admin_page_v8.append(f"🔄 **{team_assign_admin_page_v8}** → **{room_assign_admin_page_v8}** (로테이션)")

            if new_auto_list_admin_page_v8:
                new_df_admin_page_v8 = pd.DataFrame(new_auto_list_admin_page_v8)
                updated_df_admin_page_v8 = pd.concat([current_reservations_admin_page_v8, new_df_admin_page_v8], ignore_index=True)
                save_reservations(updated_df_admin_page_v8)
                
                new_next_idx_admin_page_v8 = 0
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

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin_page_v8 = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_page_v8) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["시간_종료"] == AUTO_ASSIGN_END_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_page_v8.empty:
        st.dataframe(auto_today_display_admin_page_v8[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin_page_v8.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT_STR} 시간대 자동 배정 내역이 없습니다.")


elif st.session_state.current_page == "📖 관리자 매뉴얼":
    st.header("📖 관리자 매뉴얼")
    st.markdown(f"""
    이 예약 시스템은 조모임방 예약을 효율적으로 관리하기 위해 만들어졌습니다.
    데이터는 **Google Sheets와 연동**되어 실시간으로 저장 및 업데이트됩니다.

    ### 주요 기능:

    1.  **예약 시간표 및 수동 예약 (기본 페이지):**
        *   **시간표 조회:** 접속 시 오늘 날짜가 기본으로 선택되며, 특정 날짜를 선택하여 해당 날짜의 전체 예약 현황을 **1시간 단위** 시간표 형태로 볼 수 있습니다.
            *   시간표 셀에는 조 이름(잘 보이도록 색상 적용)과 예약 유형(자동/수동)이 표시됩니다.
        *   **수동 예약 등록:**
            *   접속 시 예약 날짜가 오늘로 기본 선택됩니다. (과거 날짜 선택 불가)
            *   원하는 날짜, 조, 방, 시작 시간(기본 13:00), 종료 시간(기본 17:00)을 **1시간 단위**로 선택하여 직접 예약할 수 있습니다.
            *   예약 가능 시간: 매일 {MANUAL_RESERVATION_START_HOUR}:00부터 {MANUAL_RESERVATION_END_HOUR}:00까지.
            *   최소 예약 시간은 1시간입니다.
            *   중복 예약은 불가능합니다.
        *   **수동 예약 취소:**
            *   "새 예약 등록" 섹션에서 선택된 날짜의 수동 예약 목록이 나타납니다.
            *   각 예약 항목 옆의 "취소" 버튼을 눌러 예약을 취소할 수 있습니다.

    2.  **자동 배정 (관리자 전용):**
        *   이 페이지는 **관리자만 사용**해야 합니다. 사이드바의 "👑 관리자" 섹션을 통해 접근할 수 있습니다.
        *   **자동 배정 날짜:** 접속 시 오늘 날짜가 기본으로 선택됩니다.
        *   **배정 시간:** 자동 배정은 항상 **{AUTO_ASSIGN_TIME_SLOT_STR}** 시간대로 이루어집니다 (총 2시간).
        *   **실행 요일:** 기본적으로 매주 **수요일**과 **일요일**의 예약이 자동으로 배정됩니다.
            *   사이드바의 "🧪 테스트 모드 활성화"를 체크하면 요일 제한 없이 아무 날짜나 자동 배정을 실행하여 테스트할 수 있습니다.
        *   **고정 배정/로테이션 배정:** (기존 설명과 동일)
        *   **실행 방법:** (기존 설명과 동일)

    ### 데이터 관리: (기존 설명과 동일)
    ### 주의사항: (기존 설명과 동일)

    궁금한 점이나 문제가 발생하면 관리자에게 문의해주세요.
    """)
