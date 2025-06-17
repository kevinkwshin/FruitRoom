import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta, time
import os

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
        if '날짜' in df.columns:
            # 날짜 형식 일관성 유지 (YYYY-MM-DD 문자열 -> datetime.date)
            df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
            df = df.dropna(subset=['날짜']) # 변환 실패한 행 제거
    except FileNotFoundError:
        df = pd.DataFrame(columns=["날짜", "시간", "조", "방", "예약유형"])
    return df

def save_reservations(df):
    # 저장 시 날짜를 YYYY-MM-DD 형식의 문자열로 저장 (CSV 호환성)
    df_copy = df.copy()
    if '날짜' in df_copy.columns:
        df_copy['날짜'] = pd.to_datetime(df_copy['날짜']).dt.strftime('%Y-%m-%d')
    df_copy.to_csv(RESERVATION_FILE, index=False)


def load_rotation_state():
    try:
        if os.path.exists(ROTATION_STATE_FILE):
            df_state = pd.read_csv(ROTATION_STATE_FILE)
            if not df_state.empty and "next_team_index" in df_state.columns:
                return int(df_state.iloc[0]["next_team_index"])
    except (FileNotFoundError, IndexError, ValueError, pd.errors.EmptyDataError):
        pass # 파일이 없거나, 비어있거나, 형식이 잘못된 경우
    return 0 # 기본값: 첫 번째 조부터 시작

def save_rotation_state(next_team_index):
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    df_state.to_csv(ROTATION_STATE_FILE, index=False)

# --- UI 헬퍼 함수 ---
def display_reservations(df, title):
    st.subheader(title)
    if not df.empty:
        # 날짜를 문자열로 표시 (사용자에게 보여줄 때)
        df_display = df.copy()
        df_display['날짜'] = pd.to_datetime(df_display['날짜']).dt.strftime('%Y-%m-%d')
        st.dataframe(df_display[["날짜", "시간", "조", "방", "예약유형"]].sort_values(by=["날짜", "시간", "방"]), use_container_width=True)
    else:
        st.info("해당 조건의 예약 내역이 없습니다.")

# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약 시스템", layout="wide", initial_sidebar_state="expanded")

st.sidebar.title("🛠️ 관리자 메뉴")
if st.sidebar.button("⚠️ 모든 예약 기록 및 로테이션 초기화", key="delete_all_sidebar"):
    confirm_delete = st.sidebar.checkbox("정말로 모든 기록을 삭제하고 로테이션 상태를 초기화하시겠습니까? 이 작업은 되돌릴 수 없습니다.")
    if confirm_delete:
        try:
            if os.path.exists(RESERVATION_FILE):
                os.remove(RESERVATION_FILE)
            if os.path.exists(ROTATION_STATE_FILE):
                os.remove(ROTATION_STATE_FILE)
            st.sidebar.success("모든 예약 기록 및 로테이션 상태가 삭제되었습니다. 앱을 새로고침합니다.")
            # 상태 초기화를 위해 빈 DataFrame과 초기 로테이션 인덱스로 설정
            save_reservations(pd.DataFrame(columns=["날짜", "시간", "조", "방", "예약유형"]))
            save_rotation_state(0)
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"삭제 중 오류 발생: {e}")

st.title("🚀 조모임 스터디룸 예약 시스템")
st.markdown("조별 스터디룸 예약을 효율적으로 관리하세요!")
st.markdown("---")

reservations_df = load_reservations()

tab1, tab2, tab3 = st.tabs(["🔄 자동 배정 (11:30-13:00)", "✍️ 수동 예약 (13:00-17:00)", "🗓️ 전체 예약 현황"])

