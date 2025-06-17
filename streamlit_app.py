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
    if st.sidebar.button("🏠 시간표 및 수동 예약으로 돌아가기", key="return_to_main_btn_v7"):
        st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"
        st.rerun()
    st.sidebar.markdown("---")

st.sidebar.subheader("👑 관리자")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제", key="test_mode_checkbox_admin_v7")

if st.sidebar.button("⚙️ 자동 배정 설정 페이지로 이동", key="admin_auto_assign_nav_btn_admin_v7"):
    st.session_state.current_page = "🔄 자동 배정 (관리자)"
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 기타 설정")
if st.sidebar.button("🔄 데이터 캐시 새로고침", key="cache_refresh_btn_admin_v7"):
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
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_main_page_v7")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd', 'text-align': 'center',
                    'min-width': '75px', # 셀 너비 약간 증가
                    'height': '45px',  # 셀 높이 증가 (두 줄 표시 위해)
                    'font-size': '0.8em', # 글자 크기는 유지 또는 약간 조절
                    'line-height': '1.3' # 줄 간격 조절
                }).set_table_styles([
                    {'selector': 'th', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '5px'), ('color', '#333'),
                        ('vertical-align', 'middle') # 헤더 텍스트 수직 중앙 정렬
                    ]},
                    {'selector': 'th.row_heading', 'props': [
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '5px'), ('color', '#333'),
                        ('vertical-align', 'middle')
                    ]},
                    {'selector': 'td', 'props': [
                        ('padding', '5px'), ('vertical-align', 'top') # 셀 내용 위쪽 정렬 (줄바꿈 시 보기 좋게)
                    ]}
                ])
                def highlight_reserved_cell(val):
                    bg_color = 'background-color: white;'
                    font_weight = 'normal'
                    text_color = 'color: #212529;'
                    if isinstance(val, str) and val != '': # val은 이제 HTML 포함 가능
                        if '(자동)' in val:
                            bg_color = 'background-color: #e0f3ff;'
                            text_color = 'color: #004085;'
                        elif '(수동)' in val:
                            bg_color = 'background-color: #d4edda;'
                            text_color = 'color: #155724;'
                        # font_weight는 HTML 태그 내에서 처리
                    return f'{bg_color} {text_color} font-weight: {font_weight};' # 스타일만 반환
                try:
                    styled_df = styled_df.set_table_attributes('style="border-collapse: collapse;"') # 테두리 겹침 방지
                    styled_df = styled_df.applymap(highlight_reserved_cell) # 스타일 함수 적용
                except AttributeError:
                    styled_df = styled_df.apply(lambda col: col.map(highlight_reserved_cell))
                return styled_df

            time_slots_main_v7 = []
            current_time_main_v7 = datetime.combine(date.today(), time(11, 0))
            end_of_day_main_v7 = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_main_v7 < end_of_day_main_v7:
                time_slots_main_v7.append(current_time_main_v7.time())
                current_time_main_v7 += timedelta(minutes=30)

            timetable_df_main_v7 = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_main_v7], columns=ALL_ROOMS)
            timetable_df_main_v7 = timetable_df_main_v7.fillna('')

            for _, res_main_v7 in day_reservations.iterrows():
                start_res_dt_main_v7 = datetime.combine(date.today(), res_main_v7["시간_시작"])
                end_res_dt_main_v7 = datetime.combine(date.today(), res_main_v7["시간_종료"])
                current_slot_dt_main_v7 = start_res_dt_main_v7
                res_type_str_v7 = "(자동)" if res_main_v7['예약유형'] == '자동' else "(수동)"
                # HTML <br> 태그를 사용하여 줄바꿈
                cell_content = f"<b>{res_main_v7['조']}</b><br><small>{res_type_str_v7}</small>"

                while current_slot_dt_main_v7 < end_res_dt_main_v7:
                    slot_str_main_v7 = current_slot_dt_main_v7.strftime("%H:%M")
                    if slot_str_main_v7 in timetable_df_main_v7.index and res_main_v7["방"] in timetable_df_main_v7.columns:
                        if timetable_df_main_v7.loc[slot_str_main_v7, res_main_v7["방"]] == '':
                             timetable_df_main_v7.loc[slot_str_main_v7, res_main_v7["방"]] = cell_content
                        # else: # 이미 내용이 있으면 중첩 처리 (예: 기존 내용 + <hr> + 새 내용) - 복잡도 증가로 생략
                        #    timetable_df_main_v7.loc[slot_str_main_v7, res_main_v7["방"]] += f"<hr style='margin:2px 0; border-top: 1px dotted #ccc;'>{cell_content}"
                    current_slot_dt_main_v7 += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_main_v7).to_html(escape=False)) # escape=False 필수
            # st.caption("표시형식: 조이름 (예약유형)") # 캡션은 셀 내용에 포함됨
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
    manual_date_default_v7 = max(timetable_date, date.today())
    manual_date_main_reserve_v7 = st.date_input(
        "예약 날짜",
        value=manual_date_default_v7,
        min_value=date.today(),
        key="manual_date_main_page_reserve_v7"
    )

    cols_main_reserve_v7 = st.columns(2)
    with cols_main_reserve_v7[0]:
        selected_team_main_reserve_v7 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve_v7")
        _today_v7 = date.today()
        min_start_time_val_v7 = time(MANUAL_RESERVATION_START_HOUR, 0)
        max_start_time_dt_v7 = datetime.combine(_today_v7, time(MANUAL_RESERVATION_END_HOUR, 0)) - timedelta(minutes=30)
        max_start_time_val_v7 = max_start_time_dt_v7.time()
        start_time_default_val_v7 = min_start_time_val_v7

        manual_start_time_main_reserve_v7 = st.time_input(
            "시작 시간",
            value=start_time_default_val_v7,
            min_value=min_start_time_val_v7,
            max_value=max_start_time_val_v7,
            step=timedelta(minutes=15),
            key="manual_start_time_main_page_reserve_v7"
        )
    with cols_main_reserve_v7[1]:
        selected_room_main_reserve_v7 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve_v7")
        min_end_time_dt_v7 = datetime.combine(_today_v7, manual_start_time_main_reserve_v7) + timedelta(minutes=30)
        min_end_time_val_v7 = min_end_time_dt_v7.time()
        max_end_time_val_v7 = time(MANUAL_RESERVATION_END_HOUR, 0)
        end_time_default_val_v7 = max_end_time_val_v7
        if end_time_default_val_v7 < min_end_time_val_v7: end_time_default_val_v7 = min_end_time_val_v7
        if end_time_default_val_v7 > max_end_time_val_v7: end_time_default_val_v7 = max_end_time_val_v7

        manual_end_time_main_reserve_v7 = st.time_input(
            "종료 시간",
            value=end_time_default_val_v7,
            min_value=min_end_time_val_v7,
            max_value=max_end_time_val_v7,
            step=timedelta(minutes=15),
            key="manual_end_time_main_page_reserve_v7"
        )

    time_valid_main_reserve_v7 = True
    if manual_start_time_main_reserve_v7 >= manual_end_time_main_reserve_v7:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve_v7 = False
    if not (min_start_time_val_v7 <= manual_start_time_main_reserve_v7 <= max_start_time_val_v7): # 시작 시간 범위 재확인
        st.error(f"시작 시간은 {min_start_time_val_v7.strftime('%H:%M')}와 {max_start_time_val_v7.strftime('%H:%M')} 사이여야 합니다."); time_valid_main_reserve_v7 = False
    min_duration_main_reserve_v7 = timedelta(minutes=30)
    current_duration_v7 = datetime.combine(date.min, manual_end_time_main_reserve_v7) - datetime.combine(date.min, manual_start_time_main_reserve_v7)
    if current_duration_v7 < min_duration_main_reserve_v7:
        st.error(f"최소 예약 시간은 {min_duration_main_reserve_v7.seconds // 60}분입니다."); time_valid_main_reserve_v7 = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve_v7", type="primary", use_container_width=True, disabled=not time_valid_main_reserve_v7):
        if time_valid_main_reserve_v7:
            current_reservations_main_reserve_v7 = load_reservations()
            is_overlap_main_reserve_v7 = False
            room_res_check_v7 = current_reservations_main_reserve_v7[
                (current_reservations_main_reserve_v7["날짜"] == manual_date_main_reserve_v7) &
                (current_reservations_main_reserve_v7["방"] == selected_room_main_reserve_v7)
            ]
            for _, ex_res_check_v7 in room_res_check_v7.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v7, manual_end_time_main_reserve_v7, ex_res_check_v7["시간_시작"], ex_res_check_v7["시간_종료"]):
                    st.error(f"⚠️ {selected_room_main_reserve_v7}은(는) 해당 시간에 일부 또는 전체가 이미 예약되어 있습니다."); is_overlap_main_reserve_v7=True; break
            if is_overlap_main_reserve_v7: st.stop()

            team_res_check_v7 = current_reservations_main_reserve_v7[
                (current_reservations_main_reserve_v7["날짜"] == manual_date_main_reserve_v7) &
                (current_reservations_main_reserve_v7["조"] == selected_team_main_reserve_v7)
            ]
            for _, ex_res_check_v7 in team_res_check_v7.iterrows():
                if check_time_overlap(manual_start_time_main_reserve_v7, manual_end_time_main_reserve_v7, ex_res_check_v7["시간_시작"], ex_res_check_v7["시간_종료"]):
                    st.error(f"⚠️ {selected_team_main_reserve_v7}은(는) 해당 시간에 이미 다른 방을 예약했습니다."); is_overlap_main_reserve_v7=True; break
            if is_overlap_main_reserve_v7: st.stop()

            new_item_main_reserve_v7 = {
                "날짜": manual_date_main_reserve_v7, "시간_시작": manual_start_time_main_reserve_v7, "시간_종료": manual_end_time_main_reserve_v7,
                "조": selected_team_main_reserve_v7, "방": selected_room_main_reserve_v7, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_main_reserve_v7 = pd.concat([current_reservations_main_reserve_v7, pd.DataFrame([new_item_main_reserve_v7])], ignore_index=True)
            save_reservations(updated_df_main_reserve_v7)
            st.success(f"🎉 예약 완료!")
            st.rerun()

    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_display_cancel_v7 = reservations_df[
        (reservations_df["날짜"] == manual_date_main_reserve_v7) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_cancel_v7.empty:
        my_manual_res_display_cancel_v7 = my_manual_res_display_cancel_v7.sort_values(by=["시간_시작", "조"])
        for _, row_main_cancel_v7 in my_manual_res_display_cancel_v7.iterrows():
            res_id_main_cancel_v7 = row_main_cancel_v7["예약ID"]
            time_str_main_cancel_v7 = f"{row_main_cancel_v7['시간_시작'].strftime('%H:%M')} - {row_main_cancel_v7['시간_종료'].strftime('%H:%M')}"
            item_cols_main_cancel_v7 = st.columns([3,1])
            with item_cols_main_cancel_v7[0]: st.markdown(f"**{time_str_main_cancel_v7}** / **{row_main_cancel_v7['조']}** / `{row_main_cancel_v7['방']}`")
            with item_cols_
