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
            with open(RESERVATION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for item in data:
                    item['date'] = datetime.datetime.strptime(item['date'], '%Y-%m-%d').date()
                    if 'timestamp' in item and isinstance(item['timestamp'], str):
                        item['timestamp'] = datetime.datetime.fromisoformat(item['timestamp'])
                return data
        except Exception: return []
    return []

def save_reservations(reservations_data):
    try:
        data_to_save = []
        for item in reservations_data:
            copied_item = item.copy()
            copied_item['date'] = item['date'].isoformat()
            if 'timestamp' in item and isinstance(item['timestamp'], datetime.datetime):
                copied_item['timestamp'] = item['timestamp'].isoformat()
            data_to_save.append(copied_item)
        with open(RESERVATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=4)
    except Exception as e: st.error(f"예약 데이터 저장 실패: {e}")

# 세션 상태 초기화 (이전과 동일)
if 'reservations' not in st.session_state:
    st.session_state.reservations = load_reservations()
if 'test_mode' not in st.session_state:
    st.session_state.test_mode = False
if 'form_submit_message' not in st.session_state:
    st.session_state.form_submit_message = None


# --- Helper Functions (이전과 동일) ---
def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

def is_reservable_today(date_obj, test_mode_active=False):
    if date_obj != datetime.date.today(): return False
    if test_mode_active: return True
    return date_obj.weekday() == 2 or date_obj.weekday() == 6

def handle_reservation_submission():
    date = datetime.date.today()
    team = st.session_state.get("res_team_select_key")
    room = st.session_state.get("res_room_select_key")
    st.session_state.form_submit_message = None
    if not team or not room:
        st.session_state.form_submit_message = ("warning", "조와 회의실을 모두 선택해주세요.")
        st.rerun()
        return
    date_str = date.strftime('%Y-%m-%d')
    day_name = get_day_korean(date)
    for res in st.session_state.reservations:
        if res['date'] == date and res['room'] == room:
            st.session_state.form_submit_message = ("error", f"{date_str} ({day_name}) {room}은(는) 이미 **'{res['team']}'** 조에 의해 예약되어 있습니다.")
            st.rerun()
            return
        if res['date'] == date and res['team'] == team:
            st.session_state.form_submit_message = ("error", f"{date_str} ({day_name}) **'{team}'** 조는 이미 **'{res['room']}'**을(를) 예약했습니다.")
            st.rerun()
            return
    new_reservation = {"date": date, "team": team, "room": room, "timestamp": datetime.datetime.now()}
    st.session_state.reservations.append(new_reservation)
    save_reservations(st.session_state.reservations)
    st.session_state.form_submit_message = ("success", f"{date_str} ({day_name}) **'{team}'** 조가 **'{room}'**을(를) 성공적으로 예약했습니다.")
    st.session_state.res_team_select_key = None
    st.session_state.res_room_select_key = None
    st.rerun()

def get_reservations_for_date(date):
    return [res for res in st.session_state.reservations if res['date'] == date]

# --- Streamlit UI ---
st.set_page_config(
    page_title="회의실 예약",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 모바일 확대 방지 및 스타일링 강화
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        /* 기본 body 설정 */
        body {
            -webkit-text-size-adjust: 100%; /* iOS Safari 텍스트 자동 크기 조정 방지 */
            -ms-text-size-adjust: 100%; /* IE 텍스트 자동 크기 조정 방지 */
            text-size-adjust: 100%; /* 표준 텍스트 자동 크기 조정 방지 */
            touch-action: manipulation; /* 더블탭 등으로 인한 확대 방지 시도 */
        }

        /* Selectbox 클릭 전 보이는 부분의 폰트 크기 */
        div[data-baseweb="select"] > div,
        div[data-testid="stSelectbox"] > div > div {
            font-size: 16px !important;
        }

        /* Selectbox 드롭다운 메뉴 (옵션 리스트) 및 내부 아이템 폰트 크기 */
        /* 이 선택자들은 Streamlit/BaseWeb 버전에 따라 매우 다를 수 있으므로, 실제 검사 및 조정이 필요합니다. */
        div[data-baseweb="popover"] ul[role="listbox"] li,
        div[data-baseweb="menu"] ul[role="listbox"] li,
        div[data-baseweb="menu"] li[role="option"] { /* 좀 더 구체적인 옵션 아이템 */
            font-size: 16px !important;
            line-height: 1.6 !important; /* 가독성을 위해 줄 간격도 조절 */
        }

        /* 다른 일반적인 입력 요소들 (참고용) */
        select, input[type="text"], input[type="date"], textarea {
            font-size: 16px !important;
        }

        /* 버튼 폰트 크기는 약간 작게 유지 가능 */
        .stButton > button {
             font-size: 15px !important;
        }
    </style>
    """, unsafe_allow_html=True)

st.title("회의실 예약")
st.markdown("---")

# --- 사이드바 (이전과 거의 동일) ---
st.sidebar.header("앱 설정")
if 'test_mode_checkbox_key' not in st.session_state:
    st.session_state.test_mode_checkbox_key = False
st.session_state.test_mode = st.sidebar.checkbox("🧪 테스트 모드 (요일 제한 없이 예약)", key="test_mode_checkbox_key")
if st.session_state.test_mode: st.sidebar.warning("테스트 모드가 활성화되어 있습니다.")
st.sidebar.markdown("---")
st.sidebar.subheader("전체 예약 내역")
if st.session_state.reservations:
    display_data = []
    sorted_reservations = sorted(st.session_state.reservations, key=lambda x: (x['date'], x['room']))
    for res_item in sorted_reservations:
        item = res_item.copy()
        item['date_str'] = f"{res_item['date'].strftime('%Y-%m-%d')} ({get_day_korean(res_item['date'])})"
        item['timestamp_str'] = res_item['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(res_item.get('timestamp'), datetime.datetime) else "N/A"
        display_data.append(item)
    all_res_df = pd.DataFrame(display_data)
    st.sidebar.dataframe(all_res_df[['date_str', 'team', 'room', 'timestamp_str']].rename(
        columns={'date_str': '날짜(요일)', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
    ), height=300)
else: st.sidebar.write("저장된 예약이 없습니다.")
st.sidebar.markdown("---")


# --- 1. 오늘 예약 현황 (이전과 거의 동일) ---
st.header("1. 오늘 예약 현황")
today_for_view = datetime.date.today()
day_name_view = get_day_korean(today_for_view)
st.subheader(f"📅 {today_for_view.strftime('%Y-%m-%d')} ({day_name_view})")
reservations_on_today = get_reservations_for_date(today_for_view)
if reservations_on_today:
    st.markdown("##### 예약된 조:")
    reserved_teams_rooms = [f"{res['team']} - {res['room']}" for res in sorted(reservations_on_today, key=lambda x: x['room'])]
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
            reserved_team = next((res['team'] for res in reservations_on_today if res['room'] == room), None)
            if reserved_team:
                st.markdown(f"- {room_short_name}: <span style='color:red;'>**{reserved_team}**</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"- {room_short_name}: <span style='color:green;'>가능</span>", unsafe_allow_html=True)
if not reservations_on_today:
    st.info(f"오늘은 예약된 회의실이 없습니다.")
st.markdown("---")

# --- 2. 예약하기 (오늘) (이전과 거의 동일) ---
st.header("2. 예약하기")
today_date_res = datetime.date.today()
today_day_name_res = get_day_korean(today_date_res)
reservable_today = is_reservable_today(today_date_res, st.session_state.test_mode)
if st.session_state.form_submit_message:
    msg_type, msg_content = st.session_state.form_submit_message
    if msg_type == "success": st.success(msg_content)
    elif msg_type == "error": st.error(msg_content)
    elif msg_type == "warning": st.warning(msg_content)
    st.session_state.form_submit_message = None
if st.session_state.test_mode:
    st.caption(f"오늘은 {today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. [테스트 모드] 예약이 가능합니다.")
elif reservable_today:
    st.caption(f"오늘은 {today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. 예약이 가능합니다.")
else:
    st.caption(f"⚠️ 오늘은 {today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. 예약은 당일이면서 수/일요일만 가능합니다.")
with st.form("reservation_form_main"):
    col1_form, col2_form = st.columns(2)
    with col1_form:
        st.selectbox("조 선택", TEAMS, key="res_team_select_key", index=None, placeholder="조를 선택하세요")
    with col2_form:
        st.selectbox("회의실 선택", ORDERED_ROOMS, key="res_room_select_key", index=None, placeholder="회의실을 선택하세요")
    st.form_submit_button(
        "예약 신청",
        type="primary",
        disabled=not reservable_today,
        use_container_width=True,
        on_click=handle_reservation_submission
    )