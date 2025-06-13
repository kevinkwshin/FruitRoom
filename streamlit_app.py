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

# <<< START OF CHANGE 1 >>>
# Define a safe default KST datetime for sorting items that might lack a datetime_obj
# Using a year far in the future, but not datetime.MAXYEAR to avoid edge issues with localization.
DEFAULT_SORT_DATETIME_KST = KST.localize(datetime.datetime(9998, 1, 1, 0, 0, 0))
# <<< END OF CHANGE 1 >>>

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
                    reservation_dt_str = item.get('datetime_str') 
                    if not reservation_dt_str:
                        # print(f"Warning: Skipping item without 'datetime_str': {item}")
                        continue

                    naive_dt = datetime.datetime.fromisoformat(reservation_dt_str)
                    reservation_dt_kst = KST.localize(naive_dt)
                    
                    slot_key = item.get("time_slot_key")
                    if slot_key and slot_key in TIME_SLOTS:
                        slot_start_time, slot_end_time = TIME_SLOTS[slot_key] # Get both start and end
                        # Ensure reservation_dt_kst actually matches the slot_start_time for consistency
                        expected_naive_start_dt = datetime.datetime.combine(naive_dt.date(), slot_start_time)
                        if naive_dt != expected_naive_start_dt:
                            # print(f"Warning: Correcting datetime_str for item {item} to match slot_start_time. Was {naive_dt}, now {expected_naive_start_dt}")
                            naive_dt = expected_naive_start_dt
                            reservation_dt_kst = KST.localize(naive_dt)
                            # Update item's datetime_str if we want to auto-correct and save later (optional)
                            # item['datetime_str'] = naive_dt.isoformat()

                        reservation_end_dt_kst = KST.localize(datetime.datetime.combine(reservation_dt_kst.date(), slot_end_time))
                        
                        if reservation_end_dt_kst >= now_kst: 
                            item['datetime_obj'] = reservation_dt_kst 
                            valid_reservations.append(item)
                        # else:
                            # print(f"Filtered out past reservation by end time: {item}")
                    # else:
                        # print(f"Warning: Skipping item with invalid/missing time_slot_key: {item}")

                except ValueError as ve:
                    print(f"Warning: Skipping item with invalid datetime format: {item}. Error: {ve}")
                    continue
                except Exception as e:
                    print(f"Warning: Error processing item {item}. Error: {e}")
                    continue
            return valid_reservations
        except json.JSONDecodeError as jde:
            st.error(f"예약 데이터 파일({RESERVATION_FILE})이 JSON 형식이 아닙니다: {jde}")
            # Consider creating an empty file or handling it more gracefully
            if os.path.exists(RESERVATION_FILE):
                 os.rename(RESERVATION_FILE, RESERVATION_FILE + ".corrupted")
                 st.warning(f"{RESERVATION_FILE}을 {RESERVATION_FILE}.corrupted로 변경했습니다. 새 파일이 생성됩니다.")
            return []
        except Exception as e:
            st.error(f"예약 데이터 로드 중 오류: {e}")
            return []
    return []

def save_reservations(reservations_data):
    try:
        data_to_save = []
        for item in reservations_data:
            copied_item = item.copy()
            if 'datetime_obj' in copied_item and isinstance(copied_item['datetime_obj'], datetime.datetime):
                copied_item['datetime_str'] = copied_item['datetime_obj'].replace(tzinfo=None).isoformat()
                del copied_item['datetime_obj'] 
            # Ensure timestamp is also handled if it's a datetime object
            if 'timestamp' in copied_item and isinstance(copied_item['timestamp'], datetime.datetime):
                copied_item['timestamp'] = copied_item['timestamp'].isoformat()

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
    if selected_date.weekday() not in RESERVATION_ALLOWED_DAYS:
        return False, "예약 불가능한 요일입니다."
    if not time_slot_key or time_slot_key not in TIME_SLOTS: # 시간 슬롯 키 유효성 검사 추가
        return False, "유효하지 않은 시간 슬롯입니다."

    slot_start_time, _ = TIME_SLOTS[time_slot_key]
    slot_start_datetime_naive = datetime.datetime.combine(selected_date, slot_start_time)
    slot_start_datetime_kst = KST.localize(slot_start_datetime_naive)

    if slot_start_datetime_kst < now_kst:
        return False, "이미 지난 시간 슬롯입니다."

    deadline_datetime_kst = slot_start_datetime_kst - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
    if now_kst > deadline_datetime_kst:
        return False, f"예약 마감 시간({deadline_datetime_kst.strftime('%H:%M')})이 지났습니다."
    
    return True, "예약 가능"

