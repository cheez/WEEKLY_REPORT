import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, timedelta
import json
import re
import io

# ---------------------------------------------------------
# 1. Supabase 데이터베이스 연결 설정
# ---------------------------------------------------------
SUPABASE_URL = "https://fpwlptevwscomkbwcxxb.supabase.co"
SUPABASE_KEY = "sb_publishable_7KeBb_WPYe3_Rhx1fOcgPQ_TKPCJbWW" 

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

ROLE_LIST = [
    "운영 총괄PM",
    "거버넌스",
    "SEO 검수",
    "플랫폼PM(브랜드웹 ICS+카페24)",
    "플랫폼PM(브랜드웹 Shopify)",
    "플랫폼PM(D2C Shopify)",
    "플랫폼PM(D2C magento)",
    "통합 플랫폼•솔루션 컨설턴트",
    "Shopify Front-end 유지보수",
    "PDP Generator 유지보수 개발",
    "R/O",
    "디자인",
    "퍼블리싱",
    "UXUI 기획",
    "UXUI+QA",
    "AMC"
]

# 한국 법정 공휴일 (2026~2027)
HOLIDAYS_KR = {
    "2026-01-01": "신정", 
    "2026-02-16": "설날 연휴", "2026-02-17": "설날", "2026-02-18": "설날 연휴",
    "2026-03-01": "삼일절", "2026-03-02": "대체공휴일", 
    "2026-05-05": "어린이날", "2026-05-24": "부처님오신날", "2026-05-25": "대체공휴일", 
    "2026-06-06": "현충일", 
    "2026-08-15": "광복절", "2026-08-17": "대체공휴일",
    "2026-09-24": "추석 연휴", "2026-09-25": "추석", "2026-09-26": "추석 연휴", 
    "2026-10-03": "개천절", "2026-10-05": "대체공휴일", 
    "2026-10-09": "한글날", 
    "2026-12-25": "기독탄신일",
    "2027-01-01": "신정", 
    "2027-02-06": "설날 연휴", "2027-02-07": "설날", "2027-02-08": "설날 연휴", "2027-02-09": "대체공휴일", 
    "2027-03-01": "삼일절", 
    "2027-05-05": "어린이날", "2027-05-13": "부처님오신날", 
    "2027-06-06": "현충일", "2027-06-07": "대체공휴일", 
    "2027-08-15": "광복절", "2027-08-16": "대체공휴일",
    "2027-09-14": "추석 연휴", "2027-09-15": "추석", "2027-09-16": "추석 연휴", 
    "2027-10-03": "개천절", "2027-10-04": "대체공휴일", 
    "2027-10-09": "한글날", "2027-10-11": "대체공휴일", 
    "2027-12-25": "기독탄신일"
}

def count_working_days(start_dt, end_dt):
    cur = start_dt
    w_days = 0
    while cur <= end_dt:
        d_str = cur.strftime("%Y-%m-%d")
        if cur.weekday() < 5 and d_str not in HOLIDAYS_KR:
            w_days += 1
        cur += timedelta(days=1)
    return w_days

def highlight_status(val):
    if val == "여유":
        return "background-color: #D9E1F2; color: #1F4E78; font-weight: bold;"
    elif val == "적정":
        return "background-color: #E2EFDA; color: #375623; font-weight: bold;"
    elif val == "초과":
        return "background-color: #FCE4D6; color: #C65911; font-weight: bold;"
    return ""

st.set_page_config(page_title="위클리 가동률 & MM 리포트 시스템", layout="wide")

# ---------------------------------------------------------
# 2. 로그인 & 권한 관리
# ---------------------------------------------------------
if "user_role" not in st.session_state:
    st.session_state.user_role = None

st.sidebar.title("🔒 시스템 로그인")

