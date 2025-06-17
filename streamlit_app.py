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
ADMIN_PASSWORD = "admin" # 실제 사용시 보안 강화 필요

# --- 자동 배정 기본값 ---
DEFAULT_AUTO_ROTATION_DAYS = [2, 6] # 수요일(2), 일요일(6)
DEFAULT_AUTO_ROTATION_TIME_START = datetime.time(11, 30)
DEFAULT_AUTO_ROTATION_DURATION_MINUTES = 90

# --- 자율 예약 설정 ---
FREE_RESERVATION_SLOTS = { # 시간 슬롯 (표시용 레이블: (시작 시간, 지속 시간(분)))
    "13:00-14:00": (datetime.time(13, 0), 60),
    "14:00-15:00": (datetime.time(14, 0), 60),
    "15:00-16:00": (datetime.time(15, 0), 60),
}
FREE_RESERVATION_ALLOWED_DAYS = [0,1,2,3,4,5,6] # 모든 요일 자율 예약 가능 (테스트 모드 시 무시)
RESERVATION_DEADLINE_MINUTES = 10 # 슬롯 시작 X분 전까지 예약/취소 가능

# --- Google Sheets 설정 ---
DEFAULT_CREDENTIALS_PATH = "google_credentials.json" # 로컬 테스트 시 이 파일 필요
DEFAULT_SHEET_NAME = "조모임_통합_예약_내역_v3" # 시트 이름 변경 가능 (이전 버전과 구분)

# Google Sheet 컬럼명 (순서 중요)
COL_RESERVATION_ID = "예약ID" # 고유 식별자 (datetime_str + room) 또는 UUID
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

# --- Google Sheets 연결 ---
@st.cache_resource(ttl=300) # 캐시 시간 조정 (초 단위)
def connect_to_gsheet():
    try:
        # Streamlit Cloud Secrets 우선 사용
        if hasattr(st, 'secrets') and "google_sheets_credentials_json" in st.secrets:
            creds_json_str = st.secrets["google_sheets_credentials_json"]
            creds_dict = json.loads(creds_json_str)
            creds = Credentials.from_service_account_info(
                creds_dict,
                scopes=['https://www.googleapis.com/auth/spreadsheets',
                        'https://www.googleapis.com/auth/drive']
            )
            gc = gspread.authorize(creds)
            sheet_name = st.secrets.get("google_sheet_name", DEFAULT_SHEET_NAME)
        # 로컬 테스트용 (파일 경로 또는 환경 변수 사용)
        else:
            credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_CREDENTIALS_PATH)
            if not os.path.exists(credentials_path):
                st.error(f"Google Sheets 인증 파일({credentials_path})을 찾을 수 없습니다. README 또는 이전 설명을 확인하세요.")
                return None
            
            scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
            creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
            gc = gspread.authorize(creds)
            sheet_name = os.environ.get("GOOGLE_SHEET_NAME", DEFAULT_SHEET_NAME)

        try:
            sh = gc.open(sheet_name)
        except gspread.exceptions.SpreadsheetNotFound:
            st.warning(f"시트 '{sheet_name}'을(를) 찾을 수 없습니다. 새로 생성합니다.")
            sh = gc.create(sheet_name) # 새 시트 생성
            # 새 시트 생성 후 서비스 계정에 공유 권한 부여 필요 메시지
            if hasattr(gc, 'auth') and hasattr(gc.auth, 'service_account_email'):
                 st.info(f"새 시트 '{sheet_name}'이(가) 생성되었습니다. 서비스 계정 이메일({gc.auth.service_account_email})에 이 시트에 대한 편집 권한을 부여해주세요.")
            else:
                st.info(f"새 시트 '{sheet_name}'이(가) 생성되었습니다. 서비스 계정에 이 시트에 대한 편집 권한을 부여해주세요. (이메일 주소는 JSON 파일의 client_email 필드 확인)")


        worksheet = sh.sheet1 # 첫 번째 시트 사용
        
        # 헤더 확인 및 생성/업데이트
        current_headers = worksheet.row_values(1)
        # 헤더가 없거나, 정의된 헤더와 다르거나, 순서/개수가 다르면 업데이트
        if not current_headers or \
           any(h not in GSHEET_HEADERS for h in current_headers) or \
           any(h not in current_headers for h in GSHEET_HEADERS) or \
           len(current_headers) != len(GSHEET_HEADERS) or \
           current_headers != GSHEET_HEADERS : # 순서까지 정확히 일치하는지 확인
            worksheet.clear() # 기존 내용 모두 삭제 후 헤더부터 새로 쓰기
            worksheet.update('A1', [GSHEET_HEADERS], value_input_option='USER_ENTERED') # 헤더 새로 쓰기
            worksheet.freeze(rows=1) # 헤더 행 고정
            st.info(f"Google Sheet '{sheet_name}' 헤더를 표준 형식으로 업데이트했습니다.")
        return worksheet

    except Exception as e:
        st.error(f"Google Sheets 연결 실패 (connect_to_gsheet): {e}")
        import traceback
        st.error(traceback.format_exc()) # 스택 트레이스 출력
        return None

