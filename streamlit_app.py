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
# ... (생략 - 이전 코드와 동일) ...
@st.cache_resource
def init_gspread_client():
    # ... (내용 동일)
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
    # ... (내용 동일)
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
# ... (생략 - 이전 코드와 동일) ...
@st.cache_data(ttl=300)
def get_all_records_as_df_cached(_ws, expected_headers, _cache_key_prefix):
    # ... (내용 동일)
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
            df = df.dropna(subset=['날짜', '시간_시작', '시간_종료']) # 시간 변환 실패한 행 제거
        return df
    except Exception as e:
        st.warning(f"'{_ws.title}' 시트 로드 중 오류 (캐시 사용 시도): {e}")
        return pd.DataFrame(columns=expected_headers)


def update_worksheet_from_df(_ws, df, headers):
    # ... (내용 동일)
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

@st.cache_data(ttl=300)
def load_rotation_state_cached(_rotation_ws, _cache_key_prefix):
    # ... (내용 동일)
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
    # ... (내용 동일)
    if not GSHEET_AVAILABLE or rotation_ws is None: return
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    update_worksheet_from_df(rotation_ws, df_state, ROTATION_SHEET_HEADER)

def check_time_overlap(new_start, new_end, existing_start, existing_end):
    # ... (내용 동일)
    return max(new_start, existing_start) < min(new_end, existing_end)

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약", layout="centered", initial_sidebar_state="expanded") # 사이드바 기본 열림

# 페이지 상태 유지를 위한 세션 상태 초기화
if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표" # 기본 페이지

# --- 사이드바 ---
st.sidebar.title("🚀 조모임 스터디룸")

# 페이지 네비게이션
page_options = ["🗓️ 예약 시간표", "✍️ 수동 예약", "🔄 자동 배정 ⚠️ 관리자 전용"]
# 현재 선택된 페이지를 st.session_state에서 가져오고, 없으면 기본값 사용
# st.radio의 index를 찾기 위해 현재 페이지 이름이 page_options에 있는지 확인
try:
    current_page_index = page_options.index(st.session_state.current_page)
except ValueError:
    current_page_index = 0 # 기본값 (예약 시간표)

st.session_state.current_page = st.sidebar.radio(
    "메뉴 선택",
    page_options,
    index=current_page_index, # 이전에 선택된 페이지를 기본값으로 설정
    key="page_navigation_radio" # 고유 키 부여
)

