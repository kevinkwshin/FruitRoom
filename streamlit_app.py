import streamlit as st
import datetime
import pandas as pd
import json
import os

# --- 초기 설정 (이전과 동일) ---
TEAMS = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)]
ROOM_LOCATIONS_DETAILED = {
    "9층": {"name": "9층 회의실", "rooms": [f"9층-{i}호" for i in range(1, 7)]},
    "지하5층": {"name": "지하5층 회의실", "rooms": [f"지하5층-{i}호" for i in range(1, 4)]}
}
ORDERED_ROOMS = ROOM_LOCATIONS_DETAILED["9층"]["rooms"] + ROOM_LOCATIONS_DETAILED["지하5층"]["rooms"]
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
if 'selected_room_radio' not in st.session_state: st.session_state.selected_room_radio = None

# --- Helper Functions (이전과 동일) ---
def get_day_korean(date_obj): days = ["월", "화", "수", "목", "금", "토", "일"]; return days[date_obj.weekday()]
def is_reservable_today(date_obj_to_check, test_mode_active=False):
    if date_obj_to_check != datetime.date.today(): return False
    if test_mode_active: return True
    return date_obj_to_check.weekday() == 2 or date_obj_to_check.weekday() == 6

def handle_reservation_submission():
    date_for_reservation = datetime.date.today()
    team = st.session_state.get("selected_team_radio")
    room = st.session_state.get("selected_room_radio")
    st.session_state.form_submit_message = None
    if not team or not room:
        st.session_state.form_submit_message = ("warning", "조와 회의실을 모두 선택해주세요."); st.rerun(); return
    date_str = date_for_reservation.strftime('%Y-%m-%d'); day_name = get_day_korean(date_for_reservation)
    for res in st.session_state.reservations:
        if res['date'] == date_for_reservation and res['room'] == room:
            st.session_state.form_submit_message = ("error", f"{date_str} ({day_name}) {room}은(는) 이미 **'{res['team']}'** 조 예약됨."); st.rerun(); return
        if res['date'] == date_for_reservation and res['team'] == team:
            st.session_state.form_submit_message = ("error", f"{date_str} ({day_name}) **'{team}'** 조는 이미 **'{res['room']}'** 예약함."); st.rerun(); return
    new_reservation = {"date": date_for_reservation, "team": team, "room": room, "timestamp": datetime.datetime.now()}
    st.session_state.reservations.append(new_reservation); save_reservations(st.session_state.reservations)
    st.session_state.form_submit_message = ("success", f"{date_str} ({day_name}) **'{team}'** 조가 **'{room}'** 예약 완료.")
    st.session_state.selected_team_radio = None; st.session_state.selected_room_radio = None
    st.rerun()

def get_reservations_for_date(target_date): return [res for res in st.session_state.reservations if res.get('date') == target_date]

# --- Streamlit UI ---
st.set_page_config(page_title="회의실 예약", layout="centered", initial_sidebar_state="collapsed") # centered layout

# 모바일 확대 방지 CSS (이전과 유사)
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        body { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; text-size-adjust: 100%; touch-action: manipulation; }
        /* Radio 버튼 레이블 폰트 크기 (필요시) */
        /* .stRadio > label > div > p { font-size: 1rem !important; } */
        .stButton > button { font-size: 0.9rem !important; padding: 0.3rem 0.6rem !important; }
        /* Streamlit 컨테이너의 최대 너비 제한 (centered layout 시) */
        .main .block-container { max-width: 750px; padding-left: 1rem; padding-right: 1rem; }
        h1 { font-size: 1.8rem !important; } h2 { font-size: 1.5rem !important; } h3 { font-size: 1.25rem !important; }
        /* 모든 stMarkdown 요소의 기본 마진 줄이기 (너무 붙지 않게 조절) */
        div[data-testid="stMarkdownContainer"] p { margin-bottom: 0.5rem !important; }
        /* 구분선 마진 줄이기 */
        hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("회의실 예약") # 페이지 상단에 한 번만 표시