def get_worksheet():
    if 'gsheet_worksheet' not in st.session_state or st.session_state.gsheet_worksheet is None:
        st.session_state.gsheet_worksheet = connect_to_gsheet()
    return st.session_state.gsheet_worksheet

# --- 데이터 로드 및 처리 ---
def get_all_records_from_gsheet():
    worksheet = get_worksheet()
    if not worksheet: return [] # 연결 실패 시 빈 리스트
    try:
        return worksheet.get_all_values() # 헤더 포함 모든 값을 리스트의 리스트로
    except Exception as e:
        st.error(f"Google Sheets 데이터 로드 중 오류: {e}")
        st.session_state.gsheet_worksheet = None # 연결 오류 시 캐시 무효화
        return []

def parse_gsheet_row(row_values, headers=GSHEET_HEADERS):
    if len(row_values) != len(headers): return None # 데이터-헤더 길이 불일치
    record = dict(zip(headers, row_values))
    try:
        if record.get(COL_DATETIME_STR):
            record['datetime_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_DATETIME_STR]))
        if record.get(COL_BOOKING_TIMESTAMP_STR): # 예약 처리 시각
            record['booking_timestamp_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_BOOKING_TIMESTAMP_STR]))
        if record.get(COL_CANCELLATION_TIMESTAMP_STR) and record[COL_CANCELLATION_TIMESTAMP_STR].strip() != "": # 취소 시각 (비어있지 않을때만)
            record['cancellation_timestamp_obj_kst'] = KST.localize(datetime.datetime.fromisoformat(record[COL_CANCELLATION_TIMESTAMP_STR]))
        if record.get(COL_DURATION_MINUTES):
            record[COL_DURATION_MINUTES] = int(record[COL_DURATION_MINUTES])
        return record
    except ValueError: # 날짜/시간 파싱 오류 등
        return None 

def get_active_reservations_for_day(target_date, all_sheet_data_with_headers):
    active_reservations = []
    if not all_sheet_data_with_headers or len(all_sheet_data_with_headers) < 2: # 헤더만 있거나 비었으면
        return active_reservations

    headers = all_sheet_data_with_headers[0]
    for row_values in all_sheet_data_with_headers[1:]: # 헤더 제외하고 데이터 행만 처리
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
                                           is_test_mode=False):
    if not teams_for_auto_assign or not spaces_for_auto_assign:
        return False, "자동 배정에 사용할 조 또는 공간이 설정되지 않았습니다."
    
    if not is_test_mode and target_date.weekday() not in auto_assign_days:
        return False, "자동 배정 요일이 아닙니다."

    assignment_datetime_naive = datetime.datetime.combine(target_date, auto_assign_time_start)
    assignment_datetime_kst = KST.localize(assignment_datetime_naive)

    headers = all_sheet_data_with_headers[0] if all_sheet_data_with_headers else []
    for row_values in all_sheet_data_with_headers[1:]:
        record = parse_gsheet_row(row_values, headers)
        if record and record.get('datetime_obj_kst') == assignment_datetime_kst and \
           record.get(COL_RESERVATION_TYPE) == "자동배정" and record.get(COL_STATUS) == "예약됨":
            return False, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정이 이미 완료되었습니다."

    teams_to_assign = list(teams_for_auto_assign)
    spaces_available = list(spaces_for_auto_assign)
    random.shuffle(teams_to_assign) # 팀 순서 섞기

    assignments = []
    num_assignments = min(len(teams_to_assign), len(spaces_available))
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat() # KST naive ISO
    reservation_id_prefix = assignment_datetime_naive.strftime('%Y%m%d%H%M')

    for i in range(num_assignments):
        team = teams_to_assign[i]
        space = spaces_available[i] # 공간은 순서대로 배정 (섞고 싶으면 random.shuffle(spaces_available) 추가)
        clean_space_name = "".join(filter(str.isalnum, space)) # ID용으로 특수문자 제거
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
            "시스템" + (" (테스트)" if is_test_mode else ""),
            "", "" # 취소 관련 필드는 비워둠
        ]
        assignments.append(new_assignment_row)

    if assignments:
        worksheet = get_worksheet()
        if worksheet:
            try:
                worksheet.append_rows(assignments, value_input_option='USER_ENTERED')
                st.session_state.all_gsheet_data = get_all_records_from_gsheet() # 성공 후 데이터 즉시 새로고침
                return True, f"{target_date.strftime('%Y-%m-%d')} 점심시간 자동 배정 완료 ({len(assignments)}건)." + (" [테스트 모드]" if is_test_mode else "")
            except Exception as e:
                return False, f"자동 배정 데이터 GSheet 저장 실패: {e}"
        else:
            return False, "Google Sheets에 연결되지 않아 자동 배정을 저장할 수 없습니다."
    return False, "배정할 팀 또는 공간이 부족합니다 (설정 확인)."


