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
ALL_TEAMS_MASTER_LIST = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)] + ["시니어"] # "시니어" 조 추가
ALL_SPACES_MASTER_LIST = (
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
FREE_RESERVATION_ALLOWED_DAYS = [0,1,2,3,4,5,6] # 모든 요일 자율 예약 가능 (테스트 모드 시 무시)
RESERVATION_DEADLINE_MINUTES = 10

# --- Google Sheets 설정 (기존과 동일) ---
DEFAULT_CREDENTIALS_PATH = "google_credentials.json"
DEFAULT_SHEET_NAME = "조모임_통합_예약_내역_v2"
COL_DATETIME_STR = "예약시작시간_KST_ISO"
COL_DURATION_MINUTES = "지속시간_분"
# ... (다른 GSHEET_HEADERS 및 컬럼명 정의는 이전과 동일) ...
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
@st.cache_resource(ttl=300)
def connect_to_gsheet():
    # ... (이전 코드와 동일) ...
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
        if record.get(COL_CANCELLATION_TIMESTAMP_STR) and record[COL_CANCELLATION_TIMESTAMP_STR]:
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


# --- 자동 배정 로직 (테스트 모드 반영) ---
def run_auto_rotation_assignment_if_needed(target_date, all_sheet_data_with_headers,
                                           teams_for_auto_assign, spaces_for_auto_assign,
                                           auto_assign_days, auto_assign_time_start, auto_assign_duration_min,
                                           is_test_mode=False): # 테스트 모드 인자 추가
    """필요한 경우 자동 로테이션 배정을 실행하고 시트에 기록합니다."""
    if not teams_for_auto_assign or not spaces_for_auto_assign:
        return False, "자동 배정에 사용할 조 또는 공간이 설정되지 않았습니다."
    
    # 테스트 모드가 아니면 요일 체크
    if not is_test_mode and target_date.weekday() not in auto_assign_days:
        return False, "자동 배정 요일이 아닙니다."

    assignment_datetime_naive = datetime.datetime.combine(target_date, auto_assign_time_start)
    assignment_datetime_kst = KST.localize(assignment_datetime_naive)

    headers = all_sheet_data_with_headers[0] if all_sheet_data_with_headers else []
    for row_values in all_sheet_data_with_headers[1:]:
        record = parse_gsheet_row(row_values, headers)
        if record and record.get('datetime_obj_kst') == assignment_datetime_kst and \
           record.get(COL_RESERVATION_TYPE) == "자동배정" and record.get(COL_STATUS) == "예약됨":
            # 이미 배정된 경우, 테스트 모드여도 추가 배정 안 함
            return False, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정이 이미 완료되었습니다."

    teams_to_assign = list(teams_for_auto_assign)
    spaces_available = list(spaces_for_auto_assign)
    random.shuffle(teams_to_assign)

    assignments = []
    num_assignments = min(len(teams_to_assign), len(spaces_available))
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
    reservation_id_prefix = assignment_datetime_naive.strftime('%Y%m%d%H%M')

    for i in range(num_assignments):
        team = teams_to_assign[i]
        space = spaces_available[i]
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
            "시스템" + (" (테스트)" if is_test_mode else ""), # 예약자에 테스트 모드 명시
            "", ""
        ]
        assignments.append(new_assignment_row)

    if assignments:
        worksheet = get_worksheet()
        if worksheet:
            try:
                worksheet.append_rows(assignments, value_input_option='USER_ENTERED')
                st.session_state.all_gsheet_data = get_all_records_from_gsheet()
                return True, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정 완료 ({len(assignments)}건)." + (" [테스트 모드]" if is_test_mode else "")
            except Exception as e:
                return False, f"자동 배정 데이터 GSheet 저장 실패: {e}"
        else:
            return False, "Google Sheets에 연결되지 않아 자동 배정을 저장할 수 없습니다."
    return False, "배정할 팀 또는 공간이 부족합니다 (설정 확인)."