def get_reservations_for_datetime(target_datetime_kst):
    return [
        res for res in st.session_state.reservations
        if res.get('datetime_obj') and res['datetime_obj'] == target_datetime_kst
    ]

def get_available_spaces(target_datetime_kst):
    reservations_at_datetime = get_reservations_for_datetime(target_datetime_kst)
    reserved_spaces = [res['room'] for res in reservations_at_datetime]
    return [space for space in ALL_SPACES_LIST if space not in reserved_spaces]

def get_available_teams(target_datetime_kst):
    reservations_at_datetime = get_reservations_for_datetime(target_datetime_kst)
    reserved_teams = [res['team'] for res in reservations_at_datetime]
    return [team for team in TEAMS_ALL if team not in reserved_teams]

# --- 예약 및 취소 처리 함수 ---
def handle_reservation_submission():
    st.session_state.form_submit_message = None 
    
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
    if not reservable and not st.session_state.admin_mode: 
        st.session_state.form_submit_message = ("error", f"예약 불가: {reason}")
        return

    current_reservations = load_reservations() 
    
    for res in current_reservations:
        if res.get('datetime_obj') == reservation_datetime_kst and res.get('room') == space:
            st.session_state.form_submit_message = ("error", f"오류: {space}은(는) 해당 시간에 방금 다른 조에 의해 예약된 것 같습니다. 다시 시도해주세요.")
            return
        if res.get('datetime_obj') == reservation_datetime_kst and res.get('team') == team:
            st.session_state.form_submit_message = ("error", f"오류: {team} 조는 해당 시간에 방금 다른 공간을 예약한 것 같습니다. 다시 시도해주세요.")
            return

    new_reservation = {
        "datetime_obj": reservation_datetime_kst, 
        "time_slot_key": time_slot_key, 
        "team": team,
        "room": space,
        "timestamp": get_kst_now() 
    }
    st.session_state.reservations.append(new_reservation)
    save_reservations(st.session_state.reservations)
    
    date_str = selected_date.strftime('%Y-%m-%d')
    day_name = get_day_korean(selected_date)
    st.session_state.form_submit_message = ("success", f"{date_str}({day_name}) {time_slot_key} **'{team}'** 조가 **'{space}'** 예약 완료.")
    st.rerun() # 예약 후 바로 상태 반영 위해

def handle_cancellation(reservation_to_cancel):
    try:
        st.session_state.reservations = [
            res for res in st.session_state.reservations
            if not (res.get('datetime_obj') == reservation_to_cancel.get('datetime_obj') and \
                    res.get('team') == reservation_to_cancel.get('team') and \
                    res.get('room') == reservation_to_cancel.get('room'))
        ]
        save_reservations(st.session_state.reservations)
        st.toast(f"🗑️ '{reservation_to_cancel.get('datetime_obj').strftime('%y-%m-%d %H:%M')} {reservation_to_cancel.get('team')} - {reservation_to_cancel.get('room')}' 예약이 취소되었습니다.", icon="✅")
        st.session_state.form_submit_message = None 
        st.rerun() 
    except Exception as e:
        st.error(f"취소 중 오류 발생: {e}")


# --- Streamlit UI ---
st.set_page_config(page_title="조모임 공간 예약", layout="wide", initial_sidebar_state="collapsed")

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

current_kst_date_on_load = get_kst_today_date()
if st.session_state.last_known_kst_date != current_kst_date_on_load:
    st.toast(f"🗓️ 한국 시간 기준으로 날짜가 {current_kst_date_on_load.strftime('%m월 %d일')}로 변경되었습니다. 정보를 새로고침합니다.")
    st.session_state.last_known_kst_date = current_kst_date_on_load
    st.session_state.reservations = load_reservations() 
    st.rerun()

st.title("조모임 공간 예약 시스템")
now_kst_for_display = get_kst_now()
st.caption(f"현재 시간 (KST): {now_kst_for_display.strftime('%Y-%m-%d %H:%M:%S')}")
st.markdown("---")

