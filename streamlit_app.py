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
st.set_page_config(page_title="조모임 예약", layout="centered", initial_sidebar_state="expanded")

# 페이지 상태 유지를 위한 세션 상태 초기화
if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"

# --- 사이드바 ---
st.sidebar.title("🚀 조모임 스터디룸")
st.sidebar.markdown("---") # 앱 제목 아래 구분선

st.sidebar.subheader("👑 관리자") # 관리자 섹션 제목을 subheader로 변경
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제", key="test_mode_checkbox")

if st.sidebar.button("🔄 자동 배정 페이지로 이동", key="admin_auto_assign_nav_btn"):
    st.session_state.current_page = "🔄 자동 배정 (관리자)"
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 기타 설정") # 기타 설정 섹션
if st.sidebar.button("🔄 데이터 캐시 새로고침", key="cache_refresh_btn"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다.")
    st.rerun()

# 메인 메뉴 라디오 버튼 제거, 기본 페이지는 "예약 시간표 및 수동 예약"
# 사용자가 관리자 메뉴의 버튼을 누르면 current_page가 변경됨
# 만약 current_page가 관리자 페이지가 아니면, 기본 페이지로 간주
if st.session_state.current_page not in ["🔄 자동 배정 (관리자)"]:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"


# --- 메인 화면 콘텐츠 ---
if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df = load_reservations()

# 선택된 페이지에 따라 콘텐츠 표시
if st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약":
    # 이 페이지가 기본 페이지이므로, 별도의 헤더 대신 바로 콘텐츠 시작 가능
    # st.header("🗓️ 예약 시간표 및 수동 예약") # 필요시 헤더 추가

    # --- 예약 시간표 섹션 ---
    st.subheader("🗓️ 예약 시간표") # 섹션 제목
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_main_page")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd',
                    'text-align': 'center',
                    'min-width': '65px',
                    'height': '35px',
                    'font-size': '0.8em',
                }).set_table_styles([
                    {'selector': 'th', 'props': [ # 테이블 헤더 (방 이름)
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '4px'), ('color', '#333') # 헤더 글자색
                    ]},
                    {'selector': 'th.row_heading', 'props': [ # 인덱스 헤더 (시간)
                        ('background-color', '#f0f0f0'), ('border', '1px solid #ccc'),
                        ('font-weight', 'bold'), ('padding', '4px'), ('color', '#333')
                    ]},
                    {'selector': 'td', 'props': [('padding', '4px')]}
                ])

                def highlight_reserved_cell(val):
                    bg_color = 'background-color: white;'
                    font_weight = 'normal'
                    text_color = 'color: #333;' # 빈 셀 기본 글자색 (검은색 계열)
                    if isinstance(val, str) and val != '':
                        if '(A)' in val:
                            bg_color = 'background-color: #d1ecf1;'
                            text_color = 'color: #0c5460;' # 어두운 하늘색 계열
                        elif '(S)' in val:
                            bg_color = 'background-color: #d4edda;'
                            text_color = 'color: #155724;' # 어두운 녹색 계열
                        font_weight = 'bold'
                    return f'{bg_color} {text_color} font-weight: {font_weight};'

                # Pandas 1.4.0+ 에서는 Styler.applymap, 이전에는 Styler.apply(func, axis=None)
                try:
                    styled_df = styled_df.applymap(highlight_reserved_cell)
                except AttributeError: # 이전 Pandas 버전 호환
                    styled_df = styled_df.apply(lambda col: col.map(highlight_reserved_cell))

                return styled_df

            time_slots_main = []
            current_time_main = datetime.combine(date.today(), time(11, 0))
            end_of_day_main = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_main < end_of_day_main:
                time_slots_main.append(current_time_main.time())
                current_time_main += timedelta(minutes=30)

            timetable_df_main = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_main], columns=ALL_ROOMS)
            timetable_df_main = timetable_df_main.fillna('')

            for _, res_main in day_reservations.iterrows():
                start_res_dt_main = datetime.combine(date.today(), res_main["시간_시작"])
                end_res_dt_main = datetime.combine(date.today(), res_main["시간_종료"])
                current_slot_dt_main = start_res_dt_main
                while current_slot_dt_main < end_res_dt_main:
                    slot_str_main = current_slot_dt_main.strftime("%H:%M")
                    if slot_str_main in timetable_df_main.index and res_main["방"] in timetable_df_main.columns:
                        if timetable_df_main.loc[slot_str_main, res_main["방"]] == '':
                             timetable_df_main.loc[slot_str_main, res_main["방"]] = f"{res_main['조']} ({res_main['예약유형'][0]})"
                    current_slot_dt_main += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_main).to_html(escape=False))
            st.caption("표시형식: 조이름 (A:자동, S:수동)")
        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    # --- 수동 예약 섹션 ---
    st.markdown("---")
    st.subheader("✍️ 수동 예약 등록 및 취소") # 섹션 제목
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지 자유롭게 시간 설정.
        - 최소 예약 시간은 30분, 예약 단위는 15분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.markdown("##### 📝 새 예약 등록") # 더 작은 제목
    manual_date_main_reserve = st.date_input("예약 날짜", value=timetable_date, min_value=date.today(), key="manual_date_main_page_reserve")

    cols_main_reserve = st.columns(2)
    with cols_main_reserve[0]:
        selected_team_main_reserve = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_page_reserve")
        manual_start_time_main_reserve = st.time_input(
            "시작 시간", value=time(MANUAL_RESERVATION_START_HOUR, 0),
            step=timedelta(minutes=15), key="manual_start_time_main_page_reserve"
        )
    with cols_main_reserve[1]:
        selected_room_main_reserve = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_page_reserve")
        manual_end_time_main_reserve = st.time_input(
            "종료 시간", value=time(MANUAL_RESERVATION_START_HOUR + 1, 0),
            step=timedelta(minutes=15), key="manual_end_time_main_page_reserve"
        )

    time_valid_main_reserve = True
    # (시간 유효성 검사 로직 동일)
    if manual_start_time_main_reserve >= manual_end_time_main_reserve:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_main_reserve = False
    elif manual_start_time_main_reserve < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 이후여야 합니다."); time_valid_main_reserve = False
    elif manual_end_time_main_reserve > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"종료 시간은 {MANUAL_RESERVATION_END_HOUR}:00 이전이어야 합니다."); time_valid_main_reserve = False
    min_duration_main_reserve = timedelta(minutes=30)
    if datetime.combine(date.min, manual_end_time_main_reserve) - datetime.combine(date.min, manual_start_time_main_reserve) < min_duration_main_reserve:
        st.error(f"최소 예약 시간은 {min_duration_main_reserve.seconds // 60}분입니다."); time_valid_main_reserve = False


    if st.button("✅ 예약하기", key="manual_reserve_btn_main_page_reserve", type="primary", use_container_width=True, disabled=not time_valid_main_reserve):
        if time_valid_main_reserve:
            current_reservations_main_reserve = load_reservations()
            is_overlap_main_reserve = False
            # (중복 체크 로직 동일)
            room_res_check = current_reservations_main_reserve[
                (current_reservations_main_reserve["날짜"] == manual_date_main_reserve) &
                (current_reservations_main_reserve["방"] == selected_room_main_reserve)
            ]
            for _, ex_res_check in room_res_check.iterrows():
                if check_time_overlap(manual_start_time_main_reserve, manual_end_time_main_reserve, ex_res_check["시간_시작"], ex_res_check["시간_종료"]):
                    st.error(f"⚠️ {selected_room_main_reserve} 시간 중복"); is_overlap_main_reserve=True; break
            if is_overlap_main_reserve: st.stop()

            team_res_check = current_reservations_main_reserve[
                (current_reservations_main_reserve["날짜"] == manual_date_main_reserve) &
                (current_reservations_main_reserve["조"] == selected_team_main_reserve)
            ]
            for _, ex_res_check in team_res_check.iterrows():
                if check_time_overlap(manual_start_time_main_reserve, manual_end_time_main_reserve, ex_res_check["시간_시작"], ex_res_check["시간_종료"]):
                    st.error(f"⚠️ {selected_team_main_reserve} 시간 중복"); is_overlap_main_reserve=True; break
            if is_overlap_main_reserve: st.stop()


            new_item_main_reserve = {
                "날짜": manual_date_main_reserve, "시간_시작": manual_start_time_main_reserve, "시간_종료": manual_end_time_main_reserve,
                "조": selected_team_main_reserve, "방": selected_room_main_reserve, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_main_reserve = pd.concat([current_reservations_main_reserve, pd.DataFrame([new_item_main_reserve])], ignore_index=True)
            save_reservations(updated_df_main_reserve)
            st.success(f"🎉 예약 완료!")
            st.rerun()

    st.markdown("##### 🚫 나의 수동 예약 취소") # 더 작은 제목
    # 수동 예약 취소 날짜는 위 예약 등록 날짜와 연동
    my_manual_res_display_cancel = reservations_df[
        (reservations_df["날짜"] == manual_date_main_reserve) & # 예약 등록에 사용된 날짜 사용
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_cancel.empty:
        my_manual_res_display_cancel = my_manual_res_display_cancel.sort_values(by=["시간_시작", "조"])
        for _, row_main_cancel in my_manual_res_display_cancel.iterrows():
            res_id_main_cancel = row_main_cancel["예약ID"]
            time_str_main_cancel = f"{row_main_cancel['시간_시작'].strftime('%H:%M')} - {row_main_cancel['시간_종료'].strftime('%H:%M')}"
            item_cols_main_cancel = st.columns([3,1])
            with item_cols_main_cancel[0]: st.markdown(f"**{time_str_main_cancel}** / **{row_main_cancel['조']}** / `{row_main_cancel['방']}`")
            with item_cols_main_cancel[1]:
                if st.button("취소", key=f"cancel_{res_id_main_cancel}_main_page_reserve", use_container_width=True):
                    current_on_cancel_main_reserve = load_reservations()
                    updated_on_cancel_main_reserve = current_on_cancel_main_reserve[current_on_cancel_main_reserve["예약ID"] != res_id_main_cancel]
                    save_reservations(updated_on_cancel_main_reserve)
                    st.success(f"🗑️ 예약 취소됨")
                    st.rerun()
    else:
        st.info(f"{manual_date_main_reserve.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


elif st.session_state.current_page == "🔄 자동 배정 (관리자)":
    st.header("🔄 자동 배정 ⚠️ 관리자 전용")
    st.warning("이 기능은 관리자만 사용해주세요. 잘못된 조작은 전체 예약에 영향을 줄 수 있습니다.")
    # (자동 배정 페이지 내용, 이전과 동일)
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

    auto_assign_date_admin_page = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_page_final")
    weekday_admin_page = auto_assign_date_admin_page.weekday()
    can_auto_assign_admin_page = test_mode or (weekday_admin_page in [2, 6])

    if not can_auto_assign_admin_page:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_page_final", type="primary"):
        if can_auto_assign_admin_page:
            current_reservations_admin_page = load_reservations()
            existing_auto_admin_page = current_reservations_admin_page[
                (current_reservations_admin_page["날짜"] == auto_assign_date_admin_page) &
                (current_reservations_admin_page["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_admin_page["예약유형"] == "자동")
            ]
            if not existing_auto_admin_page.empty:
                st.warning(f"이미 {auto_assign_date_admin_page.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_admin_page = []
                assigned_info_admin_page = []
                # 시니어조
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_admin_page.append({
                        "날짜": auto_assign_date_admin_page, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션
                next_idx_admin_page = load_rotation_state()
                num_rotation_teams_admin_page = len(ROTATION_TEAMS)
                num_rotation_rooms_admin_page = len(ROTATION_ROOMS)
                available_rooms_admin_page = min(num_rotation_teams_admin_page, num_rotation_rooms_admin_page)

                for i in range(available_rooms_admin_page):
                    if num_rotation_teams_admin_page == 0: break
                    team_idx_list_admin_page = (next_idx_admin_page + i) % num_rotation_teams_admin_page
                    team_assign_admin_page = ROTATION_TEAMS[team_idx_list_admin_page]
                    room_assign_admin_page = ROTATION_ROOMS[i]
                    new_auto_list_admin_page.append({
                        "날짜": auto_assign_date_admin_page, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign_admin_page, "방": room_assign_admin_page, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_page.append(f"🔄 **{team_assign_admin_page}** → **{room_assign_admin_page}** (로테이션)")

                if new_auto_list_admin_page:
                    new_df_admin_page = pd.DataFrame(new_auto_list_admin_page)
                    updated_df_admin_page = pd.concat([current_reservations_admin_page, new_df_admin_page], ignore_index=True)
                    save_reservations(updated_df_admin_page)
                    new_next_idx_admin_page = (next_idx_admin_page + available_rooms_admin_page) % num_rotation_teams_admin_page if num_rotation_teams_admin_page > 0 else 0
                    save_rotation_state(new_next_idx_admin_page)
                    st.success(f"🎉 {auto_assign_date_admin_page.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_admin_page: st.markdown(f"- {info}")
                    if num_rotation_teams_admin_page > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin_page]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin_page = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_page) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_page.empty:
        st.dataframe(auto_today_display_admin_page[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin_page.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")