# --- 자율 예약 및 취소 로직 ---
def add_free_reservation_to_gsheet(selected_date, time_slot_key, team, space, booked_by, is_test_mode=False):
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 예약할 수 없습니다."

    slot_start_time, slot_duration = FREE_RESERVATION_SLOTS[time_slot_key]
    reservation_datetime_naive = datetime.datetime.combine(selected_date, slot_start_time)
    reservation_datetime_kst = KST.localize(reservation_datetime_naive)
    now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()
    clean_space_name_free = "".join(filter(str.isalnum, space))
    reservation_id = f"FREE_{reservation_datetime_naive.strftime('%Y%m%d%H%M')}_{clean_space_name_free}"

    # 중복 예약 확인 (항상 최신 데이터 기준)
    all_data_for_check = get_all_records_from_gsheet()
    st.session_state.all_gsheet_data = all_data_for_check # 세션 데이터도 업데이트

    active_reservations_for_slot = []
    headers_check = all_data_for_check[0] if all_data_for_check else []
    for row_val in all_data_for_check[1:]:
        rec = parse_gsheet_row(row_val, headers_check)
        if rec and rec.get('datetime_obj_kst') == reservation_datetime_kst and rec.get(COL_STATUS) == "예약됨":
            active_reservations_for_slot.append(rec)
    
    for res in active_reservations_for_slot:
        if res.get(COL_ROOM) == space:
            return False, f"오류: '{space}'은(는) 해당 시간에 이미 예약되어 있습니다."
        if res.get(COL_TEAM) == team: # 한 팀은 한 시간에 하나의 공간만 예약 가능
            return False, f"오류: '{team}' 조는 해당 시간에 이미 다른 공간('{res.get(COL_ROOM)}')을 예약했습니다."

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
        st.session_state.all_gsheet_data = get_all_records_from_gsheet() # 성공 후 데이터 즉시 새로고침
        return True, f"{selected_date.strftime('%m/%d')} {time_slot_key} '{team}' 조 '{space}' 예약 완료." + (" [테스트 모드]" if is_test_mode else "")
    except Exception as e:
        return False, f"자율 예약 GSheet 저장 실패: {e}"

def cancel_reservation_in_gsheet(reservation_id_to_cancel, cancelled_by, is_test_mode=False):
    worksheet = get_worksheet()
    if not worksheet:
        return False, "Google Sheets에 연결되지 않아 취소할 수 없습니다."
    try:
        # 예약 ID로 해당 행 찾기 (COL_RESERVATION_ID는 정의된 헤더 리스트에서의 인덱스 + 1)
        id_column_index = GSHEET_HEADERS.index(COL_RESERVATION_ID) + 1
        cell = worksheet.find(reservation_id_to_cancel, in_column=id_column_index)
        if not cell:
            return False, f"예약 ID '{reservation_id_to_cancel}'을(를) 찾을 수 없습니다."

        row_index = cell.row
        now_kst_iso = get_kst_now().replace(tzinfo=None).isoformat()

        # 업데이트할 컬럼들의 인덱스 (1부터 시작)
        status_col_index = GSHEET_HEADERS.index(COL_STATUS) + 1
        cancel_ts_col_index = GSHEET_HEADERS.index(COL_CANCELLATION_TIMESTAMP_STR) + 1
        cancelled_by_col_index = GSHEET_HEADERS.index(COL_CANCELLED_BY) + 1
        booking_ts_col_index = GSHEET_HEADERS.index(COL_BOOKING_TIMESTAMP_STR) + 1 # 처리시각도 업데이트


        update_cells_data = [
            {'range': gspread.utils.rowcol_to_a1(row_index, status_col_index), 'values': [["취소됨"]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, cancel_ts_col_index), 'values': [[now_kst_iso]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, cancelled_by_col_index), 'values': [[cancelled_by + (" (테스트)" if is_test_mode else "")]]},
            {'range': gspread.utils.rowcol_to_a1(row_index, booking_ts_col_index), 'values': [[now_kst_iso]]},
        ]
        worksheet.batch_update(update_cells_data, value_input_option='USER_ENTERED')
        st.session_state.all_gsheet_data = get_all_records_from_gsheet() # 성공 후 데이터 즉시 새로고침
        return True, f"예약 ID '{reservation_id_to_cancel}'이(가) 취소되었습니다." + (" [테스트 모드]" if is_test_mode else "")

    except gspread.exceptions.CellNotFound: # find 실패 시
        return False, f"예약 ID '{reservation_id_to_cancel}'을(를) 시트에서 찾지 못했습니다."
    except Exception as e:
        st.error(f"Google Sheets 예약 취소 중 오류: {e}")
        return False, f"예약 취소 중 오류 발생: {e}"