# --- 자율 예약 및 취소 로직 (기존과 동일, add_free_reservation_to_gsheet은 내부에서 최신 데이터 로드) ---
def add_free_reservation_to_gsheet(selected_date, time_slot_key, team, space, booked_by, is_test_mode=False):
    # ... (이전 코드와 동일, booked_by에 테스트 모드 명시 가능) ...
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 예약할 수 없습니다."

    slot_start_time, slot_duration = FREE_RESERVATION_SLOTS[time_slot_key]
    reservation_datetime_naive = datetime.datetime.combine(selected_date, slot_start_time)
    reservation_datetime_kst = KST.localize(reservation_datetime_naive)
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
    clean_space_name_free = "".join(filter(str.isalnum, space))
    reservation_id = f"FREE_{reservation_datetime_naive.strftime('%Y%m%d%H%M')}_{clean_space_name_free}"

    all_data_for_check = get_all_records_from_gsheet()
    st.session_state.all_gsheet_data = all_data_for_check

    active_reservations_for_slot = []
    headers_check = all_data_for_check[0] if all_data_for_check else []
    for row_val in all_data_for_check[1:]:
        rec = parse_gsheet_row(row_val, headers_check)
        if rec and rec.get('datetime_obj_kst') == reservation_datetime_kst and rec.get(COL_STATUS) == "예약됨":
            active_reservations_for_slot.append(rec)
    
    for res in active_reservations_for_slot:
        if res.get(COL_ROOM) == space:
            return False, f"오류: {space}은(는) 해당 시간에 이미 예약되어 있습니다."
        if res.get(COL_TEAM) == team:
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
        booked_by + (" (테스트)" if is_test_mode else ""),
        "", ""
    ]
    try:
        worksheet.append_row(new_reservation_row, value_input_option='USER_ENTERED')
        st.session_state.all_gsheet_data = get_all_records_from_gsheet()
        return True, f"{selected_date.strftime('%m/%d')} {time_slot_key} '{team}' 조 '{space}' 예약 완료." + (" [테스트 모드]" if is_test_mode else "")
    except Exception as e:
        return False, f"자율 예약 GSheet 저장 실패: {e}"

def cancel_reservation_in_gsheet(reservation_id_to_cancel, cancelled_by, is_test_mode=False):
    # ... (이전 코드와 동일, cancelled_by에 테스트 모드 명시 가능) ...
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 취소할 수 없습니다."
    try:
        cell = worksheet.find(reservation_id_to_cancel, in_column=GSHEET_HEADERS.index(COL_RESERVATION_ID) + 1)
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
            {'range': gspread.utils.rowcol_to_a1(row_index, cancelled_by_col_index), 'values': [[cancelled_by + (" (테스트)" if is_test_mode else "")]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, booking_ts_col_index), 'values': [[now_kst_iso]]}, # 처리 시각도 업데이트
        ]
        worksheet.batch_update(update_cells_data, value_input_option='USER_ENTERED')
        st.session_state.all_gsheet_data = get_all_records_from_gsheet()
        return True, f"예약 ID '{reservation_id_to_cancel}'이(가) 취소되었습니다." + (" [테스트 모드]" if is_test_mode else "")
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
if 'test_mode' not in st.session_state: st.session_state.test_mode = False # 테스트 모드 추가
if 'form_message' not in st.session_state: st.session_state.form_message = None
if 'all_gsheet_data' not in st.session_state:
    st.session_state.all_gsheet_data = get_all_records_from_gsheet()
if 'gsheet_worksheet' not in st.session_state:
    st.session_state.gsheet_worksheet = None

if 'auto_assign_teams_config' not in st.session_state:
    st.session_state.auto_assign_teams_config = ALL_TEAMS_MASTER_LIST[:8]
if 'auto_assign_spaces_config' not in st.session_state:
    st.session_state.auto_assign_spaces_config = ALL_SPACES_MASTER_LIST[:]
if 'auto_assign_days_config' not in st.session_state:
    st.session_state.auto_assign_days_config = DEFAULT_AUTO_ROTATION_DAYS
if 'auto_assign_start_time_config' not in st.session_state:
    st.session_state.auto_assign_start_time_config = DEFAULT_AUTO_ROTATION_TIME_START
if 'auto_assign_duration_config' not in st.session_state:
    st.session_state.auto_assign_duration_config = DEFAULT_AUTO_ROTATION_DURATION_MINUTES

