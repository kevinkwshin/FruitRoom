import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time

# --- 초기 설정 ---
TEAMS = [f"조 {i}" for i in range(1, 12)] + ["대면A", "대면B", "대면C", "시니어조"] # 총 15개 조
ROOMS = [f"9-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"] # 총 9개 방

RESERVATION_FILE = "reservations.csv"
ROTATION_STATE_FILE = "rotation_state.csv"

# 자동 배정 시간 슬롯
AUTO_ASSIGN_TIME_SLOT = "11:30 - 13:00"

# 수동 예약 시간 슬롯
MANUAL_TIME_SLOTS = [
    "13:00 - 14:00",
    "14:00 - 15:00",
    "15:00 - 16:00",
    "16:00 - 17:00",
]

# --- 데이터 로드 및 저장 함수 ---
def load_reservations():
    try:
        df = pd.read_csv(RESERVATION_FILE)
        # 날짜 열을 datetime 객체로 변환 (오류 발생 시 원본 유지)
        if '날짜' in df.columns:
            df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
    except FileNotFoundError:
        df = pd.DataFrame(columns=["날짜", "시간", "조", "방", "예약유형"])
    return df

def save_reservations(df):
    df.to_csv(RESERVATION_FILE, index=False)

def load_rotation_state():
    try:
        df_state = pd.read_csv(ROTATION_STATE_FILE)
        if not df_state.empty:
            return int(df_state.iloc[0]["next_team_index"])
    except (FileNotFoundError, IndexError, ValueError): # ValueError 추가 (빈 파일 또는 잘못된 형식)
        pass # 파일이 없거나 비어있거나 잘못된 형식이면 0 반환
    return 0 # 기본값: 첫 번째 조부터 시작

def save_rotation_state(next_team_index):
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    df_state.to_csv(ROTATION_STATE_FILE, index=False)

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약 시스템", layout="wide")
st.title("🚀 조모임 스터디룸 예약 시스템")

reservations_df = load_reservations()

tab1, tab2, tab3 = st.tabs(["📌 자동 배정 (11:30-13:00)", "✍️ 수동 예약 (13:00-17:00)", "🗓️ 전체 예약 현황"])

