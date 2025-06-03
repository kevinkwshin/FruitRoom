import streamlit as st
import datetime
import pandas as pd
import json
import os

# --- 초기 설정 ---
TEAMS = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)]
SPACE_LOCATIONS_DETAILED = { # "회의실" -> "조모임 공간"
    "9층": {"name": "9층 조모임 공간", "spaces": [f"9층-{i}호" for i in range(1, 7)]},
    "지하5층": {"name": "지하5층 조모임 공간", "spaces": [f"지하5층-{i}호" for i in range(1, 4)]}
}
ORDERED_SPACES = SPACE_LOCATIONS_DETAILED["9층"]["spaces"] + SPACE_LOCATIONS_DETAILED["지하5층"]["spaces"]
RESERVATION_FILE = "reservations.json"

# --- 데이터 로드 및 저장 함수 (이전과 동일) ---
def load_reservations():
    if os.path.exists(RESERVATION_FILE):
        try:
            with open(RESERVATION_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            today_date = datetime.date.today()
            valid_reservations = []
            for item in data:
                try:
                    reservation_date_str = item.get('date')
                    if not reservation_date_str: continue
                    reservation_date = datetime.datetime.strptime(reservation_date_str, '%Y-%m-%d').date()
                    if reservation_date >= today_date:
                        item['date'] = reservation_date
                        if 'timestamp' in item and isinstance(item['timestamp'], str):
                            try: item['timestamp'] = datetime.datetime.fromisoformat(item['timestamp'])
                            except ValueError: item['timestamp'] = None
                        valid_reservations.append(item)
                except ValueError: print(f"Warning: Skipping item with invalid date format: {item}"); continue
            return valid_reservations
        except Exception as e: st.error(f"예약 데이터 로드 중 오류: {e}"); return []
    return []

def save_reservations_internal(reservations_data):
    try:
        data_to_save = []
        for item in reservations_data:
            copied_item = item.copy()
            if isinstance(copied_item.get('date'), datetime.date): copied_item['date'] = copied_item['date'].isoformat()
            if 'timestamp' in copied_item and isinstance(copied_item['timestamp'], datetime.datetime): copied_item['timestamp'] = copied_item['timestamp'].isoformat()
            data_to_save.append(copied_item)
        with open(RESERVATION_FILE, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"내부 예약 데이터 저장 실패: {e}")

def save_reservations(reservations_data): save_reservations_internal(reservations_data)

# 세션 상태 초기화 (이전과 동일)
if 'reservations' not in st.session_state: st.session_state.reservations = load_reservations()
if 'test_mode' not in st.session_state: st.session_state.test_mode = False
if 'form_submit_message' not in st.session_state: st.session_state.form_submit_message = None
if 'selected_team_radio' not in st.session_state: st.session_state.selected_team_radio = None
if 'selected_space_radio' not in st.session_state: st.session_state.selected_space_radio = None # room -> space

# --- Helper Functions (이전과 동일) ---
def get_day_korean(date_obj): days = ["월", "화", "수", "목", "금", "토", "일"]; return days[date_obj.weekday()]
def is_reservable_today(date_obj_to_check, test_mode_active=False):
    if date_obj_to_check != datetime.date.today(): return False
    if test_mode_active: return True
    return date_obj_to_check.weekday() == 2 or date_obj_to_check.weekday() == 6

def handle_reservation_submission():
    date_for_reservation = datetime.date.today()
    team = st.session_state.get("selected_team_radio")
    space = st.session_state.get("selected_space_radio") # room -> space
    st.session_state.form_submit_message = None

    if not team or not space:
        st.session_state.form_submit_message = ("warning", "조와 조모임 공간을 모두 선택해주세요.")
        return

    date_str = date_for_reservation.strftime('%Y-%m-%d'); day_name = get_day_korean(date_for_reservation)
    
    for res in st.session_state.reservations:
        if res['date'] == date_for_reservation and res['room'] == space: # 'room' key는 DB 호환성 위해 유지, 변수명은 space
            st.session_state.form_submit_message = ("error", f"오류: {space}은(는) 방금 다른 조에 의해 예약된 것 같습니다. 다시 시도해주세요."); return
        if res['date'] == date_for_reservation and res['team'] == team:
            st.session_state.form_submit_message = ("error", f"{date_str} ({day_name}) **'{team}'** 조는 이미 **'{res['room']}'** 예약함."); return
            
    new_reservation = {"date": date_for_reservation, "team": team, "room": space, "timestamp": datetime.datetime.now()} # DB에는 'room'으로 저장
    st.session_state.reservations.append(new_reservation); save_reservations(st.session_state.reservations)
    st.session_state.form_submit_message = ("success", f"{date_str} ({day_name}) **'{team}'** 조가 **'{space}'** 예약 완료.")
    st.session_state.selected_team_radio = None; st.session_state.selected_space_radio = None # room -> space
    # st.rerun() 제거됨

def get_reservations_for_date(target_date): return [res for res in st.session_state.reservations if res.get('date') == target_date]

def get_available_spaces_for_today(): # room -> space
    """오늘 예약 가능한 조모임 공간 목록을 반환합니다."""
    all_spaces = SPACE_LOCATIONS_DETAILED["9층"]["spaces"] + SPACE_LOCATIONS_DETAILED["지하5층"]["spaces"]
    today_reservations = get_reservations_for_date(datetime.date.today())
    reserved_spaces_today = [res['room'] for res in today_reservations] # DB는 'room'
    available_spaces = [space for space in all_spaces if space not in reserved_spaces_today]
    return available_spaces

# --- Streamlit UI ---
st.set_page_config(page_title="조모임 공간 예약", layout="centered", initial_sidebar_state="collapsed") # 용어 변경

st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        body { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; text-size-adjust: 100%; touch-action: manipulation; }
        .stButton > button { font-size: 0.9rem !important; padding: 0.3rem 0.6rem !important; }
        .main .block-container { max-width: 750px; padding-left: 1rem; padding-right: 1rem; }
        h1 { font-size: 1.8rem !important; } h2 { font-size: 1.5rem !important; } h3 { font-size: 1.25rem !important; }
        div[data-testid="stMarkdownContainer"] p { margin-bottom: 0.5rem !important; }
        hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
        .stRadio > label { font-size: 1rem !important; margin-bottom: 0.2rem !important; }
        .stRadio > div[role="radiogroup"] > div { margin-bottom: 0.1rem !important; }
        .stRadio label span { font-size: 0.95rem !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("조모임 공간 예약") # 용어 변경
current_app_date = datetime.date.today()
day_name_app = get_day_korean(current_app_date)
st.subheader(f"🗓️ {current_app_date.strftime('%Y년 %m월 %d일')} ({day_name_app}요일)")
st.markdown("---")

# --- 사이드바 ---
with st.sidebar:
    st.header("앱 설정")
    if 'test_mode_checkbox_key' not in st.session_state: st.session_state.test_mode_checkbox_key = False
    st.session_state.test_mode = st.checkbox("🧪 테스트 모드", key="test_mode_checkbox_key", help="요일 제한 없이 오늘 날짜로 예약 가능")
    if st.button("🔄 오늘 날짜로 새로고침", use_container_width=True): st.rerun()
    if st.session_state.test_mode: st.warning("테스트 모드가 활성화되어 있습니다.")
    st.markdown("---")
    with st.expander("전체 예약 내역 (오늘 이후)", expanded=False):
        if st.session_state.reservations:
            display_data = []
            sorted_reservations = sorted(st.session_state.reservations, key=lambda x: (x.get('date', datetime.date.min), x.get('room', ''))) # DB는 'room'
            for res_item in sorted_reservations:
                item = res_item.copy(); current_date_obj = res_item.get('date')
                item['date_str'] = f"{current_date_obj.strftime('%y-%m-%d')}({get_day_korean(current_date_obj)[0]})" if isinstance(current_date_obj, datetime.date) else "날짜X"
                current_timestamp_obj = res_item.get('timestamp')
                item['timestamp_str'] = current_timestamp_obj.strftime('%H:%M') if isinstance(current_timestamp_obj, datetime.datetime) else "N/A"
                item['space_name'] = res_item.get('room') # UI 표시용 변수 추가
                display_data.append(item)
            all_res_df = pd.DataFrame(display_data)
            if not all_res_df.empty:
                st.dataframe(all_res_df[['date_str', 'team', 'space_name', 'timestamp_str']].rename( # room -> space_name
                    columns={'date_str': '날짜', 'team': '조', 'space_name': '공간', 'timestamp_str': '예약시간'} # 용어 변경
                ), height=250, use_container_width=True)
            else: st.caption("표시할 예약 내역이 없습니다.")
        else: st.caption("저장된 예약이 없습니다.")

# --- 1. 오늘 예약 현황 (레이아웃 변경) ---
with st.expander("오늘 예약 현황 보기", expanded=True):
    reservations_on_display_date = get_reservations_for_date(current_app_date)
    if reservations_on_display_date:
        reserved_list_text = [f"{res['team']}-{res['room'].split('-')[-1]}" for res in sorted(reservations_on_display_date, key=lambda x: x['room'])]
        if reserved_list_text: st.info(" ".join(reserved_list_text))
        
        # 9층과 지하5층을 좌우 컬럼으로 배치
        col1_status, col2_status = st.columns(2)

        with col1_status:
            floor_key = "9층"
            floor_info = SPACE_LOCATIONS_DETAILED[floor_key]
            st.markdown(f"**{floor_info['name']}**")
            for space_name_full in floor_info['spaces']:
                space_short_name = space_name_full.split('-')[-1]
                reserved_team = next((res['team'] for res in reservations_on_display_date if res['room'] == space_name_full), None) # DB는 'room'
                if reserved_team: st.markdown(f"<small>- {space_short_name}: <span style='color:red;'>{reserved_team}</span></small>", unsafe_allow_html=True)
                else: st.markdown(f"<small>- {space_short_name}: <span style='color:green;'>가능</span></small>", unsafe_allow_html=True)
        
        with col2_status:
            floor_key = "지하5층"
            floor_info = SPACE_LOCATIONS_DETAILED[floor_key]
            st.markdown(f"**{floor_info['name']}**")
            for space_name_full in floor_info['spaces']:
                space_short_name = space_name_full.split('-')[-1]
                reserved_team = next((res['team'] for res in reservations_on_display_date if res['room'] == space_name_full), None) # DB는 'room'
                if reserved_team: st.markdown(f"<small>- {space_short_name}: <span style='color:red;'>{reserved_team}</span></small>", unsafe_allow_html=True)
                else: st.markdown(f"<small>- {space_short_name}: <span style='color:green;'>가능</span></small>", unsafe_allow_html=True)
    else:
        st.caption(f"오늘은 예약된 조모임 공간이 없습니다.") # 용어 변경
st.markdown("---")

# --- 2. 예약하기 (오늘) ---
with st.expander("조모임 공간 예약하기", expanded=True): # 용어 변경
    today_date_for_reservation_form = current_app_date
    reservable_today_flag = is_reservable_today(today_date_for_reservation_form, st.session_state.test_mode)

    if st.session_state.form_submit_message:
        msg_type, msg_content = st.session_state.form_submit_message
        if msg_type == "success": st.success(msg_content)
        elif msg_type == "error": st.error(msg_content)
        elif msg_type == "warning": st.warning(msg_content)
        st.session_state.form_submit_message = None

    if st.session_state.test_mode: st.caption(f"오늘은 [테스트 모드]로 예약 가능합니다.")
    elif reservable_today_flag: st.caption(f"오늘은 예약 가능합니다.")
    else: st.caption(f"⚠️ 오늘은 예약이 불가능합니다 (수/일요일만 가능).")

    available_spaces_for_radio = get_available_spaces_for_today() # room -> space

    with st.form("reservation_form_main"):
        team_default_index = 0
        if st.session_state.selected_team_radio and st.session_state.selected_team_radio in TEAMS:
            team_default_index = TEAMS.index(st.session_state.selected_team_radio)
        selected_team_val = st.radio("조 선택:", TEAMS, key="selected_team_radio", index=team_default_index, horizontal=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        if available_spaces_for_radio:
            space_default_index = 0
            if st.session_state.selected_space_radio and st.session_state.selected_space_radio in available_spaces_for_radio: # room -> space
                space_default_index = available_spaces_for_radio.index(st.session_state.selected_space_radio)
            elif not available_spaces_for_radio:
                 space_default_index = None
            selected_space_val = st.radio(
                "조모임 공간 선택 (예약 가능):", available_spaces_for_radio, key="selected_space_radio", # room -> space, 용어 변경
                index=space_default_index if space_default_index is not None else 0, horizontal=True
            )
        else:
            st.warning("현재 예약 가능한 조모임 공간이 없습니다.") # 용어 변경
            st.session_state.selected_space_radio = None # room -> space

        st.form_submit_button(
            "예약 신청", type="primary", 
            disabled=not reservable_today_flag or not available_spaces_for_radio,
            use_container_width=True, on_click=handle_reservation_submission
        )