# --- 사이드바 설정 ---
with st.sidebar:
    st.header("⚙️ 앱 설정")
    # 테스트 모드 체크박스
    st.session_state.test_mode = st.checkbox("🧪 테스트 모드 활성화", value=st.session_state.test_mode, key="cb_test_mode",
                                             help="요일 제한 없이 오늘 날짜로 자동 배정 및 자율 예약 가능 (마감 시간은 적용됨)")
    if st.session_state.test_mode:
        st.warning("테스트 모드가 활성화되어 있습니다.")

    st.subheader("🔑 관리자 모드")
    admin_pw_input = st.text_input("관리자 비밀번호", type="password", key="admin_pw_input_sidebar")
    if admin_pw_input == ADMIN_PASSWORD:
        if not st.session_state.admin_mode: st.toast("관리자 모드 활성화됨", icon="👑")
        st.session_state.admin_mode = True
    elif admin_pw_input != "" :
        if st.session_state.admin_mode: st.toast("관리자 모드 비활성화됨", icon="⚙️")
        st.error("비밀번호 불일치"); st.session_state.admin_mode = False
    if st.session_state.admin_mode: st.success("관리자 모드 활성화 중")

    st.markdown("---")
    st.subheader("🔄 자동 배정 설정")
    st.caption(f"점심시간({st.session_state.auto_assign_start_time_config.strftime('%H:%M')}~"
               f"{(datetime.datetime.combine(datetime.date.min, st.session_state.auto_assign_start_time_config) + datetime.timedelta(minutes=st.session_state.auto_assign_duration_config)).time().strftime('%H:%M')}) 자동 로테이션 설정")

    st.session_state.auto_assign_teams_config = st.multiselect("자동 배정 참여 조 선택:", options=ALL_TEAMS_MASTER_LIST, default=st.session_state.auto_assign_teams_config, key="ms_auto_teams_sidebar")
    st.session_state.auto_assign_spaces_config = st.multiselect("자동 배정 사용 공간 선택:", options=ALL_SPACES_MASTER_LIST, default=st.session_state.auto_assign_spaces_config, key="ms_auto_spaces_sidebar")
    
    # 요일 설정도 사이드바에서 가능하게 하려면:
    # days_options = {"월":0, "화":1, "수":2, "목":3, "금":4, "토":5, "일":6}
    # selected_day_names = st.multiselect("자동 배정 요일:", options=list(days_options.keys()), 
    #                                     default=[name for name, idx in days_options.items() if idx in st.session_state.auto_assign_days_config],
    #                                     key="ms_auto_days_sidebar")
    # st.session_state.auto_assign_days_config = [days_options[name] for name in selected_day_names]


    if st.button("자동 배정 설정 저장", key="save_auto_settings_btn_sidebar", use_container_width=True):
        st.toast("자동 배정 설정이 앱 세션에 반영되었습니다.", icon="👍")
        # 설정 변경 후 자동 배정 로직이 즉시 재평가되도록 rerun
        st.rerun()


# --- 날짜 변경 감지 및 자동 배정 실행 ---
today_kst = get_kst_today_date()
if 'last_auto_assignment_check_date' not in st.session_state or \
   st.session_state.last_auto_assignment_check_date != today_kst or \
   st.session_state.get('force_auto_assign_check', False): # 강제 체크 플래그 (설정 변경 시 사용 가능)
    
    teams_for_assignment = st.session_state.auto_assign_teams_config
    spaces_for_assignment = st.session_state.auto_assign_spaces_config
    days_for_assignment = st.session_state.auto_assign_days_config
    time_start_for_assignment = st.session_state.auto_assign_start_time_config
    duration_for_assignment = st.session_state.auto_assign_duration_config
    current_test_mode = st.session_state.test_mode # 현재 테스트 모드 상태 가져오기

    # 테스트 모드가 켜져 있거나, 실제 자동 배정 요일인 경우에만 실행 시도
    if current_test_mode or (today_kst.weekday() in days_for_assignment):
        if current_test_mode and not (today_kst.weekday() in days_for_assignment) :
             st.info(f"테스트 모드로 오늘({today_kst.strftime('%m/%d')}) 자동 배정을 시도합니다.")
        else:
             st.info(f"오늘({today_kst.strftime('%m/%d')})은 자동 배정 요일입니다. 배정 상태를 확인합니다...")
        
        success, message = run_auto_rotation_assignment_if_needed(
            today_kst, st.session_state.all_gsheet_data,
            teams_for_assignment, spaces_for_assignment,
            days_for_assignment, time_start_for_assignment, duration_for_assignment,
            is_test_mode=current_test_mode # 테스트 모드 전달
        )
        if success:
            st.session_state.form_message = ("success", message)
        elif "이미 완료" in message or "요일이 아닙니다" in message or "설정되지 않았습니다" in message:
             st.session_state.form_message = ("info", message)
        elif message :
            st.session_state.form_message = ("warning", message)
    
    st.session_state.last_auto_assignment_check_date = today_kst
    st.session_state.pop('force_auto_assign_check', None) # 사용된 플래그 제거
    if st.session_state.form_message : st.rerun()


