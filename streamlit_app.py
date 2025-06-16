import streamlit as st
import datetime
import pandas as pd
import json
import os
import pytz
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict
import random # 로테이션 배정용

# --- 기본 설정 ---
KST = pytz.timezone('Asia/Seoul')
TEAMS_ALL = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)]
SPACE_LOCATIONS_DETAILED = {
    "9층": {"name": "9층 조모임 공간", "spaces": [f"9층-{i}호" for i in range(1, 7)]},
    "지하5층": {"name": "지하5층 조모임 공간", "spaces": [f"지하5층-{i}호" for i in range(1, 4)]}
}
ALL_SPACES_LIST = SPACE_LOCATIONS_DETAILED["9층"]["spaces"] + SPACE_LOCATIONS_DETAILED["지하5층"]["spaces"]
ADMIN_PASSWORD = "admin" # 실제 사용시 변경

# --- 자동 배정 설정 ---
# 앱 UI나 별도 설정 파일에서 관리 가능하도록 확장 가능
AUTO_ROTATION_TEAMS = ["대면A", "대면B", "대면C", "1조", "2조", "3조", "4조", "5조"] # 자동 배정 참여 조
AUTO_ROTATION_DAYS = [2, 6] # 수요일(2), 일요일(6)에 자동 배정 실행
AUTO_ROTATION_TIME_START = datetime.time(11, 30)
AUTO_ROTATION_DURATION_MINUTES = 90 # 11:30 ~ 13:00

# --- 자율 예약 설정 ---
FREE_RESERVATION_SLOTS = { # 시간 슬롯 (표시용 레이블: (시작 시간, 지속 시간(분)))
    "13:00-14:00": (datetime.time(13, 0), 60),
    "14:00-15:00": (datetime.time(14, 0), 60),
    "15:00-16:00": (datetime.time(15, 0), 60),
}
FREE_RESERVATION_ALLOWED_DAYS = [0,1,2,3,4,5,6] # 모든 요일 자율 예약 가능 (필요시 수정)
RESERVATION_DEADLINE_MINUTES = 10 # 슬롯 시작 X분 전까지 예약/취소 가능

# --- Google Sheets 설정 ---
DEFAULT_CREDENTIALS_PATH = "google_credentials.json"
DEFAULT_SHEET_NAME = "조모임_통합_예약_내역"

# Google Sheet 컬럼명 (순서 중요)
COL_DATETIME_STR = "예약시작시간_KST_ISO" # 예약 슬롯의 시작 시간 (KST 기준, naive ISO)
COL_DURATION_MINUTES = "지속시간_분"
COL_TEAM = "조이름"
COL_ROOM = "공간명"
COL_RESERVATION_TYPE = "예약유형" # "자동배정", "자율예약"
COL_STATUS = "상태" # "예약됨", "취소됨"
COL_BOOKING_TIMESTAMP_STR = "처리시각_KST_ISO" # 예약/취소 행위가 일어난 시간
COL_BOOKED_BY = "예약자" # 예: "시스템", "1조", "admin"
COL_CANCELLATION_TIMESTAMP_STR = "취소시각_KST_ISO"
COL_CANCELLED_BY = "취소자"
COL_RESERVATION_ID = "예약ID" # 고유 식별자 (datetime_str + room) 또는 UUID

GSHEET_HEADERS = [
    COL_RESERVATION_ID, COL_DATETIME_STR, COL_DURATION_MINUTES, COL_TEAM, COL_ROOM,
    COL_RESERVATION_TYPE, COL_STATUS, COL_BOOKING_TIMESTAMP_STR, COL_BOOKED_BY,
    COL_CANCELLATION_TIMESTAMP_STR, COL_CANCELLED_BY
]

# --- Helper Functions ---
def get_kst_now():
    return datetime.datetime.now(KST)

def get_kst_today_date():
    return get_kst_now().date()

def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

