import streamlit as st
import datetime
import pandas as pd

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

if 'reservations' not in st.session_state:
    st.session_state.reservations = []

# --- Helper Functions ---
def get_day_korean(date_obj):
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

def is_reservable_today(date_obj):
    """오늘이 예약 가능한 날짜(수요일 또는 일요일)인지 확인합니다."""
    if date_obj != datetime.date.today(): # 오늘 날짜가 아니면 예약 불가 (이중 체크)
        return False
    return date_obj.weekday() == 2 or date_obj.weekday() == 6  # 2: 수요일, 6: 일요일

def add_reservation(date, team, room):
    date_str = date.strftime('%Y-%m-%d')
    day_name = get_day_korean(date)

    for res in st.session_state.reservations:
        if res['date'] == date and res['room'] == room:
            st.error(f"{date_str} ({day_name}) {room}은(는) 이미 예약되어 있습니다.")
            return False
        if res['date'] == date and res['team'] == team:
            st.error(f"{date_str} ({day_name}) {team}은(는) 이미 다른 회의실을 예약했습니다.")
            return False

    st.session_state.reservations.append({
        "date": date,
        "team": team,
        "room": room,
        "timestamp": datetime.datetime.now()
    })
    st.success(f"{date_str} ({day_name}) {team}이(가) {room}을(를) 성공적으로 예약했습니다.")
    return True

def get_reservations_for_date(date):
    return [res for res in st.session_state.reservations if res['date'] == date]

# --- Streamlit UI ---
st.set_page_config(page_title="회의실 예약 시스템", layout="wide")
st.title("🗓️ 회의실 예약 현황 및 신청")
st.markdown("---")

# --- 1. 예약 현황 조회 섹션 ---
st.header("1. 회의실 예약 현황 조회")
selected_date_view = st.date_input(
    "조회할 날짜를 선택하세요",
    key="view_date_picker",
    value=datetime.date.today(),
)

if selected_date_view:
    day_name_view = get_day_korean(selected_date_view)
    st.subheader(f"📅 {selected_date_view.strftime('%Y-%m-%d')} ({day_name_view}) 예약 현황")
    reservations_on_date = get_reservations_for_date(selected_date_view)

    if reservations_on_date:
        st.markdown("##### 예약된 조 목록:")
        df_reservations = pd.DataFrame(reservations_on_date)
        df_display = df_reservations[['team', 'room']].copy()
        df_display.columns = ["조", "예약된 회의실"]
        st.dataframe(df_display.sort_values(by="예약된 회의실"), use_container_width=True)

        st.markdown("##### 회의실별 예약 상세:")
        room_status_display = {}
        for room in ORDERED_ROOMS:
            reserved_team = next((res['team'] for res in reservations_on_date if res['room'] == room), None)
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
        st.info(f"{selected_date_view.strftime('%Y-%m-%d')} ({day_name_view})에는 예약된 회의실이 없습니다.")
else:
    st.info("조회할 날짜를 선택해주세요.")

st.markdown("---")

# --- 2. 회의실 예약하기 섹션 ---
st.header("2. 회의실 예약하기")

today_date = datetime.date.today()
today_day_name = get_day_korean(today_date)
reservable_today = is_reservable_today(today_date) # 오늘 예약 가능한지 여부

if reservable_today:
    st.info(f"💡 오늘은 **{today_date.strftime('%Y-%m-%d')} ({today_day_name}요일)** 입니다. 회의실 예약이 가능합니다.")
else:
    st.warning(
        f"⚠️ 오늘은 **{today_date.strftime('%Y-%m-%d')} ({today_day_name}요일)** 입니다. "
        "회의실 예약은 **당일(오늘)**이면서 **수요일 또는 일요일**인 경우에만 가능합니다."
    )

with st.form("reservation_form"):
    # 날짜는 오늘로 고정되므로, 사용자에게는 정보만 제공
    st.markdown(f"**예약 대상 날짜**: {today_date.strftime('%Y-%m-%d')} ({today_day_name}요일)")

    col1_form, col2_form = st.columns(2)
    with col1_form:
        selected_team = st.selectbox("조 선택", TEAMS, key="res_team_select", index=None, placeholder="조를 선택하세요")
    with col2_form:
        selected_room = st.selectbox("회의실 선택", ORDERED_ROOMS, key="res_room_select", index=None, placeholder="회의실을 선택하세요")

    # 예약 버튼은 오늘이 예약 가능한 요일일 때만 활성화
    submitted = st.form_submit_button("예약 신청하기", type="primary", disabled=not reservable_today)

if submitted: # 버튼이 활성화 되어 눌렸을 경우에만 실행됨
    if not selected_team or not selected_room:
        st.warning("조와 회의실을 모두 선택해주세요.")
    else:
        # 예약 날짜는 항상 '오늘'
        add_reservation(today_date, selected_team, selected_room)


st.markdown("---")
st.sidebar.header("앱 정보")
st.sidebar.info(
    "이 앱은 Streamlit의 `st.session_state`를 사용하여 예약 정보를 임시 저장합니다. "
    "브라우저 세션이 종료되거나 앱이 재시작되면 데이터는 초기화됩니다."
)

if st.sidebar.checkbox("모든 예약 보기 (개발용)"):
    st.sidebar.subheader("모든 예약 정보 (개발용)")
    if st.session_state.reservations:
        all_res_df = pd.DataFrame(st.session_state.reservations)
        all_res_df['date_str'] = all_res_df['date'].apply(lambda x: f"{x.strftime('%Y-%m-%d')} ({get_day_korean(x)})")
        all_res_df['timestamp_str'] = pd.to_datetime(all_res_df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
        all_res_df_sorted = all_res_df.sort_values(by=['date', 'room'])
        st.sidebar.dataframe(all_res_df_sorted[['date_str', 'team', 'room', 'timestamp_str']].rename(
            columns={'date_str': '날짜(요일)', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
        ))
    else:
        st.sidebar.write("저장된 예약이 없습니다.")