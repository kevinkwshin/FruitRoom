import streamlit as st
import pandas as pd
from datetime import datetime, date, time, timedelta
import gspread
from google.oauth2.service_account import Credentials
import uuid
import json

# --- 초기 설정 ---
# (이전과 동일)
AUTO_ASSIGN_EXCLUDE_TEAMS = ["대면A", "대면B", "대면C"]
SENIOR_TEAM = "시니어"
SENIOR_ROOM = "9F-1"
ALL_TEAMS = [f"{i}조" for i in range(1, 13)] + ["대면A", "대면B", "대면C", "대면D", "청년", "중고등", SENIOR_TEAM]
ROTATION_TEAMS = [team for team in ALL_TEAMS if team not in AUTO_ASSIGN_EXCLUDE_TEAMS and team != SENIOR_TEAM]
ALL_ROOMS = [f"9F-{i}" for i in range(1, 7)] + ["B5-A", "B5-B", "B5-C"]
ROTATION_ROOMS = [room for room in ALL_ROOMS if room != SENIOR_ROOM]
AUTO_ASSIGN_TIME_SLOT = "11:30 - 13:00"
MANUAL_TIME_SLOTS = ["13:00 - 14:00", "14:00 - 15:00", "15:00 - 16:00", "16:00 - 17:00"]
RESERVATION_SHEET_HEADERS = ["날짜", "시간", "조", "방", "예약유형", "예약ID"]
ROTATION_SHEET_HEADER = ["next_team_index"]

# --- Google Sheets 클라이언트 초기화 함수 ---
# 이 함수는 한 번만 실행되도록 캐싱할 수 있습니다 (st.singleton은 deprecated, st.cache_resource 사용)
@st.cache_resource
def init_gspread_client():
    try:
        creds_json_str = st.secrets["GOOGLE_SHEETS_CREDENTIALS"]
        creds_dict = json.loads(creds_json_str)
        if 'private_key' in creds_dict and isinstance(creds_dict.get('private_key'), str):
            creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
        scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        st.error(f"Google Sheets 클라이언트 초기화 실패: {e}")
        return None

# --- 워크시트 가져오기 함수 (클라이언트가 이미 초기화되었다고 가정) ---
# 이 함수도 캐싱하여 스프레드시트와 워크시트 객체를 재사용할 수 있습니다.
@st.cache_resource
def get_worksheets(_gc_client): # _gc_client 인자를 통해 init_gspread_client의 결과에 의존하도록 함
    if _gc_client is None:
        return None, None, False # 클라이언트 초기화 실패 시
    try:
        SPREADSHEET_NAME = st.secrets["GOOGLE_SHEET_NAME"]
        spreadsheet = _gc_client.open(SPREADSHEET_NAME)
        reservations_ws = spreadsheet.worksheet("reservations")
        rotation_ws = spreadsheet.worksheet("rotation_state")
        return reservations_ws, rotation_ws, True
    except Exception as e:
        st.error(f"Google Sheets 워크시트 가져오기 실패: {e}")
        return None, None, False


# Google Sheets 클라이언트 및 워크시트 가져오기 (앱 시작 시 한 번 또는 캐시 만료 시)
gc_client = init_gspread_client()
reservations_ws, rotation_ws, GSHEET_AVAILABLE = get_worksheets(gc_client)


# --- 데이터 로드 및 저장 함수 (Google Sheets) ---
@st.cache_data(ttl=600) # 10분 동안 캐시 유지, _ws를 인자로 받아 캐시 키에 영향을 주도록 함
def get_all_records_as_df_cached(_ws, expected_headers, _cache_key_prefix): # _cache_key_prefix 추가
    if not GSHEET_AVAILABLE or _ws is None:
        return pd.DataFrame(columns=expected_headers)
    try:
        records = _ws.get_all_records() # 실제 API 호출
        df = pd.DataFrame(records)
        if df.empty or not all(h in df.columns for h in expected_headers):
            return pd.DataFrame(columns=expected_headers)
        if "날짜" in df.columns and _ws.title == "reservations":
            df['날짜'] = pd.to_datetime(df['날짜'], errors='coerce').dt.date
            df = df.dropna(subset=['날짜'])
        return df
    except Exception as e: # API 호출 실패 시
        st.warning(f"'{_ws.title}' 시트 로드 중 오류 (캐시 사용 시도): {e}")
        # 오류 발생 시 빈 DataFrame 반환하여 앱 중단 방지 (선택적)
        return pd.DataFrame(columns=expected_headers)