if st.session_state.user_role is None:
    role_choice = st.sidebar.radio("접속 권한 선택", ["일반 사용자 (보고서 조회 전용)", "관리자 (기본정보/보고서 생성)"])
    password_input = st.sidebar.text_input("비밀번호 입력", type="password")
    
    if st.sidebar.button("로그인"):
        if role_choice == "관리자 (기본정보/보고서 생성)" and password_input == "admin123":
            st.session_state.user_role = "admin"
            st.rerun()
        elif role_choice == "일반 사용자 (보고서 조회 전용)" and password_input == "user123":
            st.session_state.user_role = "user"
            st.rerun()
        else:
            st.sidebar.error("비밀번호가 올바르지 않습니다.")
else:
    st.sidebar.info(f"현재 권한: **{'관리자' if st.session_state.user_role == 'admin' else '일반 사용자'}**")
    if st.sidebar.button("로그아웃"):
        st.session_state.user_role = None
        st.rerun()

# ---------------------------------------------------------
# 3. 메뉴 구성
# ---------------------------------------------------------
if st.session_state.user_role is None:
    st.title("📊 위클리 근무 공수 & 가동률 리포트 시스템")
    st.warning("👈 왼쪽 사이드바에서 로그인해 주세요.")
else:
    if st.session_state.user_role == "admin":
        menu = st.sidebar.selectbox("📌 메뉴 선택", [
            "1. 기본정보 관리 (인력/MM)", 
            "2. 휴가/반차 수시 관리", 
            "3. 엑셀 데이터 입력 및 위클리 리포트 생성", 
            "4. 과거 보고서 저장 이력 조회"
        ])
    else:
        menu = st.sidebar.selectbox("📌 메뉴 선택", ["4. 과거 보고서 저장 이력 조회"])

    # =========================================================
    # 메뉴 1: 기본정보 관리 (관리자 전용)
    # =========================================================
    if menu == "1. 기본정보 관리 (인력/MM)":
        st.title("⚙️ 인력 기본 정보 & 직군별 MM 관리 (DB 영구 저장)")

        with st.form("add_member_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            m_name = col1.text_input("이름 (예: 강민경 또는 강AB)")
            m_role = col2.selectbox("직군", ROLE_LIST)
            m_mm = col3.number_input("투입 MM (예: 1.0, 0.5, 0.25)", min_value=0.05, max_value=5.0, value=1.0, step=0.05)
            
            if st.form_submit_button("DB에 팀원 등록"):
                if m_name:
                    supabase.table("members").insert({"name": m_name.strip(), "role": m_role, "mm": m_mm}).execute()
                    st.success(f"'{m_name}' ({m_role}, {m_mm} MM) 등록 완료")
                    st.rerun()

        st.subheader("📋 현재 DB에 등록된 인력 목록")
        members_data = supabase.table("members").select("*").order("id").execute().data
        if members_data:
            df_m = pd.DataFrame(members_data)[["id", "name", "role", "mm"]]
            df_m.columns = ["ID", "User", "구분(직군)", "MM"]
            st.dataframe(df_m, use_container_width=True)

            st.markdown("#### 💡 DB 집계 직군별 총 MM 합계")
            db_role_summary = df_m.groupby("구분(직군)")["MM"].sum().reset_index()
            st.dataframe(db_role_summary, use_container_width=True)
            
            del_id = st.number_input("삭제할 ID 입력", min_value=1, step=1)
            if st.button("팀원 삭제"):
                supabase.table("members").delete().eq("id", del_id).execute()
                st.success("삭제되었습니다.")
                st.rerun()

    # =========================================================
    # 메뉴 2: 휴가/반차 수시 관리 (관리자 전용)
    # =========================================================
    elif menu == "2. 휴가/반차 수시 관리":
        st.title("📅 휴가 / 반차 수시 일정 관리")
        members_data = supabase.table("members").select("name").execute().data
        member_names = [m["name"] for m in members_data] if members_data else []

        with st.form("add_v_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            v_name = col1.selectbox("이름 선택", member_names) if member_names else col1.text_input("이름 입력")
            v_date = col2.date_input("날짜", date.today())
            v_type = col3.selectbox("구분", ["전일휴가 (8h)", "반차(오전) (4h)", "반차(오후) (4h)", "공가/병가 (8h)"])
            v_reason = st.text_input("사유", "개인사유")
            
            if st.form_submit_button("휴가 추가"):
                if v_name:
                    supabase.table("vacations").insert({
                        "name": v_name, "v_date": str(v_date), "v_type": v_type, "reason": v_reason
                    }).execute()
                    st.success("휴가 정보가 저장되었습니다.")
                    st.rerun()

        st.subheader("📜 등록된 휴가 내역")
        v_data = supabase.table("vacations").select("*").order("v_date", desc=True).execute().data
        if v_data:
            df_v = pd.DataFrame(v_data)[["id", "name", "v_date", "v_type", "reason"]]
            df_v.columns = ["ID", "이름", "날짜", "구분", "사유"]
            st.dataframe(df_v, use_container_width=True)

            col_v1, col_v2 = st.columns([1, 4])
            del_v_id = col_v1.number_input("삭제할 휴가 ID 입력", min_value=1, step=1)
            if col_v2.button("휴가 삭제"):
                supabase.table("vacations").delete().eq("id", del_v_id).execute()
                st.success("휴가 내역이 삭제되었습니다.")
                st.rerun()

    # =========================================================
    # 메뉴 3: 엑셀 데이터 입력 및 위클리 보고서 생성 (정확한 주차 자동 파싱)
    # =========================================================
    elif menu == "3. 엑셀 데이터 입력 및 위클리 리포트 생성":
        st.title("📈 위클리 근무 공수 & 가동률 리포트 생성")

        input_method = st.radio("📥 데이터 입력 방식 선택", ["📋 엑셀 시트 복사해서 붙여넣기 (추천)", "📁 엑셀 파일(.xlsx) 업로드"], horizontal=True)

        df_raw = None

        if input_method == "📋 엑셀 시트 복사해서 붙여넣기 (추천)":
            st.info("💡 엑셀 시트에서 헤더(User, 주차별/일자별 컬럼, Total 등)를 포함하여 복사(Ctrl+C) 후 붙여넣기(Ctrl+V)하세요.")
            pasted_text = st.text_area("엑셀 데이터 붙여넣기", height=180, placeholder="User\t8월 1W\t8월 2W\tTotal (h)\n강민경() / 컨센트릭스\t36.16\t29.83\t66.00\n...")
            
            if pasted_text.strip():
                try:
                    df_raw = pd.read_csv(io.StringIO(pasted_text.strip()), sep=None, engine='python')
                    st.success(f"총 {len(df_raw)}명의 인력 데이터를 성공적으로 불러왔습니다.")
                except Exception as e:
                    st.error(f"데이터 파싱 오류: {e}")

        else:
            uploaded_file = st.file_uploader("근무시간 엑셀 파일(raw_report.xlsx) 업로드", type=["xlsx", "xls"])
            if uploaded_file is not None:
                excel_file = pd.ExcelFile(uploaded_file)
                sheet_target = "Sheet1" if "Sheet1" in excel_file.sheet_names else ("Data" if "Data" in excel_file.sheet_names else excel_file.sheet_names[0])
                df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_target)
                st.success(f"'{sheet_target}' 시트 데이터를 성공적으로 불러왔습니다.")

        if df_raw is not None and not df_raw.empty:
            def clean_name(val):
                s = str(val).strip()
                match = re.match(r"^([가-힣a-zA-Z0-9]+)", s)
                return match.group(1) if match else s

            user_col = "User" if "User" in df_raw.columns else df_raw.columns[0]
            df_raw["User_clean"] = df_raw[user_col].apply(clean_name)

            db_members = supabase.table("members").select("*").execute().data

            user_mm_map = {}
            if db_members:
                df_db_m = pd.DataFrame(db_members)
                df_db_m["mm"] = pd.to_numeric(df_db_m["mm"], errors="coerce").fillna(0.0)
                db_role_mm_map = df_db_m.groupby("role")["mm"].sum().to_dict()
                mm_table = pd.DataFrame([{"Role": r, "MM": db_role_mm_map.get(r, 0.0)} for r in ROLE_LIST])
                for m in db_members:
                    user_mm_map[clean_name(m["name"])] = float(m.get("mm", 1.0))
            else:
                mm_table = pd.DataFrame([{"Role": r, "MM": 0.0} for r in ROLE_LIST])

            def match_role_from_db(cleaned_user):
                for m in db_members:
                    db_n = clean_name(m["name"])
                    if cleaned_user == db_n or cleaned_user.startswith(db_n) or db_n.startswith(cleaned_user):
                        return m["role"]
                return None

            if db_members:
                df_raw["Role"] = df_raw["User_clean"].apply(match_role_from_db)
            else:
                df_raw["Role"] = None

            # =========================================================
            # 🔥 [핵심] 주차 컬럼 자동 감지 및 날짜 그룹화
            # =========================================================
            # 1. 이미 '1W', '2W' 등 주차명으로 되어 있는 컬럼 찾기
            raw_week_cols = [c for c in df_raw.columns if re.search(r"\d+W|Week\s*\d+|주차", str(c), re.IGNORECASE) and str(c) not in ["User_clean", "Role"]]
            
            week_cols = []
            week_date_ranges = {}

            if raw_week_cols:
                week_cols = raw_week_cols
            else:
                # 2. 날짜 컬럼(예: '03 Aug', '2026-08-03' 등)을 파싱하여 주차로 자동 그룹화
                parsed_dates = {}
                for col in df_raw.columns:
                    c_str = str(col).strip()
                    if c_str.lower() in ["user", "user_clean", "role", "total", "total (h)", "총계", "합계"]:
                        continue
                    try:
                        dt = pd.to_datetime(c_str, errors='coerce')
                        if pd.notnull(dt):
                            parsed_dates[col] = dt.date()
                    except Exception:
                        pass
                
                if parsed_dates:
                    grouped_weeks = {}
                    for col_name, dt_val in sorted(parsed_dates.items(), key=lambda x: x[1]):
                        # ((day - 1) // 7) + 1 : 1일~7일은 1W, 8일~14일은 2W, 15일~21일은 3W
                        w_num = ((dt_val.day - 1) // 7) + 1
                        w_label = f"{dt_val.month}월 {w_num}W"
                        grouped_weeks.setdefault(w_label, []).append((col_name, dt_val))

                    for w_label, col_dt_list in grouped_weeks.items():
                        cols_in_week = [x[0] for x in col_dt_list]
                        dts_in_week = [x[1] for x in col_dt_list]
                        for c in cols_in_week:
                            df_raw[c] = pd.to_numeric(df_raw[c], errors="coerce").fillna(0.0)
                        
                        df_raw[w_label] = df_raw[cols_in_week].sum(axis=1)
                        week_cols.append(w_label)
                        week_date_ranges[w_label] = (min(dts_in_week), max(dts_in_week))

            # 주차 컬럼 숫자 변환
            for w in week_cols:
                df_raw[w] = pd.to_numeric(df_raw[w], errors="coerce").fillna(0.0)

            # 월간 누적 실공수 계산
            if "Total (h)" in df_raw.columns:
                df_raw["Month_hours"] = pd.to_numeric(df_raw["Total (h)"], errors="coerce").fillna(0.0)
            elif "Total" in df_raw.columns:
                df_raw["Month_hours"] = pd.to_numeric(df_raw["Total"], errors="coerce").fillna(0.0)
            else:
                df_raw["Month_hours"] = df_raw[week_cols].sum(axis=1) if week_cols else 0.0

            # 휴가(Vacation) 가산
            vac_data = supabase.table("vacations").select("*").execute().data
            vac_user_month = {}
            if vac_data:
                for v in vac_data:
                    u_clean = clean_name(v["name"])
                    u_mm = user_mm_map.get(u_clean, 1.0)
                    base_h = 4.0 if "반차" in str(v.get("v_type", "")) else 8.0
                    vac_user_month[u_clean] = vac_user_month.get(u_clean, 0.0) + (base_h * u_mm)

            df_raw["Vac_Month"] = df_raw["User_clean"].map(vac_user_month).fillna(0.0)
            df_raw["Month_총실공수"] = df_raw["Month_hours"] + df_raw["Vac_Month"]

            # 직군별 시간 합산
            role_sum_cols = week_cols + ["Month_총실공수"]
            role_sum = df_raw.groupby("Role")[role_sum_cols].sum().reset_index()
            report_df = pd.merge(mm_table, role_sum, on="Role", how="left").fillna(0.0)

            # 주차별 가동률(%) 계산 (헤더는 그대로 '8월 1W', '8월 2W' 유지!)
            total_elapsed_working_days = 0
            for w in week_cols:
                if w in week_date_ranges:
                    s_dt, e_dt = week_date_ranges[w]
                    w_days = max(count_working_days(s_dt, e_dt), 1)
                else:
                    w_days = 5  # 기본 주 5일
                total_elapsed_working_days += w_days
                
                # 가동률 문자열 계산
                report_df[f"{w}_rate"] = report_df.apply(
                    lambda r: f"{round(r[w] / (8.0 * r['MM'] * w_days) * 100)}%" if r["MM"] > 0 else "-", axis=1
                )

            if total_elapsed_working_days == 0:
                total_elapsed_working_days = max(len(week_cols) * 5, 1)

            # 월간 누적 가동률 계산
            report_df["월간기준공수(h)"] = (total_elapsed_working_days * 8.0 * report_df["MM"]).round(1)
            report_df["월 누적 가동률_num"] = report_df.apply(
                lambda r: round(r["Month_총실공수"] / r["월간기준공수(h)"] * 100) if r["월간기준공수(h)"] > 0 else 0, axis=1
            )
            report_df["월 누적 가동률(%)"] = report_df.apply(
                lambda r: f"{int(r['월 누적 가동률_num'])}%" if r["MM"] > 0 else "-", axis=1
            )

            # 상태 판단
            def get_status(rate_num, mm):
                if mm == 0:
                    return "-"
                if rate_num < 80:
                    return "여유"
                elif rate_num <= 120:
                    return "적정"
                else:
                    return "초과"

            report_df["판단"] = report_df.apply(lambda r: get_status(r["월 누적 가동률_num"], r["MM"]), axis=1)

            # 🔥 [표 구조 정리] 구분 | MM | 월 누적 가동률(%) | 8월 1W | 8월 2W | ... | 판단 | 월간 누적 실공수(h)
            display_dict = {
                "구분": report_df["Role"],
                "MM": report_df["MM"],
                "월 누적 가동률(%)": report_df["월 누적 가동률(%)"]
            }
            
            for w in week_cols:
                display_dict[w] = report_df[f"{w}_rate"]
                
            display_dict["판단"] = report_df["판단"]
            display_dict["월간 누적 실공수(h)"] = report_df["Month_총실공수"]

            display_df = pd.DataFrame(display_dict)

            # Total 행 생성
            total_mm = display_df["MM"].sum()
            total_actual = display_df["월간 누적 실공수(h)"].sum()
            total_std = report_df["월간기준공수(h)"].sum()
            total_month_rate = round(total_actual / total_std * 100) if total_std > 0 else 0

            total_row_dict = {
                "구분": "Total",
                "MM": total_mm,
                "월 누적 가동률(%)": f"{total_month_rate}%"
            }

            for w in week_cols:
                w_sum = report_df[w].sum()
                if w in week_date_ranges:
                    s_dt, e_dt = week_date_ranges[w]
                    w_days = max(count_working_days(s_dt, e_dt), 1)
                else:
                    w_days = 5
                w_total_rate = round(w_sum / (8.0 * total_mm * w_days) * 100) if total_mm > 0 else 0
                total_row_dict[w] = f"{w_total_rate}%"

            total_row_dict["판단"] = get_status(total_month_rate, total_mm)
            total_row_dict["월간 누적 실공수(h)"] = round(total_actual, 1)

            final_view = pd.concat([display_df, pd.DataFrame([total_row_dict])], ignore_index=True)

            st.markdown("---")
            st.subheader("📊 위클리 보고 리포트")

            st.dataframe(
                final_view.style.map(highlight_status, subset=["판단"]).format({
                    "MM": "{:.2f}",
                    "월간 누적 실공수(h)": "{:,.1f}h"
                }),
                use_container_width=True,
                height=680
            )

            default_title = f"2026년 위클리 가동률 보고서 ({len(week_cols)}주차 누적)"
            report_name = st.text_input("보고서 저장 명칭", value=default_title)
            if st.button("💾 이 위클리 보고서 DB에 저장하기"):
                json_data = final_view.to_json(orient="records", force_ascii=False)
                supabase.table("reports").insert({
                    "report_title": report_name,
                    "total_mm": float(total_mm),
                    "total_hours": float(total_actual),
                    "excel_data": json.loads(json_data)
                }).execute()
                st.success(f"'{report_name}'가 DB에 성공적으로 저장되었습니다!")

    # =========================================================
    # 메뉴 4: 과거 보고서 조회
    # =========================================================
    elif menu == "4. 과거 보고서 저장 이력 조회":
        st.title("📂 저장된 위클리 보고서 이력 조회")
        reports_data = supabase.table("reports").select("id, report_title, total_mm, total_hours, created_at").order("created_at", desc=True).execute().data

        if reports_data:
            df_r = pd.DataFrame(reports_data)
            df_r.columns = ["ID", "보고서 명칭", "총 MM", "총 실공수(h)", "저장일시"]
            st.dataframe(df_r, use_container_width=True)

            report_options = {
                f"[{r['id']}] {r['report_title']} ({str(r['created_at'])[:16]})": r['id']
                for r in reports_data
            }

            selected_label = st.selectbox("상세 조회할 보고서 선택", list(report_options.keys()))
            selected_id = report_options[selected_label]

            if st.button("보고서 불러오기"):
                detail = supabase.table("reports").select("*").eq("id", selected_id).execute().data[0]
                st.subheader(f"📄 {detail['report_title']} 상세 내용")
                
                df_detail = pd.DataFrame(detail["excel_data"])

                if "MM" in df_detail.columns:
                    df_detail["MM"] = pd.to_numeric(df_detail["MM"], errors="coerce").fillna(0.0)
                if "월간 누적 실공수(h)" in df_detail.columns:
                    df_detail["월간 누적 실공수(h)"] = pd.to_numeric(df_detail["월간 누적 실공수(h)"], errors="coerce").fillna(0.0)

                st_view = df_detail.style
                if "판단" in df_detail.columns:
                    st_view = st_view.map(highlight_status, subset=["판단"])
                
                format_dict = {}
                if "MM" in df_detail.columns:
                    format_dict["MM"] = "{:.2f}"
                if "월간 누적 실공수(h)" in df_detail.columns:
                    format_dict["월간 누적 실공수(h)"] = "{:,.1f}h"
                
                if format_dict:
                    st_view = st_view.format(format_dict)

                st.dataframe(st_view, use_container_width=True, height=680)
        else:
            st.info("저장된 보고서가 없습니다.")