with st.sidebar:
    st.header("⚙️ 앱 설정")
    if st.button("🔄 정보 새로고침 (KST 기준)", use_container_width=True):
        st.session_state.reservations = load_reservations()
        st.rerun()

    st.markdown("---")
    st.subheader("🔑 관리자 모드")
    admin_pw_input = st.text_input("관리자 비밀번호", type="password", key="admin_pw")
    if admin_pw_input == ADMIN_PASSWORD:
        if not st.session_state.admin_mode: # Only show toast on new activation
            st.toast("관리자 모드 활성화됨", icon="👑")
        st.session_state.admin_mode = True
    elif admin_pw_input != "" and admin_pw_input != ADMIN_PASSWORD :
        st.error("비밀번호가 틀렸습니다.")
        st.session_state.admin_mode = False
    
    if st.session_state.admin_mode:
        st.success("관리자 모드 활성화 중")


    st.markdown("---")
    st.subheader("📜 전체 예약 내역 (예정)")
    if st.session_state.reservations:
        display_data = []
        # <<< START OF CHANGE 2 (Error line was here) >>>
        sorted_reservations = sorted(
            st.session_state.reservations,
            key=lambda x: x.get('datetime_obj', DEFAULT_SORT_DATETIME_KST) # Use safe default
        )
        # <<< END OF CHANGE 2 >>>
        for res_item in sorted_reservations:
            dt_obj = res_item.get('datetime_obj')
            if not dt_obj: continue 

            item_display = {
                "날짜": dt_obj.strftime('%y-%m-%d') + f"({get_day_korean(dt_obj)[0]})",
                "시간": res_item.get('time_slot_key', 'N/A'),
                "조": res_item.get('team'),
                "공간": res_item.get('room'),
            }
            # Add timestamp only if it exists and is a datetime object
            timestamp_obj = res_item.get('timestamp')
            if isinstance(timestamp_obj, datetime.datetime):
                 item_display["예약시점(KST)"] = timestamp_obj.astimezone(KST).strftime('%H:%M')
            elif isinstance(timestamp_obj, str): # if loaded as string from older json
                try:
                    item_display["예약시점(KST)"] = datetime.datetime.fromisoformat(timestamp_obj).astimezone(KST).strftime('%H:%M')
                except: # if string is not iso format
                     item_display["예약시점(KST)"] = "N/A"
            else:
                item_display["예약시점(KST)"] = "N/A"
            display_data.append(item_display)
        
        if display_data:
            all_res_df = pd.DataFrame(display_data)
            st.dataframe(all_res_df, height=300, use_container_width=True)
        else:
            st.caption("필터링 후 표시할 예약이 없습니다 (또는 항목에 datetime_obj 누락).")
    else:
        st.caption("저장된 예약이 없습니다.")


st.header("1. 예약 현황")
selected_date_status = st.date_input(
    "현황 조회 날짜 선택", 
    value=st.session_state.get("status_date", get_kst_today_date()), 
    min_value=get_kst_today_date(), # Allow viewing past dates if needed, or restrict to today onwards
    key="status_date"
)
status_day_name = get_day_korean(selected_date_status)
st.subheader(f"🗓️ {selected_date_status.strftime('%Y년 %m월 %d일')} ({status_day_name}요일) 예약 현황")

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

if not reservations_on_selected_date and selected_date_status.weekday() not in RESERVATION_ALLOWED_DAYS :
     st.info(f"{status_day_name}요일은 예약 가능한 날이 아닙니다 (수/일 제외).")
elif not reservations_on_selected_date:
     st.info(f"{selected_date_status.strftime('%m/%d')}에는 예약이 없습니다.")
else:
    df_status_display = pd.DataFrame(status_table_data).T 
    # Ensure all time slots are present and in order
    df_status_display = df_status_display.reindex(TIME_SLOTS.keys()) 
    # Fill NaN for slots with no reservations for any room, then fill remaining with "가능"
    for space_col in ALL_SPACES_LIST:
        if space_col not in df_status_display.columns:
            df_status_display[space_col] = pd.NA # Add column if missing
    df_status_display = df_status_display.fillna("<span style='color:green;'>가능</span>")
    
    ordered_columns = SPACE_LOCATIONS_DETAILED["9층"]["spaces"] + SPACE_LOCATIONS_DETAILED["지하5층"]["spaces"]
    df_status_display = df_status_display[ordered_columns] # Ensure column order

    if df_status_display.empty and reservations_on_selected_date : # Should not happen if reservations_on_selected_date is not empty
        st.info(f"{selected_date_status.strftime('%m/%d')}에는 예약이 없습니다.")
    elif not df_status_display.empty:
         st.markdown("<div class='centered-table'>" + df_status_display.to_html(escape=False) + "</div>", unsafe_allow_html=True)
    # else: (no reservations and not a reservable day - already handled)

