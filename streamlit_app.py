import streamlit as st
import datetime
import pandas as pd
import json
import os
import pytz
import gspread
from google.oauth2.service_account import Credentials
from collections import defaultdict
import random

# --- 기본 설정 ---
KST = pytz.timezone('Asia/Seoul')
ALL_TEAMS_MASTER_LIST = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)] # 전체 팀 목록 (설정용)
ALL_SPACES_MASTER_LIST = ( # 전체 공간 목록 (설정용)
    [f"9층-{i}호" for i in range(1, 7)] +
    [f"지하5층-{i}호" for i in range(1, 4)]
)
ADMIN_PASSWORD = "admin"

# --- 자동 배정 기본값 ---
DEFAULT_AUTO_ROTATION_DAYS = [2, 6] # 수요일(2), 일요일(6)
DEFAULT_AUTO_ROTATION_TIME_START = datetime.time(11, 30)
DEFAULT_AUTO_ROTATION_DURATION_MINUTES = 90

# --- 자율 예약 설정 ---
FREE_RESERVATION_SLOTS = {
    "13:00-14:00": (datetime.time(13, 0), 60),
    "14:00-15:00": (datetime.time(14, 0), 60),
    "15:00-16:00": (datetime.time(15, 0), 60),
}
FREE_RESERVATION_ALLOWED_DAYS = [0,1,2,3,4,5,6]
RESERVATION_DEADLINE_MINUTES = 10

# --- Google Sheets 설정 ---
DEFAULT_CREDENTIALS_PATH = "google_credentials.json"
DEFAULT_SHEET_NAME = "조모임_통합_예약_내역_v2" # 시트 이름 변경 가능

# Google Sheet 컬럼명 (기존과 동일)
COL_DATETIME_STR = "예약시작시간_KST_ISO"
COL_DURATION_MINUTES = "지속시간_분"
COL_TEAM = "조이름"
COL_ROOM = "공간명"
COL_RESERVATION_TYPE = "예약유형"
COL_STATUS = "상태"
COL_BOOKING_TIMESTAMP_STR = "처리시각_KST_ISO"
COL_BOOKED_BY = "예약자"
COL_CANCELLATION_TIMESTAMP_STR = "취소시각_KST_ISO"
COL_CANCELLED_BY = "취소자"
COL_RESERVATION_ID = "예약ID"

GSHEET_HEADERS = [
    COL_RESERVATION_ID, COL_DATETIME_STR, COL_DURATION_MINUTES, COL_TEAM, COL_ROOM,
    COL_RESERVATION_TYPE, COL_STATUS, COL_BOOKING_TIMESTAMP_STR, COL_BOOKED_BY,
    COL_CANCELLATION_TIMESTAMP_STR, COL_CANCELLED_BY
]

# --- Helper Functions (기존과 동일) ---
def get_kst_now(): return datetime.datetime.now(KST)
def get_kst_today_date(): return get_kst_now().date()
def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]; return days[date_obj.weekday()]

# --- Google Sheets 연결 (기존과 동일) ---
@st.cache_resource(ttl=300) # 캐시 시간 조정 가능
def connect_to_gsheet():
    # ... (이전 코드와 동일한 연결 로직) ...
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
            if hasattr(gc, 'auth') and hasattr(gc.auth, 'service_account_email'):
                st.info(f"새 시트 '{sheet_name}'이(가) 생성되었습니다. 서비스 계정 이메일({gc.auth.service_account_email})에 편집 권한을 부여해주세요.")
            else:
                st.info(f"새 시트 '{sheet_name}'이(가) 생성되었습니다. 서비스 계정에 이 시트에 대한 편집 권한을 부여해주세요.")

        worksheet = sh.sheet1
        headers = worksheet.row_values(1)
        if not headers or any(h not in GSHEET_HEADERS for h in headers) or len(headers) != len(GSHEET_HEADERS):
            worksheet.clear()
            worksheet.update('A1', [GSHEET_HEADERS], value_input_option='USER_ENTERED')
            worksheet.freeze(rows=1)
            st.info(f"Google Sheet '{sheet_name}' 헤더를 표준 형식으로 업데이트했습니다.")
        return worksheet
    except Exception as e:
        st.error(f"Google Sheets 연결 실패: {e}")
        return None


