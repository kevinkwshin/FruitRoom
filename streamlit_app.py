import streamlit as st
import datetime
import pandas as pd
import json
import os
import pytz # 시간대 처리를 위해 pytz 라이브러리 임포트
from collections import defaultdict

# --- 초기 설정 ---
TEAMS_ALL = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)]
SPACE_LOCATIONS_DETAILED = {
    "9층": {"name": "9층 조모임 공간", "spaces": [f"9층-{i}호" for i in range(1, 7)]},
    "지하5층": {"name": "지하5층 조모임 공간", "spaces": [f"지하5층-{i}호" for i in range(1, 4)]}
}
ALL_SPACES_LIST = SPACE_LOCATIONS_DETAILED["9층"]["spaces"] + SPACE_LOCATIONS_DETAILED["지하5층"]["spaces"]

RESERVATION_FILE = "reservations.json"
KST = pytz.timezone('Asia/Seoul') # 한국 시간대 객체
ADMIN_PASSWORD = "admin" # 간단한 관리자 비밀번호 (실제 사용시에는 더 안전한 방법 사용)

# 예약 가능 요일 (0=월, 1=화, ..., 6=일) 및 시간 슬롯 정의
RESERVATION_ALLOWED_DAYS = [2, 6] # 수요일, 일요일
TIME_SLOTS = { # 시간 슬롯 (표시용 레이블: (시작 시간, 종료 시간))
    "10:00-12:00": (datetime.time(10, 0), datetime.time(12, 0)),
    "13:00-15:00": (datetime.time(13, 0), datetime.time(15, 0)),
    "15:00-17:00": (datetime.time(15, 0), datetime.time(17, 0)),
    "17:00-19:00": (datetime.time(17, 0), datetime.time(19, 0)),
    "19:00-21:00": (datetime.time(19, 0), datetime.time(21, 0)),
}
# 예약 마감 시간 (예: 슬롯 시작 10분 전까지 예약 가능)
RESERVATION_DEADLINE_MINUTES = 10

# --- Helper Functions ---
def get_kst_now():
    """현재 한국 시간을 datetime 객체로 반환합니다."""
    return datetime.datetime.now(KST)

def get_kst_today_date():
    """현재 한국 날짜를 date 객체로 반환합니다."""
    return get_kst_now().date()

def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