st.sidebar.markdown("---")
st.sidebar.title("⚙️ 설정")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제")
if st.sidebar.button("🔄 데이터 캐시 새로고침"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다.")
    st.rerun() # 페이지 새로고침으로 캐시 적용 확인

st.sidebar.markdown("---")
st.sidebar.title("🛠️ 관리")
if st.sidebar.button("⚠️ 모든 예약 기록 초기화", key="reset_all_data_sidebar_final"):
    if st.sidebar.checkbox("정말로 모든 기록을 삭제하고 로테이션 상태를 초기화하시겠습니까?", key="confirm_delete_sidebar_final"):
        try:
            if GSHEET_AVAILABLE:
                empty_reservations_df = pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
                update_worksheet_from_df(reservations_ws, empty_reservations_df, RESERVATION_SHEET_HEADERS)
                save_rotation_state(0)
                st.sidebar.success("모든 예약 기록 및 로테이션 상태가 초기화되었습니다.")
                st.rerun()
            else: st.sidebar.error("Google Sheets에 연결되지 않아 초기화할 수 없습니다.")
        except Exception as e: st.sidebar.error(f"초기화 중 오류 발생: {e}")

# --- 메인 화면 콘텐츠 ---
if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df = load_reservations() # 전역적으로 사용할 예약 데이터

# 선택된 페이지에 따라 콘텐츠 표시
if st.session_state.current_page == "🔄 자동 배정 ⚠️ 관리자 전용":
    st.header("🔄 자동 배정 ⚠️ 관리자 전용")
    st.warning("이 기능은 관리자만 사용해주세요. 잘못된 조작은 전체 예약에 영향을 줄 수 있습니다.")
    # (자동 배정 페이지 내용, 이전 코드와 유사하게 구성, reservations_df 사용)
    # ... (생략 - 이전 자동 배정 탭 로직과 동일하게)
    if test_mode: st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else: st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT_STR}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:** (이하 설명 동일)
        """)

    auto_assign_date_auto = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_auto_page")
    weekday_auto = auto_assign_date_auto.weekday()
    can_auto_assign_auto = test_mode or (weekday_auto in [2, 6])

    if not can_auto_assign_auto:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_auto_page", type="primary"):
        if can_auto_assign_auto:
            current_reservations_auto = load_reservations() # 최신 데이터
            existing_auto_page = current_reservations_auto[
                (current_reservations_auto["날짜"] == auto_assign_date_auto) &
                (current_reservations_auto["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_auto["예약유형"] == "자동")
            ]

            if not existing_auto_page.empty:
                st.warning(f"이미 {auto_assign_date_auto.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_auto = []
                assigned_info_auto = []
                # 시니어조
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_auto.append({
                        "날짜": auto_assign_date_auto, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_auto.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션
                next_idx_auto = load_rotation_state()
                num_rotation_teams_auto = len(ROTATION_TEAMS)
                num_rotation_rooms_auto = len(ROTATION_ROOMS)
                available_rooms_auto = min(num_rotation_teams_auto, num_rotation_rooms_auto)

                for i in range(available_rooms_auto):
                    if num_rotation_teams_auto == 0: break
                    team_idx_list_auto = (next_idx_auto + i) % num_rotation_teams_auto
                    team_assign_auto = ROTATION_TEAMS[team_idx_list_auto]
                    room_assign_auto = ROTATION_ROOMS[i]
                    new_auto_list_auto.append({
                        "날짜": auto_assign_date_auto, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign_auto, "방": room_assign_auto, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_auto.append(f"🔄 **{team_assign_auto}** → **{room_assign_auto}** (로테이션)")

                if new_auto_list_auto:
                    new_df_auto = pd.DataFrame(new_auto_list_auto)
                    updated_df_auto = pd.concat([current_reservations_auto, new_df_auto], ignore_index=True)
                    save_reservations(updated_df_auto)
                    new_next_idx_auto = (next_idx_auto + available_rooms_auto) % num_rotation_teams_auto if num_rotation_teams_auto > 0 else 0
                    save_rotation_state(new_next_idx_auto)
                    st.success(f"🎉 {auto_assign_date_auto.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_auto: st.markdown(f"- {info}")
                    if num_rotation_teams_auto > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_auto]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_auto = reservations_df[ # 전역 reservations_df 사용
        (reservations_df["날짜"] == auto_assign_date_auto) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_auto.empty:
        st.dataframe(auto_today_display_auto[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_auto.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")


elif st.session_state.current_page == "✍️ 수동 예약":
    st.header("✍️ 수동 예약 및 취소")
    # (수동 예약 페이지 내용, 이전 코드와 유사하게 구성, reservations_df 사용)
    # ... (생략 - 이전 수동 예약 탭 로직과 동일하게)
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지 자유롭게 시간 설정.
        - 최소 예약 시간은 30분, 예약 단위는 15분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.subheader("📝 새 예약 등록")
    manual_date_manual = st.date_input("예약 날짜", value=date.today(), min_value=date.today(), key="manual_date_manual_page")

    cols_manual_details = st.columns(2)
    with cols_manual_details[0]:
        selected_team_manual = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_page")
        manual_start_time_manual = st.time_input(
            "시작 시간", value=time(MANUAL_RESERVATION_START_HOUR, 0),
            step=timedelta(minutes=15), key="manual_start_time_page"
        )
    with cols_manual_details[1]:
        selected_room_manual = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_page")
        manual_end_time_manual = st.time_input(
            "종료 시간", value=time(MANUAL_RESERVATION_START_HOUR + 1, 0),
            step=timedelta(minutes=15), key="manual_end_time_page"
        )

    time_valid_manual = True
    # 시간 유효성 검사 (이전과 동일)
    if manual_start_time_manual >= manual_end_time_manual:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_manual = False
    elif manual_start_time_manual < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 이후여야 합니다."); time_valid_manual = False
    elif manual_end_time_manual > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"종료 시간은 {MANUAL_RESERVATION_END_HOUR}:00 이전이어야 합니다."); time_valid_manual = False
    min_duration_manual = timedelta(minutes=30)
    if datetime.combine(date.min, manual_end_time_manual) - datetime.combine(date.min, manual_start_time_manual) < min_duration_manual:
        st.error(f"최소 예약 시간은 {min_duration_manual.seconds // 60}분입니다."); time_valid_manual = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_manual_page", type="primary", use_container_width=True, disabled=not time_valid_manual):
        if time_valid_manual:
            current_reservations_manual = load_reservations()
            is_overlap_manual = False
            # 방 중복 체크
            room_res_manual = current_reservations_manual[
                (current_reservations_manual["날짜"] == manual_date_manual) &
                (current_reservations_manual["방"] == selected_room_manual)
            ]
            for _, ex_res in room_res_manual.iterrows():
                if check_time_overlap(manual_start_time_manual, manual_end_time_manual, ex_res["시간_시작"], ex_res["시간_종료"]):
                    st.error(f"⚠️ {selected_room_manual} 시간 중복: {ex_res['시간_시작'].strftime('%H:%M')}-{ex_res['시간_종료'].strftime('%H:%M')}"); is_overlap_manual=True; break
            if is_overlap_manual: st.stop()
            # 조 중복 체크
            team_res_manual = current_reservations_manual[
                (current_reservations_manual["날짜"] == manual_date_manual) &
                (current_reservations_manual["조"] == selected_team_manual)
            ]
            for _, ex_res in team_res_manual.iterrows():
                if check_time_overlap(manual_start_time_manual, manual_end_time_manual, ex_res["시간_시작"], ex_res["시간_종료"]):
                    st.error(f"⚠️ {selected_team_manual} 시간 중복: {ex_res['방']} ({ex_res['시간_시작'].strftime('%H:%M')}-{ex_res['시간_종료'].strftime('%H:%M')})"); is_overlap_manual=True; break
            if is_overlap_manual: st.stop()

            new_item_manual = {
                "날짜": manual_date_manual, "시간_시작": manual_start_time_manual, "시간_종료": manual_end_time_manual,
                "조": selected_team_manual, "방": selected_room_manual, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_manual = pd.concat([current_reservations_manual, pd.DataFrame([new_item_manual])], ignore_index=True)
            save_reservations(updated_df_manual)
            st.success(f"🎉 예약 완료: {selected_team_manual} / {selected_room_manual} / {manual_start_time_manual.strftime('%H:%M')}-{manual_end_time_manual.strftime('%H:%M')}")
            st.rerun()

    st.markdown("---")
    st.subheader(f"🚫 나의 수동 예약 취소 ({manual_date_manual.strftime('%Y-%m-%d')})")
    my_manual_res_display_manual = reservations_df[ # 전역 reservations_df 사용
        (reservations_df["날짜"] == manual_date_manual) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_display_manual.empty:
        my_manual_res_display_manual = my_manual_res_display_manual.sort_values(by=["시간_시작", "조"])
        for _, row_manual in my_manual_res_display_manual.iterrows():
            res_id_manual = row_manual["예약ID"]
            time_str_manual = f"{row_manual['시간_시작'].strftime('%H:%M')} - {row_manual['시간_종료'].strftime('%H:%M')}"
            item_cols_manual_cancel = st.columns([3,1])
            with item_cols_manual_cancel[0]: st.markdown(f"**{time_str_manual}** / **{row_manual['조']}** / `{row_manual['방']}`")
            with item_cols_manual_cancel[1]:
                if st.button("취소", key=f"cancel_{res_id_manual}_page", use_container_width=True):
                    current_on_cancel_manual = load_reservations()
                    updated_on_cancel_manual = current_on_cancel_manual[current_on_cancel_manual["예약ID"] != res_id_manual]
                    save_reservations(updated_on_cancel_manual)
                    st.success(f"🗑️ 예약 취소됨: {row_manual['조']} / {row_manual['방']} ({time_str_manual})")
                    st.rerun()
    else: st.info(f"{manual_date_manual.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


elif st.session_state.current_page == "🗓️ 예약 시간표":
    st.header("🗓️ 예약 시간표")
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_page")

    if not reservations_df.empty: # 전역 reservations_df 사용
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            # 시간표 스타일링 함수
            def style_timetable(df_in):
                # 기본 스타일: 모든 셀 가운데 정렬, 테두리
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid black',
                    'text-align': 'center',
                    'min-width': '70px', # 최소 너비
                    'height': '40px'
                }).set_table_styles([
                    {'selector': 'th', 'props': [('background-color', '#f2f2f2'), ('border', '1px solid black'), ('font-weight', 'bold')]}, # 헤더 스타일
                    {'selector': 'td,th', 'props': [('padding', '5px')]}
                ])

                # 예약된 셀 배경색 및 텍스트 스타일 적용 함수
                def highlight_reserved(val):
                    color = ''
                    font_weight = 'normal'
                    if isinstance(val, str) and val != '':
                        if '(A)' in val: # 자동 배정
                            color = 'background-color: #e6f7ff' # 연한 하늘색
                        elif '(S)' in val: # 수동 배정
                            color = 'background-color: #f6ffed' # 연한 연두색
                        font_weight = 'bold'
                    return f'{color}; font-weight: {font_weight};'

                styled_df = styled_df.applymap(highlight_reserved) # Pandas 1.4.0 이상 applymap, 이전 버전은 Styler.applymap
                return styled_df

            time_slots_tt = []
            current_time_tt = datetime.combine(date.today(), time(11, 0))
            end_of_day_tt = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_tt < end_of_day_tt:
                time_slots_tt.append(current_time_tt.time())
                current_time_tt += timedelta(minutes=30)

            timetable_df_page = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_tt], columns=ALL_ROOMS)
            timetable_df_page = timetable_df_page.fillna('')

            for _, res_tt in day_reservations.iterrows():
                start_res_dt_tt = datetime.combine(date.today(), res_tt["시간_시작"])
                end_res_dt_tt = datetime.combine(date.today(), res_tt["시간_종료"])
                current_slot_dt_tt = start_res_dt_tt
                while current_slot_dt_tt < end_res_dt_tt:
                    slot_str_tt = current_slot_dt_tt.strftime("%H:%M")
                    if slot_str_tt in timetable_df_page.index and res_tt["방"] in timetable_df_page.columns:
                        # 한 슬롯에 여러 예약이 겹치는 경우, 간단히 첫 예약만 표시 (개선 필요)
                        if timetable_df_page.loc[slot_str_tt, res_tt["방"]] == '':
                             timetable_df_page.loc[slot_str_tt, res_tt["방"]] = f"{res_tt['조']} ({res_tt['예약유형'][0]})"
                    current_slot_dt_tt += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            # Pandas Styler 객체를 HTML로 변환하여 표시
            st.html(style_timetable(timetable_df_page).to_html())
            st.caption("표시형식: 조이름 (A:자동, S:수동)")
        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")
