import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import gspread
from google.oauth2.service_account import Credentials
import uuid
import json

# --- 초기 설정 ---
AUTO_ASSIGN_EXCLUDE_TEAMS = ["대면A", "대면B", "대면C"]
SENIOR_TEAM = "시니어"
SENIOR_ROOM = "9F-1"
ALL_TEAMS = [f"{i}조" for i in range(1, 12)] + ["대면A", "대면B", "대면C","대면D", "청년", "중고등", SENIOR_TEAM]
ROTATION_TEAMS = [team for team in ALL_TEAMS if team not in AUTO_ASSIGN_EXCLUDE_TEAMS and team != SENIOR_TEAM]
ALL_ROOMS = [f"9F-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
ROTATION_ROOMS = [room for room in ALL_ROOMS if room != SENIOR_ROOM]
AUTO_ASSIGN_TIME_SLOT_STR = "11:30 - 13:00"
AUTO_ASSIGN_START_TIME = time(11, 30)
AUTO_ASSIGN_END_TIME = time(13, 0)
MANUAL_RESERVATION_START_HOUR = 13
MANUAL_RESERVATION_END_HOUR = 17 # 17:00까지 예약 가능 (16:xx 시작 ~ 17:00 종료)
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
@st.cache_data(ttl=180) # 캐시 시간 3분
def get_all_records_as_df_cached(_ws, expected_headers, _cache_key_prefix):
    if not GSHEET_AVAILABLE or _ws is None: return pd.DataFrame(columns=expected_headers)
    try:
        records = _ws.get_all_records()
        df = pd.DataFrame(records)
        if df.empty or not all(h in df.columns for h in expected_headers):
            # 헤더가 없거나, 예상과 다를 경우 빈 DataFrame 반환 (헤더 포함)
            # 또는 여기서 헤더를 강제로 설정하고 빈 데이터를 채울 수도 있음
            return pd.DataFrame(columns=expected_headers)

        if "날짜" in df.columns and _ws.title == "reservations":
            df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
            # 시간 열을 time 객체로 변환 (오류 발생 시 NaT 처리 후 제거)
            if "시간_시작" in df.columns:
                df['시간_시작'] = pd.to_datetime(df['시간_시작'], format='%H:%M', errors='coerce').dt.time
            if "시간_종료" in df.columns:
                df['시간_종료'] = pd.to_datetime(df['시간_종료'], format='%H:%M', errors='coerce').dt.time
            df = df.dropna(subset=['날짜', '시간_시작', '시간_종료']) # 필수 열에 NaT가 있으면 해당 행 제거
        return df
    except Exception as e:
        st.warning(f"'{_ws.title}' 시트 로드 중 오류 (캐시 사용 시도): {e}")
        return pd.DataFrame(columns=expected_headers)

def update_worksheet_from_df(_ws, df, headers):
    if not GSHEET_AVAILABLE or _ws is None: return
    try:
        df_to_save = df.copy()
        # 시간 객체를 문자열로 변환하여 저장
        if "시간_시작" in df_to_save.columns:
            df_to_save['시간_시작'] = df_to_save['시간_시작'].apply(lambda t: t.strftime('%H:%M') if isinstance(t, time) else t)
        if "시간_종료" in df_to_save.columns:
            df_to_save['시간_종료'] = df_to_save['시간_종료'].apply(lambda t: t.strftime('%H:%M') if isinstance(t, time) else t)

        df_values = [headers] + df_to_save.astype(str).values.tolist()
        _ws.clear() # 기존 내용 모두 삭제
        _ws.update(df_values, value_input_option='USER_ENTERED') # 새 내용으로 업데이트
        # 데이터 변경 시 관련 캐시 무효화
        if _ws.title == "reservations":
            get_all_records_as_df_cached.clear()
        elif _ws.title == "rotation_state":
            load_rotation_state_cached.clear()
    except Exception as e:
        st.error(f"'{_ws.title}' 시트 업데이트 중 오류: {e}")

def load_reservations():
    return get_all_records_as_df_cached(reservations_ws, RESERVATION_SHEET_HEADERS, "reservations_cache")

@st.cache_data(ttl=180)
def load_rotation_state_cached(_rotation_ws, _cache_key_prefix):
    if not GSHEET_AVAILABLE or _rotation_ws is None: return 0
    df_state = get_all_records_as_df_cached(_rotation_ws, ROTATION_SHEET_HEADER, _cache_key_prefix)
    if not df_state.empty and "next_team_index" in df_state.columns:
        try:
            return int(df_state.iloc[0]["next_team_index"])
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

# 시간 중복 확인 함수
def check_time_overlap(new_start, new_end, existing_start, existing_end):
    # time 객체를 datetime 객체로 변환하여 비교 (같은 날짜로 가정)
    dummy_date = date.min
    new_start_dt = datetime.combine(dummy_date, new_start)
    new_end_dt = datetime.combine(dummy_date, new_end)
    existing_start_dt = datetime.combine(dummy_date, existing_start)
    existing_end_dt = datetime.combine(dummy_date, existing_end)
    return max(new_start_dt, existing_start_dt) < min(new_end_dt, existing_end_dt)

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임방 예약/조회", layout="centered", initial_sidebar_state="expanded")

# 페이지 상태 유지를 위한 세션 상태 초기화
if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"

# --- 사이드바 ---
st.sidebar.title("🚀 조모임방 예약/조회")
st.sidebar.markdown("---")

# 기본 페이지로 돌아가는 버튼 (관리자 페이지에 있을 때만 표시)
if st.session_state.current_page == "🔄 자동 배정 (관리자)":
    if st.sidebar.button("🏠 시간표 및 수동 예약으로 돌아가기", key="return_to_main_btn_full_code"):
        st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"
        st.rerun()
    st.sidebar.markdown("---")


st.sidebar.subheader("👑 관리자")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제", key="test_mode_checkbox_admin_full_code")

if st.sidebar.button("⚙️ 자동 배정 설정 페이지로 이동", key="admin_auto_assign_nav_btn_admin_full_code"):
    st.session_state.current_page = "🔄 자동 배정 (관리자)"
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚙️ 기타 설정")
if st.sidebar.button("🔄 데이터 캐시 새로고침", key="cache_refresh_btn_admin_full_code"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다.")
    st.rerun()

# 메인 페이지 결정 로직 (사이드바에서 버튼 클릭 시 st.session_state.current_page가 변경됨)
if st.session_state.current_page not in ["🔄 자동 배정 (관리자)"]:
    st.session_state.current_page = "🗓️ 예약 시간표 및 수동 예약"


# --- 메인 화면 콘텐츠 ---
if not GSHEET_AVAILABLE:
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

reservations_df = load_reservations()

# 선택된 페이지에 따라 콘텐츠 표시
if st.session_state.current_page == "🗓️ 예약 시간표 및 수동 예약":
    st.header("🗓️ 예약 시간표")
    timetable_date = st.date_input("시간표 조회 날짜", value=date.today(), key="timetable_date_main_page_full_code")

    if not reservations_df.empty:
        day_reservations = reservations_df[reservations_df["날짜"] == timetable_date].copy()
        if not day_reservations.empty:
            def style_timetable(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd',
                    'text-align': 'center',
                    'min-width': '70px',
                    'height': '38px',
                    'font-size': '0.85em',
                }).set_table_styles([
                    {'selector': 'th', 'props': [ # 테이블 헤더 (방 이름)
                        ('background-color', '#f8f9fa'), ('border', '1px solid #dee2e6'), # 연한 회색 배경
                        ('font-weight', 'bold'), ('padding', '6px'), ('color', '#495057') # 어두운 회색 글자
                    ]},
                    {'selector': 'th.row_heading', 'props': [ # 인덱스 헤더 (시간)
                        ('background-color', '#f8f9fa'), ('border', '1px solid #dee2e6'),
                        ('font-weight', 'bold'), ('padding', '6px'), ('color', '#495057')
                    ]},
                    {'selector': 'td', 'props': [('padding', '6px'), ('border', '1px solid #eee')]} # 셀 패딩 및 테두리
                ])

                def highlight_reserved_cell(val):
                    bg_color = 'background-color: white;'
                    font_weight = 'normal'
                    text_color = 'color: #212529;' # 기본 글자색 (거의 검정)
                    if isinstance(val, str) and val != '':
                        if '(자동)' in val:
                            bg_color = 'background-color: #cfe2ff;' # Bootstrap primary-subtle
                            text_color = 'color: #052c65;' # Bootstrap primary-emphasis
                        elif '(수동)' in val:
                            bg_color = 'background-color: #d1e7dd;' # Bootstrap success-subtle
                            text_color = 'color: #0a3622;' # Bootstrap success-emphasis
                        font_weight = 'bold'
                    return f'{bg_color} {text_color} font-weight: {font_weight};'
                try:
                    styled_df = styled_df.applymap(highlight_reserved_cell)
                except AttributeError: # 이전 Pandas 버전 호환
                    styled_df = styled_df.style.apply(lambda col: col.map(highlight_reserved_cell)) # df.style.apply()...
                return styled_df

            time_slots_fc = []
            current_time_fc = datetime.combine(date.today(), time(11, 0))
            end_of_day_fc = datetime.combine(date.today(), time(MANUAL_RESERVATION_END_HOUR, 0))
            while current_time_fc < end_of_day_fc:
                time_slots_fc.append(current_time_fc.time())
                current_time_fc += timedelta(minutes=30)

            timetable_df_fc = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_fc], columns=ALL_ROOMS)
            timetable_df_fc = timetable_df_fc.fillna('') # 빈 문자열로 초기화

            for _, res_fc in day_reservations.iterrows():
                start_res_dt_fc = datetime.combine(date.today(), res_fc["시간_시작"])
                end_res_dt_fc = datetime.combine(date.today(), res_fc["시간_종료"])
                current_slot_dt_fc = start_res_dt_fc
                res_type_str_fc = "(자동)" if res_fc['예약유형'] == '자동' else "(수동)"
                while current_slot_dt_fc < end_res_dt_fc:
                    slot_str_fc = current_slot_dt_fc.strftime("%H:%M")
                    if slot_str_fc in timetable_df_fc.index and res_fc["방"] in timetable_df_fc.columns:
                        # 한 슬롯에 여러 예약이 겹치는 경우, 간단히 첫 예약만 표시
                        if timetable_df_fc.loc[slot_str_fc, res_fc["방"]] == '':
                             timetable_df_fc.loc[slot_str_fc, res_fc["방"]] = f"{res_fc['조']} {res_type_str_fc}"
                    current_slot_dt_fc += timedelta(minutes=30)

            st.markdown(f"**{timetable_date.strftime('%Y-%m-%d')} 예약 현황**")
            st.html(style_timetable(timetable_df_fc).to_html(escape=False))
            st.caption("표시형식: 조이름 (예약유형)")
        else:
            st.info(f"{timetable_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    st.markdown("---")
    st.header("✍️ 조모임방 예약/취소")
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{MANUAL_RESERVATION_START_HOUR}:00` 부터 `{MANUAL_RESERVATION_END_HOUR}:00` 까지 자유롭게 시간 설정.
        - 최소 예약 시간은 30분, 예약 단위는 15분입니다.
        - 중복 예약은 불가능합니다.
        """)

    st.markdown("##### 📝 새 예약 등록")
    manual_date_default_fc = timetable_date if timetable_date >= date.today() else date.today()
    manual_date_reserve_fc = st.date_input(
        "예약 날짜",
        value=manual_date_default_fc,
        min_value=date.today(),
        key="manual_date_reserve_fc"
    )

    cols_reserve_fc = st.columns(2)
    with cols_reserve_fc[0]:
        selected_team_reserve_fc = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_reserve_fc")
        manual_start_time_reserve_fc = st.time_input(
            "시작 시간", value=time(MANUAL_RESERVATION_START_HOUR, 0),
            step=timedelta(minutes=15), key="manual_start_time_reserve_fc"
        )
    with cols_reserve_fc[1]:
        selected_room_reserve_fc = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_reserve_fc")
        manual_end_time_reserve_fc = st.time_input(
            "종료 시간",
            value=time(MANUAL_RESERVATION_END_HOUR, 0),
            step=timedelta(minutes=15),
            key="manual_end_time_reserve_fc"
        )

    time_valid_reserve_fc = True
    if manual_start_time_reserve_fc >= manual_end_time_reserve_fc:
        st.error("종료 시간은 시작 시간보다 이후여야 합니다."); time_valid_reserve_fc = False
    elif manual_start_time_reserve_fc < time(MANUAL_RESERVATION_START_HOUR, 0):
        st.error(f"시작 시간은 {MANUAL_RESERVATION_START_HOUR}:00 이후여야 합니다."); time_valid_reserve_fc = False
    elif manual_end_time_reserve_fc > time(MANUAL_RESERVATION_END_HOUR, 0):
        st.error(f"종료 시간은 {MANUAL_RESERVATION_END_HOUR}:00 이전이거나 같아야 합니다."); time_valid_reserve_fc = False
    min_duration_reserve_fc = timedelta(minutes=30)
    start_dt_check_fc = datetime.combine(date.min, manual_start_time_reserve_fc)
    end_dt_check_fc = datetime.combine(date.min, manual_end_time_reserve_fc)
    if (end_dt_check_fc - start_dt_check_fc) < min_duration_reserve_fc:
        st.error(f"최소 예약 시간은 {min_duration_reserve_fc.seconds // 60}분입니다."); time_valid_reserve_fc = False

    if st.button("✅ 예약하기", key="manual_reserve_btn_reserve_fc", type="primary", use_container_width=True, disabled=not time_valid_reserve_fc):
        if time_valid_reserve_fc:
            current_reservations_reserve_fc = load_reservations()
            is_overlap_reserve_fc = False
            # 방 중복 체크
            room_res_check_fc = current_reservations_reserve_fc[
                (current_reservations_reserve_fc["날짜"] == manual_date_reserve_fc) &
                (current_reservations_reserve_fc["방"] == selected_room_reserve_fc)
            ]
            for _, ex_res_fc in room_res_check_fc.iterrows():
                if check_time_overlap(manual_start_time_reserve_fc, manual_end_time_reserve_fc, ex_res_fc["시간_시작"], ex_res_fc["시간_종료"]):
                    st.error(f"⚠️ {selected_room_reserve_fc}은(는) 해당 시간에 이미 예약(또는 일부 겹침)이 있습니다."); is_overlap_reserve_fc=True; break
            if is_overlap_reserve_fc: st.stop()
            # 조 중복 체크
            team_res_check_fc = current_reservations_reserve_fc[
                (current_reservations_reserve_fc["날짜"] == manual_date_reserve_fc) &
                (current_reservations_reserve_fc["조"] == selected_team_reserve_fc)
            ]
            for _, ex_res_fc in team_res_check_fc.iterrows():
                if check_time_overlap(manual_start_time_reserve_fc, manual_end_time_reserve_fc, ex_res_fc["시간_시작"], ex_res_fc["시간_종료"]):
                    st.error(f"⚠️ {selected_team_reserve_fc}은(는) 해당 시간에 이미 다른 예약(또는 일부 겹침)이 있습니다."); is_overlap_reserve_fc=True; break
            if is_overlap_reserve_fc: st.stop()

            new_item_reserve_fc = {
                "날짜": manual_date_reserve_fc, "시간_시작": manual_start_time_reserve_fc, "시간_종료": manual_end_time_reserve_fc,
                "조": selected_team_reserve_fc, "방": selected_room_reserve_fc, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }
            updated_df_reserve_fc = pd.concat([current_reservations_reserve_fc, pd.DataFrame([new_item_reserve_fc])], ignore_index=True)
            save_reservations(updated_df_reserve_fc)
            st.success(f"🎉 예약 완료!")
            st.rerun()

    st.markdown("##### 🚫 나의 수동 예약 취소")
    my_manual_res_cancel_fc = reservations_df[
        (reservations_df["날짜"] == manual_date_reserve_fc) & # 예약 등록에 사용된 날짜와 연동
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_res_cancel_fc.empty:
        my_manual_res_cancel_fc = my_manual_res_cancel_fc.sort_values(by=["시간_시작", "조"])
        for _, row_cancel_fc in my_manual_res_cancel_fc.iterrows():
            res_id_cancel_fc = row_cancel_fc["예약ID"]
            time_str_cancel_fc = f"{row_cancel_fc['시간_시작'].strftime('%H:%M')} - {row_cancel_fc['시간_종료'].strftime('%H:%M')}"
            item_cols_cancel_fc = st.columns([3,1])
            with item_cols_cancel_fc[0]: st.markdown(f"**{time_str_cancel_fc}** / **{row_cancel_fc['조']}** / `{row_cancel_fc['방']}`")
            with item_cols_cancel_fc[1]:
                if st.button("취소", key=f"cancel_{res_id_cancel_fc}_reserve_fc", use_container_width=True):
                    current_on_cancel_fc = load_reservations()
                    updated_on_cancel_fc = current_on_cancel_fc[current_on_cancel_fc["예약ID"] != res_id_cancel_fc]
                    save_reservations(updated_on_cancel_fc)
                    st.success(f"🗑️ 예약 취소됨")
                    st.rerun()
    else:
        st.info(f"{manual_date_reserve_fc.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


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

    auto_assign_date_admin_fc = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_admin_fc")
    weekday_admin_fc = auto_assign_date_admin_fc.weekday()
    can_auto_assign_admin_fc = test_mode or (weekday_admin_fc in [2, 6])

    if not can_auto_assign_admin_fc:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_admin_fc", type="primary"):
        if can_auto_assign_admin_fc:
            current_reservations_admin_fc = load_reservations()
            existing_auto_admin_fc = current_reservations_admin_fc[
                (current_reservations_admin_fc["날짜"] == auto_assign_date_admin_fc) &
                (current_reservations_admin_fc["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_admin_fc["예약유형"] == "자동")
            ]
            if not existing_auto_admin_fc.empty:
                st.warning(f"이미 {auto_assign_date_admin_fc.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_list_admin_fc = []
                assigned_info_admin_fc = []
                # 시니어조 배정
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_admin_fc.append({
                        "날짜": auto_assign_date_admin_fc, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_fc.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션 배정
                next_idx_admin_fc = load_rotation_state()
                num_rotation_teams_fc = len(ROTATION_TEAMS)
                num_rotation_rooms_fc = len(ROTATION_ROOMS)
                available_rooms_fc = min(num_rotation_teams_fc, num_rotation_rooms_fc)

                for i in range(available_rooms_fc):
                    if num_rotation_teams_fc == 0: break
                    team_idx_list_fc = (next_idx_admin_fc + i) % num_rotation_teams_fc
                    team_assign_fc = ROTATION_TEAMS[team_idx_list_fc]
                    room_assign_fc = ROTATION_ROOMS[i]
                    new_auto_list_admin_fc.append({
                        "날짜": auto_assign_date_admin_fc, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": team_assign_fc, "방": room_assign_fc, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_admin_fc.append(f"🔄 **{team_assign_fc}** → **{room_assign_fc}** (로테이션)")

                if new_auto_list_admin_fc:
                    new_df_admin_fc = pd.DataFrame(new_auto_list_admin_fc)
                    updated_df_admin_fc = pd.concat([current_reservations_admin_fc, new_df_admin_fc], ignore_index=True)
                    save_reservations(updated_df_admin_fc)
                    new_next_idx_admin_fc = (next_idx_admin_fc + available_rooms_fc) % num_rotation_teams_fc if num_rotation_teams_fc > 0 else 0
                    save_rotation_state(new_next_idx_admin_fc)
                    st.success(f"🎉 {auto_assign_date_admin_fc.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_admin_fc: st.markdown(f"- {info}")
                    if num_rotation_teams_fc > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx_admin_fc]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_admin_fc = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_admin_fc) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_admin_fc.empty:
        st.dataframe(auto_today_display_admin_fc[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date_admin_fc.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")