# --- Streamlit UI ---
st.set_page_config(page_title="통합 조모임 공간 예약", layout="wide", initial_sidebar_state="auto")
# CSS 스타일 (필요시 추가)
st.markdown("""
    <style>
        .stMultiSelect [data-baseweb="tag"] {
            height: fit-content; # 멀티셀렉트 태그 높이 조절
        }
    </style>
""", unsafe_allow_html=True)

# --- 세션 상태 초기화 ---
if 'admin_mode' not in st.session_state: st.session_state.admin_mode = False
if 'test_mode' not in st.session_state: st.session_state.test_mode = False
if 'form_message' not in st.session_state: st.session_state.form_message = None # (type, content)
if 'gsheet_worksheet' not in st.session_state: st.session_state.gsheet_worksheet = None # GSheet 연결 객체 캐시
if 'all_gsheet_data' not in st.session_state: # 시트 전체 데이터 캐시
    st.session_state.all_gsheet_data = get_all_records_from_gsheet() # 앱 시작 시 한 번 로드

# 자동 배정 설정 기본값 (세션에 없으면 초기화)
if 'auto_assign_teams_config' not in st.session_state:
    st.session_state.auto_assign_teams_config = ALL_TEAMS_MASTER_LIST[:8] # 예시: 처음 8팀 기본 선택
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
    # 테스트 모드 체크박스
    st.session_state.test_mode = st.checkbox("🧪 테스트 모드 활성화", value=st.session_state.test_mode, key="cb_test_mode_sidebar",
                                             help="요일 제한 없이 오늘 날짜로 자동 배정 및 자율 예약 가능 (마감 시간 제약도 해제됨)")
    if st.session_state.test_mode:
        st.warning("테스트 모드가 활성화되어 있습니다.")

    st.subheader("🔑 관리자 모드")
    admin_pw_input_sidebar = st.text_input("관리자 비밀번호", type="password", key="admin_pw_input_sidebar_key")
    if admin_pw_input_sidebar == ADMIN_PASSWORD:
        if not st.session_state.admin_mode: st.toast("관리자 모드 활성화됨", icon="👑")
        st.session_state.admin_mode = True
    elif admin_pw_input_sidebar != "" : # 입력값이 있는데 비밀번호가 틀린 경우
        if st.session_state.admin_mode: st.toast("관리자 모드 비활성화됨", icon="⚙️") # 이전 상태가 admin이었으면 비활성화 알림
        st.session_state.admin_mode = False # 비밀번호 틀리면 무조건 비활성화
        st.error("비밀번호가 일치하지 않습니다.")
    
    if st.session_state.admin_mode: st.success("관리자 모드 활성화 중")

    st.markdown("---")
    st.subheader("🔄 자동 배정 설정")
    # 자동 배정 시간 표시 (설정값 기준)
    auto_assign_start_cfg_sb = st.session_state.auto_assign_start_time_config
    auto_assign_duration_cfg_sb = st.session_state.auto_assign_duration_config
    auto_assign_end_cfg_sb = (datetime.datetime.combine(datetime.date.min, auto_assign_start_cfg_sb) + datetime.timedelta(minutes=auto_assign_duration_cfg_sb)).time()
    st.caption(f"점심시간({auto_assign_start_cfg_sb.strftime('%H:%M')}~{auto_assign_end_cfg_sb.strftime('%H:%M')}) 자동 로테이션 설정")

    st.session_state.auto_assign_teams_config = st.multiselect(
        "자동 배정 참여 조 선택:", options=ALL_TEAMS_MASTER_LIST,
        default=st.session_state.auto_assign_teams_config, key="ms_auto_teams_sidebar_key"
    )
    st.session_state.auto_assign_spaces_config = st.multiselect(
        "자동 배정 사용 공간 선택:", options=ALL_SPACES_MASTER_LIST,
        default=st.session_state.auto_assign_spaces_config, key="ms_auto_spaces_sidebar_key"
    )
    
    # 요일 설정 UI (선택 사항)
    days_map = {"월":0, "화":1, "수":2, "목":3, "금":4, "토":5, "일":6}
    default_day_names = [day_name for day_name, day_idx in days_map.items() if day_idx in st.session_state.auto_assign_days_config]
    selected_day_names_sb = st.multiselect("자동 배정 요일:", options=list(days_map.keys()), 
                                        default=default_day_names, key="ms_auto_days_sidebar_key")
    st.session_state.auto_assign_days_config = [days_map[name] for name in selected_day_names_sb]

    if st.button("자동 배정 설정 저장 및 재확인", key="save_auto_settings_btn_sidebar_key", use_container_width=True):
        st.toast("자동 배정 설정이 앱 세션에 반영되었습니다.", icon="👍")
        st.session_state.force_auto_assign_check = True # 자동 배정 로직 강제 재실행 플래그
        st.rerun()