# --- 데이터 로드 및 저장 함수 ---
def load_reservations():
    if os.path.exists(RESERVATION_FILE):
        try:
            with open(RESERVATION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            valid_reservations = []
            now_kst = get_kst_now()
            
            for item in data:
                try:
                    # 'datetime' 필드를 기준으로 파싱 (이전 'date'는 호환성 위해 남겨둘 수 있으나, 새 필드 사용)
                    reservation_dt_str = item.get('datetime_str') # 저장된 시간은 항상 KST 기준이었어야 함
                    if not reservation_dt_str:
                        # Fallback for old format (date only, assume 00:00 KST for filtering)
                        # This part might need adjustment based on how old data was stored.
                        # For simplicity, let's assume new format. If old data exists, it might be ignored or need migration.
                        # print(f"Warning: Skipping item without 'datetime_str': {item}")
                        continue

                    # JSON에 저장된 문자열은 naive datetime 문자열로 간주하고 KST로 localize
                    naive_dt = datetime.datetime.fromisoformat(reservation_dt_str)
                    reservation_dt_kst = KST.localize(naive_dt)
                    
                    # 예약 슬롯의 종료 시간을 기준으로 과거 예약 필터링
                    # TIME_SLOTS에서 해당 슬롯의 종료 시간 가져오기
                    slot_key = item.get("time_slot_key")
                    if slot_key and slot_key in TIME_SLOTS:
                        slot_end_time = TIME_SLOTS[slot_key][1]
                        reservation_end_dt_kst = KST.localize(datetime.datetime.combine(reservation_dt_kst.date(), slot_end_time))
                        if reservation_end_dt_kst >= now_kst: # 슬롯 종료 시간이 현재 시간 이후인 경우만 유효
                            item['datetime_obj'] = reservation_dt_kst # datetime 객체로 변환하여 저장
                            valid_reservations.append(item)
                        # else:
                            # print(f"Filtered out past reservation: {item}")
                    # else:
                        # print(f"Warning: Skipping item with invalid/missing time_slot_key: {item}")

                except ValueError as ve:
                    print(f"Warning: Skipping item with invalid datetime format: {item}. Error: {ve}")
                    continue
                except Exception as e:
                    print(f"Warning: Error processing item {item}. Error: {e}")
                    continue
            return valid_reservations
        except Exception as e:
            st.error(f"예약 데이터 로드 중 오류: {e}")
            return []
    return []

def save_reservations(reservations_data):
    try:
        data_to_save = []
        for item in reservations_data:
            copied_item = item.copy()
            # 'datetime_obj'를 'datetime_str'로 변환 (naive ISO format)
            if 'datetime_obj' in copied_item and isinstance(copied_item['datetime_obj'], datetime.datetime):
                # KST 정보를 제거하고 naive datetime으로 저장 (로드 시 KST로 localize)
                copied_item['datetime_str'] = copied_item['datetime_obj'].replace(tzinfo=None).isoformat()
                del copied_item['datetime_obj'] # 객체는 저장하지 않음
            data_to_save.append(copied_item)
        
        with open(RESERVATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"예약 데이터 저장 실패: {e}")


# --- 세션 상태 초기화 ---
if 'reservations' not in st.session_state:
    st.session_state.reservations = load_reservations()
if 'last_known_kst_date' not in st.session_state:
    st.session_state.last_known_kst_date = get_kst_today_date()
if 'admin_mode' not in st.session_state:
    st.session_state.admin_mode = False
if 'form_submit_message' not in st.session_state:
    st.session_state.form_submit_message = None
# 예약 폼 관련 세션 상태
if 'selected_date_for_reservation' not in st.session_state:
    st.session_state.selected_date_for_reservation = get_kst_today_date()
if 'selected_time_slot_key' not in st.session_state:
    st.session_state.selected_time_slot_key = None
if 'selected_team_radio' not in st.session_state:
    st.session_state.selected_team_radio = None
if 'selected_space_radio' not in st.session_state:
    st.session_state.selected_space_radio = None


# --- 예약 가능 여부 및 상태 확인 함수 ---
def is_slot_reservable(selected_date, time_slot_key, now_kst):
    """선택된 날짜와 시간 슬롯이 현재 예약 가능한지 확인 (요일, 시간대, 마감 시간 고려)"""
    if selected_date.weekday() not in RESERVATION_ALLOWED_DAYS:
        return False, "예약 불가능한 요일입니다."

    slot_start_time, _ = TIME_SLOTS[time_slot_key]
    slot_start_datetime_naive = datetime.datetime.combine(selected_date, slot_start_time)
    slot_start_datetime_kst = KST.localize(slot_start_datetime_naive)

    # 이미 지난 슬롯인지 확인
    if slot_start_datetime_kst < now_kst:
        return False, "이미 지난 시간 슬롯입니다."

    # 예약 마감 시간 확인
    deadline_datetime_kst = slot_start_datetime_kst - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
    if now_kst > deadline_datetime_kst:
        return False, f"예약 마감 시간({deadline_datetime_kst.strftime('%H:%M')})이 지났습니다."
    
    return True, "예약 가능"

def get_reservations_for_datetime(target_datetime_kst):
    """특정 KST datetime에 해당하는 예약만 필터링 (시간 슬롯의 시작 시간 기준)"""
    return [
        res for res in st.session_state.reservations
        if res.get('datetime_obj') and res['datetime_obj'] == target_datetime_kst
    ]

def get_available_spaces(target_datetime_kst):
    """특정 KST datetime에 예약 가능한 공간 목록 반환"""
    reservations_at_datetime = get_reservations_for_datetime(target_datetime_kst)
    reserved_spaces = [res['room'] for res in reservations_at_datetime]
    return [space for space in ALL_SPACES_LIST if space not in reserved_spaces]

def get_available_teams(target_datetime_kst):
    """특정 KST datetime에 예약 가능한 팀 목록 반환"""
    reservations_at_datetime = get_reservations_for_datetime(target_datetime_kst)
    reserved_teams = [res['team'] for res in reservations_at_datetime]
    return [team for team in TEAMS_ALL if team not in reserved_teams]

# --- 예약 및 취소 처리 함수 ---
def handle_reservation_submission():
    st.session_state.form_submit_message = None # 이전 메시지 초기화
    
    selected_date = st.session_state.get("selected_date_for_reservation")
    time_slot_key = st.session_state.get("selected_time_slot_key")
    team = st.session_state.get("selected_team_radio")
    space = st.session_state.get("selected_space_radio")

    if not all([selected_date, time_slot_key, team, space]):
        st.session_state.form_submit_message = ("warning", "날짜, 시간, 조, 공간을 모두 선택해주세요.")
        return

    slot_start_time, _ = TIME_SLOTS[time_slot_key]
    reservation_datetime_naive = datetime.datetime.combine(selected_date, slot_start_time)
    reservation_datetime_kst = KST.localize(reservation_datetime_naive)
    
    now_kst = get_kst_now()
    reservable, reason = is_slot_reservable(selected_date, time_slot_key, now_kst)
    if not reservable and not st.session_state.admin_mode: # 관리자는 제한 무시 가능 (테스트용)
        st.session_state.form_submit_message = ("error", f"예약 불가: {reason}")
        return

    # 동시 예약 방지 (선택된 datetime 기준)
    # 데이터를 다시 로드하여 최신 상태 확인 (매우 짧은 시간 동안의 동시 요청 대응)
    current_reservations = load_reservations() 
    
    for res in current_reservations:
        if res.get('datetime_obj') == reservation_datetime_kst and res.get('room') == space:
            st.session_state.form_submit_message = ("error", f"오류: {space}은(는) 해당 시간에 방금 다른 조에 의해 예약된 것 같습니다. 다시 시도해주세요.")
            return
        if res.get('datetime_obj') == reservation_datetime_kst and res.get('team') == team:
            st.session_state.form_submit_message = ("error", f"오류: {team} 조는 해당 시간에 방금 다른 공간을 예약한 것 같습니다. 다시 시도해주세요.")
            return

    new_reservation = {
        "datetime_obj": reservation_datetime_kst, # 실제 datetime 객체
        "time_slot_key": time_slot_key, # "10:00-12:00" 같은 키
        "team": team,
        "room": space,
        "timestamp": get_kst_now() # 예약 행위가 일어난 시간 (메타데이터용)
    }
    st.session_state.reservations.append(new_reservation)
    save_reservations(st.session_state.reservations)
    
    date_str = selected_date.strftime('%Y-%m-%d')
    day_name = get_day_korean(selected_date)
    st.session_state.form_submit_message = ("success", f"{date_str}({day_name}) {time_slot_key} **'{team}'** 조가 **'{space}'** 예약 완료.")
    
    # 성공 후 선택 값 초기화 (선택적)
    # st.session_state.selected_team_radio = None 
    # st.session_state.selected_space_radio = None
    # st.experimental_rerun() # 예약 후 바로 상태 반영 위해

def handle_cancellation(reservation_to_cancel):
    try:
        # st.session_state.reservations에서 해당 예약 제거
        # datetime_obj, team, room으로 고유하게 식별
        st.session_state.reservations = [
            res for res in st.session_state.reservations
            if not (res.get('datetime_obj') == reservation_to_cancel.get('datetime_obj') and \
                    res.get('team') == reservation_to_cancel.get('team') and \
                    res.get('room') == reservation_to_cancel.get('room'))
        ]
        save_reservations(st.session_state.reservations)
        st.toast(f"🗑️ '{reservation_to_cancel['datetime_obj'].strftime('%y-%m-%d %H:%M')} {reservation_to_cancel['team']} - {reservation_to_cancel['room']}' 예약이 취소되었습니다.", icon="✅")
        st.session_state.form_submit_message = None # 다른 메시지 삭제
        # st.experimental_rerun() # 취소 후 바로 상태 반영
    except Exception as e:
        st.error(f"취소 중 오류 발생: {e}")


# --- Streamlit UI ---
st.set_page_config(page_title="조모임 공간 예약", layout="wide", initial_sidebar_state="collapsed")

# --- CSS 스타일 ---
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        body { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; text-size-adjust: 100%; touch-action: manipulation; }
        .stButton > button { font-size: 0.9rem !important; padding: 0.3rem 0.6rem !important; margin-top: 5px; }
        .main .block-container { max-width: 1000px; padding-left: 1rem; padding-right: 1rem; }
        h1 { font-size: 1.8rem !important; } h2 { font-size: 1.5rem !important; } h3 { font-size: 1.25rem !important; }
        div[data-testid="stMarkdownContainer"] p { margin-bottom: 0.5rem !important; }
        hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
        .stRadio > label { font-size: 1rem !important; margin-bottom: 0.2rem !important; }
        .stRadio > div[role="radiogroup"] > div { margin-bottom: 0.1rem !important; margin-right: 10px !important;}
        .stRadio label span { font-size: 0.95rem !important; }
        table { font-size: 0.9rem !important; } th, td { padding: 4px 8px !important; }
        .centered-table table { margin-left: auto; margin-right: auto; }
    </style>
    """, unsafe_allow_html=True)

# --- 날짜 변경 감지 및 처리 ---
current_kst_date_on_load = get_kst_today_date()
if st.session_state.last_known_kst_date != current_kst_date_on_load:
    st.toast(f"🗓️ 한국 시간 기준으로 날짜가 {current_kst_date_on_load.strftime('%m월 %d일')}로 변경되었습니다. 정보를 새로고침합니다.")
    st.session_state.last_known_kst_date = current_kst_date_on_load
    st.session_state.reservations = load_reservations() # 날짜 변경 시 예약 데이터도 다시 로드 (과거 필터링)
    st.rerun()

st.title("조모임 공간 예약 시스템")
now_kst_for_display = get_kst_now()
st.caption(f"현재 시간 (KST): {now_kst_for_display.strftime('%Y-%m-%d %H:%M:%S')}")
st.markdown("---")

# --- 사이드바 ---
with st.sidebar:
    st.header("⚙️ 앱 설정")
    if st.button("🔄 정보 새로고침 (KST 기준)", use_container_width=True):
        st.session_state.reservations = load_reservations()
        st.rerun()

    st.markdown("---")
    st.subheader("🔑 관리자 모드")
    admin_pw_input = st.text_input("관리자 비밀번호", type="password", key="admin_pw")
    if admin_pw_input == ADMIN_PASSWORD:
        st.session_state.admin_mode = True
        st.success("관리자 모드 활성화됨")
    elif admin_pw_input != "" and admin_pw_input != ADMIN_PASSWORD :
        st.error("비밀번호가 틀렸습니다.")
        st.session_state.admin_mode = False

    if st.session_state.admin_mode:
        st.warning("관리자 모드가 활성화되어 있습니다. 모든 예약 취소 가능.")

    st.markdown("---")
    st.subheader("📜 전체 예약 내역 (예정)")
    if st.session_state.reservations:
        display_data = []
        # datetime_obj 기준으로 정렬 (날짜, 시간 순)
        sorted_reservations = sorted(
            st.session_state.reservations,
            key=lambda x: x.get('datetime_obj', KST.localize(datetime.datetime.min))
        )
        for res_item in sorted_reservations:
            dt_obj = res_item.get('datetime_obj')
            if not dt_obj: continue # Skip if no datetime_obj

            item_display = {
                "날짜": dt_obj.strftime('%y-%m-%d') + f"({get_day_korean(dt_obj)[0]})",
                "시간": res_item.get('time_slot_key', 'N/A'),
                "조": res_item.get('team'),
                "공간": res_item.get('room'),
                "예약시점(KST)": res_item.get('timestamp').astimezone(KST).strftime('%H:%M') if res_item.get('timestamp') else "N/A"
            }
            display_data.append(item_display)
        
        if display_data:
            all_res_df = pd.DataFrame(display_data)
            st.dataframe(all_res_df, height=300, use_container_width=True)
        else:
            st.caption("예정된 예약이 없습니다.")
    else:
        st.caption("저장된 예약이 없습니다.")


# --- 1. 예약 현황 보기 ---
st.header("1. 예약 현황")
# 현황 조회용 날짜 선택
selected_date_status = st.date_input(
    "현황 조회 날짜 선택", 
    value=get_kst_today_date(), 
    min_value=get_kst_today_date(),
    key="status_date"
)
status_day_name = get_day_korean(selected_date_status)
st.subheader(f"🗓️ {selected_date_status.strftime('%Y년 %m월 %d일')} ({status_day_name}요일) 예약 현황")

# 시간대별 예약 현황 테이블 생성
status_table_data = defaultdict(lambda: {space: "<span style='color:green;'>가능</span>" for space in ALL_SPACES_LIST})
reservations_on_selected_date = [
    res for res in st.session_state.reservations 
    if res.get('datetime_obj') and res['datetime_obj'].date() == selected_date_status
]

for res in reservations_on_selected_date:
    time_key = res.get('time_slot_key')
    room = res.get('room')
    team = res.get('team')
    if time_key and room:
        status_table_data[time_key][room] = f"<span style='color:red;'>{team}</span>"

if not status_table_data and selected_date_status.weekday() not in RESERVATION_ALLOWED_DAYS:
     st.info(f"{status_day_name}요일은 예약 가능한 날이 아닙니다.")
elif not status_table_data:
     st.info(f"{selected_date_status.strftime('%m/%d')}에는 예약이 없습니다.")
else:
    df_status = pd.DataFrame(status_table_data).T # Transpose to have time slots as rows
    df_status = df_status.reindex(TIME_SLOTS.keys()).fillna("<span style='color:green;'>가능</span>") # 모든 시간 슬롯 포함 및 빈칸 채우기
    
    # 컬럼 순서 정렬 (9층 먼저, 지하5층 다음)
    ordered_columns = SPACE_LOCATIONS_DETAILED["9층"]["spaces"] + SPACE_LOCATIONS_DETAILED["지하5층"]["spaces"]
    df_status = df_status[ordered_columns]

    st.markdown("<div class='centered-table'>" + df_status.to_html(escape=False) + "</div>", unsafe_allow_html=True)

st.markdown("---")

# --- 2. 예약하기 ---
with st.expander(f"2. 조모임 공간 예약하기", expanded=True):
    if st.session_state.form_submit_message:
        msg_type, msg_content = st.session_state.form_submit_message
        if msg_type == "success": st.success(msg_content)
        elif msg_type == "error": st.error(msg_content)
        elif msg_type == "warning": st.warning(msg_content)
        # 메시지 한 번만 표시 후 초기화 (rerun 후에도 유지되지 않도록)
        # st.session_state.form_submit_message = None # Submit 버튼 누를 때 초기화로 변경

    # 예약할 날짜 및 시간 선택
    col_date, col_time = st.columns(2)
    with col_date:
        # 예약 날짜 선택 (오늘부터 선택 가능)
        st.session_state.selected_date_for_reservation = st.date_input(
            "예약 날짜 선택",
            value=st.session_state.get("selected_date_for_reservation", get_kst_today_date()), # 유지
            min_value=get_kst_today_date(),
            key="reservation_form_date_picker" # 키 변경으로 분리
        )
    with col_time:
        # 예약 시간 슬롯 선택
        time_slot_options = list(TIME_SLOTS.keys())
        # 이전에 선택한 값이 있으면 유지, 없으면 첫번째 값
        current_selected_time_slot = st.session_state.get("selected_time_slot_key")
        time_slot_default_index = time_slot_options.index(current_selected_time_slot) if current_selected_time_slot in time_slot_options else 0

        st.session_state.selected_time_slot_key = st.selectbox(
            "예약 시간 선택",
            options=time_slot_options,
            index=time_slot_default_index,
            key="reservation_form_time_slot_selector" # 키 변경
        )

    # 선택된 날짜와 시간의 유효성 검사
    selected_date_obj = st.session_state.selected_date_for_reservation
    selected_time_key = st.session_state.selected_time_slot_key
    
    now_kst_check = get_kst_now()
    is_reservable_slot, reservable_reason = is_slot_reservable(selected_date_obj, selected_time_key, now_kst_check)
    
    form_disabled = not is_reservable_slot
    if st.session_state.admin_mode: # 관리자 모드일 경우 항상 활성화
        st.caption(f"선택일: {selected_date_obj.strftime('%m/%d')} ({get_day_korean(selected_date_obj)}), 시간: {selected_time_key}. [관리자 모드] {reservable_reason}")
        form_disabled = False
    elif is_reservable_slot:
        st.caption(f"선택일: {selected_date_obj.strftime('%m/%d')} ({get_day_korean(selected_date_obj)}), 시간: {selected_time_key}. {reservable_reason}")
    else:
        st.warning(f"선택일: {selected_date_obj.strftime('%m/%d')} ({get_day_korean(selected_date_obj)}), 시간: {selected_time_key}. 예약 불가: {reservable_reason}")

    if selected_date_obj and selected_time_key:
        slot_start_time, _ = TIME_SLOTS[selected_time_key]
        target_datetime_kst_for_form = KST.localize(datetime.datetime.combine(selected_date_obj, slot_start_time))

        available_spaces_for_form = get_available_spaces(target_datetime_kst_for_form)
        available_teams_for_form = get_available_teams(target_datetime_kst_for_form)

        with st.form("reservation_form_main"):
            if available_teams_for_form:
                # 이전에 선택한 팀 유지
                team_default_idx = available_teams_for_form.index(st.session_state.selected_team_radio) \
                                   if st.session_state.selected_team_radio in available_teams_for_form else 0
                st.radio("조 선택:", available_teams_for_form, key="selected_team_radio", index=team_default_idx, horizontal=True)
            else:
                st.warning("이 시간대에 예약 가능한 조가 없습니다."); st.session_state.selected_team_radio = None
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if available_spaces_for_form:
                # 이전에 선택한 공간 유지
                space_default_idx = available_spaces_for_form.index(st.session_state.selected_space_radio) \
                                    if st.session_state.selected_space_radio in available_spaces_for_form else 0
                st.radio("조모임 공간 선택:", available_spaces_for_form, key="selected_space_radio", index=space_default_idx, horizontal=True)
            else:
                st.warning("이 시간대에 예약 가능한 조모임 공간이 없습니다."); st.session_state.selected_space_radio = None

            submit_button_disabled = form_disabled or not available_spaces_for_form or not available_teams_for_form
            st.form_submit_button(
                "예약 신청", type="primary",
                disabled=submit_button_disabled,
                use_container_width=True,
                on_click=handle_reservation_submission
            )
    else:
        st.info("예약할 날짜와 시간을 먼저 선택해주세요.")


st.markdown("---")

# --- 3. 나의 예약 확인 및 취소 ---
st.header("3. 나의 예약 확인 및 취소")
my_team_select = st.selectbox("내 조 선택:", TEAMS_ALL, key="my_team_for_cancellation_selector", index=0)

if my_team_select:
    my_reservations = [
        res for res in st.session_state.reservations
        if res.get('team') == my_team_select
    ]
    # 시간순 정렬
    my_reservations_sorted = sorted(my_reservations, key=lambda x: x.get('datetime_obj', KST.localize(datetime.datetime.min)))

    if not my_reservations_sorted:
        st.info(f"'{my_team_select}' 조의 예약 내역이 없습니다.")
    else:
        st.markdown(f"**'{my_team_select}' 조의 예약 목록:**")
        for i, res_item in enumerate(my_reservations_sorted):
            dt_obj = res_item.get('datetime_obj')
            if not dt_obj: continue

            col1, col2, col3 = st.columns([3,2,1])
            with col1:
                st.text(f"{dt_obj.strftime('%Y-%m-%d (%a)')} {res_item.get('time_slot_key')}")
            with col2:
                st.text(f"📍 {res_item.get('room')}")
            with col3:
                # 예약 슬롯 시작 시간 KST
                slot_start_dt_kst = res_item.get('datetime_obj')
                # 현재 시간 KST
                now_kst_cancel_check = get_kst_now()
                
                # 예약 취소 마감 시간 (예: 슬롯 시작 30분 전)
                # 더 일찍 마감하고 싶으면 timedelta 값을 늘리면 됨
                # 여기서는 is_slot_reservable의 DEADLINE_MINUTES와 동일하게 사용
                cancel_deadline_kst = slot_start_dt_kst - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
                
                can_cancel = now_kst_cancel_check < cancel_deadline_kst or st.session_state.admin_mode

                cancel_key = f"cancel_btn_{my_team_select}_{dt_obj.strftime('%Y%m%d%H%M')}_{res_item.get('room')}" # 고유 키
                if st.button("취소", key=cancel_key, disabled=not can_cancel, use_container_width=True):
                    handle_cancellation(res_item)
                    st.rerun() # 취소 후 목록 즉시 갱신
            if not can_cancel and not st.session_state.admin_mode:
                 st.caption(f"취소 마감시간({cancel_deadline_kst.strftime('%H:%M')})이 지나 취소할 수 없습니다.", unsafe_allow_html=True)
            st.divider()

# --- 4. (관리자 전용) 전체 예약 관리 ---
if st.session_state.admin_mode:
    st.markdown("---")
    st.header("👑 4. (관리자) 전체 예약 관리")
    
    if not st.session_state.reservations:
        st.info("현재 활성화된 예약이 없습니다.")
    else:
        # 날짜와 시간으로 정렬
        admin_sorted_reservations = sorted(
            st.session_state.reservations,
            key=lambda x: x.get('datetime_obj', KST.localize(datetime.datetime.min))
        )
        st.markdown(f"총 {len(admin_sorted_reservations)}개의 예약이 있습니다.")
        for i, res_item in enumerate(admin_sorted_reservations):
            dt_obj = res_item.get('datetime_obj')
            if not dt_obj: continue

            col_info, col_action = st.columns([4,1])
            with col_info:
                st.markdown(
                    f"**{dt_obj.strftime('%Y-%m-%d (%a) %H:%M')}** ({res_item.get('time_slot_key')}) - "
                    f"**{res_item.get('team')}** - ` {res_item.get('room')} ` "
                )
            with col_action:
                admin_cancel_key = f"admin_cancel_btn_{dt_obj.strftime('%Y%m%d%H%M')}_{res_item.get('team')}_{res_item.get('room')}"
                if st.button("강제 취소", key=admin_cancel_key, type="secondary", use_container_width=True):
                    handle_cancellation(res_item)
                    st.rerun()
            st.divider()