st.markdown("---")

with st.expander(f"2. 조모임 공간 예약하기", expanded=True):
    if st.session_state.form_submit_message:
        msg_type, msg_content = st.session_state.form_submit_message
        if msg_type == "success": st.success(msg_content)
        elif msg_type == "error": st.error(msg_content)
        elif msg_type == "warning": st.warning(msg_content)
        # Keep message until next submission or explicit clear
        # st.session_state.form_submit_message = None 

    col_date, col_time = st.columns(2)
    with col_date:
        st.session_state.selected_date_for_reservation = st.date_input(
            "예약 날짜 선택",
            value=st.session_state.get("selected_date_for_reservation", get_kst_today_date()),
            min_value=get_kst_today_date(),
            key="reservation_form_date_picker" 
        )
    with col_time:
        time_slot_options = list(TIME_SLOTS.keys())
        current_selected_time_slot = st.session_state.get("selected_time_slot_key")
        time_slot_default_index = time_slot_options.index(current_selected_time_slot) if current_selected_time_slot in time_slot_options else 0

        st.session_state.selected_time_slot_key = st.selectbox(
            "예약 시간 선택",
            options=time_slot_options,
            index=time_slot_default_index,
            key="reservation_form_time_slot_selector"
        )

    selected_date_obj = st.session_state.selected_date_for_reservation
    selected_time_key = st.session_state.selected_time_slot_key
    
    now_kst_check = get_kst_now()
    # Ensure selected_time_key is valid before calling is_slot_reservable
    if selected_time_key and selected_time_key in TIME_SLOTS:
        is_reservable_slot, reservable_reason = is_slot_reservable(selected_date_obj, selected_time_key, now_kst_check)
    else:
        is_reservable_slot, reservable_reason = False, "시간 슬롯을 선택해주세요."


    form_disabled = not is_reservable_slot
    caption_message = f"선택일: {selected_date_obj.strftime('%m/%d')} ({get_day_korean(selected_date_obj)}), 시간: {selected_time_key or '미선택'}."
    if st.session_state.admin_mode:
        caption_message += f" [관리자 모드] {reservable_reason}"
        form_disabled = False # Admin can override
        if is_reservable_slot: st.caption(caption_message)
        else: st.warning(caption_message + f" (원래는 예약 불가: {reservable_reason})")

    elif is_reservable_slot:
        st.caption(caption_message + f" {reservable_reason}")
    else:
        st.warning(caption_message + f" 예약 불가: {reservable_reason}")

    if selected_date_obj and selected_time_key and selected_time_key in TIME_SLOTS: # Check again if time_key is valid
        slot_start_time_form, _ = TIME_SLOTS[selected_time_key]
        target_datetime_kst_for_form = KST.localize(datetime.datetime.combine(selected_date_obj, slot_start_time_form))

        available_spaces_for_form = get_available_spaces(target_datetime_kst_for_form)
        available_teams_for_form = get_available_teams(target_datetime_kst_for_form)

        with st.form("reservation_form_main"):
            team_radio_val = st.session_state.get("selected_team_radio")
            if available_teams_for_form:
                team_default_idx = available_teams_for_form.index(team_radio_val) \
                                   if team_radio_val in available_teams_for_form else 0
                st.radio("조 선택:", available_teams_for_form, key="selected_team_radio", index=team_default_idx, horizontal=True)
            else:
                st.warning("이 시간대에 예약 가능한 조가 없습니다."); st.session_state.selected_team_radio = None
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            space_radio_val = st.session_state.get("selected_space_radio")
            if available_spaces_for_form:
                space_default_idx = available_spaces_for_form.index(space_radio_val) \
                                    if space_radio_val in available_spaces_for_form else 0
                st.radio("조모임 공간 선택:", available_spaces_for_form, key="selected_space_radio", index=space_default_idx, horizontal=True)
            else:
                st.warning("이 시간대에 예약 가능한 조모임 공간이 없습니다."); st.session_state.selected_space_radio = None

            submit_button_disabled = form_disabled or not st.session_state.selected_space_radio or not st.session_state.selected_team_radio
            st.form_submit_button(
                "예약 신청", type="primary",
                disabled=submit_button_disabled,
                use_container_width=True,
                on_click=handle_reservation_submission # This will rerun
            )
    else:
        st.info("예약할 날짜와 시간을 먼저 선택해주세요 (시간 슬롯이 유효한지 확인).")