# --- 날짜 변경 감지 및 자동 배정 실행 ---
today_kst = get_kst_today_date() # 이 변수는 UI 전체에서 사용됨

# 앱 로드 시 또는 특정 조건(날짜 변경, 설정 변경 후 강제 체크)에서 자동 배정 실행 로직
if 'last_auto_assignment_check_date' not in st.session_state or \
   st.session_state.last_auto_assignment_check_date != today_kst or \
   st.session_state.get('force_auto_assign_check', False):
    
    teams_for_assignment_run = st.session_state.auto_assign_teams_config
    spaces_for_assignment_run = st.session_state.auto_assign_spaces_config
    days_for_assignment_run = st.session_state.auto_assign_days_config
    time_start_for_assignment_run = st.session_state.auto_assign_start_time_config
    duration_for_assignment_run = st.session_state.auto_assign_duration_config
    current_test_mode_run = st.session_state.test_mode

    # 테스트 모드가 켜져 있거나, 실제 자동 배정 요일인 경우에만 실행 시도
    # (단, force_auto_assign_check가 True면 요일 상관없이 테스트 모드처럼 일단 시도)
    should_run_auto_assign = current_test_mode_run or \
                             (today_kst.weekday() in days_for_assignment_run) or \
                             st.session_state.get('force_auto_assign_check', False)

    if should_run_auto_assign:
        run_message_prefix = ""
        if st.session_state.get('force_auto_assign_check', False):
            run_message_prefix = "설정 변경으로 "
        elif current_test_mode_run and not (today_kst.weekday() in days_for_assignment_run) :
             run_message_prefix = "테스트 모드로 "
        
        st.info(f"{run_message_prefix}오늘({today_kst.strftime('%m/%d')}) 자동 배정 상태를 확인/실행합니다...")
        
        success_auto, message_auto = run_auto_rotation_assignment_if_needed(
            today_kst, st.session_state.all_gsheet_data,
            teams_for_assignment_run, spaces_for_assignment_run,
            days_for_assignment_run, time_start_for_assignment_run, duration_for_assignment_run,
            is_test_mode=current_test_mode_run # 테스트 모드 상태 전달
        )
        if success_auto:
            st.session_state.form_message = ("success", message_auto)
        # "이미 완료" 등의 정보성 메시지도 표시
        elif "이미 완료" in message_auto or "요일이 아닙니다" in message_auto or "설정되지 않았습니다" in message_auto or "부족합니다" in message_auto:
             st.session_state.form_message = ("info", message_auto)
        elif message_auto : # 그 외 메시지 (오류 등)
            st.session_state.form_message = ("warning", message_auto)
    
    st.session_state.last_auto_assignment_check_date = today_kst # 오늘 날짜로 업데이트
    st.session_state.pop('force_auto_assign_check', None) # 사용된 플래그는 제거
    if st.session_state.form_message : st.rerun() # 메시지 표시 및 UI 업데이트 위해


# --- 메인 페이지 UI ---
st.title("조모임 공간 통합 예약")
if st.session_state.test_mode: st.subheader("🧪 테스트 모드 동작 중 🧪", anchor=False) # 페이지 상단에도 표시
st.caption(f"현재 시간 (KST): {get_kst_now().strftime('%Y-%m-%d %H:%M:%S')}")

# 예약/취소 결과 메시지 표시
if st.session_state.form_message:
    msg_type, msg_content = st.session_state.form_message
    if msg_type == "success": st.success(msg_content)
    elif msg_type == "error": st.error(msg_content)
    elif msg_type == "warning": st.warning(msg_content)
    elif msg_type == "info": st.info(msg_content)
    st.session_state.form_message = None # 한 번 표시 후 초기화

# --- 1. 오늘 예약 현황 ---
st.header(f"🗓️ 오늘 ({today_kst.strftime('%Y년 %m월 %d일')}) 예약 현황")
active_reservations_today_display = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)

all_time_points_display_main = {}
auto_assign_start_cfg_main = st.session_state.auto_assign_start_time_config
auto_assign_duration_cfg_main = st.session_state.auto_assign_duration_config
auto_assign_days_cfg_main = st.session_state.auto_assign_days_config

# 테스트 모드이거나 실제 자동 배정 요일이면 자동 배정 시간 슬롯을 현황판에 추가
if st.session_state.test_mode or (today_kst.weekday() in auto_assign_days_cfg_main):
    auto_assign_start_naive_main = datetime.datetime.combine(today_kst, auto_assign_start_cfg_main)
    auto_assign_end_time_main = (datetime.datetime.combine(datetime.date.min, auto_assign_start_cfg_main) + datetime.timedelta(minutes=auto_assign_duration_cfg_main)).time()
    all_time_points_display_main[f"{auto_assign_start_cfg_main.strftime('%H:%M')}~{auto_assign_end_time_main.strftime('%H:%M')} (자동)"] = KST.localize(auto_assign_start_naive_main)