def get_worksheet():
    if 'gsheet_worksheet' not in st.session_state or st.session_state.gsheet_worksheet is None:
        st.session_state.gsheet_worksheet = connect_to_gsheet()
    return st.session_state.gsheet_worksheet

# --- 데이터 로드 및 처리 (기존과 동일) ---
def get_all_records_from_gsheet():
    # ... (이전 코드와 동일) ...
    worksheet = get_worksheet()
    if not worksheet: return []
    try:
        return worksheet.get_all_values()
    except Exception as e:
        st.error(f"Google Sheets 데이터 로드 중 오류: {e}")
        st.session_state.gsheet_worksheet = None
        return []

def parse_gsheet_row(row_values, headers=GSHEET_HEADERS):
    # ... (이전 코드와 동일) ...
    if len(row_values) != len(headers): return None
    record = dict(zip(headers, row_values))
    try:
        if record.get(COL_DATETIME_STR):
            record['datetime_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_DATETIME_STR]))
        if record.get(COL_BOOKING_TIMESTAMP_STR):
            record['booking_timestamp_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_BOOKING_TIMESTAMP_STR]))
        if record.get(COL_CANCELLATION_TIMESTAMP_STR) and record[COL_CANCELLATION_TIMESTAMP_STR]: # 비어있지 않을 때만 파싱
            record['cancellation_timestamp_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_CANCELLATION_TIMESTAMP_STR]))
        if record.get(COL_DURATION_MINUTES):
            record[COL_DURATION_MINUTES] = int(record[COL_DURATION_MINUTES])
        return record
    except ValueError:
        return None

def get_active_reservations_for_day(target_date, all_sheet_data_with_headers):
    # ... (이전 코드와 동일) ...
    active_reservations = []
    if not all_sheet_data_with_headers or len(all_sheet_data_with_headers) < 2:
        return active_reservations

    headers = all_sheet_data_with_headers[0]
    for row_values in all_sheet_data_with_headers[1:]:
        record = parse_gsheet_row(row_values, headers)
        if record and record.get('datetime_obj_kst') and \
           record['datetime_obj_kst'].date() == target_date and \
           record.get(COL_STATUS) == "예약됨":
            active_reservations.append(record)
    return active_reservations

# --- 자동 배정 로직 (설정값 사용하도록 수정) ---
def run_auto_rotation_assignment_if_needed(target_date, all_sheet_data_with_headers,
                                           teams_for_auto_assign, spaces_for_auto_assign,
                                           auto_assign_days, auto_assign_time_start, auto_assign_duration_min):
    """필요한 경우 자동 로테이션 배정을 실행하고 시트에 기록합니다."""
    if not teams_for_auto_assign or not spaces_for_auto_assign:
        return False, "자동 배정에 사용할 조 또는 공간이 설정되지 않았습니다."
    if target_date.weekday() not in auto_assign_days:
        return False, "자동 배정 요일이 아닙니다."

    assignment_datetime_naive = datetime.datetime.combine(target_date, auto_assign_time_start)
    assignment_datetime_kst = KST.localize(assignment_datetime_naive)

    headers = all_sheet_data_with_headers[0] if all_sheet_data_with_headers else []
    for row_values in all_sheet_data_with_headers[1:]:
        record = parse_gsheet_row(row_values, headers)
        if record and record.get('datetime_obj_kst') == assignment_datetime_kst and \
           record.get(COL_RESERVATION_TYPE) == "자동배정" and record.get(COL_STATUS) == "예약됨":
            return False, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정이 이미 완료되었습니다."

    # 설정된 값으로 배정 실행
    teams_to_assign = list(teams_for_auto_assign) # 복사본 사용
    spaces_available = list(spaces_for_auto_assign) # 복사본 사용
    random.shuffle(teams_to_assign)
    # random.shuffle(spaces_available) # 공간 순서도 섞을 수 있음

    assignments = []
    num_assignments = min(len(teams_to_assign), len(spaces_available))
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
    reservation_id_prefix = assignment_datetime_naive.strftime('%Y%m%d%H%M')

    for i in range(num_assignments):
        team = teams_to_assign[i]
        space = spaces_available[i]
        # 예약 ID 생성 시 특수문자 제거 또는 변경 (시트 호환성)
        clean_space_name = "".join(filter(str.isalnum, space))
        reservation_id = f"AUTO_{reservation_id_prefix}_{clean_space_name}"


        new_assignment_row = [
            reservation_id,
            assignment_datetime_naive.isoformat(),
            auto_assign_duration_min,
            team,
            space,
            "자동배정",
            "예약됨",
            now_kst_iso,
            "시스템",
            "", ""
        ]
        assignments.append(new_assignment_row)

    if assignments:
        worksheet = get_worksheet()
        if worksheet:
            try:
                worksheet.append_rows(assignments, value_input_option='USER_ENTERED')
                # 성공 후 데이터 다시 로드
                st.session_state.all_gsheet_data = get_all_records_from_gsheet()
                return True, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정 완료 ({len(assignments)}건)."
            except Exception as e:
                return False, f"자동 배정 데이터 GSheet 저장 실패: {e}"
        else:
            return False, "Google Sheets에 연결되지 않아 자동 배정을 저장할 수 없습니다."
    return False, "배정할 팀 또는 공간이 부족합니다 (설정 확인)."


# --- 자율 예약 및 취소 로직 (기존과 동일) ---
def add_free_reservation_to_gsheet(selected_date, time_slot_key, team, space, booked_by):
    # ... (이전 코드와 동일) ...
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 예약할 수 없습니다."

    slot_start_time, slot_duration = FREE_RESERVATION_SLOTS[time_slot_key]
    reservation_datetime_naive = datetime.datetime.combine(selected_date, slot_start_time)
    reservation_datetime_kst = KST.localize(reservation_datetime_naive)
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
    clean_space_name_free = "".join(filter(str.isalnum, space))
    reservation_id = f"FREE_{reservation_datetime_naive.strftime('%Y%m%d%H%M')}_{clean_space_name_free}"


    # 중복 예약 확인 (시트에서 최신 정보 기준)
    all_data_for_check = get_all_records_from_gsheet() # 항상 최신 데이터로 확인
    st.session_state.all_gsheet_data = all_data_for_check # 세션 데이터도 업데이트

    active_reservations_for_slot = []
    headers_check = all_data_for_check[0] if all_data_for_check else []
    for row_val in all_data_for_check[1:]:
        rec = parse_gsheet_row(row_val, headers_check)
        if rec and rec.get('datetime_obj_kst') == reservation_datetime_kst and rec.get(COL_STATUS) == "예약됨":
            active_reservations_for_slot.append(rec)
    
    for res in active_reservations_for_slot:
        if res.get(COL_ROOM) == space:
            return False, f"오류: {space}은(는) 해당 시간에 이미 예약되어 있습니다."
        if res.get(COL_TEAM) == team: # 한 팀은 한 시간에 하나의 공간만 예약 가능
            return False, f"오류: {team} 조는 해당 시간에 이미 다른 공간('{res.get(COL_ROOM)}')을 예약했습니다."


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
        # 성공 후 데이터 다시 로드
        st.session_state.all_gsheet_data = get_all_records_from_gsheet()
        return True, f"{selected_date.strftime('%m/%d')} {time_slot_key} '{team}' 조 '{space}' 예약 완료."
    except Exception as e:
        return False, f"자율 예약 GSheet 저장 실패: {e}"


def cancel_reservation_in_gsheet(reservation_id_to_cancel, cancelled_by):
    # ... (이전 코드와 동일, 성공 시 데이터 다시 로드 추가) ...
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 취소할 수 없습니다."
    try:
        cell = worksheet.find(reservation_id_to_cancel, in_column=GSHEET_HEADERS.index(COL_RESERVATION_ID) + 1) # ID 컬럼 인덱스 사용
        if not cell:
            return False, f"예약 ID '{reservation_id_to_cancel}'을(를) 찾을 수 없습니다."

        row_index = cell.row
        now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
        status_col_index = GSHEET_HEADERS.index(COL_STATUS) + 1
        cancel_ts_col_index = GSHEET_HEADERS.index(COL_CANCELLATION_TIMESTAMP_STR) + 1
        cancelled_by_col_index = GSHEET_HEADERS.index(COL_CANCELLED_BY) + 1
        booking_ts_col_index = GSHEET_HEADERS.index(COL_BOOKING_TIMESTAMP_STR) + 1

        update_cells_data = [
            {'range': gspread.utils.rowcol_to_a1(row_index, status_col_index), 'values': [["취소됨"]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, cancel_ts_col_index), 'values': [[now_kst_iso]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, cancelled_by_col_index), 'values': [[cancelled_by]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, booking_ts_col_index), 'values': [[now_kst_iso]]},
        ]
        worksheet.batch_update(update_cells_data, value_input_option='USER_ENTERED')
        # 성공 후 데이터 다시 로드
        st.session_state.all_gsheet_data = get_all_records_from_gsheet()
        return True, f"예약 ID '{reservation_id_to_cancel}'이(가) 취소되었습니다."
    except gspread.exceptions.CellNotFound:
        return False, f"예약 ID '{reservation_id_to_cancel}'을(를) 시트에서 찾지 못했습니다."
    except Exception as e:
        st.error(f"Google Sheets 예약 취소 중 오류: {e}")
        return False, f"예약 취소 중 오류 발생: {e}"

# --- Streamlit UI ---
st.set_page_config(page_title="통합 조모임 공간 예약", layout="wide")
st.markdown("""<style>...</style>""", unsafe_allow_html=True) # 기존 CSS

# --- 세션 상태 초기화 ---
if 'admin_mode' not in st.session_state: st.session_state.admin_mode = False
if 'form_message' not in st.session_state: st.session_state.form_message = None
if 'all_gsheet_data' not in st.session_state:
    st.session_state.all_gsheet_data = get_all_records_from_gsheet()
if 'gsheet_worksheet' not in st.session_state:
    st.session_state.gsheet_worksheet = None # connect_to_gsheet 캐시용

# 자동 배정 설정 기본값 (세션에 없으면 초기화)
if 'auto_assign_teams_config' not in st.session_state:
    st.session_state.auto_assign_teams_config = ALL_TEAMS_MASTER_LIST[:8] # 예시: 앞 8팀 기본 선택
if 'auto_assign_spaces_config' not in st.session_state:
    st.session_state.auto_assign_spaces_config = ALL_SPACES_MASTER_LIST[:] # 예시: 모든 공간 기본 선택
if 'auto_assign_days_config' not in st.session_state:
    st.session_state.auto_assign_days_config = DEFAULT_AUTO_ROTATION_DAYS
if 'auto_assign_start_time_config' not in st.session_state:
    st.session_state.auto_assign_start_time_config = DEFAULT_AUTO_ROTATION_TIME_START
if 'auto_assign_duration_config' not in st.session_state:
    st.session_state.auto_assign_duration_config = DEFAULT_AUTO_ROTATION_DURATION_MINUTES


# --- 사이드바 설정 ---
with st.sidebar:
    st.header("⚙️ 앱 설정")
    st.subheader("🔑 관리자 모드")
    admin_pw_input = st.text_input("관리자 비밀번호", type="password", key="admin_pw_input_sidebar")
    if admin_pw_input == ADMIN_PASSWORD:
        if not st.session_state.admin_mode: st.toast("관리자 모드 활성화됨", icon="👑")
        st.session_state.admin_mode = True
    elif admin_pw_input != "" :
        if st.session_state.admin_mode: st.toast("관리자 모드 비활성화됨", icon="⚙️")
        st.error("비밀번호 불일치"); st.session_state.admin_mode = False
    
    if st.session_state.admin_mode:
        st.success("관리자 모드 활성화 중")

    st.markdown("---")
    st.subheader("🔄 자동 배정 설정")
    st.caption("점심시간(11:30-13:00) 자동 로테이션 설정")

    # 이 설정들은 관리자 모드에서만 변경 가능하게 할 수도 있음
    # 예: if st.session_state.admin_mode:
    st.session_state.auto_assign_teams_config = st.multiselect(
        "자동 배정 참여 조 선택:",
        options=ALL_TEAMS_MASTER_LIST,
        default=st.session_state.auto_assign_teams_config,
        key="ms_auto_teams"
    )
    st.session_state.auto_assign_spaces_config = st.multiselect(
        "자동 배정 사용 공간 선택:",
        options=ALL_SPACES_MASTER_LIST,
        default=st.session_state.auto_assign_spaces_config,
        key="ms_auto_spaces"
    )
    # 다른 자동 배정 설정 (요일, 시간 등)도 사이드바에서 변경 가능하게 할 수 있음 (여기서는 생략)

    if st.button("자동 배정 설정 저장", key="save_auto_settings_btn", use_container_width=True):
        # 현재는 세션 상태에 즉시 반영되므로 별도 저장은 필요 없으나,
        # 만약 설정을 파일이나 DB에 저장한다면 여기에 로직 추가
        st.toast("자동 배정 설정이 앱 세션에 반영되었습니다.", icon="👍")
        # 설정 변경 후 자동 배정 로직이 다시 평가되도록 rerun 할 수 있음
        # st.rerun() 


# --- 날짜 변경 감지 및 자동 배정 실행 ---
today_kst = get_kst_today_date()
if 'last_auto_assignment_check_date' not in st.session_state or \
   st.session_state.last_auto_assignment_check_date != today_kst :
    
    # 세션에서 설정값 가져오기
    teams_for_assignment = st.session_state.auto_assign_teams_config
    spaces_for_assignment = st.session_state.auto_assign_spaces_config
    days_for_assignment = st.session_state.auto_assign_days_config
    time_start_for_assignment = st.session_state.auto_assign_start_time_config
    duration_for_assignment = st.session_state.auto_assign_duration_config

    if today_kst.weekday() in days_for_assignment: # 설정된 자동 배정 요일
        st.info(f"오늘({today_kst.strftime('%m/%d')})은 자동 배정 요일입니다. 배정 상태를 확인합니다...")
        success, message = run_auto_rotation_assignment_if_needed(
            today_kst, st.session_state.all_gsheet_data,
            teams_for_assignment, spaces_for_assignment,
            days_for_assignment, time_start_for_assignment, duration_for_assignment
        )
        if success:
            st.session_state.form_message = ("success", message)
            # run_auto_rotation_assignment_if_needed 내부에서 이미 데이터 로드함
        elif "이미 완료" in message or "요일이 아닙니다" in message or "설정되지 않았습니다" in message:
             st.session_state.form_message = ("info", message)
        elif message : # 다른 오류
            st.session_state.form_message = ("warning", message)
    st.session_state.last_auto_assignment_check_date = today_kst
    if st.session_state.form_message : st.rerun() # 메시지 표시 및 UI 업데이트 위해


st.title("조모임 공간 통합 예약")
st.caption(f"현재 시간 (KST): {get_kst_now().strftime('%Y-%m-%d %H:%M:%S')}")

if st.session_state.form_message:
    msg_type, msg_content = st.session_state.form_message
    if msg_type == "success": st.success(msg_content)
    elif msg_type == "error": st.error(msg_content)
    elif msg_type == "warning": st.warning(msg_content)
    elif msg_type == "info": st.info(msg_content)
    st.session_state.form_message = None


# --- 1. 오늘 예약 현황 (UI 기존과 유사하게 유지) ---
st.header(f"🗓️ 오늘 ({today_kst.strftime('%Y년 %m월 %d일')}) 예약 현황")
active_reservations_today = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)

if not active_reservations_today:
    st.info("오늘 예약된 조모임 공간이 없습니다.")
else:
    all_time_points = {}
    auto_assign_start_kst_naive = datetime.datetime.combine(today_kst, st.session_state.auto_assign_start_time_config)
    auto_assign_duration = st.session_state.auto_assign_duration_config
    auto_assign_end_time = (datetime.datetime.combine(datetime.date.min, st.session_state.auto_assign_start_time_config) + datetime.timedelta(minutes=auto_assign_duration)).time()
    
    all_time_points[f"{st.session_state.auto_assign_start_time_config.strftime('%H:%M')}~{auto_assign_end_time.strftime('%H:%M')} (자동)"] = KST.localize(auto_assign_start_kst_naive)

    for key, (start_time, dur) in FREE_RESERVATION_SLOTS.items():
        free_slot_start_kst_naive = datetime.datetime.combine(today_kst, start_time)
        all_time_points[key + " (자율)"] = KST.localize(free_slot_start_kst_naive)
    
    # 전체 공간 목록은 사이드바 설정값이 아닌 마스터 리스트를 사용 (모든 공간 현황 표시)
    df_data = {slot_label: {space: "<span style='color:green;'>가능</span>" for space in ALL_SPACES_MASTER_LIST} for slot_label in all_time_points.keys()}

    for res in active_reservations_today:
        res_start_kst = res.get('datetime_obj_kst')
        res_room = res.get(COL_ROOM)
        res_team = res.get(COL_TEAM)
        res_type = res.get(COL_RESERVATION_TYPE)
        
        target_slot_label = None
        for slot_label, slot_start_kst_map_val in all_time_points.items():
            if res_start_kst == slot_start_kst_map_val :
                if (res_type == "자동배정" and "(자동)" in slot_label) or \
                   (res_type == "자율예약" and "(자율)" in slot_label and res_type != "자동배정"):
                    target_slot_label = slot_label
                    break
        
        if target_slot_label and res_room in df_data[target_slot_label]:
            df_data[target_slot_label][res_room] = f"<span style='color:red;'>{res_team}</span>"

    df_status = pd.DataFrame(df_data).T
    
    ordered_space_columns_display = [col for col in ALL_SPACES_MASTER_LIST if col in df_status.columns]
    if ordered_space_columns_display: # df_status에 열이 있을 때만
      df_status = df_status[ordered_space_columns_display]
    
    if not df_status.empty:
        st.markdown(df_status.to_html(escape=False, index=True), unsafe_allow_html=True)
    # else: 현황 데이터 없을 시 메시지는 이미 위에서 처리


# --- 2. 자율 예약 하기 (UI 기존과 유사) ---
# ... (이전 자율 예약 UI 코드와 동일하게 유지) ...
# 단, add_free_reservation_to_gsheet 호출 후 st.rerun() 추가 및 메시지 처리
st.markdown("---")
st.header("🕒 자율 예약 (오늘 13:00 ~ 16:00)")
can_reserve_today_free = today_kst.weekday() in FREE_RESERVATION_ALLOWED_DAYS
if not can_reserve_today_free:
    st.warning(f"오늘은 ({get_day_korean(today_kst)}요일) 자율 예약이 불가능합니다.")
else:
    active_reservations_today_parsed_free = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)
    selected_time_slot_key_free = st.selectbox("예약 시간 선택:", options=list(FREE_RESERVATION_SLOTS.keys()), key="free_slot_selector_main")
    
    if selected_time_slot_key_free:
        slot_start_time_free, _ = FREE_RESERVATION_SLOTS[selected_time_slot_key_free]
        slot_start_datetime_kst_free = KST.localize(datetime.datetime.combine(today_kst, slot_start_time_free))

        reserved_spaces_at_slot_free = [r[COL_ROOM] for r in active_reservations_today_parsed_free if r.get('datetime_obj_kst') == slot_start_datetime_kst_free]
        available_spaces_at_slot_free = [s for s in ALL_SPACES_MASTER_LIST if s not in reserved_spaces_at_slot_free] # 마스터 리스트 사용
        
        # 특정 시간에 이미 예약한 팀은 해당 시간의 다른 공간/다른 팀 예약 불가
        teams_already_booked_at_slot = [r[COL_TEAM] for r in active_reservations_today_parsed_free if r.get('datetime_obj_kst') == slot_start_datetime_kst_free]
        available_teams_at_slot_free = [t for t in ALL_TEAMS_MASTER_LIST if t not in teams_already_booked_at_slot] # 마스터 리스트 사용

        reservable_now_free = True
        reason_free = ""
        now_kst_free = get_kst_now()
        deadline_datetime_kst_free = slot_start_datetime_kst_free - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
        if now_kst_free > deadline_datetime_kst_free and not st.session_state.admin_mode:
            reservable_now_free = False; reason_free = f"예약 마감 시간({deadline_datetime_kst_free.strftime('%H:%M')})이 지났습니다."
        if slot_start_datetime_kst_free < now_kst_free and not st.session_state.admin_mode:
            reservable_now_free = False; reason_free = "이미 지난 시간입니다."

        if not reservable_now_free: st.warning(reason_free)

        with st.form("free_reservation_form_main"):
            selected_team_free = st.selectbox("조 선택:", available_teams_at_slot_free, key="free_team_selector_main", disabled=not available_teams_at_slot_free)
            selected_space_free = st.selectbox("공간 선택:", available_spaces_at_slot_free, key="free_space_selector_main", disabled=not available_spaces_at_slot_free)
            
            submitted_free = st.form_submit_button("예약 신청", type="primary",
                disabled=not reservable_now_free or not selected_team_free or not selected_space_free,
                use_container_width=True)

            if submitted_free:
                if not selected_team_free or not selected_space_free:
                    st.session_state.form_message = ("warning", "조와 공간을 모두 선택해주세요.")
                else:
                    booked_by_user_free = selected_team_free
                    success_free, message_free = add_free_reservation_to_gsheet(today_kst, selected_time_slot_key_free, selected_team_free, selected_space_free, booked_by_user_free)
                    st.session_state.form_message = ("success" if success_free else "error", message_free)
                st.rerun()


# --- 3. 나의 예약 확인 및 취소 (UI 기존과 유사) ---
# ... (이전 나의 예약 UI 코드와 동일하게 유지) ...
# 단, cancel_reservation_in_gsheet 호출 후 st.rerun() 추가 및 메시지 처리
st.markdown("---")
st.header("📝 나의 자율 예약 확인 및 취소")
my_team_for_view_main = st.selectbox("내 조 선택 (확인/취소용):", ALL_TEAMS_MASTER_LIST, key="my_team_view_selector_main") # 마스터 리스트 사용

if my_team_for_view_main:
    my_free_reservations_main = []
    headers_main_view = st.session_state.all_gsheet_data[0] if st.session_state.all_gsheet_data else []
    for row_values_mv in st.session_state.all_gsheet_data[1:]:
        res_mv = parse_gsheet_row(row_values_mv, headers_main_view)
        if res_mv and res_mv.get(COL_TEAM) == my_team_for_view_main and \
           res_mv.get(COL_RESERVATION_TYPE) == "자율예약" and \
           res_mv.get(COL_STATUS) == "예약됨" and \
           res_mv.get('datetime_obj_kst') and res_mv['datetime_obj_kst'].date() >= today_kst :
            my_free_reservations_main.append(res_mv)
    
    my_free_reservations_sorted_main = sorted(my_free_reservations_main, key=lambda x: x.get('datetime_obj_kst', KST.localize(datetime.datetime.max)))

    if not my_free_reservations_sorted_main:
        st.info(f"'{my_team_for_view_main}' 조의 예정된 자율 예약이 없습니다.")
    else:
        for i_mv, res_item_mv in enumerate(my_free_reservations_sorted_main):
            dt_obj_kst_mv = res_item_mv.get('datetime_obj_kst')
            duration_mv = res_item_mv.get(COL_DURATION_MINUTES)
            time_label_mv = dt_obj_kst_mv.strftime('%H:%M') + (f" (~{ (dt_obj_kst_mv + datetime.timedelta(minutes=duration_mv)).strftime('%H:%M') })" if duration_mv else "")
            
            can_cancel_this_item_mv = False
            deadline_cancel_kst_mv_str = "N/A"
            if dt_obj_kst_mv:
                deadline_cancel_kst_mv = dt_obj_kst_mv - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
                deadline_cancel_kst_mv_str = deadline_cancel_kst_mv.strftime('%H:%M')
                if get_kst_now() < deadline_cancel_kst_mv or st.session_state.admin_mode:
                    can_cancel_this_item_mv = True
            
            item_id_for_cancel_mv = res_item_mv.get(COL_RESERVATION_ID)

            col_info_mv, col_action_mv = st.columns([4,1])
            with col_info_mv:
                st.markdown(f"**{dt_obj_kst_mv.strftime('%Y-%m-%d (%a)')} {time_label_mv}** - `{res_item_mv.get(COL_ROOM)}` (ID: `{item_id_for_cancel_mv}`)")
            with col_action_mv:
                if st.button("취소", key=f"cancel_main_{item_id_for_cancel_mv}_{i_mv}", disabled=not can_cancel_this_item_mv or not item_id_for_cancel_mv, use_container_width=True):
                    cancelled_by_user_mv = my_team_for_view_main
                    if st.session_state.admin_mode: cancelled_by_user_mv = "admin"
                    
                    success_mv, message_mv = cancel_reservation_in_gsheet(item_id_for_cancel_mv, cancelled_by_user_mv)
                    st.session_state.form_message = ("success" if success_mv else "error", message_mv)
                    st.rerun()
            if not can_cancel_this_item_mv and not st.session_state.admin_mode:
                 st.caption(f"취소 마감({deadline_cancel_kst_mv_str})", unsafe_allow_html=True)
            st.divider()

# --- (관리자용) 전체 기록 보기 (UI 기존과 유사) ---
# ... (이전 관리자 UI 코드와 동일하게 유지) ...
if st.session_state.admin_mode:
    st.markdown("---")
    st.header("👑 (관리자) 전체 예약 기록 (Google Sheet)")
    if not st.session_state.all_gsheet_data or len(st.session_state.all_gsheet_data) < 2:
        st.info("Google Sheet에 기록이 없습니다.")
    else:
        # 데이터프레임으로 변환 시, 모든 값이 문자열로 들어올 수 있음을 감안
        df_all_records_admin = pd.DataFrame(st.session_state.all_gsheet_data[1:], columns=st.session_state.all_gsheet_data[0])
        try:
            # 정렬 전에 datetime 컬럼들을 datetime 객체로 변환 시도 (오류 발생 가능성 있음)
            # df_all_records_admin[COL_DATETIME_STR] = pd.to_datetime(df_all_records_admin[COL_DATETIME_STR], errors='coerce')
            # df_all_records_admin[COL_BOOKING_TIMESTAMP_STR] = pd.to_datetime(df_all_records_admin[COL_BOOKING_TIMESTAMP_STR], errors='coerce')
            # NaT 처리 후 정렬
            # df_all_records_admin = df_all_records_admin.sort_values(by=[COL_DATETIME_STR, COL_BOOKING_TIMESTAMP_STR], ascending=[False, False], na_position='last')
            # 단순 문자열 정렬로 유지 (데이터 변환 복잡성 회피)
             df_all_records_admin = df_all_records_admin.sort_values(by=[GSHEET_HEADERS[1], GSHEET_HEADERS[7]], ascending=[False, False])


        except KeyError:
            st.warning("정렬 기준 컬럼을 찾을 수 없어 원본 순서대로 표시합니다.")
        except Exception as e_sort:
            st.warning(f"데이터 정렬 중 오류: {e_sort}. 원본 순서대로 표시합니다.")


        st.dataframe(df_all_records_admin, use_container_width=True, height=400)