st.title("조모임 공간 통합 예약")
if st.session_state.test_mode: st.subheader("🧪 테스트 모드 동작 중 🧪", anchor=False)
st.caption(f"현재 시간 (KST): {get_kst_now().strftime('%Y-%m-%d %H:%M:%S')}")

if st.session_state.form_message:
    # ... (메시지 표시 로직은 동일) ...
    msg_type, msg_content = st.session_state.form_message
    if msg_type == "success": st.success(msg_content)
    elif msg_type == "error": st.error(msg_content)
    elif msg_type == "warning": st.warning(msg_content)
    elif msg_type == "info": st.info(msg_content)
    st.session_state.form_message = None


# --- 1. 오늘 예약 현황 ---
st.header(f"🗓️ 오늘 ({today_kst.strftime('%Y년 %m월 %d일')}) 예약 현황")
active_reservations_today = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)

# 현황판 생성 로직 (테스트 모드일 때 자동 배정 슬롯 표시 고려)
all_time_points_display = {}
auto_assign_start_time_cfg = st.session_state.auto_assign_start_time_config
auto_assign_duration_cfg = st.session_state.auto_assign_duration_config
auto_assign_days_cfg = st.session_state.auto_assign_days_config

# 테스트 모드이거나 실제 자동 배정 요일이면 자동 배정 시간 슬롯을 현황판에 추가
if st.session_state.test_mode or (today_kst.weekday() in auto_assign_days_cfg):
    auto_assign_start_kst_naive_display = datetime.datetime.combine(today_kst, auto_assign_start_time_cfg)
    auto_assign_end_time_display = (datetime.datetime.combine(datetime.date.min, auto_assign_start_time_cfg) + datetime.timedelta(minutes=auto_assign_duration_cfg)).time()
    all_time_points_display[f"{auto_assign_start_time_cfg.strftime('%H:%M')}~{auto_assign_end_time_display.strftime('%H:%M')} (자동)"] = KST.localize(auto_assign_start_kst_naive_display)

for key, (start_time, dur) in FREE_RESERVATION_SLOTS.items():
    free_slot_start_kst_naive_display = datetime.datetime.combine(today_kst, start_time)
    all_time_points_display[key + " (자율)"] = KST.localize(free_slot_start_kst_naive_display)

if not all_time_points_display: # 표시할 시간 슬롯이 없으면 (예: 자동 배정 요일 아니고 테스트 모드도 아님)
    st.info("오늘은 표시할 예약 시간대가 없습니다.")
elif not active_reservations_today and not all_time_points_display : # 예약도 없고 표시할 시간 슬롯도 없을 때 (위에서 처리될 가능성 높음)
    st.info("오늘 예약된 조모임 공간이 없습니다.")