for key_free_main, (start_time_free_main, _) in FREE_RESERVATION_SLOTS.items(): # dur_free_main 사용 안함
    free_slot_start_naive_main = datetime.datetime.combine(today_kst, start_time_free_main)
    all_time_points_display_main[key_free_main + " (자율)"] = KST.localize(free_slot_start_naive_main)

if not all_time_points_display_main:
    st.info("오늘은 표시할 예약 시간대가 없습니다 (자동 배정 요일이 아니고 테스트 모드도 비활성 상태일 수 있습니다).")
else:
    df_data_display_main = {slot_label: {space: "<span style='color:green;'>가능</span>" for space in ALL_SPACES_MASTER_LIST} for slot_label in all_time_points_display_main.keys()}
    for res_disp_main in active_reservations_today_display:
        res_start_kst_main = res_disp_main.get('datetime_obj_kst')
        res_room_main = res_disp_main.get(COL_ROOM)
        res_team_main = res_disp_main.get(COL_TEAM)
        res_type_main = res_disp_main.get(COL_RESERVATION_TYPE)
        
        target_slot_label_main = None
        for slot_label_iter_main, slot_start_kst_iter_main in all_time_points_display_main.items():
            if res_start_kst_main == slot_start_kst_iter_main :
                if (res_type_main == "자동배정" and "(자동)" in slot_label_iter_main) or \
                   (res_type_main == "자율예약" and "(자율)" in slot_label_iter_main and res_type_main != "자동배정"): # 자율예약은 자동배정 시간이 아닐때
                    target_slot_label_main = slot_label_iter_main
                    break
        
        if target_slot_label_main and res_room_main in df_data_display_main[target_slot_label_main]:
            df_data_display_main[target_slot_label_main][res_room_main] = f"<span style='color:red;'>{res_team_main}</span>"

    df_status_main = pd.DataFrame(df_data_display_main).T
    ordered_space_cols_main = [col for col in ALL_SPACES_MASTER_LIST if col in df_status_main.columns] # 실제 존재하는 컬럼만
    if ordered_space_cols_main: # 컬럼이 있을 때만 적용
      df_status_main = df_status_main[ordered_space_cols_main]
    
    if not df_status_main.empty:
        st.markdown(df_status_main.to_html(escape=False, index=True), unsafe_allow_html=True)
    elif not active_reservations_today_display: # 현황판은 비었지만 실제 예약도 없는 경우
         st.info("오늘 예약된 조모임 공간이 없습니다.")
    # else: 현황판은 비었고 예약은 있으나 매칭되는 슬롯이 없는 경우 (로직 오류 가능성) - 이 경우는 잘 발생 안 할듯


# --- 2. 자율 예약 하기 ---
st.markdown("---")
st.header("🕒 자율 예약 (오늘 13:00 ~ 16:00)")
# 테스트 모드이거나, 실제 자율 예약 가능한 요일이면 폼 표시
can_reserve_today_free_ui_main = st.session_state.test_mode or (today_kst.weekday() in FREE_RESERVATION_ALLOWED_DAYS)

if not can_reserve_today_free_ui_main:
    st.warning(f"오늘은 ({get_day_korean(today_kst)}요일) 자율 예약이 불가능합니다." + (" 테스트 모드를 사용해보세요." if not st.session_state.test_mode else ""))
