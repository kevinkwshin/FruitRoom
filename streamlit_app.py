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

# --- 데이터 로드 및 저장 함수 ---
def load_reservations(): # 과거 데이터 필터링 로직 활성화
    if os.path.exists(RESERVATION_FILE):
        try:
            with open(RESERVATION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            today_date = datetime.date.today() # 이 함수가 호출될 때의 '오늘'
            valid_reservations = []
            for item in data:
                try:
                    reservation_date_str = item.get('date')
                    if not reservation_date_str:
                        continue # 날짜 정보가 없는 아이템은 건너뜀
                    
                    reservation_date = datetime.datetime.strptime(reservation_date_str, '%Y-%m-%d').date()
                    
                    # 오늘 날짜 또는 미래의 예약만 유지 (또는 필요한 경우 '오늘 날짜만 유지')
                    if reservation_date >= today_date: 
                        item['date'] = reservation_date # datetime.date 객체로 변환
                        if 'timestamp' in item and isinstance(item['timestamp'], str):
                            try:
                                item['timestamp'] = datetime.datetime.fromisoformat(item['timestamp'])
                            except ValueError: # ISO 형식이 아닌 경우 처리 (예: 이전 데이터)
                                item['timestamp'] = None # 또는 다른 기본값
                        valid_reservations.append(item)
                except ValueError:
                    # 날짜 형식 오류가 있는 데이터는 건너뜀
                    print(f"Warning: Skipping item with invalid date format: {item}")
                    continue
            
            # 필터링된 데이터로 파일 다시 저장 (선택 사항: 데이터 정리 시)
            # 현재는 로드 시 필터링만 하고, 파일 재저장은 save_reservations에서만 하도록 함
            # 만약 로드 시점에서 정리된 내용으로 파일을 덮어쓰고 싶다면 아래 주석 해제
            # if len(data) != len(valid_reservations): # 변경된 경우에만 저장
            #    save_reservations_internal(valid_reservations) # 별도 저장 함수 사용 또는 save_reservations 재귀 호출 주의
            return valid_reservations
        except Exception as e:
            st.error(f"예약 데이터 로드 중 오류: {e}")
            return []
    return []

def save_reservations_internal(reservations_data): # 파일 저장만 담당 (save_reservations와 구분)
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
        # st.error는 UI에 메시지를 표시하므로, 내부 저장 함수에서는 print나 logging 사용 고려
        print(f"내부 예약 데이터 저장 실패: {e}")


def save_reservations(reservations_data): # UI에 메시지 표시 가능
    save_reservations_internal(reservations_data)
    # st.success("예약 정보가 저장되었습니다.") # 필요시 메시지

# 세션 상태 초기화
if 'reservations' not in st.session_state:
    st.session_state.reservations = load_reservations() # 앱 시작/새로고침 시 과거 데이터 필터링됨
if 'test_mode' not in st.session_state:
    st.session_state.test_mode = False
if 'form_submit_message' not in st.session_state:
    st.session_state.form_submit_message = None


# --- Helper Functions ---
def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

def is_reservable_today(date_obj, test_mode_active=False):
    # 이 함수는 항상 현재 스크립트 실행 시점의 datetime.date.today()와 비교해야 함
    # 따라서 date_obj가 실제 오늘인지 확인하는 것이 중요
    if date_obj != datetime.date.today(): return False # 전달된 date_obj가 오늘이 아니면 예약 불가
    if test_mode_active: return True
    return date_obj.weekday() == 2 or date_obj.weekday() == 6

def handle_reservation_submission():
    # 이 함수 내의 date는 항상 현재 스크립트 실행 시점의 오늘 날짜임
    date_for_reservation = datetime.date.today() 
    team = st.session_state.get("res_team_select_key")
    room = st.session_state.get("res_room_select_key")
    st.session_state.form_submit_message = None
    if not team or not room:
        st.session_state.form_submit_message = ("warning", "조와 회의실을 모두 선택해주세요.")
        st.rerun()
        return
    date_str = date_for_reservation.strftime('%Y-%m-%d')
    day_name = get_day_korean(date_for_reservation)

    # 중복 체크 시 st.session_state.reservations의 날짜와 비교
    for res in st.session_state.reservations:
        # res['date']는 load_reservations에서 datetime.date 객체로 변환됨
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
    save_reservations(st.session_state.reservations) # 전체 세션 상태 저장
    st.session_state.form_submit_message = ("success", f"{date_str} ({day_name}) **'{team}'** 조가 **'{room}'**을(를) 성공적으로 예약했습니다.")
    st.session_state.res_team_select_key = None
    st.session_state.res_room_select_key = None
    st.rerun()

def get_reservations_for_date(target_date): # 함수 인자로 받은 날짜 기준 조회
    return [res for res in st.session_state.reservations if res.get('date') == target_date]

# --- Streamlit UI ---
st.set_page_config(
    page_title="회의실 예약",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 모바일 확대 방지 및 스타일링 (이전과 동일하게 최대한 시도)
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        body {
            -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; text-size-adjust: 100%;
            touch-action: manipulation;
        }
        div[data-baseweb="select"] > div,
        div[data-testid="stSelectbox"] > div > div {
            font-size: 16px !important; line-height: 1.5 !important;
        }
        div[data-baseweb="popover"] ul[role="listbox"],
        div[data-baseweb="popover"] ul[role="listbox"] li,
        div[data-baseweb="popover"] ul[role="listbox"] li div,
        div[data-baseweb="menu"] ul[role="listbox"],
        div[data-baseweb="menu"] ul[role="listbox"] li,
        div[data-baseweb="menu"] li[role="option"],
        div[data-baseweb="menu"] li[role="option"] div {
            font-size: 16px !important; line-height: 1.6 !important;
            padding-top: 0.3rem !important; padding-bottom: 0.3rem !important;
        }
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
    # st.session_state.reservations = load_reservations() # 파일에서 다시 로드 (과거 데이터 정리 효과)
    # 위 라인은 load_reservations의 파일 재저장 로직 유무에 따라 신중히 사용
    st.rerun() # 스크립트 전체 재실행으로 모든 날짜 변수 갱신

if st.session_state.test_mode: st.sidebar.warning("테스트 모드가 활성화되어 있습니다.")
st.sidebar.markdown("---")
st.sidebar.subheader("전체 예약 내역 (오늘 이후)") # 필터링된 내역을 보여줌
if st.session_state.reservations: # 이 reservations는 load_reservations에 의해 필터링된 상태일 수 있음
    display_data = []
    # 정렬은 여기서 다시 수행
    sorted_reservations = sorted(st.session_state.reservations, key=lambda x: (x.get('date', datetime.date.min), x.get('room', '')))
    for res_item in sorted_reservations:
        item = res_item.copy()
        # res_item['date']는 이미 datetime.date 객체여야 함
        current_date_obj = res_item.get('date')
        if isinstance(current_date_obj, datetime.date):
            item['date_str'] = f"{current_date_obj.strftime('%Y-%m-%d')} ({get_day_korean(current_date_obj)})"
        else:
            item['date_str'] = "날짜 없음"

        current_timestamp_obj = res_item.get('timestamp')
        if isinstance(current_timestamp_obj, datetime.datetime):
            item['timestamp_str'] = current_timestamp_obj.strftime('%Y-%m-%d %H:%M:%S')
        else:
            item['timestamp_str'] = "N/A"
        display_data.append(item)
        
    all_res_df = pd.DataFrame(display_data)
    if not all_res_df.empty:
        st.sidebar.dataframe(all_res_df[['date_str', 'team', 'room', 'timestamp_str']].rename(
            columns={'date_str': '날짜(요일)', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
        ), height=300)
    else:
        st.sidebar.write("표시할 예약 내역이 없습니다.")
else: st.sidebar.write("저장된 예약이 없습니다.")
st.sidebar.markdown("---")


# --- 1. 오늘 예약 현황 ---
st.header("1. 오늘 예약 현황")
# 이 today_for_view는 항상 스크립트 실행 시점의 오늘 날짜
current_display_date = datetime.date.today() 
day_name_view = get_day_korean(current_display_date)
st.subheader(f"📅 {current_display_date.strftime('%Y-%m-%d')} ({day_name_view})")

# get_reservations_for_date는 st.session_state.reservations (필터링 되었을 수 있음)에서 찾음
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
            if reserved_team:
                st.markdown(f"- {room_short_name}: <span style='color:red;'>**{reserved_team}**</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"- {room_short_name}: <span style='color:green;'>가능</span>", unsafe_allow_html=True)

if not reservations_on_display_date: # 여기서는 current_display_date 기준
    st.info(f"오늘({current_display_date.strftime('%Y-%m-%d')})은 예약된 회의실이 없습니다.")
st.markdown("---")

# --- 2. 예약하기 (오늘) ---
st.header("2. 예약하기")
# 이 today_date_for_reservation도 항상 스크립트 실행 시점의 오늘
today_date_for_reservation = datetime.date.today() 
today_day_name_res = get_day_korean(today_date_for_reservation)
# is_reservable_today는 내부적으로 today_date_for_reservation와 datetime.date.today()를 비교함
reservable_today_flag = is_reservable_today(today_date_for_reservation, st.session_state.test_mode) 

if st.session_state.form_submit_message:
    msg_type, msg_content = st.session_state.form_submit_message
    if msg_type == "success": st.success(msg_content)
    elif msg_type == "error": st.error(msg_content)
    elif msg_type == "warning": st.warning(msg_content)
    st.session_state.form_submit_message = None

if st.session_state.test_mode:
    st.caption(f"오늘은 {today_date_for_reservation.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. [테스트 모드] 예약이 가능합니다.")
elif reservable_today_flag:
    st.caption(f"오늘은 {today_date_for_reservation.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. 예약이 가능합니다.")
else:
    st.caption(f"⚠️ 오늘은 {today_date_for_reservation.strftime('%Y-%m-%d')} ({today_day_name_res}요일) 입니다. 예약은 당일이면서 수/일요일만 가능합니다.")

with st.form("reservation_form_main"):
    col1_form, col2_form = st.columns(2)
    with col1_form:
        st.selectbox("조 선택", TEAMS, key="res_team_select_key", index=None, placeholder="조를 선택하세요")
    with col2_form:
        st.selectbox("회의실 선택", ORDERED_ROOMS, key="res_room_select_key", index=None, placeholder="회의실을 선택하세요")
    st.form_submit_button(
        "예약 신청",
        type="primary",
        disabled=not reservable_today_flag, # 여기서 사용되는 플래그는 현재 실행 시점의 오늘 기준
        use_container_width=True,
        on_click=handle_reservation_submission
    )