def update_worksheet_from_df(_ws, df, headers): # _ws를 인자로 받음
    if not GSHEET_AVAILABLE or _ws is None: return
    try:
        df_values = [headers] + df.astype(str).values.tolist()
        _ws.clear()
        _ws.update(df_values, value_input_option='USER_ENTERED')
        # 데이터 변경 시 관련 캐시 무효화
        if _ws.title == "reservations":
            get_all_records_as_df_cached.clear() # 모든 예약 로드 캐시 초기화
        elif _ws.title == "rotation_state":
            load_rotation_state_cached.clear() # 로테이션 상태 로드 캐시 초기화
    except Exception as e:
        st.error(f"'{_ws.title}' 시트 업데이트 중 오류: {e}")


# load_reservations와 load_rotation_state를 캐싱된 함수를 호출하도록 변경
def load_reservations():
    # 고유한 캐시 키를 위해 reservations_ws 객체의 id나 이름을 사용할 수 있으나,
    # 여기서는 간단히 문자열 prefix를 사용
    return get_all_records_as_df_cached(reservations_ws, RESERVATION_SHEET_HEADERS, "reservations_cache")

@st.cache_data(ttl=600) # 로테이션 상태도 캐싱
def load_rotation_state_cached(_rotation_ws, _cache_key_prefix): # _rotation_ws를 인자로 받고, cache_key_prefix 추가
    if not GSHEET_AVAILABLE or _rotation_ws is None: return 0
    df_state = get_all_records_as_df_cached(_rotation_ws, ROTATION_SHEET_HEADER, _cache_key_prefix) # 내부적으로 캐시된 함수 호출
    if not df_state.empty and "next_team_index" in df_state.columns:
        try:
            return int(df_state.iloc[0]["next_team_index"])
        except (ValueError, TypeError): return 0
    return 0

def load_rotation_state():
    return load_rotation_state_cached(rotation_ws, "rotation_state_cache")

def save_reservations(df):
    update_worksheet_from_df(reservations_ws, df, RESERVATION_SHEET_HEADERS)

def save_rotation_state(next_team_index):
    if not GSHEET_AVAILABLE or rotation_ws is None: return
    df_state = pd.DataFrame({"next_team_index": [next_team_index]})
    update_worksheet_from_df(rotation_ws, df_state, ROTATION_SHEET_HEADER)


# --- 메인 애플리케이션 ---
st.set_page_config(page_title="조모임 예약", layout="centered", initial_sidebar_state="auto")

# --- 사이드바 ---
st.sidebar.title("⚙️ 설정 및 관리")
test_mode = st.sidebar.checkbox("🧪 테스트 모드 활성화", help="활성화 시 자동 배정 요일 제한 해제")

# 캐시 초기화 버튼 (디버깅 또는 강제 새로고침용)
if st.sidebar.button("🔄 데이터 캐시 새로고침"):
    get_all_records_as_df_cached.clear()
    load_rotation_state_cached.clear()
    st.sidebar.success("데이터 캐시가 초기화되었습니다. 페이지가 새로고침됩니다.")
    st.rerun()