else:
    if st.session_state.test_mode and not (today_kst.weekday() in FREE_RESERVATION_ALLOWED_DAYS): # 테스트 모드 안내
        st.info("테스트 모드로 자율 예약이 가능합니다 (요일 제한 없음).")
        
    active_reservations_today_free_form = get_active_reservations_for_day(today_kst, st.session_state.all_gsheet_data)
    selected_time_slot_key_free_form = st.selectbox("예약 시간 선택:", options=list(FREE_RESERVATION_SLOTS.keys()), key="free_slot_selector_form")
    
    if selected_time_slot_key_free_form:
        slot_start_time_free_form, _ = FREE_RESERVATION_SLOTS[selected_time_slot_key_free_form]
        slot_start_datetime_kst_free_form = KST.localize(datetime.datetime.combine(today_kst, slot_start_time_free_form))

        # 현재 슬롯에 예약된 공간/팀 필터링
        reserved_spaces_at_slot_form = [r[COL_ROOM] for r in active_reservations_today_free_form if r.get('datetime_obj_kst') == slot_start_datetime_kst_free_form]
        available_spaces_at_slot_form = [s for s in ALL_SPACES_MASTER_LIST if s not in reserved_spaces_at_slot_form]
        
        teams_already_booked_at_slot_form = [r[COL_TEAM] for r in active_reservations_today_free_form if r.get('datetime_obj_kst') == slot_start_datetime_kst_free_form]
        available_teams_at_slot_form = [t for t in ALL_TEAMS_MASTER_LIST if t not in teams_already_booked_at_slot_form]

        # 예약 가능 시간 체크 (테스트/관리자 모드 시 제약 완화)
        reservable_now_form = True 
        reason_form = ""
        now_kst_form = get_kst_now()
        deadline_datetime_kst_form = slot_start_datetime_kst_free_form - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
        
        if not st.session_state.test_mode and not st.session_state.admin_mode: # 일반 모드일 때만 시간 제약 엄격 적용
            if now_kst_form > deadline_datetime_kst_form :
                reservable_now_form = False; reason_form = f"예약 마감 시간({deadline_datetime_kst_form.strftime('%H:%M')})이 지났습니다."
            if slot_start_datetime_kst_free_form < now_kst_form:
                reservable_now_form = False; reason_form = "이미 지난 시간입니다."
        elif st.session_state.test_mode: # 테스트 모드 안내
            if slot_start_datetime_kst_free_form < now_kst_form:
                 st.info(f"테스트 모드: 이미 지난 시간({slot_start_time_free_form.strftime('%H:%M')})이지만 예약 가능합니다.")
            elif now_kst_form > deadline_datetime_kst_form:
                 st.info(f"테스트 모드: 예약 마감 시간({deadline_datetime_kst_form.strftime('%H:%M')})이 지났지만 예약 가능합니다.")
        # 관리자 모드는 항상 예약 가능 (별도 메시지 없음)

        if not reservable_now_form and not st.session_state.test_mode and not st.session_state.admin_mode:
            st.warning(reason_form)

        with st.form("free_reservation_form_main_key"):
            selected_team_form = st.selectbox("조 선택:", available_teams_at_slot_form, key="free_team_selector_form", disabled=not available_teams_at_slot_form)
            selected_space_form = st.selectbox("공간 선택:", available_spaces_at_slot_form, key="free_space_selector_form", disabled=not available_spaces_at_slot_form)
            
            # 버튼 비활성화 조건: (일반 모드이고 예약 불가 시간) OR (팀/공간 미선택)
            submit_disabled_form = (not reservable_now_form and not st.session_state.test_mode and not st.session_state.admin_mode) or \
                                   (not selected_team_form or not selected_space_form)

            submitted_form = st.form_submit_button("예약 신청", type="primary",
                disabled=submit_disabled_form,
                use_container_width=True)

            if submitted_form:
                if not selected_team_form or not selected_space_form: # 모든 모드에서 팀/공간 선택 필수
                    st.session_state.form_message = ("warning", "조와 공간을 모두 선택해주세요.")
                else:
                    booked_by_user_form = selected_team_form
                    if st.session_state.admin_mode: booked_by_user_form = "admin" # 관리자가 예약시 admin으로
                    
                    success_form, message_form = add_free_reservation_to_gsheet(
                        today_kst, selected_time_slot_key_free_form, selected_team_form, selected_space_form, 
                        booked_by_user_form, is_test_mode=st.session_state.test_mode
                    )
                    st.session_state.form_message = ("success" if success_form else "error", message_form)
                st.rerun() # 예약 시도 후에는 항상 새로고침

# --- 3. 나의 예약 확인 및 취소 ---
st.markdown("---")
st.header("📝 나의 자율 예약 확인 및 취소")
my_team_for_view_cancel = st.selectbox("내 조 선택 (확인/취소용):", ALL_TEAMS_MASTER_LIST, key="my_team_view_cancel_selector")