# --- Google Sheets 연결 (기존 코드와 유사, 헤더 처리 강화) ---
@st.cache_resource(ttl=600)
def connect_to_gsheet():
    try:
        if hasattr(st, 'secrets') and "google_sheets_credentials_json" in st.secrets:
            creds_json_str = st.secrets["google_sheets_credentials_json"]
            creds_dict = json.loads(creds_json_str)
            creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive'])
            gc = gspread.authorize(creds)
            sheet_name = st.secrets.get("google_sheet_name", DEFAULT_SHEET_NAME)
        else:
            credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_CREDENTIALS_PATH)
            if not os.path.exists(credentials_path):
                st.error(f"Google Sheets 인증 파일({credentials_path})을 찾을 수 없습니다.")
                return None
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
            gc = gspread.authorize(creds)
            sheet_name = os.environ.get("GOOGLE_SHEET_NAME", DEFAULT_SHEET_NAME)
        try:
            sh = gc.open(sheet_name)
        except gspread.exceptions.SpreadsheetNotFound:
            st.warning(f"시트 '{sheet_name}'을(를) 찾을 수 없습니다. 새로 생성합니다.")
            sh = gc.create(sheet_name)
            st.info(f"새 시트 '{sheet_name}'이(가) 생성되었습니다. 서비스 계정 이메일({gc.auth.service_account_email})에 편집 권한을 부여해주세요.")
        worksheet = sh.sheet1
        headers = worksheet.row_values(1)
        if not headers or any(h not in GSHEET_HEADERS for h in headers) or len(headers) != len(GSHEET_HEADERS): # 헤더가 다르거나 개수가 다르면
            worksheet.clear()
            worksheet.update('A1', [GSHEET_HEADERS], value_input_option='USER_ENTERED')
            worksheet.freeze(rows=1) # 헤더 행 고정
            st.info(f"Google Sheet '{sheet_name}' 헤더를 표준 형식으로 업데이트했습니다.")
        return worksheet
    except Exception as e:
        st.error(f"Google Sheets 연결 실패: {e}")
        return None

def get_worksheet():
    if 'gsheet_worksheet' not in st.session_state or st.session_state.gsheet_worksheet is None:
        st.session_state.gsheet_worksheet = connect_to_gsheet()
    return st.session_state.gsheet_worksheet

# --- 데이터 로드 및 처리 ---
def get_all_records_from_gsheet():
    """Google Sheet에서 모든 레코드를 가져옵니다 (헤더 포함)."""
    worksheet = get_worksheet()
    if not worksheet: return []
    try:
        return worksheet.get_all_values() # 모든 값을 리스트의 리스트로 가져옴
    except Exception as e:
        st.error(f"Google Sheets 데이터 로드 중 오류: {e}")
        st.session_state.gsheet_worksheet = None # 연결 오류 시 캐시 무효화
        return []

