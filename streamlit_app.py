import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import gspread
from google.oauth2.service_account import Credentials
import uuid
import json

# --- 초기 설정 ---
AUTO_ASSIGN_EXCLUDE_TEAMS = ["대면A", "대면B", "대면C", "대면D"]
SENIOR_TEAM = "시니어조"
SENIOR_ROOM = "9F-1"
ALL_TEAMS = [f"{i}조" for i in range(1, 14)] + ["대면A", "대면B", "대면C", "대면D", "청년", "중고등", SENIOR_TEAM]
ROTATION_TEAMS = [team for team in ALL_TEAMS if team not in AUTO_ASSIGN_EXCLUDE_TEAMS and team != SENIOR_TEAM]
ALL_ROOMS = [f"9F-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
ROTATION_ROOMS = [room for room in ALL_ROOMS if room != SENIOR_ROOM]
AUTO_ASSIGN_TIME_SLOT_STR = "11:30 - 13:00"
AUTO_ASSIGN_START_TIME = time(11, 30)
AUTO_ASSIGN_END_TIME = time(13, 0)
MANUAL_RESERVATION_START_HOUR = 13
MANUAL_RESERVATION_END_HOUR = 17 # 17:00 정각까지 예약 가능
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
    if st.sidebar.button("🏠 시간표 및 수동 예약으로 돌아가기", key="return_to_main_btn_v6"):
        st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"
        st.rerun()
    st.sidebar.markdown("---")

st.sidebar.subheader("👑 관리자")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제", key="test_mode_checkbox_admin_v6")

if st.sidebar.button("⚙️ 자동 배정 설정 페이지로 이동", key="admin_auto_assign_nav_btn_admin_v6"):
    st.session_state.current_page = "🔄 자동 배정 (관리자)"
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 기타 설정")
if st.sidebar.button("🔄 데이터 캐시 새로고침", key="cache_refresh_btn_admin_v6"):
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
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_main_page_v6")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd', 'text-align': 'center', 'vertical-align': 'middle', # 수직 정렬 추가
                    'min-width': '75px', 'height': '50px', 'font-size': '0.8em', # 셀 크기, 폰트 크기 조정
                    'line-height': '1.4' # 줄 간격
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
                    {'selector': 'td', 'props': [('padding', '5px'), ('vertical-align', 'middle')]}
                ])

                def format_cell_value(val): # 셀 내용 포맷팅 함수
                    if isinstance(val, str) and val != '':
                        parts = val.split(' (') # 조 이름과 예약 유형 분리 시도
                        if len(parts) == 2:
                            team_name = parts[0]
                            res_type_with_bracket = '(' + parts[1]
                            return f"{team_name}<br><small style='color: #555;'>{res_type_with_bracket}</small>" # HTML 줄바꿈 및 작은 글씨
                        return val # 분리 실패 시 원본 반환
                    return '' # 빈 셀은 그대로

                def highlight_reserved_cell(val_html): # HTML 포맷된 값을 받아 스타일 적용
                    bg_color = 'background-color: white;'
                    font_weight = 'normal'
                    # 기본 글자색은 HTML 내에서 처리되므로 여기서는 배경색과 굵기만 제어
                    if isinstance(val_html, str) and val_html != '':
                        if '(자동)' in val_html:
                            bg_color = 'background-color: #e0f3ff;'
                            font_weight = 'bold' # 조 이름에만 굵기 적용되도록 HTML 수정 필요
                        elif '(수동)' in val_html:
                            bg_color = 'background-color: #d4edda;'
                            font_weight = 'bold'
                    return f'{bg_color}; font-weight: {font_weight};' # font-weight는 전체 셀에 적용됨

                # 1. 셀 내용 포맷팅 (HTML 태그 포함)
                formatted_df = df_in.applymap(format_cell_value)
                # 2. 포맷팅된 값 기준으로 스타일 적용
                styled_df = styled_df.format(None).pipe(lambda s: s.apply(lambda x: x.map(highlight_reserved_cell), axis=None)) # applymap 대신 map 사용 시도

                return styled_df

            time_slots_v6 = []
            current_time_v6 = datetime.combine(date.today(), time(11, 0))
            end_of_day_v6 = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_v6 < end_of_day_v6:
                time_slots_v6.append(current_time_v6.time())
                current_time_v6 += timedelta(minutes=30)

            timetable_df_v6 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_v6], columns=ALL_ROOMS)
            timetable_df_v6 = timetable_df_v6.fillna('')

            for _, res_v6 in day_reservations.iterrows():
                start_res_dt_v6 = datetime.combine(date.today(), res_v6["시간_시작"])
                end_res_dt_v6 = datetime.combine(date.today(), res_v6["시간_종료"])
                current_slot_dt_v6 = start_res_dt_v6
                res_type_str_v6 = "(자동)" if res_v6['예약유형'] == '자동' else "(수동)"
                cell_display_text = f"{res_v6['조']} {res_type_str_v6}" # 포맷팅은 style 함수에서 처리

                while current_slot_dt_v6 < end_res_dt_v6:
                    slot_str_v6 = current_slot_dt_v6.strftime("%H:%M")
                    if slot_str_v6 in timetable_df_v6.index and res_v6["방"] in timetable_df_v6.columns:
                        if timetable_df_v6.loc[slot_str_v6, res_v6["방"]] == '':
                             timetable_df_v6.loc[slot_str_v6, res_v6["방"]] = cell_display_text # 조이름 (예약유형)
                    current_slot_dt_v6 += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_v6).to_html(escape=False))
            # st.caption("표시형식: 조이름<br>(예약유형)") # 캡션도 HTML 줄바꿈 가능

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
    manual_date_default_v6 = max(timetable_date, date.today())
    manual_date_main_reserve_v6 = st.date_input(
        "예약 날짜",
        value=manual_date_default_v6,
        min_value=date.today(),
        key="manual_date_main_page_reserve_v6"
    )

    cols_main_reserve_v6 = st.columns(2)
    with cols_main_reserve_v6[0]:
        selected_team_main_reserve_v6 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve_v6")
        
        max_start_time_val_v6_dt = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR,0)) - timedelta(minutes=30)
        max_start_time_val_v6 = max_start_time_val_v6_dt.time() if max_start_time_val_v6_dt.time() >= time(MANUAL_RESERVATION_START_HOUR,0) else time(MANUAL_RESERVATION_START_HOUR,0)

        manual_start_time_main_reserve_v6 = st.time_input(
            "시작 시간",
            value=time(MANUAL_RESERVATION_START_HOUR, 0),
            min_value=time(MANUAL_RESERVATION_START_HOUR,0),
            max_value=max_start_time_val_v6,
            step=timedelta(minutes=15),
            key="manual_start_time_main_page_reserve_v6"
        )
    with cols_main_reserve_v6[1]:
        selected_room_main_reserve_v6 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve_v6")
        
        end_time_min_val_v6_dt = datetime.combine(date.today(), manual_start_time_main_reserve_v6) + timedelta(minutes=30)
        end_time_min_val_v6 = end_time_min_val_v6_dt.time()
        end_time_default_val_v6 = max(time(MANUAL_RESERVATION_END_HOUR, 0), end_time_min_val_v6)
        # 만약 17:00 보다 min_val이 크면 min_val을 사용 (예: 시작이 16:45면 종료는 17:15가 최소인데, 최대는 17:00이므로 오류 방지)
        # 이 경우는 max_value에서 걸러지므로, 기본값은 17:00 또는 (시작+30분) 중 큰 값으로 하되, max_value를 넘지 않도록.
        if end_time_default_val_v6 > time(MANUAL_RESERVATION_END_HOUR, 0):
            end_time_default_val_v6 = time(MANUAL_RESERVATION_END_HOUR, 0)
        if end_time_default_val_v6 < end_time_min_val_v6: #시작시간 +30분이 17:00을 넘을 수 없으므로 사실상 이 조건은 드뭄.
             end_time_default_val_v6 = end_time_min_val_v6


        manual_end_time_main_reserve_v6 = st.time_input(
            "종료 시간",
            value=end_time_default_val_v6,
            min_value=end_time_min_val_v6,
            max_value=time(MANUAL_RESERVATION_END_HOUR, 0),
            step=timedelta(minutes=15),
            key="manual_end_time_main_page_reserve_v6"
        )

    time_valid_main_reserve_v6 = True
    if manual_start_time_main_reserve_v6 >= manual_end_time_main_reserve_v6:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v6 = False
    
    # 시작 시간은 13:00 부터 (17:00 - 30분) 인 16:30 까지만 가능해야 함.
    # 종료 시간은 (시작 시간 + 30분) 부터 17:00 까지만 가능해야 함.
    if not (time(MANUAL_RESERVATION_START_HOUR,0) <= manual_start_time_main_reserve_v6 < time(MANUAL_RESERVATION_END_HOUR,0)): # 시작은 17:00 바로 전까지
        st.error(f"시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 와 {MANUAL_RESERVATION_END_HOUR}:00 사이여야 합니다."); time_valid_main_reserve_v6 = False
    
    if not (datetime.combine(date.min, manual_start_time_main_reserve_v6) < datetime.combine(date.min, manual_end_time_main_reserve_v6) <= datetime.combine(date.min, time(MANUAL_RESERVATION_END_HOUR,0))):
        st.error(f"종료 시간은 시작 시간 이후부터 {MANUAL_RESERVATION_END_HOUR}:00 사이여야 합니다."); time_valid_main_reserve_v6 = False


    min_duration_main_reserve_v6 = timedelta(minutes=30)
    current_duration_v6 = datetime.combine(date.min, manual_end_time_main_reserve_v6) - datetime.combine(date.min, manual_start_time_main_reserve_v6)
    if current_duration_v6 < min_duration_main_reserve_v6:
        st.error(f"최소 예약 시간은 {min_duration_main_reserve_v6.seconds // 60}분입니다."); time_valid_main_reserve_v6 = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v6", type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v6):
        if time_valid_main_reserve_v6:
            current_reservations_main_reserve_v6 = load_reservations()
            is_overlap_main_reserve_v6 = False
            room_res_check_v6 = current_reservations_main_reserve_v6[
                (current_reservations_main_reserve_v6["날짜"] == manual_date_main_reserve_v6) &
                (current_reservations_main_reserve_v6["방"] == selected_room_main_reserve_v6)
            ]
            for _, ex_res_check_v6 in room_res_check_v6.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v6, manual_end_time_main_reserve_v6, ex_res_check_v6["시간_시작"], ex_res_check_v6["시간_종료"]):
                    st.error(f"⚠️ {selected_room_main_reserve_v6}은(는) 해당 시간에 일부 또는 전체가 이미 예약되어 있습니다."); is_overlap_main_reserve_v6=True; break
            if is_overlap_main_reserve_v6: st.stop()

            team_res_check_v6 = current_reservations_main_reserve_v6[
                (current_reservations_main_reserve_v6["날짜"] == manual_date_main_reserve_v6) &
                (current_reservations_main_reserve_v6["조"] == selected_team_main_reserve_v6)
            ]
            for _, ex_res_check_v6 in team_res_check_v6.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v6, manual_end_time_main_reserve_v6, ex_res_check_v6["시간_시작"], ex_res_check_v6["시간_종료"]):
                    st.error(f"⚠️ {selected_team_main_reserve_v6}은(는) 해당 시간에 이미 다른 방을 예약했습니다."); is_overlap_main_reserve_v6=True; break
            if is_overlap_main_reserve_v6: st.stop()

            new_item_main_reserve_v6 = {
                "날짜": manual_date_main_reserve_v6, "시간_시작": manual_start_time_main_reserve_v6, "시간_종료": manual_end_time_main_reserve_v6,
                "조": selected_team_main_reserve_v6, "방": selected_room_main_reserve_v6, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_main_reserve_v6 = pd.concat([current_reservations_main_reserve_v6, pd.DataFrame([new_item_main_reserve_v6])], ignore_index=True)
            save_reservations(updated_df_main_reserve_v6)
            st.success(f"🎉 예약 완료!")
            st.rerun()

    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_display_cancel_v6 = reservations_df[
        (reservations_df["날짜"] == manual_date_main_reserve_v6) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_cancel_v6.empty:
        my_manual_res_display_cancel_v6 = my_manual_res_display_cancel_v6.sort_values(by=["시간_시작", "조"])
        for _, row_main_cancel_v6 in my_manual_res_display_cancel_v6.iterrows():
            res_id_main_cancel_v6 = row_main_cancel_v6["예약ID"]
            time_str_main_cancel_v6 = f"{row_main_cancel_v6['시간_시작'].strftime('%H:%M')} - {row_main_cancel_v6['시간_종료'].strftime('%H:%M')}"
            item_cols_main_cancel_v6 = st.columns([3,1])
            with item_cols_main_cancel_v6[0]: st.markdown(f"**{time_str_main_cancel_v6}** / **{row_main_cancel_v6['조']}** / `{row_main_cancel_v6['방']}`")
            with item_cols_main_cancel_v6[1]:
                if st.button("취소", key=f"cancel_{res_id_main_cancel_v6}_main_page_reserve_v6", use_container_width=True):
                    current_on_cancel_main_reserve_v6 = load_reservations()
                    updated_on_cancel_main_reserve_v6 = current_on_cancel_main_reserve_v6[current_on_cancel_main_reserve_v6["예약ID"] != res_id_main_cancel_v6]
                    save_reservations(updated_on_cancel_main_reserve_v6)
                    st.success(f"🗑️ 예약 취소됨")
                    st.rerun()
    else:
        st.info(f"{manual_date_main_reserve_v6.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


elif st.session_state.current_page == "🔄 자동 배정 (관리자)":
    st.header("🔄 자동 배정 ⚠️ 관리자 전용")
    st.warning("이 기능은 관리자만 사용해주세요. 잘못된 조작은 전체 예약에 영향을 줄 수 있습니다.")
    if test_mode: st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else: st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT_STR}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** (이하 설명 동일)
        """)

    auto_assign_date_admin_page_v6 = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_page_final_v6")
    weekday_admin_page_v6 = auto_assign_date_admin_page_v6.weekday()
    can_auto_assign_admin_page_v6 = test_mode or (weekday_admin_page_v6 in [2, 6])

    if not can_auto_assign_admin_page_v6:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page_final_v6", type="primary"):
        if can_auto_assign_admin_page_v6:
            current_reservations_admin_page_v6 = load_reservations()
            existing_auto_admin_page_v6 = current_reservations_admin_page_v6[
                (current_reservations_admin_page_v6["날짜"] == auto_assign_date_admin_page_v6) &
                (current_reservations_admin_page_v6["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_admin_page_v6["예약유형"] == "자동")
            ]
            if not existing_auto_admin_page_v6.empty:
                st.warning(f"이미 {auto_assign_date_admin_page_v6.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_admin_page_v6 = []
                assigned_info_admin_page_v6 = []
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_admin_page_v6.append({
                        "날짜": auto_assign_date_admin_page_v6, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page_v6.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                next_idx_admin_page_v6 = load_rotation_state()
                num_rotation_teams_admin_page_v6 = len(ROTATION_TEAMS)
                num_rotation_rooms_admin_page_v6 = len(ROTATION_ROOMS)
                available_rooms_admin_page_v6 = min(num_rotation_teams_admin_page_v6, num_rotation_rooms_admin_page_v6)

                for i in range(available_rooms_admin_page_v6):
                    if num_rotation_teams_admin_page_v6 == 0: break
                    team_idx_list_admin_page_v6 = (next_idx_admin_page_v6 + i) % num_rotation_teams_admin_page_v6
                    team_assign_admin_page_v6 = ROTATION_TEAMS[team_idx_list_admin_page_v6]
                    room_assign_admin_page_v6 = ROTATION_ROOMS[i]
                    new_auto_list_admin_page_v6.append({
                        "날짜": auto_assign_date_admin_page_v6, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign_admin_page_v6, "방": room_assign_admin_page_v6, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page_v6.append(f"🔄 **{team_assign_admin_page_v6}** → **{room_assign_admin_page_v6}** (로테이션)")

                if new_auto_list_admin_page_v6:
                    new_df_admin_page_v6 = pd.DataFrame(new_auto_list_admin_page_v6)
                    updated_df_admin_page_v6 = pd.concat([current_reservations_admin_page_v6, new_df_admin_page_v6], ignore_index=True)
                    save_reservations(updated_df_admin_page_v6)
                    new_next_idx_admin_page_v6 = (next_idx_admin_page_v6 + available_rooms_admin_page_v6) % num_rotation_teams_admin_page_v6 if num_rotation_teams_admin_page_v6 > 0 else 0
                    save_rotation_state(new_next_idx_admin_page_v6)
                    st.success(f"🎉 {auto_assign_date_admin_page_v6.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_admin_page_v6: st.markdown(f"- {info}")
                    if num_rotation_teams_admin_page_v6 > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin_page_v6]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin_page_v6 = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_page_v6) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_page_v6.empty:
        st.dataframe(auto_today_display_admin_page_v6[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin_page_v6.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")