st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ 관리자 메뉴")
if st.sidebar.button("⚠️ 모든 예약 기록 및 로테이션 초기화", key="reset_all_data_g_sheets_sidebar_main"):
    if st.sidebar.checkbox("정말로 모든 기록을 삭제하고 로테이션 상태를 초기화하시겠습니까? (Google Sheets 데이터가 삭제됩니다)", key="confirm_delete_g_sheets_sidebar_main"):
        try:
            if GSHEET_AVAILABLE:
                empty_reservations_df = pd.DataFrame(columns=RESERVATION_SHEET_HEADERS)
                update_worksheet_from_df(reservations_ws, empty_reservations_df, RESERVATION_SHEET_HEADERS) # reservations_ws 전달
                save_rotation_state(0) # 내부적으로 rotation_ws 사용
                st.sidebar.success("모든 예약 기록 및 로테이션 상태가 Google Sheets에서 초기화되었습니다.")
                st.rerun()
            else:
                st.sidebar.error("Google Sheets에 연결되지 않아 초기화할 수 없습니다.")
        except Exception as e:
            st.sidebar.error(f"초기화 중 오류 발생: {e}")

# --- 메인 화면 ---
st.title("🚀 조모임 스터디룸 예약")
if test_mode:
    st.caption("Google Sheets 연동 | 🧪 **테스트 모드 실행 중** (자동 배정 요일 제한 없음)")
else:
    st.caption("Google Sheets 연동 | 자동 배정은 수, 일요일에만")
st.markdown("---")


if not GSHEET_AVAILABLE: # 앱 실행 시 GSHEET_AVAILABLE 상태 다시 확인
    st.error("Google Sheets에 연결할 수 없습니다. 설정을 확인하고 페이지를 새로고침해주세요.")
    st.stop()

# 앱의 주요 데이터 로드는 여기서 한 번 수행 (캐시 활용)
reservations_df = load_reservations()
# next_rotation_idx_on_load = load_rotation_state() # 탭1에서 필요시 로드하도록 변경 가능

tab1, tab2, tab3 = st.tabs(["🔄 자동 배정", "✍️ 수동 예약", "🗓️ 예약 현황"])

