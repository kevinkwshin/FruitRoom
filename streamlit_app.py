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
@st.cache_data(ttl=300)
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
        _ws.clear(); _ws.update(df_values, value_input_option='USER_ENTERED')
        if _ws.title == "reservations": get_all_records_as_df_cached.clear()
        elif _ws.title == "rotation_state": load_rotation_state_cached.clear()
    except Exception as e: st.error(f"'{_ws.title}' 시트 업데이트 중 오류: {e}")

def load_reservations():
    return get_all_records_as_df_cached(reservations_ws, RESERVATION_SHEET_HEADERS, "reservations_cache")

@st.cache_data(ttl=300)
def load_rotation_state_cached(_rotation_ws, _cache_key_prefix):
    if not GSHEET_AVAILABLE or _rotation_ws is None: return 0
    df_state = get_all_records_as_df_cached(_rotation_ws, ROTATION_SHEET_HEADER, _cache_key_prefix)
    if not df_state.empty and "next_team_index" in df_state.columns:
        try: return int(df_state.iloc[0]["next_team_index"])
        except (ValueError, TypeError): return 0
    return 0

def load_rotation_state(): return load_rotation_state_cached(rotation_ws, "rotation_state_cache")
def save_reservations(df): update_worksheet_from_df(reservations_ws, df, RESERVATION_SHEET_HEADERS)
def save_rotation_state(next_team_index):
    if not GSHEET_AVAILABLE or rotation_ws is None: return
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    update_worksheet_from_df(rotation_ws, df_state, ROTATION_SHEET_HEADER)
def check_time_overlap(new_start, new_end, existing_start, existing_end):
    return max(new_start, existing_start) < min(new_end, existing_end)

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약", layout="centered", initial_sidebar_state="expanded")

if "current_page" not in st.session_state:
    st.session_state.current_page = "🗓️ 예약 현황 및 수동 예약" # 기본 페이지 변경

# --- 사이드바 ---
st.sidebar.title("🚀 조모임 스터디룸")
page_options = ["🗓️ 예약 현황 및 수동 예약", "🔄 자동 배정"] # 메뉴 단순화
try: current_page_index = page_options.index(st.session_state.current_page)
except ValueError: current_page_index = 0

st.session_state.current_page = st.sidebar.radio(
    "메뉴 선택", page_options, index=current_page_index, key="page_nav_radio_final"
)
st.sidebar.markdown("---")
# "데이터 캐시 새로고침" 버튼만 남김 (설정/관리 제목 제거)
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