# --- 탭 1: 자동 배정 ---
with tab1:
    st.header("자동 배정 (로테이션)")
    st.markdown(f"**시간:** {AUTO_ASSIGN_TIME_SLOT}")
    st.markdown(f"**대상 조:** {', '.join(TEAMS)}")
    st.markdown(f"**대상 방:** {', '.join(ROOMS)}")
    st.markdown("---")

    auto_assign_date = st.date_input("자동 배정 실행할 날짜 선택", value=date.today(), key="auto_date")

    if st.button("오늘의 자동 배정 실행하기", key="auto_assign_btn"):
        # 해당 날짜, 해당 시간 슬롯에 이미 자동 배정된 내역이 있는지 확인
        existing_auto_assignment = reservations_df[
            (reservations_df["날짜"] == auto_assign_date) &
            (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
            (reservations_df["예약유형"] == "자동")
        ]

        if not existing_auto_assignment.empty:
            st.warning(f"{auto_assign_date.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT}에 이미 자동 배정된 내역이 있습니다.")
        else:
            next_team_start_index = load_rotation_state()
            num_teams = len(TEAMS)
            num_rooms = len(ROOMS)
            new_reservations = []

            assigned_teams_today = []
            for i in range(num_rooms):
                current_team_index = (next_team_start_index + i) % num_teams
                team_to_assign = TEAMS[current_team_index]
                room_to_assign = ROOMS[i] # 방은 순서대로 배정

                new_reservations.append({
                    "날짜": auto_assign_date,
                    "시간": AUTO_ASSIGN_TIME_SLOT,
                    "조": team_to_assign,
                    "방": room_to_assign,
                    "예약유형": "자동"
                })
                assigned_teams_today.append(team_to_assign)

            if new_reservations:
                reservations_df = pd.concat([reservations_df, pd.DataFrame(new_reservations)], ignore_index=True)
                save_reservations(reservations_df)
                # 다음 시작 인덱스 업데이트 (배정된 방의 수만큼 이동)
                save_rotation_state((next_team_start_index + num_rooms) % num_teams)
                st.success(f"{auto_assign_date.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT} 자동 배정 완료!")
                st.write("배정된 조:")
                for res in new_reservations:
                    st.write(f"- {res['조']} -> {res['방']}")
                st.experimental_rerun() # 예약 현황 즉시 업데이트
            else:
                st.error("자동 배정에 실패했습니다.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT})")
    auto_reservations_today = reservations_df[
        (reservations_df["날짜"] == auto_assign_date) &
        (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_reservations_today.empty:
        st.dataframe(auto_reservations_today[["날짜", "조", "방"]].sort_values(by="방"))
    else:
        st.info(f"{auto_assign_date.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT}에 자동 배정된 내역이 없습니다.")


# --- 탭 2: 수동 예약 ---
with tab2:
    st.header("수동 예약")
    st.markdown("원하는 조, 방, 시간을 선택하여 예약하세요.")
    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        manual_date = st.date_input("예약 날짜", value=date.today(), min_value=date.today(), key="manual_date")
    with col2:
        selected_team = st.selectbox("조 선택", TEAMS, key="manual_team")
    with col3:
        selected_time_slot = st.selectbox("시간 선택", MANUAL_TIME_SLOTS, key="manual_time")
    with col4:
        selected_room = st.selectbox("방 선택", ROOMS, key="manual_room")

    if st.button("예약하기", key="manual_reserve_btn"):
        # 중복 예약 확인
        # 1. 해당 날짜, 시간, 방이 이미 예약되었는지
        conflict_room = reservations_df[
            (reservations_df["날짜"] == manual_date) &
            (reservations_df["시간"] == selected_time_slot) &
            (reservations_df["방"] == selected_room)
        ]
        # 2. 해당 날짜, 시간에 해당 조가 이미 다른 방을 예약했는지
        conflict_team = reservations_df[
            (reservations_df["날짜"] == manual_date) &
            (reservations_df["시간"] == selected_time_slot) &
            (reservations_df["조"] == selected_team)
        ]

        if not conflict_room.empty:
            st.error(f"{manual_date.strftime('%Y-%m-%d')} {selected_time_slot}에 {selected_room}은(는) 이미 예약되어 있습니다.")
        elif not conflict_team.empty:
            existing_room = conflict_team.iloc[0]["방"]
            st.error(f"{selected_team}은(는) {manual_date.strftime('%Y-%m-%d')} {selected_time_slot}에 이미 {existing_room}을(를) 예약했습니다.")
        else:
            new_reservation = pd.DataFrame([{
                "날짜": manual_date,
                "시간": selected_time_slot,
                "조": selected_team,
                "방": selected_room,
                "예약유형": "수동"
            }])
            reservations_df = pd.concat([reservations_df, new_reservation], ignore_index=True)
            save_reservations(reservations_df)
            st.success(f"예약 완료: {manual_date.strftime('%Y-%m-%d')} {selected_time_slot} / {selected_team} / {selected_room}")
            st.experimental_rerun() # 예약 현황 즉시 업데이트

    st.subheader("오늘의 수동 예약 현황 (13:00 - 17:00)")
    manual_reservations_today = reservations_df[
        (reservations_df["날짜"] == date.today()) & # 오늘 날짜로 필터
        (reservations_df["시간"].isin(MANUAL_TIME_SLOTS)) &
        (reservations_df["예약유형"] == "수동")
    ].sort_values(by=["시간", "방"])

    if not manual_reservations_today.empty:
        st.dataframe(manual_reservations_today[["시간", "조", "방"]])
    else:
        st.info(f"{date.today().strftime('%Y-%m-%d')} 수동 예약 내역이 없습니다.")


# --- 탭 3: 전체 예약 현황 ---
with tab3:
    st.header("전체 예약 현황")
    
    view_date = st.date_input("조회할 날짜 선택", value=date.today(), key="view_date_all")

    if not reservations_df.empty:
        # 날짜 열이 datetime.date 객체인지 확인하고, 아니면 변환 시도
        if not all(isinstance(d, date) for d in reservations_df['날짜']):
            reservations_df['날짜'] = pd.to_datetime(reservations_df['날짜'], errors='coerce').dt.date
        
        # NaT 값 (변환 실패) 제거
        reservations_df_cleaned = reservations_df.dropna(subset=['날짜'])

        # 선택된 날짜의 예약만 필터링
        display_df = reservations_df_cleaned[reservations_df_cleaned["날짜"] == view_date]
        
        if not display_df.empty:
            st.subheader(f"{view_date.strftime('%Y-%m-%d')} 예약 내역")
            
            # 시간대별 정렬을 위해 시간 슬롯 순서 정의
            time_slot_order = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            display_df['시간'] = pd.Categorical(display_df['시간'], categories=time_slot_order, ordered=True)
            
            # 보기 좋게 정렬
            display_df_sorted = display_df.sort_values(by=["시간", "방"])
            st.dataframe(display_df_sorted[["시간", "조", "방", "예약유형"]], use_container_width=True)
        else:
            st.info(f"{view_date.strftime('%Y-%m-%d')}에 예약된 내역이 없습니다.")
    else:
        st.info("아직 등록된 예약이 없습니다.")

    if st.checkbox("전체 데이터 보기 (모든 날짜)"):
        if not reservations_df.empty:
            st.dataframe(reservations_df.sort_values(by=["날짜", "시간", "방"]), use_container_width=True)
        else:
            st.info("아직 등록된 예약이 없습니다.")

    if st.button("모든 예약 기록 삭제 (주의!)", key="delete_all"):
        if st.checkbox("정말로 모든 기록을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다."):
            try:
                import os
                if os.path.exists(RESERVATION_FILE):
                    os.remove(RESERVATION_FILE)
                if os.path.exists(ROTATION_STATE_FILE):
                    os.remove(ROTATION_STATE_FILE) # 로테이션 상태도 초기화
                st.success("모든 예약 기록 및 로테이션 상태가 삭제되었습니다. 페이지를 새로고침하세요.")
                # reservations_df = load_reservations() # 데이터프레임 다시 로드 (빈 상태로)
                # save_rotation_state(0) # 로테이션 상태 초기화
                st.experimental_rerun()
            except Exception as e:
                st.error(f"삭제 중 오류 발생: {e}")