# --- 사이드바 ---
with st.sidebar:
    st.header("앱 설정")
    if 'test_mode_checkbox_key' not in st.session_state:
        st.session_state.test_mode_checkbox_key = False
    st.session_state.test_mode = st.checkbox("🧪 테스트 모드", key="test_mode_checkbox_key", help="요일 제한 없이 오늘 날짜로 예약 가능")

    if st.button("🔄 오늘 날짜로 새로고침", use_container_width=True):
        st.rerun()

    if st.session_state.test_mode: st.warning("테스트 모드가 활성화되어 있습니다.")
    
    st.markdown("---")
    with st.expander("전체 예약 내역 (오늘 이후)", expanded=False): # 기본적으로 접어둠
        if st.session_state.reservations:
            display_data = []
            sorted_reservations = sorted(st.session_state.reservations, key=lambda x: (x.get('date', datetime.date.min), x.get('room', '')))
            for res_item in sorted_reservations:
                item = res_item.copy()
                current_date_obj = res_item.get('date')
                item['date_str'] = f"{current_date_obj.strftime('%y-%m-%d')}({get_day_korean(current_date_obj)[0]})" if isinstance(current_date_obj, datetime.date) else "날짜X" # 날짜 간결화
                current_timestamp_obj = res_item.get('timestamp')
                item['timestamp_str'] = current_timestamp_obj.strftime('%H:%M') if isinstance(current_timestamp_obj, datetime.datetime) else "N/A" # 시간만
                display_data.append(item)
            all_res_df = pd.DataFrame(display_data)
            if not all_res_df.empty:
                st.dataframe(all_res_df[['date_str', 'team', 'room', 'timestamp_str']].rename(
                    columns={'date_str': '날짜', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
                ), height=250, use_container_width=True)
            else: st.caption("표시할 예약 내역이 없습니다.")
        else: st.caption("저장된 예약이 없습니다.")


# --- 메인 화면 ---
# 오늘 날짜 및 요일 표시 (앱 상단에 한 번)
current_app_date = datetime.date.today()
day_name_app = get_day_korean(current_app_date)
st.subheader(f"🗓️ {current_app_date.strftime('%Y년 %m월 %d일')} ({day_name_app}요일)")
st.markdown("---")


# --- 1. 오늘 예약 현황 ---
# st.header("1. 오늘 예약 현황") # 섹션 헤더 대신 expander 제목 사용
with st.expander("오늘 예약 현황 보기", expanded=True): # 기본적으로 펼쳐둠
    reservations_on_display_date = get_reservations_for_date(current_app_date)
    if reservations_on_display_date:
        # st.markdown("##### 예약된 조:") # expander 내에서는 중복 느낌
        reserved_teams_rooms = [f"{res['team']}-{res['room'].split('-')[-1]}" for res in sorted(reservations_on_display_date, key=lambda x: x['room'])]
        if reserved_teams_rooms:
            st.info(" ".join(reserved_teams_rooms)) # 쉼표 대신 공백으로 더 압축
        
        # st.markdown("##### 회의실별 상세:")
        col1_status, col2_status = st.columns(2)
        floor_keys = ["9층", "지하5층"]
        cols = [col1_status, col2_status]
        for i, floor_key in enumerate(floor_keys):
            with cols[i]:
                floor_info = ROOM_LOCATIONS_DETAILED[floor_key]
                st.markdown(f"**{floor_info['name']}**")
                for room in floor_info['rooms']:
                    room_short_name = room.split('-')[-1] # "1호"
                    reserved_team = next((res['team'] for res in reservations_on_display_date if res['room'] == room), None)
                    if reserved_team: st.markdown(f"<small>- {room_short_name}: <span style='color:red;'>{reserved_team}</span></small>", unsafe_allow_html=True) # 폰트 작게
                    else: st.markdown(f"<small>- {room_short_name}: <span style='color:green;'>가능</span></small>", unsafe_allow_html=True) # 폰트 작게
    else:
        st.caption(f"오늘은 예약된 회의실이 없습니다.")
st.markdown("---")


# --- 2. 예약하기 (오늘) ---
# st.header("2. 예약하기") # 섹션 헤더 대신 expander 제목 사용
with st.expander("회의실 예약하기", expanded=True): # 기본적으로 펼쳐둠
    today_date_for_reservation_form = current_app_date # 앱 상단 날짜와 동일
    today_day_name_res_form = day_name_app
    reservable_today_flag = is_reservable_today(today_date_for_reservation_form, st.session_state.test_mode)

    if st.session_state.form_submit_message:
        msg_type, msg_content = st.session_state.form_submit_message
        if msg_type == "success": st.success(msg_content)
        elif msg_type == "error": st.error(msg_content)
        elif msg_type == "warning": st.warning(msg_content)
        st.session_state.form_submit_message = None # 메시지 표시 후 초기화

    # 예약 가능 여부 안내 (예약 폼 위에)
    if st.session_state.test_mode:
        st.caption(f"오늘은 [테스트 모드]로 예약 가능합니다.")
    elif reservable_today_flag:
        st.caption(f"오늘은 예약 가능합니다.")
    else:
        st.caption(f"⚠️ 오늘은 예약이 불가능합니다 (수/일요일만 가능).")

    with st.form("reservation_form_main"):
        # Radio 버튼을 가로로 배치하여 공간 절약 시도
        st.markdown("**조 선택:**")
        selected_team_val = st.radio(
            "조 선택 레이블 숨김", TEAMS, key="selected_team_radio",
            index=TEAMS.index(st.session_state.selected_team_radio) if st.session_state.selected_team_radio in TEAMS else 0,
            horizontal=True, label_visibility="collapsed" # 레이블 숨기고 가로 배치
        )
        st.markdown("<br>", unsafe_allow_html=True) # Radio 그룹 간 간격
        
        st.markdown("**회의실 선택:**")
        selected_room_val = st.radio(
            "회의실 선택 레이블 숨김", ORDERED_ROOMS, key="selected_room_radio",
            index=ORDERED_ROOMS.index(st.session_state.selected_room_radio) if st.session_state.selected_room_radio in ORDERED_ROOMS else 0,
            horizontal=True, label_visibility="collapsed" # 레이블 숨기고 가로 배치
        )
        
        st.form_submit_button(
            "예약 신청", type="primary", disabled=not reservable_today_flag,
            use_container_width=True, on_click=handle_reservation_submission
        )