if st.session_state.current_page == "🔄 자동 배정":
    st.header("🔄 자동 배정")
    st.warning("⚠️ 이 기능은 관리자만 사용해주세요. 예약 시스템에 큰 영향을 줄 수 있습니다.")

    with st.expander("🛠️ 관리자 설정", expanded=True): # 기본적으로 펼쳐짐
        test_mode_auto = st.checkbox("🧪 테스트 모드 활성화", key="test_mode_auto_page", help="활성화 시 자동 배정 요일 제한 해제")

    # (자동 배정 로직 부분 - 이전 코드와 동일)
    if test_mode_auto: st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else: st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 상세 안내", expanded=False): # 상세 안내는 접힘
        st.markdown(f"""
        - 배정 시간: `{AUTO_ASSIGN_TIME_SLOT_STR}`
        - 실행 요일: 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - 고정 배정: `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정.
        - 로테이션 배정: `{SENIOR_TEAM}`, `{SENIOR_ROOM}` 제외, `{', '.join(AUTO_ASSIGN_EXCLUDE_TEAMS)}` 제외.
        - 로테이션 대상 조: `{', '.join(ROTATION_TEAMS)}`
        - 로테이션 대상 방: `{', '.join(ROTATION_ROOMS)}`
        """)

    auto_assign_date = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_auto_final")
    weekday_auto_final = auto_assign_date.weekday()
    can_auto_assign_final = test_mode_auto or (weekday_auto_final in [2, 6])

    if not can_auto_assign_final:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다. (테스트 모드 비활성화 상태)")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_auto_final", type="primary"):
        if can_auto_assign_final:
            current_reservations_auto_final = load_reservations()
            existing_auto_final = current_reservations_auto_final[
                (current_reservations_auto_final["날짜"] == auto_assign_date) &
                (current_reservations_auto_final["시간_시작"] == AUTO_ASSIGN_START_TIME) &
                (current_reservations_auto_final["예약유형"] == "자동")
            ]
            if not existing_auto_final.empty: st.warning(f"이미 {auto_assign_date.strftime('%Y-%m-%d')}에 자동 배정 내역 존재.")
            else:
                new_auto_list_final, assigned_info_final = [], []
                # 시니어조
                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_list_final.append({
                        "날짜": auto_assign_date, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_final.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")
                # 로테이션
                next_idx_final = load_rotation_state()
                num_rot_teams_final, num_rot_rooms_final = len(ROTATION_TEAMS), len(ROTATION_ROOMS)
                avail_rooms_final = min(num_rot_teams_final, num_rot_rooms_final)
                for i in range(avail_rooms_final):
                    if num_rot_teams_final == 0: break
                    team_idx = (next_idx_final + i) % num_rot_teams_final
                    new_auto_list_final.append({
                        "날짜": auto_assign_date, "시간_시작": AUTO_ASSIGN_START_TIME, "시간_종료": AUTO_ASSIGN_END_TIME,
                        "조": ROTATION_TEAMS[team_idx], "방": ROTATION_ROOMS[i], "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_final.append(f"🔄 **{ROTATION_TEAMS[team_idx]}** → **{ROTATION_ROOMS[i]}** (로테이션)")

                if new_auto_list_final:
                    updated_df_final = pd.concat([current_reservations_auto_final, pd.DataFrame(new_auto_list_final)], ignore_index=True)
                    save_reservations(updated_df_final)
                    new_next_idx = (next_idx_final + avail_rooms_final) % num_rot_teams_final if num_rot_teams_final > 0 else 0
                    save_rotation_state(new_next_idx)
                    st.success(f"🎉 {auto_assign_date.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_final: st.markdown(f"- {info}")
                    if num_rot_teams_final > 0: st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_idx]}'")
                    st.rerun()
                else: st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else: st.error("자동 배정을 실행할 수 없는 날짜입니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT_STR})")
    auto_today_display_final = reservations_df[
        (reservations_df["날짜"] == auto_assign_date) &
        (reservations_df["시간_시작"] == AUTO_ASSIGN_START_TIME) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display_final.empty: st.dataframe(auto_today_display_final[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else: st.info(f"{auto_assign_date.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")


elif st.session_state.current_page == "🗓️ 예약 현황 및 수동 예약":
    st.header("🗓️ 예약 현황 및 수동 예약")
    display_date = st.date_input("조회 및 예약 날짜", value=date.today(), key="display_reserve_date")

    # --- 시간표 표시 ---
    st.subheader(f"⏱️ {display_date.strftime('%Y-%m-%d')} 예약 시간표")
    if not reservations_df.empty:
        day_reservations_tt = reservations_df[reservations_df["날짜"] == display_date].copy()
        if not day_reservations_tt.empty:
            def style_timetable_final(df_in):
                styled_df = df_in.style.set_properties(**{
                    'border': '1px solid #ddd', 'padding': '8px',
                    'text-align': 'center', 'min-width': '65px', 'height': '35px',
                    'font-size': '0.9em' # 폰트 크기 약간 줄임
                }).set_table_styles([
                    {'selector': 'th', 'props': [('background-color', '#f0f0f0'), ('border', '1px solid #ccc'), ('font-weight', 'bold'), ('padding', '8px')]},
                    {'selector': 'td', 'props': [('border', '1px solid #eee')]} # 셀 테두리 연하게
                ])
                def highlight_reserved_final(val):
                    bg_color = 'white'
                    text_color = 'black' # 기본 텍스트 색상
                    font_weight = 'normal'
                    if isinstance(val, str) and val != '':
                        font_weight = 'bold'
                        if '(A)' in val: bg_color = '#d1e7dd'; text_color = '#0f5132'; # 연한 초록 (자동)
                        elif '(S)' in val: bg_color = '#cfe2ff'; text_color = '#0a58ca'; # 연한 파랑 (수동)
                    return f'background-color: {bg_color}; color: {text_color}; font-weight: {font_weight};'
                styled_df = styled_df.apply(lambda x: x.map(highlight_reserved_final) if x.name in ALL_ROOMS else x) # ALL_ROOMS 열에만 적용
                return styled_df

            time_slots_final = [ (datetime.combine(date.today(), time(11,0)) + timedelta(minutes=30*i)).time()
                                for i in range((MANUAL_RESERVATION_END_HOUR - 11) * 2) ] # 11:00 ~ 16:30
            timetable_df_final = pd.DataFrame(index=[t.strftime("%H:%M") for t in time_slots_final], columns=ALL_ROOMS).fillna('')

            for _, res in day_reservations_tt.iterrows():
                current_slot_dt = datetime.combine(date.today(), res["시간_시작"])
                end_res_dt = datetime.combine(date.today(), res["시간_종료"])
                while current_slot_dt < end_res_dt:
                    slot_str = current_slot_dt.strftime("%H:%M")
                    if slot_str in timetable_df_final.index and res["방"] in timetable_df_final.columns:
                        if timetable_df_final.loc[slot_str, res["방"]] == '': # 겹치면 첫 예약만 표시
                             timetable_df_final.loc[slot_str, res["방"]] = f"{res['조']} ({res['예약유형'][0]})"
                    current_slot_dt += timedelta(minutes=30)
            st.html(style_timetable_final(timetable_df_final).to_html(escape=False))
            st.caption("표시형식: 조이름 (A:자동, S:수동)")
        else: st.info(f"{display_date.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else: st.info("등록된 예약이 없습니다.")
    st.markdown("---")

    # --- 수동 예약 등록 ---
    st.subheader("📝 새 수동 예약 등록")
    with st.expander("ℹ️ 수동 예약 안내", expanded=False):
        st.markdown(f"13:00 ~ 17:00 사이, 최소 30분, 15분 단위 예약 가능.")

    cols_manual_reg = st.columns(2)
    with cols_manual_reg[0]:
        selected_team_reg = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_reg_final")
        start_time_reg = st.time_input("시작 시간", value=time(MANUAL_RESERVATION_START_HOUR, 0), step=timedelta(minutes=15), key="start_time_reg_final")
    with cols_manual_reg[1]:
        selected_room_reg = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_reg_final")
        end_time_reg = st.time_input("종료 시간", value=time(MANUAL_RESERVATION_START_HOUR + 1, 0), step=timedelta(minutes=15), key="end_time_reg_final")

    time_valid_reg = True # 시간 유효성 검사 (이전과 동일)
    if start_time_reg >= end_time_reg: st.error("종료>시작"); time_valid_reg=False
    elif start_time_reg < time(MANUAL_RESERVATION_START_HOUR,0): st.error(f"시작은 {MANUAL_RESERVATION_START_HOUR}:00 이후"); time_valid_reg=False
    elif end_time_reg > time(MANUAL_RESERVATION_END_HOUR,0): st.error(f"종료는 {MANUAL_RESERVATION_END_HOUR}:00 이전"); time_valid_reg=False
    if datetime.combine(date.min,end_time_reg)-datetime.combine(date.min,start_time_reg) < timedelta(minutes=30): st.error("최소 30분 예약"); time_valid_reg=False

    if st.button("✅ 이 시간에 예약하기", key="manual_reserve_btn_reg_final", type="primary", use_container_width=True, disabled=not time_valid_reg):
        if time_valid_reg:
            current_res_reg = load_reservations()
            overlap_reg = False # 중복 체크 (이전과 동일)
            room_res_check = current_res_reg[(current_res_reg["날짜"]==display_date)&(current_res_reg["방"]==selected_room_reg)]
            for _,r in room_res_check.iterrows():
                if check_time_overlap(start_time_reg,end_time_reg,r["시간_시작"],r["시간_종료"]):
                    st.error(f"방 시간 중복"); overlap_reg=True; break
            if overlap_reg: st.stop()
            team_res_check = current_res_reg[(current_res_reg["날짜"]==display_date)&(current_res_reg["조"]==selected_team_reg)]
            for _,r in team_res_check.iterrows():
                if check_time_overlap(start_time_reg,end_time_reg,r["시간_시작"],r["시간_종료"]):
                    st.error(f"조 시간 중복"); overlap_reg=True; break
            if overlap_reg: st.stop()

            new_item_reg = {"날짜":display_date, "시간_시작":start_time_reg, "시간_종료":end_time_reg, "조":selected_team_reg,
                            "방":selected_room_reg, "예약유형":"수동", "예약ID":str(uuid.uuid4())}
            updated_df_reg = pd.concat([current_res_reg, pd.DataFrame([new_item_reg])],ignore_index=True)
            save_reservations(updated_df_reg)
            st.success(f"예약 완료: {selected_team_reg} / {selected_room_reg} / {start_time_reg.strftime('%H:%M')}-{end_time_reg.strftime('%H:%M')}")
            st.rerun()
    st.markdown("---")

    # --- 수동 예약 취소 ---
    st.subheader(f"🚫 나의 수동 예약 취소 ({display_date.strftime('%Y-%m-%d')})")
    my_manual_res_cancel = reservations_df[(reservations_df["날짜"]==display_date)&(reservations_df["예약유형"]=="수동")].copy()
    if not my_manual_res_cancel.empty:
        my_manual_res_cancel = my_manual_res_cancel.sort_values(by=["시간_시작", "조"])
        for _, row_cancel in my_manual_res_cancel.iterrows():
            res_id_cancel = row_cancel["예약ID"]
            time_str_cancel = f"{row_cancel['시간_시작'].strftime('%H:%M')} - {row_cancel['시간_종료'].strftime('%H:%M')}"
            cols_cancel = st.columns([3,1])
            with cols_cancel[0]: st.markdown(f"**{time_str_cancel}** / **{row_cancel['조']}** / `{row_cancel['방']}`")
            with cols_cancel[1]:
                if st.button("취소", key=f"cancel_{res_id_cancel}_final", use_container_width=True):
                    current_on_cancel = load_reservations()
                    updated_on_cancel = current_on_cancel[current_on_cancel["예약ID"] != res_id_cancel]
                    save_reservations(updated_on_cancel)
                    st.success(f"예약 취소됨: {row_cancel['조']} / {row_cancel['방']} ({time_str_cancel})")
                    st.rerun()
    else: st.info(f"{display_date.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")