with tab1:
    st.header("🔄 자동 배정")
    # ... (tab1 내용 이전과 유사하게, 단 load_rotation_state()는 필요시 호출) ...
    # 예시: next_rotation_idx = load_rotation_state() 버튼 클릭 로직 내부에서 호출

    if test_mode:
        st.info("🧪 테스트 모드: 요일 제한 없이 자동 배정 가능합니다.")
    else:
        st.info("🗓️ 자동 배정은 수요일 또는 일요일에만 실행 가능합니다.")

    with st.expander("ℹ️ 자동 배정 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **배정 시간:** `{AUTO_ASSIGN_TIME_SLOT}`
        - **실행 요일:** 수요일, 일요일 (테스트 모드 시 요일 제한 없음)
        - **고정 배정:** `{SENIOR_TEAM}`은 항상 `{SENIOR_ROOM}`에 배정됩니다.
        - **로테이션 배정:**
            - `{SENIOR_TEAM}`과 `{SENIOR_ROOM}`을 제외한 나머지 조와 방으로 로테이션 배정됩니다.
            - 제외 조: `{', '.join(AUTO_ASSIGN_EXCLUDE_TEAMS)}`
            - 로테이션 대상 조: `{', '.join(ROTATION_TEAMS)}`
            - 로테이션 대상 방: `{', '.join(ROTATION_ROOMS)}`
        - 이전 자동 배정 기록을 바탕으로 순서대로 배정됩니다.
        """)

    auto_assign_date_input = st.date_input("자동 배정 실행할 날짜", value=date.today(), key="auto_date_tab1_main")
    weekday = auto_assign_date_input.weekday()
    can_auto_assign = test_mode or (weekday in [2, 6])

    if not can_auto_assign:
        st.warning("⚠️ 자동 배정은 수요일 또는 일요일에만 실행할 수 있습니다. (테스트 모드 비활성화 상태)")
        st.markdown("*자동 배정을 실행하려면 해당 요일을 선택하거나 테스트 모드를 활성화하세요.*")

    if st.button("✨ 선택 날짜 자동 배정 실행", key="auto_assign_btn_tab1_main_cached", type="primary"):
        if can_auto_assign:
            # 버튼 클릭 시 최신 데이터를 반영하기 위해 캐시된 reservations_df를 사용할 수 있으나,
            # 안전하게 하려면 여기서 load_reservations()를 다시 호출하거나,
            # 또는 예약 변경이 있는 다른 액션 후에는 st.rerun()을 통해 reservations_df가 갱신되도록 함.
            # 현재는 페이지 로드 시 reservations_df가 로드되므로, 그 값을 사용.
            # 만약 다른 사용자가 동시에 수정하는 경우를 고려한다면, 여기서 다시 load하는 것이 정확.
            # 여기서는 편의상 로드된 reservations_df를 사용.
            current_reservations_df = load_reservations() # 최신 데이터 반영을 위해 여기서 다시 로드

            existing_auto = current_reservations_df[ # current_reservations_df 사용
                (current_reservations_df["날짜"] == auto_assign_date_input) &
                (current_reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
                (current_reservations_df["예약유형"] == "자동")
            ]

            if not existing_auto.empty:
                st.warning(f"이미 {auto_assign_date_input.strftime('%Y-%m-%d')}에 자동 배정 내역이 있습니다.")
            else:
                new_auto_reservations_list = []
                assigned_info_display = []

                if SENIOR_TEAM in ALL_TEAMS and SENIOR_ROOM in ALL_ROOMS:
                    new_auto_reservations_list.append({
                        "날짜": auto_assign_date_input, "시간": AUTO_ASSIGN_TIME_SLOT,
                        "조": SENIOR_TEAM, "방": SENIOR_ROOM, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_display.append(f"🔒 **{SENIOR_TEAM}** → **{SENIOR_ROOM}** (고정)")

                next_rotation_idx = load_rotation_state() # 여기서 로테이션 상태 로드
                num_rotation_teams = len(ROTATION_TEAMS)
                num_rotation_rooms = len(ROTATION_ROOMS)
                available_rooms_for_rotation = min(num_rotation_teams, num_rotation_rooms)

                for i in range(available_rooms_for_rotation):
                    if num_rotation_teams == 0: break
                    team_idx_in_rotation_list = (next_rotation_idx + i) % num_rotation_teams
                    team_to_assign = ROTATION_TEAMS[team_idx_in_rotation_list]
                    room_to_assign = ROTATION_ROOMS[i]
                    new_auto_reservations_list.append({
                        "날짜": auto_assign_date_input, "시간": AUTO_ASSIGN_TIME_SLOT,
                        "조": team_to_assign, "방": room_to_assign, "예약유형": "자동", "예약ID": str(uuid.uuid4())
                    })
                    assigned_info_display.append(f"🔄 **{team_to_assign}** → **{room_to_assign}** (로테이션)")

                if new_auto_reservations_list:
                    new_df = pd.DataFrame(new_auto_reservations_list)
                    # current_reservations_df에 추가 (전역 reservations_df와는 별개일 수 있음)
                    updated_reservations_df = pd.concat([current_reservations_df, new_df], ignore_index=True)
                    save_reservations(updated_reservations_df) # 업데이트된 전체 DataFrame 저장
                    new_next_rotation_idx = (next_rotation_idx + available_rooms_for_rotation) % num_rotation_teams if num_rotation_teams > 0 else 0
                    save_rotation_state(new_next_rotation_idx)
                    st.success(f"🎉 {auto_assign_date_input.strftime('%Y-%m-%d')} 자동 배정 완료!")
                    for info in assigned_info_display: st.markdown(f"- {info}")
                    if num_rotation_teams > 0 :
                        st.info(f"ℹ️ 다음 로테이션 시작 조: '{ROTATION_TEAMS[new_next_rotation_idx]}'")
                    st.rerun() # 변경사항 반영 및 캐시된 데이터 재로드를 위해
                else:
                    st.error("자동 배정할 조 또는 방이 없습니다 (시니어조 제외).")
        else:
            st.error("자동 배정을 실행할 수 없는 날짜입니다. 수요일 또는 일요일을 선택하거나, 사이드바에서 테스트 모드를 활성화하세요.")

    st.subheader(f"자동 배정 현황 ({AUTO_ASSIGN_TIME_SLOT})")
    # 현재 날짜의 자동 배정 현황은 로드된 reservations_df (캐시되었을 수 있음)를 사용
    auto_today_display = reservations_df[
        (reservations_df["날짜"] == auto_assign_date_input) &
        (reservations_df["시간"] == AUTO_ASSIGN_TIME_SLOT) &
        (reservations_df["예약유형"] == "자동")
    ]
    if not auto_today_display.empty:
        st.dataframe(auto_today_display[["조", "방"]].sort_values(by="방"), use_container_width=True, height=len(auto_today_display)*38 + 38)
    else:
        st.info(f"{auto_assign_date_input.strftime('%Y-%m-%d')} 자동 배정 내역이 없습니다.")


# --- 탭 2: 수동 예약 ---
with tab2:
    st.header("✍️ 수동 예약 및 취소")
    with st.expander("ℹ️ 수동 예약 안내 (클릭하여 보기)", expanded=False):
        st.markdown(f"""
        - **예약 가능 시간:** 매일 `{', '.join(MANUAL_TIME_SLOTS)}` (1시간 단위)
        - 원하는 날짜, 조, 시간, 방을 선택하여 예약합니다.
        - 중복 예약은 불가능합니다.
        - 아래 '나의 수동 예약 취소' 섹션에서 예약을 취소할 수 있습니다.
        """)

    st.subheader("📝 새 예약 등록")
    manual_date_t2 = st.date_input("예약 날짜", value=date.today(), min_value=date.today(), key="manual_date_tab2_main_cached")

    col1_t2_cached, col2_t2_cached = st.columns(2)
    with col1_t2_cached:
        selected_team_t2 = st.selectbox("조 선택", ALL_TEAMS, key="manual_team_sel_main_cached")
    with col2_t2_cached:
        selected_room_t2 = st.selectbox("방 선택", ALL_ROOMS, key="manual_room_sel_main_cached")

    selected_time_slot_t2 = st.selectbox("시간 선택", MANUAL_TIME_SLOTS, key="manual_time_sel_main_cached")

    if st.button("✅ 예약하기", key="manual_reserve_btn_tab2_main_cached", type="primary", use_container_width=True):
        # 수동 예약 시에도 최신 데이터 반영
        current_reservations_df_t2 = load_reservations()
        conflict_room = current_reservations_df_t2[
            (current_reservations_df_t2["날짜"] == manual_date_t2) &
            (current_reservations_df_t2["시간"] == selected_time_slot_t2) &
            (current_reservations_df_t2["방"] == selected_room_t2)
        ]
        conflict_team = current_reservations_df_t2[
            (current_reservations_df_t2["날짜"] == manual_date_t2) &
            (current_reservations_df_t2["시간"] == selected_time_slot_t2) &
            (current_reservations_df_t2["조"] == selected_team_t2)
        ]

        if not conflict_room.empty:
            st.error(f"⚠️ {selected_room_t2}은(는) 해당 시간에 이미 예약되어 있습니다.")
        elif not conflict_team.empty:
            st.error(f"⚠️ {selected_team_t2}은(는) 해당 시간에 이미 다른 예약을 했습니다.")
        else:
            new_manual_res = pd.DataFrame([{
                "날짜": manual_date_t2, "시간": selected_time_slot_t2, "조": selected_team_t2,
                "방": selected_room_t2, "예약유형": "수동", "예약ID": str(uuid.uuid4())
            }])
            updated_reservations_df_t2 = pd.concat([current_reservations_df_t2, new_manual_res], ignore_index=True)
            save_reservations(updated_reservations_df_t2)
            st.success(f"🎉 예약 완료: {manual_date_t2.strftime('%Y-%m-%d')} / {selected_team_t2} / {selected_room_t2} / {selected_time_slot_t2}")
            st.rerun() # 변경사항 반영 및 캐시된 데이터 재로드를 위해

    st.markdown("---")
    st.subheader(f"🚫 나의 수동 예약 취소 ({manual_date_t2.strftime('%Y-%m-%d')})")
    # 취소 목록은 현재 로드된 reservations_df (캐시된 것)를 사용
    my_manual_reservations_display = reservations_df[
        (reservations_df["날짜"] == manual_date_t2) &
        (reservations_df["예약유형"] == "수동")
    ].copy()

    if not my_manual_reservations_display.empty:
        my_manual_reservations_display['시간'] = pd.Categorical(my_manual_reservations_display['시간'], categories=MANUAL_TIME_SLOTS, ordered=True)
        my_manual_reservations_display = my_manual_reservations_display.sort_values(by=["시간", "조"])

        for index, row in my_manual_reservations_display.iterrows():
            res_id = row["예약ID"]
            item_cols_t2_cancel = st.columns([3, 1])
            with item_cols_t2_cancel[0]:
                st.markdown(f"**{row['시간']}** / **{row['조']}** / `{row['방']}`")
            with item_cols_t2_cancel[1]:
                if st.button("취소", key=f"cancel_{res_id}_main_cached", use_container_width=True):
                    # 취소 시에도 최신 데이터 기반으로 작업
                    current_reservations_on_cancel = load_reservations()
                    updated_df_on_cancel = current_reservations_on_cancel[current_reservations_on_cancel["예약ID"] != res_id]
                    save_reservations(updated_df_on_cancel)
                    st.success(f"🗑️ 예약 취소됨: {row['조']} / {row['방']} ({row['시간']})")
                    st.rerun() # 변경사항 반영 및 캐시된 데이터 재로드를 위해
    else:
        st.info(f"{manual_date_t2.strftime('%Y-%m-%d')}에 취소할 수동 예약 내역이 없습니다.")


# --- 탭 3: 전체 예약 현황 ---
with tab3:
    st.header("🗓️ 전체 예약 현황")
    view_date_all_t3 = st.date_input("조회할 날짜", value=date.today(), key="view_date_all_tab3_input_main_cached")

    # 전체 예약 현황은 현재 로드된 reservations_df (캐시된 것)를 사용
    if not reservations_df.empty:
        display_df_t3 = reservations_df[reservations_df["날짜"] == view_date_all_t3].copy()

        if not display_df_t3.empty:
            st.subheader(f"{view_date_all_t3.strftime('%Y-%m-%d')} 예약 내역")
            time_order_t3 = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            display_df_t3['시간'] = pd.Categorical(display_df_t3['시간'], categories=time_order_t3, ordered=True)
            display_df_sorted_t3 = display_df_t3.sort_values(by=["시간", "방"])
            st.dataframe(display_df_sorted_t3[["시간", "조", "방", "예약유형"]], use_container_width=True, height=len(display_df_sorted_t3)*38 + 38)
        else:
            st.info(f"{view_date_all_t3.strftime('%Y-%m-%d')}에 예약 내역이 없습니다.")
    else:
        st.info("등록된 예약이 없습니다.")

    with st.expander("🔍 전체 기간 모든 예약 보기 (클릭)", expanded=False):
        if not reservations_df.empty:
            st.subheader("모든 예약 기록")
            df_all_copy_t3 = reservations_df.copy()
            time_order_all_t3 = [AUTO_ASSIGN_TIME_SLOT] + MANUAL_TIME_SLOTS
            df_all_copy_t3['시간'] = pd.Categorical(df_all_copy_t3['시간'], categories=time_order_all_t3, ordered=True)
            st.dataframe(df_all_copy_t3.sort_values(by=["날짜","시간", "방"])[["날짜", "시간", "조", "방", "예약유형"]], use_container_width=True)
        else:
            st.info("등록된 예약이 없습니다.")
