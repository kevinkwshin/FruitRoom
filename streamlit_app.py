import streamlit as st
import datetime
import pandas as pd
import json
import os
import pytz # 시간대 처리를 위해 pytz 라이브러리 임포트

# --- 초기 설정 ---
TEAMS_ALL = ["대면A", "대면B", "대면C"] + [f"{i}조" for i in range(1, 12)]
SPACE_LOCATIONS_DETAILED = {
    "9층": {"name": "9층 조모임 공간", "spaces": [f"9층-{i}호" for i in range(1, 7)]},
    "지하5층": {"name": "지하5층 조모임 공간", "spaces": [f"지하5층-{i}호" for i in range(1, 4)]}
}
RESERVATION_FILE = "reservations.json"
KST = pytz.timezone('Asia/Seoul') # 한국 시간대 객체

# --- Helper Functions ---
def get_kst_now():
    """현재 한국 시간을 반환합니다."""
    return datetime.datetime.now(KST)

def get_kst_today():
    """현재 한국 날짜를 반환합니다."""
    return get_kst_now().date()

# --- 데이터 로드 및 저장 함수 ---
def load_reservations():
    if os.path.exists(RESERVATION_FILE):
        try:
            with open(RESERVATION_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
            kst_today_date = get_kst_today() # KST 기준 오늘 날짜 사용
            valid_reservations = []
            for item in data:
                try:
                    reservation_date_str = item.get('date')
                    if not reservation_date_str: continue
                    reservation_date = datetime.datetime.strptime(reservation_date_str, '%Y-%m-%d').date()
                    if reservation_date >= kst_today_date: # KST 오늘 또는 미래 예약만 유지
                        item['date'] = reservation_date
                        if 'timestamp' in item and isinstance(item['timestamp'], str):
                            try: item['timestamp'] = datetime.datetime.fromisoformat(item['timestamp'])
                            except ValueError: item['timestamp'] = None
                        valid_reservations.append(item)
                except ValueError: print(f"Warning: Skipping item with invalid date format: {item}"); continue
            return valid_reservations
        except Exception as e: st.error(f"예약 데이터 로드 중 오류: {e}"); return []
    return []

def save_reservations_internal(reservations_data):
    try:
        data_to_save = []
        for item in reservations_data:
            copied_item = item.copy()
            if isinstance(copied_item.get('date'), datetime.date): copied_item['date'] = copied_item['date'].isoformat()
            if 'timestamp' in copied_item and isinstance(copied_item['timestamp'], datetime.datetime): copied_item['timestamp'] = copied_item['timestamp'].isoformat()
            data_to_save.append(copied_item)
        with open(RESERVATION_FILE, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"내부 예약 데이터 저장 실패: {e}")

def save_reservations(reservations_data): save_reservations_internal(reservations_data)

# 세션 상태 초기화
if 'reservations' not in st.session_state:
    st.session_state.reservations = load_reservations()
if 'last_known_kst_date' not in st.session_state: # 마지막으로 인지한 KST 날짜 저장
    st.session_state.last_known_kst_date = get_kst_today()
if 'test_mode' not in st.session_state: st.session_state.test_mode = False
if 'form_submit_message' not in st.session_state: st.session_state.form_submit_message = None
if 'selected_team_radio' not in st.session_state: st.session_state.selected_team_radio = None
if 'selected_space_radio' not in st.session_state: st.session_state.selected_space_radio = None


def get_day_korean(date_obj): days = ["월", "화", "수", "목", "금", "토", "일"]; return days[date_obj.weekday()]

def is_reservable_today(date_obj_to_check, test_mode_active=False):
    # 이 함수는 date_obj_to_check가 KST 기준 오늘인지 확인
    if date_obj_to_check != get_kst_today(): return False
    if test_mode_active: return True
    # 요일은 해당 날짜 객체의 요일을 따름
    return date_obj_to_check.weekday() == 2 or date_obj_to_check.weekday() == 6

def handle_reservation_submission():
    date_for_reservation = get_kst_today() # 예약은 항상 KST 오늘 기준
    team = st.session_state.get("selected_team_radio")
    space = st.session_state.get("selected_space_radio")
    st.session_state.form_submit_message = None
    if not team or not space:
        st.session_state.form_submit_message = ("warning", "조와 조모임 공간을 모두 선택해주세요."); return
    date_str = date_for_reservation.strftime('%Y-%m-%d'); day_name = get_day_korean(date_for_reservation)
    for res in st.session_state.reservations:
        if res['date'] == date_for_reservation and res['room'] == space:
            st.session_state.form_submit_message = ("error", f"오류: {space}은(는) 방금 다른 조에 의해 예약된 것 같습니다. 다시 시도해주세요."); return
        if res['date'] == date_for_reservation and res['team'] == team:
            st.session_state.form_submit_message = ("error", f"오류: {team} 조는 방금 다른 공간을 예약한 것 같습니다. 다시 시도해주세요."); return
    new_reservation = {"date": date_for_reservation, "team": team, "room": space, "timestamp": get_kst_now()} # 예약 시간도 KST
    st.session_state.reservations.append(new_reservation); save_reservations(st.session_state.reservations)
    st.session_state.form_submit_message = ("success", f"{date_str} ({day_name}) **'{team}'** 조가 **'{space}'** 예약 완료.")
    st.session_state.selected_team_radio = None; st.session_state.selected_space_radio = None

def get_reservations_for_date(target_date): return [res for res in st.session_state.reservations if res.get('date') == target_date]

def get_available_spaces_for_today():
    all_spaces_list = SPACE_LOCATIONS_DETAILED["9층"]["spaces"] + SPACE_LOCATIONS_DETAILED["지하5층"]["spaces"]
    today_reservations = get_reservations_for_date(get_kst_today()) # KST 오늘 기준
    reserved_spaces_today = [res['room'] for res in today_reservations]
    available_spaces = [space for space in all_spaces_list if space not in reserved_spaces_today]
    return available_spaces

def get_available_teams_for_today():
    today_reservations = get_reservations_for_date(get_kst_today()) # KST 오늘 기준
    teams_with_reservations_today = [res['team'] for res in today_reservations]
    available_teams = [team for team in TEAMS_ALL if team not in teams_with_reservations_today]
    return available_teams

# --- Streamlit UI ---
st.set_page_config(page_title="조모임 공간 예약", layout="centered", initial_sidebar_state="collapsed")

# --- 날짜 변경 감지 및 처리 ---
current_kst_date_on_load = get_kst_today()
if st.session_state.last_known_kst_date != current_kst_date_on_load:
    st.toast(f"🗓️ 한국 시간 기준으로 날짜가 {current_kst_date_on_load.strftime('%m월 %d일')}로 변경되었습니다. 정보를 새로고침합니다.")
    st.session_state.last_known_kst_date = current_kst_date_on_load
    st.session_state.reservations = load_reservations() # 날짜 변경 시 예약 데이터도 다시 로드 (과거 필터링)
    # 필요한 다른 세션 상태 초기화 (예: 폼 선택값)
    st.session_state.selected_team_radio = None
    st.session_state.selected_space_radio = None
    st.session_state.form_submit_message = None
    st.rerun() # UI 전체 새로고침

# 현재 앱에서 사용할 날짜 (스크립트 실행 시점의 KST 오늘)
# 이 변수는 스크립트가 실행될 때마다 갱신됨
app_display_date = get_kst_today()


st.markdown("""
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, shrink-to-fit=no">
    <style>
        body { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; text-size-adjust: 100%; touch-action: manipulation; }
        .stButton > button { font-size: 0.9rem !important; padding: 0.3rem 0.6rem !important; }
        .main .block-container { max-width: 800px; padding-left: 1rem; padding-right: 1rem; }
        h1 { font-size: 1.8rem !important; } h2 { font-size: 1.5rem !important; } h3 { font-size: 1.25rem !important; }
        div[data-testid="stMarkdownContainer"] p { margin-bottom: 0.5rem !important; }
        hr { margin-top: 0.5rem !important; margin-bottom: 0.5rem !important; }
        .stRadio > label { font-size: 1rem !important; margin-bottom: 0.2rem !important; }
        .stRadio > div[role="radiogroup"] > div { margin-bottom: 0.1rem !important; }
        .stRadio label span { font-size: 0.95rem !important; }
        table { font-size: 0.9rem !important; } th, td { padding: 4px 8px !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("조모임 공간 예약")
day_name_app = get_day_korean(app_display_date)
st.subheader(f"🗓️ {app_display_date.strftime('%Y년 %m월 %d일')} ({day_name_app}요일) [KST]") # KST 명시
st.markdown("---")

# --- 사이드바 ---
with st.sidebar:
    st.header("앱 설정")
    if 'test_mode_checkbox_key' not in st.session_state: st.session_state.test_mode_checkbox_key = False
    st.session_state.test_mode = st.checkbox("🧪 테스트 모드", key="test_mode_checkbox_key", help="요일 제한 없이 오늘 날짜로 예약 가능")
    if st.button("🔄 정보 새로고침 (KST 기준)", use_container_width=True): # 버튼 텍스트 변경
        # st.session_state.reservations = load_reservations() # 필요시 주석 해제
        st.rerun()
    if st.session_state.test_mode: st.warning("테스트 모드가 활성화되어 있습니다.")
    st.markdown("---")
    with st.expander("전체 예약 내역 (오늘 이후 KST)", expanded=False): # KST 명시
        # st.session_state.reservations는 이미 KST 오늘 이후로 필터링 되어 있어야 함
        if st.session_state.reservations:
            display_data = []; sorted_reservations = sorted(st.session_state.reservations, key=lambda x: (x.get('date', get_kst_today()), x.get('room', '')))
            for res_item in sorted_reservations:
                item = res_item.copy(); current_date_obj = res_item.get('date')
                item['date_str'] = f"{current_date_obj.strftime('%y-%m-%d')}({get_day_korean(current_date_obj)[0]})" if isinstance(current_date_obj, datetime.date) else "날짜X"
                current_timestamp_obj = res_item.get('timestamp')
                item['timestamp_str'] = KST.localize(current_timestamp_obj).strftime('%H:%M') if isinstance(current_timestamp_obj, datetime.datetime) and current_timestamp_obj.tzinfo is None else (current_timestamp_obj.astimezone(KST).strftime('%H:%M') if isinstance(current_timestamp_obj, datetime.datetime) and current_timestamp_obj.tzinfo is not None else "N/A") # 타임스탬프 KST 변환
                item['space_name'] = res_item.get('room')
                display_data.append(item)
            all_res_df = pd.DataFrame(display_data)
            if not all_res_df.empty:
                st.dataframe(all_res_df[['date_str', 'team', 'space_name', 'timestamp_str']].rename(
                    columns={'date_str': '날짜', 'team': '조', 'space_name': '공간', 'timestamp_str': '예약시간(KST)'}
                ), height=250, use_container_width=True)
            else: st.caption("표시할 예약 내역이 없습니다.")
        else: st.caption("저장된 예약이 없습니다.")

# --- 1. 오늘 예약 현황 ---
with st.expander(f"1. 오늘 ({app_display_date.strftime('%m/%d')}) 예약 현황 보기", expanded=True): # 날짜 표시
    reservations_on_display_date = get_reservations_for_date(app_display_date) # app_display_date는 KST 오늘
    if not reservations_on_display_date:
        st.caption(f"오늘은 예약된 조모임 공간이 없습니다.")
    else:
        col1_table, col2_table = st.columns(2)
        status_data = {"9층": [], "지하5층": []}
        for floor_key, floor_details in SPACE_LOCATIONS_DETAILED.items():
            for space_name_full in floor_details["spaces"]:
                space_short_name = space_name_full.split('-')[-1]
                reserved_team = next((res['team'] for res in reservations_on_display_date if res['room'] == space_name_full), None)
                status_text = f"<span style='color:red;'>{reserved_team}</span>" if reserved_team else "<span style='color:green;'>가능</span>"
                status_data[floor_key].append({"호실": space_short_name, "예약 조": status_text})

        with col1_table:
            st.markdown(f"**{SPACE_LOCATIONS_DETAILED['9층']['name']}**")
            df_9f = pd.DataFrame(status_data["9층"])
            if not df_9f.empty: st.markdown(df_9f.to_html(escape=False, index=False), unsafe_allow_html=True)
            else: st.caption("정보 없음")
        
        with col2_table:
            st.markdown(f"**{SPACE_LOCATIONS_DETAILED['지하5층']['name']}**")
            df_b5f = pd.DataFrame(status_data["지하5층"])
            if not df_b5f.empty: st.markdown(df_b5f.to_html(escape=False, index=False), unsafe_allow_html=True)
            else: st.caption("정보 없음")
st.markdown("---")

# --- 2. 예약하기 (오늘) ---
with st.expander(f"2. 조모임 공간 예약하기 ({app_display_date.strftime('%m/%d')})", expanded=True): # 날짜 표시
    # 예약 로직에 사용될 날짜는 항상 KST 오늘 (app_display_date와 동일)
    reservable_today_flag = is_reservable_today(app_display_date, st.session_state.test_mode)

    if st.session_state.form_submit_message:
        msg_type, msg_content = st.session_state.form_submit_message
        if msg_type == "success": st.success(msg_content)
        elif msg_type == "error": st.error(msg_content)
        elif msg_type == "warning": st.warning(msg_content)
        st.session_state.form_submit_message = None

    if st.session_state.test_mode: st.caption(f"오늘은 [테스트 모드]로 예약 가능합니다.")
    elif reservable_today_flag: st.caption(f"오늘은 예약 가능합니다.")
    else: st.caption(f"⚠️ 오늘은 예약이 불가능합니다 (수/일요일만 가능).")

    available_spaces_for_radio = get_available_spaces_for_today() # KST 오늘 기준
    available_teams_for_radio = get_available_teams_for_today() # KST 오늘 기준

    with st.form("reservation_form_main"):
        if available_teams_for_radio:
            team_default_index = 0
            if st.session_state.selected_team_radio and st.session_state.selected_team_radio in available_teams_for_radio:
                team_default_index = available_teams_for_radio.index(st.session_state.selected_team_radio)
            selected_team_val = st.radio("조 선택 (예약 가능):", available_teams_for_radio, key="selected_team_radio", index=team_default_index, horizontal=True)
        else:
            st.warning("모든 조가 오늘 이미 예약을 완료했거나, 예약 가능한 조가 없습니다."); st.session_state.selected_team_radio = None
        st.markdown("<br>", unsafe_allow_html=True)
        if available_spaces_for_radio:
            space_default_index = 0
            if st.session_state.selected_space_radio and st.session_state.selected_space_radio in available_spaces_for_radio:
                space_default_index = available_spaces_for_radio.index(st.session_state.selected_space_radio)
            selected_space_val = st.radio("조모임 공간 선택 (예약 가능):", available_spaces_for_radio, key="selected_space_radio", index=space_default_index, horizontal=True)
        else:
            st.warning("현재 예약 가능한 조모임 공간이 없습니다."); st.session_state.selected_space_radio = None
        st.form_submit_button(
            "예약 신청", type="primary", 
            disabled=not reservable_today_flag or not available_spaces_for_radio or not available_teams_for_radio,
            use_container_width=True, on_click=handle_reservation_submission
        )