else:
    df_data_display = {slot_label: {space: "<span style='color:green;'>가능</span>" for space in ALL_SPACES_MASTER_LIST} for slot_label in all_time_points_display.keys()}
    for res_disp in active_reservations_today:
        res_start_kst_disp = res_disp.get('datetime_obj_kst')
        res_room_disp = res_disp.get(COL_ROOM)
        res_team_disp = res_disp.get(COL_TEAM)
        res_type_disp = res_disp.get(COL_RESERVATION_TYPE)
        
        target_slot_label_disp = None
        for slot_label_disp, slot_start_kst_map_val_disp in all_time_points_display.items():
            if res_start_kst_disp == slot_start_kst_map_val_disp :
                if (res_type_disp == "자동배정" and "(자동)" in slot_label_disp) or \
                   (res_type_disp == "자율예약" and "(자율)" in slot_label_disp and res_type_disp != "자동배정"):
                    target_slot_label_disp = slot_label_disp
                    break
        
        if target_slot_label_disp and res_room_disp in df_data_display[target_slot_label_disp]:
            df_data_display[target_slot_label_disp][res_room_disp] = f"<span style='color:red;'>{res_team_disp}</span>"

    df_status_display = pd.DataFrame(df_data_display).T
    ordered_space_columns_display_final = [col for col in ALL_SPACES_MASTER_LIST if col in df_status_display.columns]
    if ordered_space_columns_display_final:
      df_status_display = df_status_display[ordered_space_columns_display_final]
    
    if not df_status_display.empty:
        st.markdown(df_status_display.to_html(escape=False, index=True), unsafe_allow_html=True)
    elif not active_reservations_today: # df_status는 비었지만 예약이 없는 경우
         st.info("오늘 예약된 조모임 공간이 없습니다.")


# --- 2. 자율 예약 하기 ---
st.markdown("---")
st.header("🕒 자율 예약 (오늘 13:00 ~ 16:00)")
# 테스트 모드이거나, 실제 자율 예약 가능한 요일이면 폼 표시
can_reserve_today_free_ui = st.session_state.test_mode or (today_kst.weekday() in FREE_RESERVATION_ALLOWED_DAYS)

if not can_reserve_today_free_ui:
    st.warning(f"오늘은 ({get_day_korean(today_kst)}요일) 자율 예약이 불가능합니다." + (" 테스트 모드를 사용해보세요." if not st.session_state.test_mode else ""))
else:
    if st.session_state.test_mode and not (today_kst.weekday() in FREE_RESERVATION_ALLOWED_DAYS):
        st.info("테스트 모드로 자율 예약이 가능합니다.")
        
    active_reservations_today_parsed_free = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)
    selected_time_slot_key_free = st.selectbox("예약 시간 선택:", options=list(FREE_RESERVATION_SLOTS.keys()), key="free_slot_selector_main_ui")
    
    if selected_time_slot_key_free:
        slot_start_time_free, _ = FREE_RESERVATION_SLOTS[selected_time_slot_key_free]
        slot_start_datetime_kst_free = KST.localize(datetime.datetime.combine(today_kst, slot_start_time_free))

        reserved_spaces_at_slot_free = [r[COL_ROOM] for r in active_reservations_today_parsed_free if r.get('datetime_obj_kst') == slot_start_datetime_kst_free]
        available_spaces_at_slot_free = [s for s in ALL_SPACES_MASTER_LIST if s not in reserved_spaces_at_slot_free]
        
        teams_already_booked_at_slot = [r[COL_TEAM] for r in active_reservations_today_parsed_free if r.get('datetime_obj_kst') == slot_start_datetime_kst_free]
        available_teams_at_slot_free = [t for t in ALL_TEAMS_MASTER_LIST if t not in teams_already_booked_at_slot]

        reservable_now_free = True
        reason_free = ""
        now_kst_free = get_kst_now()
        deadline_datetime_kst_free = slot_start_datetime_kst_free - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
        
        # 테스트 모드라도 마감 시간 및 이미 지난 시간 체크는 유지 (관리자는 무시)
        if not st.session_state.admin_mode:
            if now_kst_free > deadline_datetime_kst_free :
                reservable_now_free = False; reason_free = f"예약 마감 시간({deadline_datetime_kst_free.strftime('%H:%M')})이 지났습니다."
            if slot_start_datetime_kst_free < now_kst_free: # 이미 지난 슬롯
                reservable_now_free = False; reason_free = "이미 지난 시간입니다."

        if not reservable_now_free: st.warning(reason_free)

        with st.form("free_reservation_form_main_ui"):
            selected_team_free = st.selectbox("조 선택:", available_teams_at_slot_free, key="free_team_selector_main_ui", disabled=not available_teams_at_slot_free)
            selected_space_free = st.selectbox("공간 선택:", available_spaces_at_slot_free, key="free_space_selector_main_ui", disabled=not available_spaces_at_slot_free)
            
            submit_disabled_free = not reservable_now_free or not selected_team_free or not selected_space_free
            if st.session_state.admin_mode and (not selected_team_free or not selected_space_free): # 관리자는 팀/공간 없어도 제출은 가능하게 (메시지 처리)
                 submit_disabled_free = False


            submitted_free = st.form_submit_button("예약 신청", type="primary",
                disabled=submit_disabled_free,
                use_container_width=True)

            if submitted_free:
                if not selected_team_free or not selected_space_free: # 관리자도 팀/공간 선택 안하면 경고
                    st.session_state.form_message = ("warning", "조와 공간을 모두 선택해주세요.")
                else:
                    booked_by_user_free = selected_team_free
                    if st.session_state.admin_mode: booked_by_user_free = "admin" # 관리자가 예약시 admin으로 기록
                    
                    success_free, message_free = add_free_reservation_to_gsheet(
                        today_kst, selected_time_slot_key_free, selected_team_free, selected_space_free, 
                        booked_by_user_free, is_test_mode=st.session_state.test_mode
                    )
                    st.session_state.form_message = ("success" if success_free else "error", message_free)
                st.rerun()