if my_team_for_view_cancel:
    my_free_reservations_cancel = []
    # all_gsheet_data가 비어있거나 헤더만 있을 경우를 대비
    headers_cancel_view = st.session_state.all_gsheet_data[0] if st.session_state.all_gsheet_data and len(st.session_state.all_gsheet_data) > 0 else []
    
    if headers_cancel_view: # 헤더가 있어야 파싱 가능
        for row_values_cancel in st.session_state.all_gsheet_data[1:]:
            res_cancel = parse_gsheet_row(row_values_cancel, headers_cancel_view)
            if res_cancel and res_cancel.get(COL_TEAM) == my_team_for_view_cancel and \
               res_cancel.get(COL_RESERVATION_TYPE) == "자율예약" and \
               res_cancel.get(COL_STATUS) == "예약됨" and \
               res_cancel.get('datetime_obj_kst') and res_cancel['datetime_obj_kst'].date() >= today_kst : # 오늘 이후의 "예약됨" 상태인 자율예약만
                my_free_reservations_cancel.append(res_cancel)
    
    # 시간순 정렬
    my_free_reservations_sorted_cancel = sorted(my_free_reservations_cancel, key=lambda x: x.get('datetime_obj_kst', KST.localize(datetime.datetime.max)))

    if not my_free_reservations_sorted_cancel:
        st.info(f"'{my_team_for_view_cancel}' 조의 예정된 자율 예약이 없습니다.")
    else:
        for i_cancel, res_item_cancel in enumerate(my_free_reservations_sorted_cancel):
            dt_obj_kst_cancel = res_item_cancel.get('datetime_obj_kst')
            duration_cancel = res_item_cancel.get(COL_DURATION_MINUTES)
            # 시간 레이블 생성
            time_label_cancel = dt_obj_kst_cancel.strftime('%H:%M') 
            if duration_cancel:
                end_time_cancel = (dt_obj_kst_cancel + datetime.timedelta(minutes=duration_cancel)).strftime('%H:%M')
                time_label_cancel += f" ~ {end_time_cancel}"
            
            can_cancel_this_item = False
            deadline_cancel_str = "N/A" # 취소 마감 시간 문자열

            if dt_obj_kst_cancel: # 예약 시간이 있어야 마감 시간 계산 가능
                deadline_for_this_cancel = dt_obj_kst_cancel - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
                deadline_cancel_str = deadline_for_this_cancel.strftime('%H:%M')
                # 테스트 모드 또는 관리자 모드이거나, 마감 시간 이전이면 취소 가능
                if st.session_state.test_mode or st.session_state.admin_mode or (get_kst_now() < deadline_for_this_cancel) :
                    can_cancel_this_item = True
            
            reservation_id_to_cancel_ui = res_item_cancel.get(COL_RESERVATION_ID) # 취소할 예약의 ID

            col_info_cancel, col_action_cancel = st.columns([4,1])
            with col_info_cancel:
                st.markdown(f"**{dt_obj_kst_cancel.strftime('%Y-%m-%d (%a)')} {time_label_cancel}** - `{res_item_cancel.get(COL_ROOM)}` (ID: `{reservation_id_to_cancel_ui}`)")
            with col_action_cancel:
                # 취소 버튼: ID가 있고, 취소 가능할 때만 활성화
                if st.button("취소", key=f"cancel_btn_ui_{reservation_id_to_cancel_ui}_{i_cancel}", 
                             disabled=not reservation_id_to_cancel_ui or not can_cancel_this_item, 
                             use_container_width=True):
                    
                    cancelled_by_user_ui = my_team_for_view_cancel # 기본 취소자는 선택된 팀
                    if st.session_state.admin_mode: cancelled_by_user_ui = "admin" # 관리자가 취소 시 admin으로
                    
                    success_cancel_ui, message_cancel_ui = cancel_reservation_in_gsheet(
                        reservation_id_to_cancel_ui, cancelled_by_user_ui, is_test_mode=st.session_state.test_mode
                    )
                    st.session_state.form_message = ("success" if success_cancel_ui else "error", message_cancel_ui)
                    st.rerun() # 취소 후 새로고침
            
            # 취소 불가 사유 표시 (일반 사용자 & 테스트 모드 아닐 때)
            if not can_cancel_this_item and not st.session_state.test_mode and not st.session_state.admin_mode:
                 st.caption(f"취소 마감({deadline_cancel_str})", unsafe_allow_html=True)
            # 테스트 모드에서 마감시간 지났지만 취소 가능한 경우 안내
            elif can_cancel_this_item and st.session_state.test_mode and not st.session_state.admin_mode and not (get_kst_now() < deadline_for_this_cancel):
                st.caption(f"테스트 모드: 취소 마감({deadline_cancel_str})이 지났지만 취소 가능", unsafe_allow_html=True)

            st.divider()

# --- (관리자용) 전체 기록 보기 ---
if st.session_state.admin_mode:
    st.markdown("---")
    st.header("👑 (관리자) 전체 예약 기록 (Google Sheet)")
    if not st.session_state.all_gsheet_data or len(st.session_state.all_gsheet_data) < 2: # 헤더만 있거나 비었을 경우
        st.info("Google Sheet에 기록이 없습니다.")
    else:
        # 데이터프레임으로 변환
        df_all_records_admin_view = pd.DataFrame(st.session_state.all_gsheet_data[1:], columns=st.session_state.all_gsheet_data[0])
        try:
            # 주요 시간 컬럼 기준 내림차순 정렬 (최신순)
            # GSHEET_HEADERS[1] = COL_DATETIME_STR, GSHEET_HEADERS[7] = COL_BOOKING_TIMESTAMP_STR
            df_all_records_admin_view = df_all_records_admin_view.sort_values(
                by=[GSHEET_HEADERS[1], GSHEET_HEADERS[7]], 
                ascending=[False, False]
            )
        except KeyError: # 정렬 기준 컬럼이 없는 경우 (거의 발생 안함)
            st.warning("정렬 기준 컬럼을 찾을 수 없어 원본 순서대로 표시합니다.")
        except Exception as e_sort_admin: # 기타 정렬 오류
            st.warning(f"데이터 정렬 중 오류: {e_sort_admin}. 원본 순서대로 표시합니다.")

        st.dataframe(df_all_records_admin_view, use_container_width=True, height=400)
