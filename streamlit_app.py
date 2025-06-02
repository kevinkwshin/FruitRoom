import streamlit as st
import datetime
import pandas as pd
import json
import os

# --- 초기 설정 ---
TEAMS = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)]
ROOM_LOCATIONS_DETAILED = {
    "9층": {"name": "9층 회의실", "rooms": [f"9층-{i}호" for i in range(1, 7)]},
    "지하5층": {"name": "지하5층 회의실", "rooms": [f"지하5층-{i}호" for i in range(1, 4)]}
}
ORDERED_ROOMS = ROOM_LOCATIONS_DETAILED["9층"]["rooms"] + ROOM_LOCATIONS_DETAILED["지하5층"]["rooms"]
RESERVATION_FILE = "reservations.json"

# --- 데이터 로드 및 저장 함수 (이전과 동일, 과거 데이터 필터링 로직 포함) ---
def load_reservations():
    if os.path.exists(RESERVATION_FILE):
        try:
            with open(RESERVATION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
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
                except ValueError:
                    print(f"Warning: Skipping item with invalid date format: {item}")
                    continue
            return valid_reservations
        except Exception as e:
            st.error(f"예약 데이터 로드 중 오류: {e}")
            return []
    return []

def save_reservations_internal(reservations_data):
    try:
        data_to_save = []
        for item in reservations_data:
            copied_item = item.copy()
            if isinstance(copied_item.get('date'), datetime.date):
                 copied_item['date'] = copied_item['date'].isoformat()
            if 'timestamp' in copied_item and isinstance(copied_item['timestamp'], datetime.datetime):
                copied_item['timestamp'] = copied_item['timestamp'].isoformat()
            data_to_save.append(copied_item)
        with open(RESERVATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"내부 예약 데이터 저장 실패: {e}")

def save_reservations(reservations_data):
    save_reservations_internal(reservations_data)

# 세션 상태 초기화
if 'reservations' not in st.session_state:
    st.session_state.reservations = load_reservations()
if 'test_mode' not in st.session_state:
    st.session_state.test_mode = False
if 'form_submit_message' not in st.session_state:
    st.session_state.form_submit_message = None
# Radio 버튼용 세션 상태 (선택 값 저장 및 초기화용)
if 'selected_team_radio' not in st.session_state:
    st.session_state.selected_team_radio = None
if 'selected_room_radio' not in st.session_state:
    st.session_state.selected_room_radio = None


# --- Helper Functions ---
def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

def is_reservable_today(date_obj_to_check, test_mode_active=False):
    # 이 함수는 항상 현재 스크립트 실행 시점의 datetime.date.today()와 비교
    if date_obj_to_check != datetime.date.today():
        return False
    if test_mode_active:
        return True
    return date_obj_to_check.weekday() == 2 or date_obj_to_check.weekday() == 6

def handle_reservation_submission():
    date_for_reservation = datetime.date.today()
    # Radio 버튼의 값은 st.session_state에서 직접 가져옴 (key 사용)
    team = st.session_state.get("selected_team_radio")
    room = st.session_state.get("selected_room_radio")
    
    st.session_state.form_submit_message = None

    if not team or not room:
        st.session_state.form_submit_message = ("warning", "조와 회의실을 모두 선택해주세요.")
        st.rerun()
        return

    date_str = date_for_reservation.strftime('%Y-%m-%d')
    day_name = get_day_korean(date_for_reservation)

    for res in st.session_state.reservations:
        if res['date'] == date_for_reservation and res['room'] == room:
            st.session_state.form_submit_message = ("error", f"{date_str} ({day_name}) {room}은(는) 이미 **'{res['team']}'** 조에 의해 예약되어 있습니다.")
            st.rerun()
            return
        if res['date'] == date_for_reservation and res['team'] == team:
            st.session_state.form_submit_message = ("error", f"{date_str} ({day_name}) **'{team}'** 조는 이미 **'{res['room']}'**을(를) 예약했습니다.")
            st.rerun()
            return
            
    new_reservation = {"date": date_for_reservation, "team": team, "room": room, "timestamp": datetime.datetime.now()}
    st.session_state.reservations.append(new_reservation)
    save_reservations(st.session_state.reservations)
    st.session_state.form_submit_message = ("success", f"{date_str} ({day_name}) **'{team}'** 조가 **'{room}'**을(를) 성공적으로 예약했습니다.")
    
    # Radio 버튼 선택값 초기화
    st.session_state.selected_team_radio = None
    st.session_state.selected_room_radio = None
    
    st.rerun()

def get_reservations_for_date(target_date):
    return [res for res in st.session_state.reservations if res.get('date') == target_date]

# --- Streamlit UI ---
st.set_page_config(
    page_title="회의실 예약",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 모바일 확대 방지 CSS (Selectbox 관련 CSS는 주석 처리 또는 삭제)
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        body {
            -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; text-size-adjust: 100%;
            touch-action: manipulation;
        }
        /* Radio 버튼의 폰트 크기는 보통 body/p 태그를 따르므로 별도 지정이 덜 필요할 수 있음 */
        /* 필요하다면 .stRadio > label > div > p { font-size: 16px !important; } 와 같이 지정 */

        select, input[type="text"], input[type="date"], textarea { font-size: 16px !important; }
        .stButton > button { font-size: 15px !important; padding: 0.4rem 0.75rem !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("회의실 예약")
st.markdown("---")

# --- 사이드바 ---
st.sidebar.header("앱 설정")
if 'test_mode_checkbox_key' not in st.session_state:
    st.session_state.test_mode_checkbox_key = False
st.session_state.test_mode = st.sidebar.checkbox("🧪 테스트 모드 (요일 제한 없이 예약)", key="test_mode_checkbox_key")

if st.sidebar.button("🔄 오늘 날짜로 정보 새로고침"):
    # st.session_state.reservations = load_reservations() # 파일 다시 로드 (선택사항)
    st.rerun()

if st.session_state.test_mode: st.sidebar.warning("테스트 모드가 활성화되어 있습니다.")
st.sidebar.markdown("---")
st.sidebar.subheader("전체 예약 내역 (오늘 이후)")
if st.session_state.reservations:
    display_data = []
    sorted_reservations = sorted(st.session_state.reservations, key=lambda x: (x.get('date', datetime.date.min), x.get('room', '')))
    for res_item in sorted_reservations:
        item = res_item.copy()
        current_date_obj = res_item.get('date')
        item['date_str'] = f"{current_date_obj.strftime('%Y-%m-%d')} ({get_day_korean(current_date_obj)})" if isinstance(current_date_obj, datetime.date) else "날짜 없음"
        current_timestamp_obj = res_item.get('timestamp')
        item['timestamp_str'] = current_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S') if isinstance(current_timestamp_obj, datetime.datetime) else "N/A"
        display_data.append(item)
    all_res_df = pd.DataFrame(display_data)
    if not all_res_df.empty:
        st.sidebar.dataframe(all_res_df[['date_str', 'team', 'room', 'timestamp_str']].rename(
            columns={'date_str': '날짜(요일)', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
        ), height=300)
    else: st.sidebar.write("표시할 예약 내역이 없습니다.")
else: st.sidebar.write("저장된 예약이 없습니다.")
st.sidebar.markdown("---")


# --- 1. 오늘 예약 현황 ---
st.header("1. 오늘 예약 현황")
# 이 날짜는 항상 스크립트 실행 시점의 오늘 날짜
current_display_date = datetime.date.today()
day_name_view = get_day_korean(current_display_date)
st.subheader(f"📅 {current_display_date.strftime('%Y-%m-%d')} ({day_name_view})")

reservations_on_display_date = get_reservations_for_date(current_display_date)
if reservations_on_display_date:
    st.markdown("##### 예약된 조:")
    reserved_teams_rooms = [f"{res['team']} - {res['room']}" for res in sorted(reservations_on_display_date, key=lambda x: x['room'])]
    if reserved_teams_rooms: st.info(", ".join(reserved_teams_rooms))
st.markdown("---")
st.markdown("##### 회의실별 상세:")
col1_status, col2_status = st.columns(2)
floor_keys = ["9층", "지하5층"]
cols = [col1_status, col2_status]
for i, floor_key in enumerate(floor_keys):
    with cols[i]:
        floor_info = ROOM_LOCATIONS_DETAILED[floor_key]
        st.markdown(f"**{floor_info['name']}**")
        for room in floor_info['rooms']:
            room_short_name = room.split('-')[-1]
            reserved_team = next((res['team'] for res in reservations_on_display_date if res['room'] == room), None)
            if reserved_team: st.markdown(f"- {room_short_name}: <span style='color:red;'>**{reserved_team}**</span>", unsafe_allow_html=True)
            else: st.markdown(f"- {room_short_name}: <span style='color:green;'>가능</span>", unsafe_allow_html=True)
if not reservations_on_display_date:
    st.info(f"오늘({current_display_date.strftime('%Y-%m-%d')})은 예약된 회의실이 없습니다.")
st.markdown("---")

# --- 2. 예약하기 (오늘) ---
st.header("2. 예약하기")
today_date_for_reservation_form = datetime.date.today()
today_day_name_res_form = get_day_korean(today_date_for_reservation_form)
reservable_today_flag = is_reservable_today(today_date_for_reservation_form, st.session_state.test_mode)

if st.session_state.form_submit_message:
    msg_type, msg_content = st.session_state.form_submit_message
    if msg_type == "success": st.success(msg_content)
    elif msg_type == "error": st.error(msg_content)
    elif msg_type == "warning": st.warning(msg_content)
    st.session_state.form_submit_message = None

if st.session_state.test_mode:
    st.caption(f"오늘은 {today_date_for_reservation_form.strftime('%Y-%m-%d')} ({today_day_name_res_form}요일) 입니다. [테스트 모드] 예약이 가능합니다.")
elif reservable_today_flag:
    st.caption(f"오늘은 {today_date_for_reservation_form.strftime('%Y-%m-%d')} ({today_day_name_res_form}요일) 입니다. 예약이 가능합니다.")
else:
    st.caption(f"⚠️ 오늘은 {today_date_for_reservation_form.strftime('%Y-%m-%d')} ({today_day_name_res_form}요일) 입니다. 예약은 당일이면서 수/일요일만 가능합니다.")

with st.form("reservation_form_main"):
    # Radio 버튼으로 변경
    # st.radio는 기본적으로 첫 번째 항목이 선택되거나, index=None (Streamlit 1.26.0+ 에서 지원) 또는 추가 로직으로 초기 선택 없앨 수 있음
    # 여기서는 index=0 (첫 번째 항목)이 기본 선택되도록 둠. 사용자가 명시적으로 선택하도록 유도.
    # 선택된 값을 st.session_state에 저장하기 위해 key 사용
    selected_team_val = st.radio(
        "조 선택:",
        TEAMS,
        key="selected_team_radio", # 이 key로 세션 상태에 저장됨
        index=TEAMS.index(st.session_state.selected_team_radio) if st.session_state.selected_team_radio in TEAMS else 0, # 이전 선택 유지 또는 첫번째
        # horizontal=True # 목록이 길면 세로가 더 나을 수 있음
    )
    
    selected_room_val = st.radio(
        "회의실 선택:",
        ORDERED_ROOMS,
        key="selected_room_radio",
        index=ORDERED_ROOMS.index(st.session_state.selected_room_radio) if st.session_state.selected_room_radio in ORDERED_ROOMS else 0,
        # horizontal=True
    )
    
    st.form_submit_button(
        "예약 신청",
        type="primary",
        disabled=not reservable_today_flag,
        use_container_width=True,
        on_click=handle_reservation_submission
    )