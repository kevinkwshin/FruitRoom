import streamlit as st
import datetime
import pandas as pd

# --- 초기 설정 ---
# 조 목록
TEAMS = [
    "대면A", "대면B", "대면C",
    "1조", "2조", "3조", "4조", "5조",
    "6조", "7조", "8조", "9조", "10조", "11조"
]

# 회의실 목록
ROOMS = [
    "9층-1호", "9층-2호", "9층-3호", "9층-4호", "9층-5호", "9층-6호",
    "지하5층-1호", "지하5층-2호", "지하5층-3호"
]

# 세션 상태 초기화 (예약 데이터 저장용)
if 'reservations' not in st.session_state:
    st.session_state.reservations = [] # 예약 정보를 담을 리스트

# --- Helper Functions ---
def add_reservation(date, team, room):
    """새로운 예약을 추가합니다."""
    # 중복 예약 확인 (같은 날짜, 같은 회의실)
    for res in st.session_state.reservations:
        if res['date'] == date and res['room'] == room:
            st.error(f"{date.strftime('%Y-%m-%d')}에 {room}은(는) 이미 예약되어 있습니다.")
            return False
    # 중복 예약 확인 (같은 날짜, 같은 조)
    for res in st.session_state.reservations:
        if res['date'] == date and res['team'] == team:
            st.error(f"{date.strftime('%Y-%m-%d')}에 {team}은(는) 이미 다른 회의실을 예약했습니다.")
            return False

    st.session_state.reservations.append({
        "date": date,
        "team": team,
        "room": room,
        "timestamp": datetime.datetime.now() # 예약 시간 기록 (선택 사항)
    })
    st.success(f"{date.strftime('%Y-%m-%d')}에 {team}이(가) {room}을(를) 예약했습니다.")
    return True

def get_reservations_for_date(date):
    """특정 날짜의 예약 목록을 반환합니다."""
    return [res for res in st.session_state.reservations if res['date'] == date]

# --- Streamlit UI ---
st.set_page_config(page_title="회의실 예약 시스템", layout="wide")
st.title("🗓️ 회의실 예약 시스템")
st.markdown("---")

# --- 예약 섹션 ---
st.header("회의실 예약하기")
with st.form("reservation_form"):
    col1, col2, col3 = st.columns(3)
    with col1:
        selected_date_res = st.date_input("날짜 선택", min_value=datetime.date.today())
    with col2:
        selected_team = st.selectbox("조 선택", TEAMS)
    with col3:
        selected_room = st.selectbox("회의실 선택", ROOMS)

    submit_button = st.form_submit_button(label="예약하기")

if submit_button:
    if selected_date_res and selected_team and selected_room:
        add_reservation(selected_date_res, selected_team, selected_room)
    else:
        st.warning("모든 필드를 선택해주세요.")

st.markdown("---")

# --- 예약 조회 섹션 ---
st.header("예약 현황 조회")
selected_date_view = st.date_input("조회할 날짜 선택", key="view_date_picker", value=datetime.date.today())

if selected_date_view:
    reservations_on_date = get_reservations_for_date(selected_date_view)
    if reservations_on_date:
        st.subheader(f"{selected_date_view.strftime('%Y-%m-%d')} 예약 현황")

        # Pandas DataFrame으로 보기 좋게 표시
        df_reservations = pd.DataFrame(reservations_on_date)
        # 날짜 형식 변경 및 필요한 컬럼만 선택
        df_display = df_reservations[['date', 'team', 'room']].copy()
        df_display['date'] = df_display['date'].apply(lambda x: x.strftime('%Y-%m-%d'))
        df_display.columns = ["날짜", "조", "회의실"]
        st.dataframe(df_display.sort_values(by="회의실"), use_container_width=True)

        # 각 회의실별 예약 현황
        st.markdown("#### 회의실별 예약 상황:")
        room_status = {room: "예약 가능" for room in ROOMS}
        for res in reservations_on_date:
            room_status[res['room']] = f"**{res['team']}** 예약됨"

        cols = st.columns(3) # 3열로 표시
        col_idx = 0
        for room, status in room_status.items():
            with cols[col_idx % 3]:
                if "예약됨" in status:
                    st.markdown(f"- {room}: {status}", unsafe_allow_html=True)
                else:
                    st.markdown(f"- {room}: <span style='color:green;'>{status}</span>", unsafe_allow_html=True)
            col_idx += 1

    else:
        st.info(f"{selected_date_view.strftime('%Y-%m-%d')}에는 예약된 회의실이 없습니다.")

st.markdown("---")
st.sidebar.header("안내")
st.sidebar.info(
    "이 앱은 Streamlit의 `st.session_state`를 사용하여 예약 정보를 저장합니다. "
    "브라우저 세션이 종료되거나 앱이 재시작되면 데이터가 초기화됩니다. "
    "영구적인 데이터 저장을 위해서는 Google Sheets 연동 또는 데이터베이스 설정이 필요합니다."
)

# (선택사항) 현재 모든 예약 보기 (디버깅용)
if st.sidebar.checkbox("모든 예약 보기 (개발용)"):
    st.sidebar.subheader("모든 예약 정보")
    if st.session_state.reservations:
        all_res_df = pd.DataFrame(st.session_state.reservations)
        all_res_df['date'] = all_res_df['date'].apply(lambda x: x.strftime('%Y-%m-%d'))
        st.sidebar.dataframe(all_res_df[['date', 'team', 'room']])
    else:
        st.sidebar.write("저장된 예약이 없습니다.")