def parse_gsheet_row(row_values, headers=GSHEET_HEADERS):
    """시트의 한 행(값 리스트)을 딕셔너리로 변환합니다."""
    if len(row_values) != len(headers): return None # 데이터 길이 불일치
    record = dict(zip(headers, row_values))
    try:
        # datetime_str과 booking_timestamp_str 등을 datetime 객체로 변환 (앱 내부용)
        if record.get(COL_DATETIME_STR):
            record['datetime_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_DATETIME_STR]))
        if record.get(COL_BOOKING_TIMESTAMP_STR):
            record['booking_timestamp_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_BOOKING_TIMESTAMP_STR]))
        if record.get(COL_CANCELLATION_TIMESTAMP_STR):
            record['cancellation_timestamp_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_CANCELLATION_TIMESTAMP_STR]))
        if record.get(COL_DURATION_MINUTES):
            record[COL_DURATION_MINUTES] = int(record[COL_DURATION_MINUTES])
        return record
    except ValueError: # 날짜/시간 파싱 오류 등
        return None # 또는 오류 처리

def get_active_reservations_for_day(target_date, all_sheet_data_with_headers):
    """특정 날짜의 '예약됨' 상태인 모든 예약을 반환합니다."""
    active_reservations = []
    if not all_sheet_data_with_headers or len(all_sheet_data_with_headers) < 2: # 헤더만 있거나 비었으면
        return active_reservations

    headers = all_sheet_data_with_headers[0]
    for row_values in all_sheet_data_with_headers[1:]: # 헤더 제외
        record = parse_gsheet_row(row_values, headers)
        if record and record.get('datetime_obj_kst') and record['datetime_obj_kst'].date() == target_date and record.get(COL_STATUS) == "예약됨":
            active_reservations.append(record)
    return active_reservations


# --- 자동 배정 로직 ---
def run_auto_rotation_assignment_if_needed(target_date, all_sheet_data_with_headers):
    """필요한 경우 (요일, 시간, 기존 배정 없음) 자동 로테이션 배정을 실행하고 시트에 기록합니다."""
    if target_date.weekday() not in AUTO_ROTATION_DAYS:
        return False, "자동 배정 요일이 아닙니다."

    # 해당 날짜, 자동 배정 시간에 이미 '자동배정' 타입의 예약이 있는지 확인
    assignment_datetime_naive = datetime.datetime.combine(target_date, AUTO_ROTATION_TIME_START)
    assignment_datetime_kst = KST.localize(assignment_datetime_naive)

    headers = all_sheet_data_with_headers[0] if all_sheet_data_with_headers else []
    for row_values in all_sheet_data_with_headers[1:]:
        record = parse_gsheet_row(row_values, headers)
        if record and record.get('datetime_obj_kst') == assignment_datetime_kst and \
           record.get(COL_RESERVATION_TYPE) == "자동배정" and record.get(COL_STATUS) == "예약됨":
            return False, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정이 이미 완료되었습니다."

    # 배정 실행
    teams_to_assign = list(AUTO_ROTATION_TEAMS) # 복사본 사용
    spaces_available = list(ALL_SPACES_LIST)    # 복사본 사용
    random.shuffle(teams_to_assign) # 팀 순서 섞기 (매번 다른 배정 유도)
    random.shuffle(spaces_available) # 공간 순서도 섞을 수 있음 (선택적)

    assignments = []
    num_assignments = min(len(teams_to_assign), len(spaces_available))
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
    reservation_id_prefix = assignment_datetime_naive.strftime('%Y%m%d%H%M')

    for i in range(num_assignments):
        team = teams_to_assign[i]
        space = spaces_available[i]
        reservation_id = f"AUTO_{reservation_id_prefix}_{space.replace('-', '')}"

        new_assignment_row = [
            reservation_id,
            assignment_datetime_naive.isoformat(), # KST naive ISO
            AUTO_ROTATION_DURATION_MINUTES,
            team,
            space,
            "자동배정",
            "예약됨",
            now_kst_iso, # 처리 시각
            "시스템", # 예약자
            "", # 취소 시각
            ""  # 취소자
        ]
        assignments.append(new_assignment_row)

    if assignments:
        worksheet = get_worksheet()
        if worksheet:
            try:
                worksheet.append_rows(assignments, value_input_option='USER_ENTERED')
                return True, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정 완료 ({len(assignments)}건)."
            except Exception as e:
                return False, f"자동 배정 데이터 GSheet 저장 실패: {e}"
        else:
            return False, "Google Sheets에 연결되지 않아 자동 배정을 저장할 수 없습니다."
    return False, "배정할 팀 또는 공간이 부족합니다."

# --- 자율 예약 및 취소 로직 ---
def add_free_reservation_to_gsheet(selected_date, time_slot_key, team, space, booked_by):
    """자율 예약을 Google Sheet에 추가합니다."""
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 예약할 수 없습니다."

    slot_start_time, slot_duration = FREE_RESERVATION_SLOTS[time_slot_key]
    reservation_datetime_naive = datetime.datetime.combine(selected_date, slot_start_time)
    reservation_datetime_kst = KST.localize(reservation_datetime_naive)
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
    reservation_id = f"FREE_{reservation_datetime_naive.strftime('%Y%m%d%H%M')}_{space.replace('-', '')}"


    # 중복 예약 확인 (시트에서 최신 정보 기준) - 중요!
    all_data = get_all_records_from_gsheet()
    active_reservations_for_slot = []
    headers = all_data[0] if all_data else []
    for row_val in all_data[1:]:
        rec = parse_gsheet_row(row_val, headers)
        if rec and rec.get('datetime_obj_kst') == reservation_datetime_kst and rec.get(COL_STATUS) == "예약됨":
            active_reservations_for_slot.append(rec)
    
    for res in active_reservations_for_slot:
        if res.get(COL_ROOM) == space:
            return False, f"오류: {space}은(는) 해당 시간에 이미 예약되어 있습니다. (시트 확인)"
        if res.get(COL_TEAM) == team:
            return False, f"오류: {team} 조는 해당 시간에 이미 다른 공간을 예약했습니다. (시트 확인)"


    new_reservation_row = [
        reservation_id,
        reservation_datetime_naive.isoformat(),
        slot_duration,
        team,
        space,
        "자율예약",
        "예약됨",
        now_kst_iso,
        booked_by,
        "", ""
    ]
    try:
        worksheet.append_row(new_reservation_row, value_input_option='USER_ENTERED')
        return True, f"{selected_date.strftime('%m/%d')} {time_slot_key} '{team}' 조 '{space}' 예약 완료."
    except Exception as e:
        return False, f"자율 예약 GSheet 저장 실패: {e}"

def cancel_reservation_in_gsheet(reservation_id_to_cancel, cancelled_by):
    """Google Sheet에서 특정 예약을 찾아 '취소됨'으로 상태 변경 및 취소 정보 기록."""
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 취소할 수 없습니다."

    try:
        # 예약 ID로 해당 행 찾기 (COL_RESERVATION_ID는 첫번째 컬럼이라고 가정)
        cell = worksheet.find(reservation_id_to_cancel, in_column=1)
        if not cell:
            return False, f"예약 ID '{reservation_id_to_cancel}'을(를) 찾을 수 없습니다."

        row_index = cell.row
        now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()

        # 상태, 취소시각, 취소자 컬럼 업데이트
        # GSHEET_HEADERS 리스트에서 각 컬럼의 인덱스(1부터 시작) 찾기
        status_col_index = GSHEET_HEADERS.index(COL_STATUS) + 1
        cancel_ts_col_index = GSHEET_HEADERS.index(COL_CANCELLATION_TIMESTAMP_STR) + 1
        cancelled_by_col_index = GSHEET_HEADERS.index(COL_CANCELLED_BY) + 1
        booking_ts_col_index = GSHEET_HEADERS.index(COL_BOOKING_TIMESTAMP_STR) + 1


        # 여러 셀을 한 번에 업데이트 (더 효율적)
        update_cells_data = [
            {'range': gspread.utils.rowcol_to_a1(row_index, status_col_index), 'values': [["취소됨"]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, cancel_ts_col_index), 'values': [[now_kst_iso]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, cancelled_by_col_index), 'values': [[cancelled_by]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, booking_ts_col_index), 'values': [[now_kst_iso]]}, # 처리시각도 현재로 업데이트
        ]
        worksheet.batch_update(update_cells_data, value_input_option='USER_ENTERED')

        return True, f"예약 ID '{reservation_id_to_cancel}'이(가) 취소되었습니다."

    except gspread.exceptions.CellNotFound:
        return False, f"예약 ID '{reservation_id_to_cancel}'을(를) 시트에서 찾지 못했습니다."
    except Exception as e:
        st.error(f"Google Sheets 예약 취소 중 오류: {e}")
        return False, f"예약 취소 중 오류 발생: {e}"


# --- Streamlit UI ---
st.set_page_config(page_title="통합 조모임 공간 예약", layout="wide")

# --- CSS (기존 것 사용 가능) ---
st.markdown("""<style>...</style>""", unsafe_allow_html=True) # 기존 CSS 삽입

# --- 세션 상태 초기화 ---
if 'admin_mode' not in st.session_state: st.session_state.admin_mode = False
if 'form_message' not in st.session_state: st.session_state.form_message = None # (type, content)
if 'all_gsheet_data' not in st.session_state: # 시트 전체 데이터 캐싱
    st.session_state.all_gsheet_data = get_all_records_from_gsheet()

# --- 날짜 변경 감지 및 자동 배정 실행 ---
# 앱 로드 시 또는 특정 조건에서 하루 한 번 자동 배정 실행 로직
today_kst = get_kst_today_date()
if 'last_auto_assignment_check_date' not in st.session_state or st.session_state.last_auto_assignment_check_date != today_kst:
    if today_kst.weekday() in AUTO_ROTATION_DAYS:
        st.info(f"오늘({today_kst.strftime('%m/%d')})은 자동 배정 요일입니다. 배정 상태를 확인합니다...")
        success, message = run_auto_rotation_assignment_if_needed(today_kst, st.session_state.all_gsheet_data)
        if success:
            st.success(message)
            st.session_state.all_gsheet_data = get_all_records_from_gsheet() # 데이터 새로고침
        elif "이미 완료" in message:
            st.info(message)
        elif message: # 다른 메시지 (오류 등)
            st.warning(message)
    st.session_state.last_auto_assignment_check_date = today_kst


st.title("조모임 공간 통합 예약")
st.caption(f"현재 시간 (KST): {get_kst_now().strftime('%Y-%m-%d %H:%M:%S')}")

# --- 관리자 모드 ---
with st.sidebar:
    st.header("⚙️ 앱 설정")
    if st.button("🔄 정보 새로고침 (Google Sheet)", use_container_width=True):
        st.session_state.all_gsheet_data = get_all_records_from_gsheet()
        st.session_state.gsheet_worksheet = None # 캐시된 워크시트 연결도 초기화
        st.rerun()
    st.subheader("🔑 관리자 모드")
    admin_pw_input = st.text_input("관리자 비밀번호", type="password", key="admin_pw_input")
    if admin_pw_input == ADMIN_PASSWORD:
        st.session_state.admin_mode = True
        st.success("관리자 모드 활성화됨")
    elif admin_pw_input != "" :
        st.error("비밀번호 불일치"); st.session_state.admin_mode = False

# --- 메시지 표시 ---
if st.session_state.form_message:
    msg_type, msg_content = st.session_state.form_message
    if msg_type == "success": st.success(msg_content)
    elif msg_type == "error": st.error(msg_content)
    elif msg_type == "warning": st.warning(msg_content)
    elif msg_type == "info": st.info(msg_content)
    st.session_state.form_message = None # 한 번만 표시


# --- 1. 오늘 예약 현황 ---
st.header(f"🗓️ 오늘 ({today_kst.strftime('%Y년 %m월 %d일')}) 예약 현황")
active_reservations_today = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)

if not active_reservations_today:
    st.info("오늘 예약된 조모임 공간이 없습니다.")
else:
    # 시간대별, 공간별 현황판 만들기 (Pandas DataFrame 사용)
    status_display_data = []
    # 모든 시간 슬롯 (자동 + 자율) 정의
    all_time_points = {}
    auto_assign_start_kst_naive = datetime.datetime.combine(today_kst, AUTO_ROTATION_TIME_START)
    all_time_points[f"11:30-13:00 (자동)"] = KST.localize(auto_assign_start_kst_naive)

    for key, (start_time, _) in FREE_RESERVATION_SLOTS.items():
        free_slot_start_kst_naive = datetime.datetime.combine(today_kst, start_time)
        all_time_points[key + " (자율)"] = KST.localize(free_slot_start_kst_naive)
    
    # 데이터프레임용 데이터 준비
    df_data = {slot_label: {space: "<span style='color:green;'>가능</span>" for space in ALL_SPACES_LIST} for slot_label in all_time_points.keys()}

    for res in active_reservations_today:
        res_start_kst = res.get('datetime_obj_kst')
        res_room = res.get(COL_ROOM)
        res_team = res.get(COL_TEAM)
        res_type = res.get(COL_RESERVATION_TYPE)
        
        # DataFrame의 어떤 행(시간 레이블)에 해당하는지 찾기
        target_slot_label = None
        for slot_label, slot_start_kst in all_time_points.items():
            if res_start_kst == slot_start_kst : # 시간대가 정확히 일치하는 경우
                 # 자동배정과 자율예약 시간이 겹칠 경우 유형으로 구분
                if (res_type == "자동배정" and "(자동)" in slot_label) or \
                   (res_type == "자율예약" and "(자율)" in slot_label and res_type != "자동배정"): # 자율예약은 자동배정 시간이 아닐때
                    target_slot_label = slot_label
                    break
        
        if target_slot_label and res_room in df_data[target_slot_label]:
            df_data[target_slot_label][res_room] = f"<span style='color:red;'>{res_team}</span>"

    df_status = pd.DataFrame(df_data).T # 시간 슬롯을 행으로
    
    # 컬럼 순서 정렬
    ordered_space_columns = [col for col in ALL_SPACES_LIST if col in df_status.columns]
    df_status = df_status[ordered_space_columns]
    
    if not df_status.empty:
        st.markdown(df_status.to_html(escape=False, index=True), unsafe_allow_html=True)
    else:
        st.info("현황 데이터를 표시할 수 없습니다.")


# --- 2. 자율 예약 하기 (13:00 - 16:00) ---
st.markdown("---")
st.header("🕒 자율 예약 (오늘 13:00 ~ 16:00)")

# 오늘 자율 예약 가능한지 확인
can_reserve_today_free = today_kst.weekday() in FREE_RESERVATION_ALLOWED_DAYS

if not can_reserve_today_free:
    st.warning(f"오늘은 ({get_day_korean(today_kst)}요일) 자율 예약이 불가능합니다.")
else:
    # 현재 활성 예약 (오늘) 가져오기 - 중복 체크 및 가능 슬롯 표시에 사용
    active_reservations_today_parsed = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)

    # 예약 폼
    selected_time_slot_key = st.selectbox(
        "예약 시간 선택:",
        options=list(FREE_RESERVATION_SLOTS.keys()),
        key="free_slot_selector"
    )
    
    if selected_time_slot_key:
        slot_start_time, _ = FREE_RESERVATION_SLOTS[selected_time_slot_key]
        slot_start_datetime_kst = KST.localize(datetime.datetime.combine(today_kst, slot_start_time))

        # 이 시간대에 예약 가능한 공간/팀 찾기
        reserved_spaces_at_slot = [r[COL_ROOM] for r in active_reservations_today_parsed if r.get('datetime_obj_kst') == slot_start_datetime_kst]
        available_spaces_at_slot = [s for s in ALL_SPACES_LIST if s not in reserved_spaces_at_slot]
        
        reserved_teams_at_slot = [r[COL_TEAM] for r in active_reservations_today_parsed if r.get('datetime_obj_kst') == slot_start_datetime_kst]
        available_teams_at_slot = [t for t in TEAMS_ALL if t not in reserved_teams_at_slot]

        # 예약 마감 시간 체크
        reservable_now = True
        reason = ""
        now_kst = get_kst_now()
        deadline_datetime_kst = slot_start_datetime_kst - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
        if now_kst > deadline_datetime_kst and not st.session_state.admin_mode:
            reservable_now = False
            reason = f"예약 마감 시간({deadline_datetime_kst.strftime('%H:%M')})이 지났습니다."
        if slot_start_datetime_kst < now_kst and not st.session_state.admin_mode: # 이미 지난 슬롯
            reservable_now = False
            reason = "이미 지난 시간입니다."

        if not reservable_now:
            st.warning(reason)

        with st.form("free_reservation_form"):
            selected_team = st.selectbox("조 선택:", available_teams_at_slot, key="free_team_selector")
            selected_space = st.selectbox("공간 선택:", available_spaces_at_slot, key="free_space_selector")
            
            submitted = st.form_submit_button(
                "예약 신청",
                type="primary",
                disabled=not reservable_now or not selected_team or not selected_space,
                use_container_width=True
            )

            if submitted:
                if not selected_team or not selected_space:
                    st.session_state.form_message = ("warning", "조와 공간을 모두 선택해주세요.")
                else:
                    booked_by_user = selected_team # 또는 st.user.email (Streamlit Cloud 인증 사용시)
                    success, message = add_free_reservation_to_gsheet(today_kst, selected_time_slot_key, selected_team, selected_space, booked_by_user)
                    st.session_state.form_message = ("success" if success else "error", message)
                    if success:
                        st.session_state.all_gsheet_data = get_all_records_from_gsheet() # 데이터 새로고침
                st.rerun()


# --- 3. 나의 예약 확인 및 취소 (자율 예약만) ---
st.markdown("---")
st.header("📝 나의 자율 예약 확인 및 취소")
my_team_for_view = st.selectbox("내 조 선택 (확인/취소용):", TEAMS_ALL, key="my_team_view_selector")

if my_team_for_view:
    my_free_reservations = []
    headers = st.session_state.all_gsheet_data[0] if st.session_state.all_gsheet_data else []
    for row_values in st.session_state.all_gsheet_data[1:]:
        res = parse_gsheet_row(row_values, headers)
        if res and res.get(COL_TEAM) == my_team_for_view and \
           res.get(COL_RESERVATION_TYPE) == "자율예약" and \
           res.get(COL_STATUS) == "예약됨" and \
           res.get('datetime_obj_kst') and res['datetime_obj_kst'].date() >= today_kst : # 오늘 이후 예약만
            my_free_reservations.append(res)
    
    my_free_reservations_sorted = sorted(my_free_reservations, key=lambda x: x.get('datetime_obj_kst', KST.localize(datetime.datetime.max)))

    if not my_free_reservations_sorted:
        st.info(f"'{my_team_for_view}' 조의 예정된 자율 예약이 없습니다.")
    else:
        for i, res_item in enumerate(my_free_reservations_sorted):
            dt_obj_kst = res_item.get('datetime_obj_kst')
            duration = res_item.get(COL_DURATION_MINUTES)
            time_label = dt_obj_kst.strftime('%H:%M') + f" (~{ (dt_obj_kst + datetime.timedelta(minutes=duration)).strftime('%H:%M') })" if duration else dt_obj_kst.strftime('%H:%M')
            
            can_cancel_this_item = False
            if dt_obj_kst:
                deadline_cancel_kst = dt_obj_kst - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
                if get_kst_now() < deadline_cancel_kst or st.session_state.admin_mode:
                    can_cancel_this_item = True
            
            item_id_for_cancel = res_item.get(COL_RESERVATION_ID)

            col_info, col_action = st.columns([4,1])
            with col_info:
                st.markdown(f"**{dt_obj_kst.strftime('%Y-%m-%d (%a)')} {time_label}** - `{res_item.get(COL_ROOM)}`")
            with col_action:
                if st.button("취소", key=f"cancel_{item_id_for_cancel}_{i}", disabled=not can_cancel_this_item, use_container_width=True):
                    cancelled_by_user = my_team_for_view # 또는 관리자 ID
                    if st.session_state.admin_mode: cancelled_by_user = "admin"
                    
                    success, message = cancel_reservation_in_gsheet(item_id_for_cancel, cancelled_by_user)
                    st.session_state.form_message = ("success" if success else "error", message)
                    if success:
                         st.session_state.all_gsheet_data = get_all_records_from_gsheet() # 데이터 새로고침
                    st.rerun()
            if not can_cancel_this_item and not st.session_state.admin_mode:
                 st.caption(f"취소 마감시간({deadline_cancel_kst.strftime('%H:%M')})이 지났습니다.", unsafe_allow_html=True)
            st.divider()


# --- (관리자용) 전체 기록 보기 ---
if st.session_state.admin_mode:
    st.markdown("---")
    st.header("👑 (관리자) 전체 예약 기록 (Google Sheet)")
    if not st.session_state.all_gsheet_data or len(st.session_state.all_gsheet_data) < 2:
        st.info("Google Sheet에 기록이 없습니다.")
    else:
        df_all_records = pd.DataFrame(st.session_state.all_gsheet_data[1:], columns=st.session_state.all_gsheet_data[0])
        # 최신 기록이 위로 오도록 정렬 (예약시작시간 기준 내림차순, 처리시각 기준 내림차순)
        try:
            df_all_records = df_all_records.sort_values(by=[COL_DATETIME_STR, COL_BOOKING_TIMESTAMP_STR], ascending=[False, False])
        except KeyError: # 정렬 기준 컬럼이 없을 경우 대비
            st.warning("정렬 기준 컬럼을 찾을 수 없어 원본 순서대로 표시합니다.")

        st.dataframe(df_all_records, use_container_width=True, height=400)