# --- 탭 1: 자동 배정 ---
with tab1:
    st.header("🔄 오늘의 자동 배정 (로테이션 방식)")
    st.markdown(f"""
    - **배정 시간:** 매일 `{AUTO_ASSIGN_TIME_SLOT}`
    - **진행 방식:**
        1. 아래 '자동 배정 실행할 날짜'를 선택합니다.
        2. '오늘의 자동 배정 실행하기' 버튼을 누릅니다.
        3. 시스템이 설정된 조 목록에서 순서대로 방을 배정합니다. (방 개수: {len(ROOMS)}개)
        4. 다음 날에는 이전 날 배정받지 않은 조부터 순서대로 배정됩니다.
    - **대상 조:** `{', '.join(TEAMS)}`
    - **대상 방:** `{', '.join(ROOMS)}`
    """)
    st.markdown("---")

    auto_assign_date = st.date_input("자동 배정 실행할 날짜 선택", value=date.today(), key="auto_date", help="이 날짜에 대한 자동 배정을 실행합니다.")

    if st.button("✨ 오늘의 자동 배정 실행하기", key="auto_assign_btn", type="primary"):
        reservations_df = load_reservations() # 최신 데이터 로드
        existing_auto_assignment = reservations_df[
            (reservations_df["날짜"] == auto_assign_date) &
            (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
            (reservations_df["예약유형"] == "자동")
        ]

        if not existing_auto_assignment.empty:
            st.warning(f"⚠️ {auto_assign_date.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT}에 이미 자동 배정된 내역이 있습니다.")
            st.dataframe(existing_auto_assignment[["조", "방"]].sort_values(by="방"))
        else:
            next_team_start_index = load_rotation_state()
            num_teams = len(TEAMS)
            num_rooms = len(ROOMS)
            new_reservations_list = [] # DataFrame 만들 때 사용할 리스트

            st.write(f"**{auto_assign_date.strftime('%Y-%m-%d')} 자동 배정 결과:**")
            assigned_details = []
            for i in range(num_rooms):
                if num_teams == 0: break # 팀이 없으면 중단
                current_team_index = (next_team_start_index + i) % num_teams
                team_to_assign = TEAMS[current_team_index]
                room_to_assign = ROOMS[i]

                new_reservations_list.append({
                    "날짜": auto_assign_date,
                    "시간": AUTO_ASSIGN_TIME_SLOT,
                    "조": team_to_assign,
                    "방": room_to_assign,
                    "예약유형": "자동"
                })
                assigned_details.append(f"✅ **{team_to_assign}** → **{room_to_assign}**")

            if new_reservations_list:
                new_df_part = pd.DataFrame(new_reservations_list)
                reservations_df = pd.concat([reservations_df, new_df_part], ignore_index=True)
                save_reservations(reservations_df)
                save_rotation_state((next_team_start_index + num_rooms) % num_teams if num_teams > 0 else 0)

                st.success(f"🎉 {auto_assign_date.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT} 자동 배정 완료!")
                for detail in assigned_details:
                    st.markdown(f"- {detail}")
                st.info(f"ℹ️ 다음 자동 배정은 '{TEAMS[(next_team_start_index + num_rooms) % num_teams if num_teams > 0 else 0]}' 조부터 시작됩니다.")
                st.rerun()
            else:
                st.error("자동 배정에 실패했습니다. (배정할 조 또는 방이 부족할 수 있습니다.)")

    st.subheader(f"🗓️ 현재 자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT})")
    current_auto_reservations = reservations_df[
        (reservations_df["날짜"] == auto_assign_date) & # 선택된 날짜 기준
        (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not current_auto_reservations.empty:
        st.dataframe(current_auto_reservations[["조", "방"]].sort_values(by="방"), use_container_width=True)
    else:
        st.info(f"{auto_assign_date.strftime('%Y-%m-%d')} {AUTO_ASSIGN_TIME_SLOT}에 자동 배정된 내역이 없습니다.")


# --- 탭 2: 수동 예약 ---
with tab2:
    st.header("✍️ 원하는 시간/방 직접 예약")
    st.markdown(f"""
    - **예약 가능 시간:** 매일 `13:00` 부터 `17:00` 까지 1시간 단위
    - **진행 방식:**
        1. 예약할 날짜, 조, 시간, 방을 선택합니다.
        2. '예약하기' 버튼을 누릅니다.
        3. 이미 예약된 시간/방이거나, 해당 시간에 이미 다른 방을 예약한 조는 중복 예약할 수 없습니다.
    """)
    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        manual_date = st.date_input("예약 날짜", value=date.today(), min_value=date.today(), key="manual_date_input")
        selected_team = st.selectbox("조 선택", TEAMS, key="manual_team_select", help="예약을 원하는 조를 선택하세요.")
    with col2:
        selected_time_slot = st.selectbox("시간 선택", MANUAL_TIME_SLOTS, key="manual_time_select", help="원하는 예약 시간을 선택하세요.")
        selected_room = st.selectbox("방 선택", ROOMS, key="manual_room_select", help="사용하고 싶은 방을 선택하세요.")

    if st.button("✅ 예약하기", key="manual_reserve_btn", type="primary"):
        reservations_df = load_reservations() # 최신 데이터 로드
        # 중복 예약 확인
        conflict_room = reservations_df[
            (reservations_df["날짜"] == manual_date) &
            (reservations_df["시간"] == selected_time_slot) &
            (reservations_df["방"] == selected_room)
        ]
        conflict_team = reservations_df[
            (reservations_df["날짜"] == manual_date) &
            (reservations_df["시간"] == selected_time_slot) &
            (reservations_df["조"] == selected_team)
        ]

        # 자동배정 시간과 겹치는지 확인 (수동예약은 13시부터 가능하므로, 이 로직은 이론상 불필요할 수 있으나 방어적으로 추가)
        auto_assign_conflict = (selected_time_slot == AUTO_ASSIGN_TIME_SLOT)

        if auto_assign_conflict:
             st.error(f"⚠️ {selected_time_slot}은 자동 배정 시간이므로 수동 예약할 수 없습니다.")
        elif not conflict_room.empty:
            st.error(f"⚠️ {manual_date.strftime('%Y-%m-%d')} {selected_time_slot}에 '{selected_room}'은(는) 이미 예약되어 있습니다.")
        elif not conflict_team.empty:
            existing_room = conflict_team.iloc[0]["방"]
            st.error(f"⚠️ '{selected_team}'은(는) {manual_date.strftime('%Y-%m-%d')} {selected_time_slot}에 이미 '{existing_room}'을(를) 예약했습니다.")
        else:
            new_reservation_data = {
                "날짜": manual_date,
                "시간": selected_time_slot,
                "조": selected_team,
                "방": selected_room,
                "예약유형": "수동"
            }
            new_reservation_df = pd.DataFrame([new_reservation_data])
            reservations_df = pd.concat([reservations_df, new_reservation_df], ignore_index=True)
            save_reservations(reservations_df)
            st.success(f"🎉 예약 완료: {manual_date.strftime('%Y-%m-%d')} / {selected_time_slot} / {selected_team} / {selected_room}")
            st.rerun()

    st.subheader(f"🗓️ 오늘의 수동 예약 현황 ({date.today().strftime('%Y-%m-%d')})")
    manual_reservations_today = reservations_df[
        (reservations_df["날짜"] == date.today()) &
        (reservations_df["시간"].isin(MANUAL_TIME_SLOTS)) &
        (reservations_df["예약유형"] == "수동")
    ].sort_values(by=["시간", "방"])

    if not manual_reservations_today.empty:
        # 시간 순서대로 정렬하기 위해 Categorical type 사용
        manual_reservations_today['시간'] = pd.Categorical(manual_reservations_today['시간'], categories=MANUAL_TIME_SLOTS, ordered=True)
        st.dataframe(manual_reservations_today.sort_values(by="시간")[["시간", "조", "방"]], use_container_width=True)
    else:
        st.info(f"{date.today().strftime('%Y-%m-%d')} 수동 예약 내역이 없습니다.")

# --- 탭 3: 전체 예약 현황 ---
with tab3:
    st.header("🗓️ 전체 예약 현황 조회")
    st.markdown("특정 날짜의 모든 예약(자동/수동)을 확인하거나, 전체 기간의 예약 내역을 볼 수 있습니다.")
    st.markdown("---")

    view_date = st.date_input("조회할 날짜 선택", value=date.today(), key="view_date_all_tab3")

    # 데이터 로드 시 날짜 형식 통일
    reservations_df_for_display = load_reservations()

    if not reservations_df_for_display.empty:
        # 선택된 날짜의 예약만 필터링
        display_df_selected_date = reservations_df_for_display[reservations_df_for_display["날짜"] == view_date].copy() # SettingWithCopyWarning 방지

        if not display_df_selected_date.empty:
            st.subheader(f"{view_date.strftime('%Y-%m-%d')} 예약 내역")
            time_slot_order = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            display_df_selected_date['시간'] = pd.Categorical(display_df_selected_date['시간'], categories=time_slot_order, ordered=True)
            display_df_sorted = display_df_selected_date.sort_values(by=["시간", "방"])
            # 날짜 열은 이미 datetime.date 객체이므로, 표시할 때만 문자열로 변경하거나 그대로 둬도 됨
            # 여기서는 DataFrame을 직접 보여주므로 Pandas가 알아서 처리
            st.dataframe(display_df_sorted[["시간", "조", "방", "예약유형"]], use_container_width=True)
        else:
            st.info(f"{view_date.strftime('%Y-%m-%d')}에 예약된 내역이 없습니다.")
    else:
        st.info("아직 등록된 예약이 없습니다.")

    st.markdown("---")
    if st.checkbox("🔍 전체 기간의 모든 예약 기록 보기", key="show_all_data_checkbox"):
        if not reservations_df_for_display.empty:
            st.subheader("모든 예약 기록")
            # 전체 데이터 표시 시에도 시간 정렬을 위해 Categorical 사용
            reservations_df_for_display_copy = reservations_df_for_display.copy()
            time_slot_order_all = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            reservations_df_for_display_copy['시간'] = pd.Categorical(reservations_df_for_display_copy['시간'], categories=time_slot_order_all, ordered=True)
            # 날짜, 시간, 방 순으로 정렬
            st.dataframe(reservations_df_for_display_copy.sort_values(by=["날짜","시간", "방"])[["날짜", "시간", "조", "방", "예약유형"]], use_container_width=True)
        else:
            st.info("아직 등록된 예약이 없습니다.")