# --- 3. 나의 예약 확인 및 취소 (테스트 모드일 때 취소자 명시) ---
st.markdown("---")
st.header("📝 나의 자율 예약 확인 및 취소")
my_team_for_view_main = st.selectbox("내 조 선택 (확인/취소용):", ALL_TEAMS_MASTER_LIST, key="my_team_view_selector_main_ui")

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
                # 테스트 모드여도 마감 시간은 체크, 관리자는 무시
                if st.session_state.admin_mode or get_kst_now() < deadline_cancel_kst_mv:
                    can_cancel_this_item_mv = True
            
            item_id_for_cancel_mv = res_item_mv.get(COL_RESERVATION_ID)

            col_info_mv, col_action_mv = st.columns([4,1])
            with col_info_mv:
                st.markdown(f"**{dt_obj_kst_mv.strftime('%Y-%m-%d (%a)')} {time_label_mv}** - `{res_item_mv.get(COL_ROOM)}` (ID: `{item_id_for_cancel_mv}`)")
            with col_action_mv:
                if st.button("취소", key=f"cancel_main_ui_{item_id_for_cancel_mv}_{i_mv}", disabled=not can_cancel_this_item_mv or not item_id_for_cancel_mv, use_container_width=True):
                    cancelled_by_user_mv = my_team_for_view_main
                    if st.session_state.admin_mode: cancelled_by_user_mv = "admin"
                    
                    success_mv, message_mv = cancel_reservation_in_gsheet(
                        item_id_for_cancel_mv, cancelled_by_user_mv, is_test_mode=st.session_state.test_mode
                    )
                    st.session_state.form_message = ("success" if success_mv else "error", message_mv)
                    st.rerun()
            if not can_cancel_this_item_mv and not st.session_state.admin_mode: # 관리자가 아닐 때만 마감 시간 메시지 표시
                 st.caption(f"취소 마감({deadline_cancel_kst_mv_str})", unsafe_allow_html=True)
            st.divider()

# --- (관리자용) 전체 기록 보기 (기존과 동일) ---
if st.session_state.admin_mode:
    # ... (이전 코드와 동일) ...
    st.markdown("---")
    st.header("👑 (관리자) 전체 예약 기록 (Google Sheet)")
    if not st.session_state.all_gsheet_data or len(st.session_state.all_gsheet_data) < 2:
        st.info("Google Sheet에 기록이 없습니다.")
    else:
        df_all_records_admin = pd.DataFrame(st.session_state.all_gsheet_data[1:], columns=st.session_state.all_gsheet_data[0])
        try:
             df_all_records_admin = df_all_records_admin.sort_values(by=[GSHEET_HEADERS[1], GSHEET_HEADERS[7]], ascending=[False, False]) # datetime_str, booking_timestamp_str
        except KeyError:
            st.warning("정렬 기준 컬럼을 찾을 수 없어 원본 순서대로 표시합니다.")
        except Exception as e_sort:
            st.warning(f"데이터 정렬 중 오류: {e_sort}. 원본 순서대로 표시합니다.")
        st.dataframe(df_all_records_admin, use_container_width=True, height=400)
