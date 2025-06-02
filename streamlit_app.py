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

# 회의실 목록 (정렬을 위해 층과 번호로 분리된 튜플 사용 후 조합)
ROOM_LOCATIONS = {
    "9층": [f"9층-{i}호" for i in range(1, 7)],
    "지하5층": [f"지하5층-{i}호" for i in range(1, 4)]
}
ORDERED_ROOMS = ROOM_LOCATIONS["9층"] + ROOM_LOCATIONS["지하5층"]


# 세션 상태 초기화 (예약 데이터 저장용)
if 'reservations' not in st.session_state:
    st.session_state.reservations = [] # 예약 정보를 담을 리스트

# --- Helper Functions ---
def get_day_korean(date_obj):
    """날짜 객체로부터 한국어 요일을 반환합니다."""
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return days[date_obj.weekday()]

def is_valid_reservation_day(date_obj):
    """선택된 날짜가 일요일 또는 수요일인지 확인합니다."""
    # weekday(): 월요일 0 ~ 일요일 6
    return date_obj.weekday() == 6 or date_obj.weekday() == 2 # 6: 일요일, 2: 수요일

def add_reservation(date, team, room):
    """새로운 예약을 추가합니다."""
    date_str = date.strftime('%Y-%m-%d')
    day_name = get_day_korean(date)

    # 중복 예약 확인 (같은 날짜, 같은 회의실)
    for res in st.session_state.reservations:
        if res['date'] == date and res['room'] == room:
            st.error(f"{date_str} ({day_name}) {room}은(는) 이미 예약되어 있습니다.")
            return False
    # 중복 예약 확인 (같은 날짜, 같은 조)
    for res in st.session_state.reservations:
        if res['date'] == date and res['team'] == team:
            st.error(f"{date_str} ({day_name}) {team}은(는) 이미 다른 회의실을 예약했습니다.")
            return False

    st.session_state.reservations.append({
        "date": date,
        "team": team,
        "room": room,
        "timestamp": datetime.datetime.now() # 예약 시간 기록
    })
    st.success(f"{date_str} ({day_name}) {team}이(가) {room}을(를) 성공적으로 예약했습니다.")
    return True

def get_reservations_for_date(date):
    """특정 날짜의 예약 목록을 반환합니다."""
    return [res for res in st.session_state.reservations if res['date'] == date]

# --- Streamlit UI ---
st.set_page_config(page_title="회의실 예약 시스템", layout="wide")
st.title("🗓️ 회의실 예약 현황 및 신청")
st.markdown("---")

# --- 1. 예약 현황 조회 섹션 (우선 표시) ---
st.header("1. 회의실 예약 현황 조회")
selected_date_view = st.date_input(
    "조회할 날짜를 선택하세요",
    key="view_date_picker",
    value=datetime.date.today(),
    # min_value=datetime.date.today() # 과거 날짜 조회도 가능하도록 주석 처리 또는 삭제
)

if selected_date_view:
    day_name_view = get_day_korean(selected_date_view)
    st.subheader(f"📅 {selected_date_view.strftime('%Y-%m-%d')} ({day_name_view}) 예약 현황")
    reservations_on_date = get_reservations_for_date(selected_date_view)

    if reservations_on_date:
        # 예약된 조 목록 테이블
        st.markdown("##### 예약된 조 목록:")
        df_reservations = pd.DataFrame(reservations_on_date)
        df_display = df_reservations[['team', 'room']].copy()
        df_display.columns = ["조", "예약된 회의실"]
        st.dataframe(df_display.sort_values(by="예약된 회의실"), use_container_width=True)

        # 회의실별 예약 상세
        st.markdown("##### 회의실별 예약 상세:")
        room_status_display = {}
        for room in ORDERED_ROOMS:
            reserved_team = next((res['team'] for res in reservations_on_date if res['room'] == room), None)
            if reserved_team:
                room_status_display[room] = f"<span style='color:red;'>**{reserved_team}** 예약됨</span>"
            else:
                room_status_display[room] = "<span style='color:green;'>예약 가능</span>"
        
        cols = st.columns(3) # 3열로 표시
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
st.info("💡 회의실 예약은 **일요일** 또는 **수요일**만 가능합니다.")

with st.form("reservation_form"):
    col1_form, col2_form, col3_form = st.columns(3)
    with col1_form:
        selected_date_res = st.date_input(
            "예약 날짜 (일/수요일)",
            min_value=datetime.date.today(), # 오늘 이전 날짜 예약 불가
            key="res_date_picker"
        )
    with col2_form:
        selected_team = st.selectbox("조 선택", TEAMS, key="res_team_select", index=None, placeholder="조를 선택하세요")
    with col3_form:
        selected_room = st.selectbox("회의실 선택", ORDERED_ROOMS, key="res_room_select", index=None, placeholder="회의실을 선택하세요")

    # 날짜 유효성 피드백 (선택 시 바로 표시)
    if selected_date_res:
        day_name_res = get_day_korean(selected_date_res)
        if is_valid_reservation_day(selected_date_res):
            st.markdown(f"선택된 날짜: {selected_date_res.strftime('%Y-%m-%d')} **({day_name_res}요일)** - <span style='color:green;'>예약 가능한 요일입니다.</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"선택된 날짜: {selected_date_res.strftime('%Y-%m-%d')} **({day_name_res}요일)** - <span style='color:red;'>예약 불가능한 요일입니다. (일/수요일만 가능)</span>", unsafe_allow_html=True)

    submitted = st.form_submit_button("예약 신청하기", type="primary")

if submitted:
    if not selected_date_res or not selected_team or not selected_room:
        st.warning("모든 필드(날짜, 조, 회의실)를 선택해주세요.")
    elif not is_valid_reservation_day(selected_date_res):
        day_name_res = get_day_korean(selected_date_res)
        st.error(f"예약 실패: {selected_date_res.strftime('%Y-%m-%d')} ({day_name_res}요일)은 예약이 불가능한 요일입니다. 일요일 또는 수요일을 선택해주세요.")
    else:
        # 모든 조건 만족 시 예약 시도
        add_reservation(selected_date_res, selected_team, selected_room)

st.markdown("---")

# --- 사이드바 안내 ---
st.sidebar.header("앱 정보")
st.sidebar.info(
    "이 앱은 Streamlit의 `st.session_state`를 사용하여 예약 정보를 임시 저장합니다. "
    "브라우저 세션이 종료되거나 앱이 재시작되면 데이터는 초기화됩니다."
)

# (선택사항) 현재 모든 예약 보기 (개발용)
if st.sidebar.checkbox("모든 예약 보기 (개발용)"):
    st.sidebar.subheader("모든 예약 정보 (개발용)")
    if st.session_state.reservations:
        all_res_df = pd.DataFrame(st.session_state.reservations)
        # 날짜 객체를 문자열로 변환 및 요일 추가
        all_res_df['date_str'] = all_res_df['date'].apply(lambda x: f"{x.strftime('%Y-%m-%d')} ({get_day_korean(x)})")
        all_res_df['timestamp_str'] = pd.to_datetime(all_res_df['timestamp']).dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # 원본 'date' 컬럼을 기준으로 정렬 후, 필요한 컬럼만 선택하여 표시
        all_res_df_sorted = all_res_df.sort_values(by=['date', 'room'])
        st.sidebar.dataframe(all_res_df_sorted[['date_str', 'team', 'room', 'timestamp_str']].rename(
            columns={'date_str': '날짜(요일)', 'team': '조', 'room': '회의실', 'timestamp_str': '예약시간'}
        ))
    else:
        st.sidebar.write("저장된 예약이 없습니다.")