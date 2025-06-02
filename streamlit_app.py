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
ROOM_LOCATIONS = {
    "9층": [f"9층-{i}호" for i in range(1, 7)],
    "지하5층": [f"지하5층-{i}호" for i in range(1, 4)]
}
ORDERED_ROOMS = ROOM_LOCATIONS["9층"] + ROOM_LOCATIONS["지하5층"]
RESERVATION_FILE = "reservations.json" # 데이터 저장 파일명

# --- 데이터 로드 및 저장 함수 ---
def load_reservations():
    """JSON 파일에서 예약 데이터를 로드합니다."""
    if os.path.exists(RESERVATION_FILE):
        try:
            with open(RESERVATION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # JSON에서 문자열로 저장된 날짜를 datetime.date 객체로 변환
                for item in data:
                    item['date'] = datetime.datetime.strptime(item['date'], '%Y-%m-%d').date()
                    # timestamp도 datetime 객체로 변환 (선택사항, 필요시)
                    if 'timestamp' in item and isinstance(item['timestamp'], str):
                         item['timestamp'] = datetime.datetime.fromisoformat(item['timestamp'])
                return data
        except json.JSONDecodeError:
            st.error("예약 데이터 파일이 손상되었습니다. 새 파일로 시작합니다.")
            return []
        except Exception as e:
            st.error(f"예약 데이터 로드 중 오류 발생: {e}")
            return []
    return []

def save_reservations(reservations_data):
    """예약 데이터를 JSON 파일에 저장합니다."""
    try:
        # datetime.date 및 datetime.datetime 객체를 문자열로 변환하여 저장
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
        st.error(f"예약 데이터 저장 중 오류 발생: {e}")


# 세션 상태 초기화 (파일에서 로드)
if 'reservations' not in st.session_state:
    st.session_state.reservations = load_reservations()
if 'test_mode' not in st.session_state:
    st.session_state.test_mode = False


# --- Helper Functions ---
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

    new_reservation = {
        "date": date,
        "team": team,
        "room": room,
        "timestamp": datetime.datetime.now()
    }
    st.session_state.reservations.append(new_reservation)
    save_reservations(st.session_state.reservations) # 변경 시 파일에 저장
    st.success(f"{date_str} ({day_name}) **'{team}'** 조가 **'{room}'**을(를) 성공적으로 예약했습니다.")
    return True

def get_reservations_for_date(date):
    return [res for res in st.session_state.reservations if res['date'] == date]

# --- Streamlit UI ---
st.set_page_config(page_title="회의실 예약 시스템", layout="wide")
st.title("🗓️ 회의실 예약 현황 및 신청")
st.markdown("---")

# --- 사이드바 ---
st.sidebar.header("앱 설정")
if 'test_mode_checkbox_key' not in st.session_state:
    st.session_state.test_mode_checkbox_key = False

st.session_state.test_mode = st.sidebar.checkbox(
    "🧪 테스트 모드 활성화 (오늘 날짜 요일 제한 없이 예약)",
    key="test_mode_checkbox_key"
)

if st.session_state.test_mode:
    st.sidebar.warning("테스트 모드가 활성화되어 있습니다. 요일 제한 없이 '오늘' 날짜로 예약이 가능합니다.")

st.sidebar.markdown("---")
st.sidebar.subheader("모든 예약 정보 (개발용)")
if st.session_state.reservations:
    # 데이터프레임 표시 전 날짜와 타임스탬프 형식 변환 (원본 데이터는 유지)
    display_data = []
    for res in st.session_state.reservations:
        item = res.copy() # 원본 수정을 피하기 위해 복사
        item['date_str'] = f"{res['date'].strftime('%Y-%m-%d')} ({get_day_korean(res['date'])})"
        if isinstance(res.get('timestamp'), datetime.datetime):
            item['timestamp_str'] = res['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
        else:
            item['timestamp_str'] = "N/A" # 혹시 타임스탬프가 없는 경우
        display_data.append(item)
    
    all_res_df = pd.DataFrame(display_data)
    # 날짜 객체로 정렬하기 위해 원본 'date' 사용 후 문자열 컬럼 선택
    all_res_df_sorted = all_res_df.sort_values(by=['date', 'room'])
    st.sidebar.dataframe(all_res_df_sorted[['date_str', 'team', 'room', 'timestamp_str']].rename(
        columns={'date_str': '날짜(요일)', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
    ))
else:
    st.sidebar.write("저장된 예약이 없습니다.")
st.sidebar.markdown("---")


# --- 1. 오늘 예약 현황 조회 섹션 ---
st.header("1. 오늘 회의실 예약 현황")
today_for_view = datetime.date.today()
day_name_view = get_day_korean(today_for_view)
st.subheader(f"📅 {today_for_view.strftime('%Y-%m-%d')} ({day_name_view})")

reservations_on_today = get_reservations_for_date(today_for_view)

if reservations_on_today:
    st.markdown("##### 예약된 조 목록:")
    df_reservations = pd.DataFrame(reservations_on_today)
    df_display = df_reservations[['team', 'room']].copy()
    df_display.columns = ["조", "예약된 회의실"]
    st.dataframe(df_display.sort_values(by="예약된 회의실"), use_container_width=True)

    st.markdown("##### 회의실별 예약 상세:")
    room_status_display = {}
    for room in ORDERED_ROOMS:
        reserved_team = next((res['team'] for res in reservations_on_today if res['room'] == room), None)
        if reserved_team:
            room_status_display[room] = f"<span style='color:red;'>**{reserved_team}** 예약됨</span>"
        else:
            room_status_display[room] = "<span style='color:green;'>예약 가능</span>"
    
    cols = st.columns(3)
    col_idx = 0
    for room in ORDERED_ROOMS:
        status = room_status_display[room]
        with cols[col_idx % 3]:
            st.markdown(f"- {room}: {status}", unsafe_allow_html=True)
        col_idx += 1
else:
    st.info(f"오늘({today_for_view.strftime('%Y-%m-%d')}, {day_name_view})은 예약된 회의실이 없습니다.")

st.markdown("---")

# --- 2. 회의실 예약하기 섹션 ---
st.header("2. 회의실 예약하기 (오늘)")

today_date_res = datetime.date.today()
today_day_name_res = get_day_korean(today_date_res)
reservable_today = is_reservable_today(today_date_res, st.session_state.test_mode)

if st.session_state.test_mode:
    st.info(f"💡 오늘은 **{today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일)** 입니다. [테스트 모드] 회의실 예약이 가능합니다.")
elif reservable_today:
    st.info(f"💡 오늘은 **{today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일)** 입니다. 회의실 예약이 가능합니다.")
else:
    st.warning(
        f"⚠️ 오늘은 **{today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일)** 입니다. "
        "회의실 예약은 **당일(오늘)**이면서 **수요일 또는 일요일**인 경우에만 가능합니다."
    )

with st.form("reservation_form"):
    st.markdown(f"**예약 대상 날짜**: {today_date_res.strftime('%Y-%m-%d')} ({today_day_name_res}요일)")

    col1_form, col2_form = st.columns(2)
    with col1_form:
        selected_team = st.selectbox("조 선택", TEAMS, key="res_team_select", index=None, placeholder="조를 선택하세요")
    with col2_form:
        selected_room = st.selectbox("회의실 선택", ORDERED_ROOMS, key="res_room_select", index=None, placeholder="회의실을 선택하세요")

    submitted = st.form_submit_button("예약 신청하기", type="primary", disabled=not reservable_today)

if submitted:
    if not selected_team or not selected_room:
        st.warning("조와 회의실을 모두 선택해주세요.")
    else:
        add_reservation(today_date_res, selected_team, selected_room)