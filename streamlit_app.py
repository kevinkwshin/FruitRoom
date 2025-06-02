import streamlit as st
import datetime
import pandas as pd
import json
import os

# --- 초기 설정 ---
TEAMS = [
    "대면A", "대면B", "대면C",
    "1조", "2조", "3조", "4조", "5조",
    "6조", "7조", "8조", "9조", "10조", "11조"
]
ROOM_LOCATIONS_DETAILED = { # 상세 정보 포함 (정렬 및 표시에 사용)
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
        except Exception:
            return []
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
    except Exception as e:
        st.error(f"예약 데이터 저장 실패: {e}")


# 세션 상태 초기화
if 'reservations' not in st.session_state:
    st.session_state.reservations = load_reservations()
if 'test_mode' not in st.session_state:
    st.session_state.test_mode = False

# --- Helper Functions (이전과 동일) ---
def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

def is_reservable_today(date_obj, test_mode_active=False):
    if date_obj != datetime.date.today():
        return False
    if test_mode_active:
        return True
    return date_obj.weekday() == 2 or date_obj.weekday() == 6

def add_reservation(date, team, room):
    date_str = date.strftime('%Y-%m-%d')
    day_name = get_day_korean(date)
    for res in st.session_state.reservations:
        if res['date'] == date and res['room'] == room:
            st.error(f"{date_str} ({day_name}) {room}은(는) 이미 **'{res['team']}'** 조에 의해 예약되어 있습니다.")
            return False
        if res['date'] == date and res['team'] == team:
            st.error(f"{date_str} ({day_name}) **'{team}'** 조는 이미 **'{res['room']}'**을(를) 예약했습니다.")
            return False
    new_reservation = {"date": date, "team": team, "room": room, "timestamp": datetime.datetime.now()}
    st.session_state.reservations.append(new_reservation)
    save_reservations(st.session_state.reservations)
    st.success(f"{date_str} ({day_name}) **'{team}'** 조가 **'{room}'**을(를) 성공적으로 예약했습니다.")
    return True

def get_reservations_for_date(date):
    return [res for res in st.session_state.reservations if res['date'] == date]

# --- Streamlit UI ---
st.set_page_config(
    page_title="회의실 예약",
    layout="wide",
    initial_sidebar_state="collapsed" # 모바일에서 사이드바 초기에 닫기
)

# 모바일 확대 방지 및 스타일링 시도
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
        body { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; } /* 텍스트 크기 고정 시도 */
        #root > div:nth-child(1) > div > div > div > div > section[data-testid="stSidebar"] {
            width: 280px; /* 사이드바 너비 고정 (필요시 조정) */
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
if st.session_state.test_mode:
    st.sidebar.warning("테스트 모드가 활성화되어 있습니다.")
st.sidebar.markdown("---")
st.sidebar.subheader("전체 예약 내역")
if st.session_state.reservations:
    display_data = []
    for res_item in sorted(st.session_state.reservations, key=lambda x: (x['date'], x['room'])):
        item = res_item.copy()
        item['date_str'] = f"{res_item['date'].strftime('%Y-%m-%d')} ({get_day_korean(res_item['date'])})"
        item['timestamp_str'] = res_item['timestamp'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(res_item.get('timestamp'), datetime.datetime) else "N/A"
        display_data.append(item)
    all_res_df = pd.DataFrame(display_data)
    st.sidebar.dataframe(all_res_df[['date_str', 'team', 'room', 'timestamp_str']].rename(
        columns={'date_str': '날짜(요일)', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
    ), height=300)
else:
    st.sidebar.write("저장된 예약이 없습니다.")
st.sidebar.markdown("---")


# --- 1. 오늘 예약 현황 ---
st.header("1. 오늘 예약 현황")
today_for_view = datetime.date.today()
day_name_view = get_day_korean(today_for_view)
st.subheader(f"📅 {today_for_view.strftime('%Y-%m-%d')} ({day_name_view})")

reservations_on_today = get_reservations_for_date(today_for_view)

if reservations_on_today:
    st.markdown("##### 예약된 조:")
    reserved_teams_rooms = [f"{res['team']}-{res['room'].split('-')[-1]}" for res in sorted(reservations_on_today, key=lambda x: x['room'])]
    if reserved_teams_rooms:
        st.info(", ".join(reserved_teams_rooms)) # 9층-1호 -> 9층-1호 (회의실 이름 그대로)
    else:
        st.info("현재 예약된 조가 없습니다.")
else:
    st.info(f"오늘은 예약된 회의실이 없습니다.") # 예약이 하나도 없을 때

st.markdown("##### 회의실별 상세:")
col1_status, col2_status = st.columns(2) # 9층과 지하5층을 좌우로 배치

with col1_status:
    floor_key = "9층"
    floor_info = ROOM_LOCATIONS_DETAILED[floor_key]
    st.markdown(f"**{floor_info['name']}**")
    for room in floor_info['rooms']:
        room_short_name = room.split('-')[-1] # 예: "1호"
        reserved_team = next((res['team'] for res in reservations_on_today if res['room'] == room), None)
        if reserved_team:
            st.markdown(f"- {room_short_name}: <span style='color:red;'>**{reserved_team}**</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"- {room_short_name}: <span style='color:green;'>가능</span>", unsafe_allow_html=True)
    st.markdown("---") # 구분선

with col2_status:
    floor_key = "지하5층"
    floor_info = ROOM_LOCATIONS_DETAILED[floor_key]
    st.markdown(f"**{floor_info['name']}**")
    for room in floor_info['rooms']:
        room_short_name = room.split('-')[-1]
        reserved_team = next((res['team'] for res in reservations_on_today if res['room'] == room), None)
        if reserved_team:
            st.markdown(f"- {room_short_name}: <span style='color:red;'>**{reserved_team}**</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"- {room_short_name}: <span style='color:green;'>가능</span>", unsafe_allow_html=True)
    st.markdown("---")


# --- 2. 예약하기 (오늘) ---
st.header("2. 예약하기")
today_date_res = datetime.date.today()
today_day_name_res = get_day_korean(today_date_res)
reservable_today = is_reservable_today(today_date_res, st.session_state.test_mode)

if st.session_state.test_mode:
    st.caption(f"오늘은 {today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. [테스트 모드] 예약이 가능합니다.")
elif reservable_today:
    st.caption(f"오늘은 {today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. 예약이 가능합니다.")
else:
    st.caption(f"⚠️ 오늘은 {today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. 예약은 당일이면서 수/일요일만 가능합니다.")

with st.form("reservation_form"):
    col1_form, col2_form = st.columns(2)
    with col1_form:
        selected_team = st.selectbox("조 선택", TEAMS, key="res_team_select", index=None, placeholder="조를 선택하세요")
    with col2_form:
        selected_room = st.selectbox("회의실 선택", ORDERED_ROOMS, key="res_room_select", index=None, placeholder="회의실을 선택하세요")
    submitted = st.form_submit_button("예약 신청", type="primary", disabled=not reservable_today, use_container_width=True)

if submitted:
    if not selected_team or not selected_room:
        st.warning("조와 회의실을 모두 선택해주세요.")
    else:
        add_reservation(today_date_res, selected_team, selected_room)