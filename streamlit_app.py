import streamlit as st
import datetime
import pandas as pd
import json
import os

# --- 초기 설정 ---
TEAMS = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)]
ROOM_LOCATIONS_DETAILED = {
    "9F": {"name": "9층 회의실", "rooms": [f"9층-{i}호" for i in range(1, 7)]},
    "B5F": {"name": "지하5층 회의실", "rooms": [f"지하5층-{i}호" for i in range(1, 4)]}
}
ORDERED_ROOMS = ROOM_LOCATIONS_DETAILED["9F"]["rooms"] + ROOM_LOCATIONS_DETAILED["B5F"]["rooms"]
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
# st.radio는 index=None으로 초기화하면 기본 선택 없음 (Streamlit 1.26.0+)
# 이전 버전에서는 None을 index로 직접 사용할 수 없으므로, 콜백에서 값을 가져올 때 None인지 체크
if 'selected_team_radio' not in st.session_state: # 초기에는 None으로 설정하여 아무것도 선택 안된 상태로 시작
    st.session_state.selected_team_radio = None
if 'selected_room_radio' not in st.session_state:
    st.session_state.selected_room_radio = None


# --- Helper Functions ---
def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

def is_reservable_today(date_obj_to_check, test_mode_active=False):
    if date_obj_to_check != datetime.date.today(): return False
    if test_mode_active: return True
    return date_obj_to_check.weekday() == 2 or date_obj_to_check.weekday() == 6

def handle_reservation_submission():
    date_for_reservation = datetime.date.today()
    team = st.session_state.get("selected_team_radio") # radio의 key로 값 가져옴
    room = st.session_state.get("selected_room_radio") # radio의 key로 값 가져옴
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
    st.session_state.selected_team_radio = None # 예약 후 선택 초기화
    st.session_state.selected_room_radio = None # 예약 후 선택 초기화
    st.rerun()

def get_reservations_for_date(target_date):
    return [res for res in st.session_state.reservations if res.get('date') == target_date]

# --- Streamlit UI ---
st.set_page_config(
    page_title="회의실 예약",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# 모바일 확대 방지 CSS
st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        body {
            -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; text-size-adjust: 100%;
            touch-action: manipulation;
        }
        /* Radio 버튼의 라벨 폰트 크기 (필요시 조정) */
        .stRadio [data-testid="stMarkdownContainer"] p { /* Radio 라벨은 p 태그 안에 있을 수 있음 */
            font-size: 15px !important; /* 모바일 확대를 피하기 위해 16px 권장, 상황 따라 조절 */
        }
        .stButton > button { font-size: 15px !important; padding: 0.4rem 0.75rem !important; }

        /* 카드 스타일 UI를 위한 CSS (선택사항) */
        .room-card {
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.1);
        }
        .room-card h5 { /* 회의실 호수 */
            margin-top: 0;
            margin-bottom: 5px;
            font-size: 1.1em;
        }
        .room-card .status { /* 예약 상태 */
            font-size: 0.95em;
        }
        .available { color: green; font-weight: bold; }
        .reserved { color: red; font-weight: bold; }
    </style>
    """, unsafe_allow_html=True)

st.title("회의실 예약")
st.markdown("---") # 이 구분선은 제목 바로 아래에 하나만 두는 것이 깔끔할 수 있습니다.

# --- 사이드바 ---
st.sidebar.header("앱 설정")
if 'test_mode_checkbox_key' not in st.session_state:
    st.session_state.test_mode_checkbox_key = False
st.session_state.test_mode = st.sidebar.checkbox("🧪 테스트 모드", key="test_mode_checkbox_key", help="활성화 시 요일 제한 없이 오늘 날짜로 예약 가능")

if st.sidebar.button("🔄 오늘 날짜로 정보 새로고침"):
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
current_display_date = datetime.date.today()
day_name_view = get_day_korean(current_display_date)
st.subheader(f"📅 {current_display_date.strftime('%Y-%m-%d')} ({day_name_view})")

reservations_on_display_date = get_reservations_for_date(current_display_date)

# "예약된 조:" 메뉴 삭제됨

st.markdown("##### 회의실별 상세 현황") # 부제목 변경

col1_status, col2_status = st.columns(2)
floor_data = {
    "9F": (col1_status, ROOM_LOCATIONS_DETAILED["9F"]),
    "B5F": (col2_status, ROOM_LOCATIONS_DETAILED["B5F"])
}

for floor_key, (column, floor_info) in floor_data.items():
    with column:
        st.subheader(f"{floor_info['name']}") # 각 층 제목을 subheader로
        if not floor_info['rooms']: # 해당 층에 회의실 정보가 없으면
            st.caption("등록된 회의실이 없습니다.")
            continue

        for room in floor_info['rooms']:
            with st.container(): # 각 회의실 정보를 카드처럼 보이게 하기 위한 컨테이너
                st.markdown(f"<div class='room-card'>", unsafe_allow_html=True) # 카드 시작
                room_short_name = room.split('-')[-1]
                reserved_team = next((res['team'] for res in reservations_on_display_date if res['room'] == room), None)
                
                if reserved_team:
                    status_html = f"<h5>{room_short_name}</h5><span class='status reserved'>{reserved_team} 예약됨</span>"
                else:
                    status_html = f"<h5>{room_short_name}</h5><span class='status available'>예약 가능</span>"
                st.markdown(status_html, unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True) # 카드 끝
        st.markdown("<br>", unsafe_allow_html=True) # 층별 정보 사이에 약간의 간격

if not reservations_on_display_date:
    st.info(f"오늘({current_display_date.strftime('%Y-%m-%d')})은 예약된 회의실이 없습니다.")
st.markdown("---") # 오늘 예약 현황과 예약하기 섹션 구분

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
    # Radio 버튼으로 변경, 초기 선택 없도록 index=None 또는 로직 처리
    # st.radio의 index 매개변수에 None을 사용하려면 Streamlit 1.26.0 이상 필요
    # 현재 st.session_state.selected_team_radio 가 None이면 첫번째 항목이 선택될 수 있으므로,
    # 사용자가 반드시 선택하도록 유도하거나, 옵션 앞에 "선택안함" 항목을 추가하는 방법도 고려 가능
    
    team_options = TEAMS
    room_options = ORDERED_ROOMS

    # 현재 선택된 값을 유지하거나, 없으면 첫 번째를 기본값으로 (또는 None이면 첫번째)
    # radio는 None을 index로 직접 줄 수 없으므로, 선택된 값이 없으면 첫 번째가 선택됨.
    # handle_reservation_submission에서 값이 없는 경우를 체크.
    current_team_index = 0
    if st.session_state.selected_team_radio and st.session_state.selected_team_radio in team_options:
        current_team_index = team_options.index(st.session_state.selected_team_radio)
    
    current_room_index = 0
    if st.session_state.selected_room_radio and st.session_state.selected_room_radio in room_options:
        current_room_index = room_options.index(st.session_state.selected_room_radio)

    st.radio(
        "조 선택:",
        team_options,
        key="selected_team_radio",
        index=current_team_index, # 이전 선택 유지 또는 첫번째 (None이면 첫번째)
        # help="예약할 조를 선택하세요."
    )
    
    st.radio(
        "회의실 선택:",
        room_options,
        key="selected_room_radio",
        index=current_room_index,
        # help="예약할 회의실을 선택하세요."
    )
    
    st.form_submit_button(
        "예약 신청",
        type="primary",
        disabled=not reservable_today_flag,
        use_container_width=True,
        on_click=handle_reservation_submission
    )