st.markdown("---")

st.header("3. 나의 예약 확인 및 취소")
# Ensure my_team_for_cancellation_selector uses a distinct key if it's different from selected_team_radio
# Using a default from TEAMS_ALL if not previously set
my_team_default_index = TEAMS_ALL.index(st.session_state.get("my_team_for_cancellation_selector_val", TEAMS_ALL[0])) \
                        if st.session_state.get("my_team_for_cancellation_selector_val") in TEAMS_ALL else 0

my_team_select = st.selectbox(
    "내 조 선택:", 
    TEAMS_ALL, 
    key="my_team_for_cancellation_selector_val",  # store selection here
    index=my_team_default_index
)


if my_team_select:
    my_reservations = [
        res for res in st.session_state.reservations
        if res.get('team') == my_team_select
    ]
    # <<< START OF CHANGE 3 >>>
    my_reservations_sorted = sorted(my_reservations, key=lambda x: x.get('datetime_obj', DEFAULT_SORT_DATETIME_KST)) # Use safe default
    # <<< END OF CHANGE 3 >>>


    if not my_reservations_sorted:
        st.info(f"'{my_team_select}' 조의 예약 내역이 없습니다.")
    else:
        st.markdown(f"**'{my_team_select}' 조의 예약 목록 ({len(my_reservations_sorted)} 건):**")
        for i, res_item in enumerate(my_reservations_sorted):
            dt_obj = res_item.get('datetime_obj')
            if not dt_obj: continue

            col1, col2, col3 = st.columns([3,2,1])
            with col1:
                st.text(f"{dt_obj.strftime('%Y-%m-%d (%a)')} {res_item.get('time_slot_key')}")
            with col2:
                st.text(f"📍 {res_item.get('room')}")
            with col3:
                slot_start_dt_kst = res_item.get('datetime_obj')
                now_kst_cancel_check = get_kst_now()
                
                cancel_deadline_kst = slot_start_dt_kst - datetime.timedelta(minutes=RESERVATION_DEADLINE_MINUTES)
                
                can_cancel = now_kst_cancel_check < cancel_deadline_kst or st.session_state.admin_mode

                cancel_key = f"cancel_btn_{my_team_select}_{dt_obj.strftime('%Y%m%d%H%M%S')}_{res_item.get('room')}_{i}" 
                if st.button("취소", key=cancel_key, disabled=not can_cancel, use_container_width=True):
                    handle_cancellation(res_item)
                    # st.rerun() # handle_cancellation already reruns
            if not can_cancel and not st.session_state.admin_mode:
                 st.caption(f"취소 마감({cancel_deadline_kst.strftime('%H:%M')})", unsafe_allow_html=True)
            st.divider()

if st.session_state.admin_mode:
    st.markdown("---")
    st.header("👑 4. (관리자) 전체 예약 관리")
    
    if not st.session_state.reservations:
        st.info("현재 활성화된 예약이 없습니다.")
    else:
        # <<< START OF CHANGE 4 >>>
        admin_sorted_reservations = sorted(
            st.session_state.reservations,
            key=lambda x: x.get('datetime_obj', DEFAULT_SORT_DATETIME_KST) # Use safe default
        )
        # <<< END OF CHANGE 4 >>>
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
                admin_cancel_key = f"admin_cancel_btn_{dt_obj.strftime('%Y%m%d%H%M%S')}_{res_item.get('team')}_{res_item.get('room')}_{i}"
                if st.button("강제 취소", key=admin_cancel_key, type="secondary", use_container_width=True):
                    handle_cancellation(res_item)
                    # st.rerun() # handle_cancellation already reruns
            st.divider()
