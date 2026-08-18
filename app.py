import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date
import json
import re

# ---------------------------------------------------------
# 1. Supabase 데이터베이스 연결 설정
# ---------------------------------------------------------
SUPABASE_URL = "https://fpwlptevwscomkbwcxxb.supabase.co"
SUPABASE_KEY = "sb_publishable_7KeBb_WPYe3_Rhx1fOcgPQ_TKPCJbWW" 

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# 16개 기준 직군 목록
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

st.set_page_config(page_title="위클리 가동률 & MM 리포트 시스템", layout="wide")

# ---------------------------------------------------------
# 2. 로그인 & 권한 관리
# ---------------------------------------------------------
if "user_role" not in st.session_state:
    st.session_state.user_role = None

st.sidebar.title("🔒 시스템 로그인")

if st.session_state.user_role is None:
    role_choice = st.sidebar.radio("접속 권한 선택", ["일반 사용자 (보고서 조회/생성)", "관리자 (기본정보 관리)"])
    password_input = st.sidebar.text_input("비밀번호 입력", type="password")
    
    if st.sidebar.button("로그인"):
        if role_choice == "관리자 (기본정보 관리)" and password_input == "admin123":
            st.session_state.user_role = "admin"
            st.rerun()
        elif role_choice == "일반 사용자 (보고서 조회/생성)" and password_input == "user123":
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
            "3. 엑셀 업로드 및 위클리 리포트 생성", 
            "4. 과거 보고서 저장 이력 조회"
        ])
    else:
        menu = st.sidebar.selectbox("📌 메뉴 선택", [
            "3. 엑셀 업로드 및 위클리 리포트 생성", 
            "4. 과거 보고서 저장 이력 조회"
        ])

    # =========================================================
    # 메뉴 1: 기본정보 관리 (관리자 전용 - DB 저장)
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
            col1, col2, col3 = st.columns(4)
            v_name = col1.selectbox("이름 선택", member_names) if member_names else col1.text_input("이름 입력")
            v_date = col2.date_input("날짜", date.today())
            v_type = col3.selectbox("구분", ["전일휴가 (8h)", "반차(오전) (4h)", "반차(오후) (4h)", "공가/병가 (8h)"])
            v_reason = col4.text_input("사유", "개인사유")
            
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
    # 메뉴 3: 엑셀 업로드 및 위클리 보고서 생성 (누적 가동률 기준 계산)
    # =========================================================
    elif menu == "3. 엑셀 업로드 및 위클리 리포트 생성":
        st.title("📈 위클리 근무 공수 & 가동률 리포트")
        uploaded_file = st.file_uploader("근무시간 엑셀 파일(raw_report.xlsx) 업로드", type=["xlsx", "xls"])

        if uploaded_file is not None:
            excel_file = pd.ExcelFile(uploaded_file)
            sheet_target = "Sheet1" if "Sheet1" in excel_file.sheet_names else ("Data" if "Data" in excel_file.sheet_names else excel_file.sheet_names[0])
            df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_target)

            st.success(f"'{sheet_target}' 시트 데이터를 성공적으로 불러왔습니다.")

            def clean_name(val):
                s = str(val).strip()
                match = re.match(r"^([가-힣a-zA-Z0-9]+)", s)
                return match.group(1) if match else s

            user_col = "User" if "User" in df_raw.columns else df_raw.columns[0]
            df_raw["User_clean"] = df_raw[user_col].apply(clean_name)

            # DB에서 인력 및 직군별 MM 집계
            db_members = supabase.table("members").select("*").execute().data

            if db_members:
                df_db_m = pd.DataFrame(db_members)
                df_db_m["mm"] = pd.to_numeric(df_db_m["mm"], errors="coerce").fillna(0.0)
                db_role_mm_map = df_db_m.groupby("role")["mm"].sum().to_dict()
                mm_table = pd.DataFrame([{"Role": r, "MM": db_role_mm_map.get(r, 0.0)} for r in ROLE_LIST])
            else:
                mm_table = pd.DataFrame([{"Role": r, "MM": 0.0} for r in ROLE_LIST])

            # 사용자별 직군 매칭
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

            if (df_raw["Role"].isnull().any() or not db_members) and "인력 기준 및 양식" in excel_file.sheet_names:
                df_info_sheet = pd.read_excel(uploaded_file, sheet_name="인력 기준 및 양식")
                backup_map = df_info_sheet.iloc[1:28, [0, 1]].dropna()
                backup_dict = {clean_name(u): str(r).strip() for u, r in zip(backup_map.iloc[:, 0], backup_map.iloc[:, 1])}
                df_raw["Role"] = df_raw["Role"].fillna(df_raw["User_clean"].map(backup_dict))

            # 엑셀 근무시간 추출
            date_cols = [c for c in df_raw.columns if any(m in str(c) for m in ["Aug", "8월", "Mon", "Tue", "Wed", "Thu", "Fri"]) and c not in ["Total (h)", "8월 1W", "8월 2W"]]
            w1_cols = [c for c in df_raw.columns if any(k in str(c) for k in ["03 Aug", "04 Aug", "05 Aug", "06 Aug", "07 Aug"])]
            w2_cols = [c for c in df_raw.columns if any(k in str(c) for k in ["10 Aug", "11 Aug", "12 Aug", "13 Aug", "14 Aug"])]

            df_raw["W1_hours"] = pd.to_numeric(df_raw["8월 1W"], errors="coerce").fillna(0) if "8월 1W" in df_raw.columns else df_raw[w1_cols].sum(axis=1)
            df_raw["W2_hours"] = pd.to_numeric(df_raw["8월 2W"], errors="coerce").fillna(0) if "8월 2W" in df_raw.columns else df_raw[w2_cols].sum(axis=1)
            df_raw["Month_hours"] = pd.to_numeric(df_raw["Total (h)"], errors="coerce").fillna(0) if "Total (h)" in df_raw.columns else df_raw[date_cols].sum(axis=1)

            # DB Vacation(휴가/반차) 합산
            vac_data = supabase.table("vacations").select("*").execute().data
            vac_w1_map = {}
            vac_w2_map = {}
            vac_month_map = {}

            if vac_data:
                for v in vac_data:
                    v_user_clean = clean_name(v["name"])
                    h = 4.0 if "반차" in str(v.get("v_type", "")) else 8.0
                    v_dt = str(v.get("v_date", ""))

                    if "-08-" in v_dt or "2026-08" in v_dt:
                        vac_month_map[v_user_clean] = vac_month_map.get(v_user_clean, 0.0) + h

                    if any(d in v_dt for d in ["-08-03", "-08-04", "-08-05", "-08-06", "-08-07"]):
                        vac_w1_map[v_user_clean] = vac_w1_map.get(v_user_clean, 0.0) + h

                    if any(d in v_dt for d in ["-08-10", "-08-11", "-08-12", "-08-13", "-08-14"]):
                        vac_w2_map[v_user_clean] = vac_w2_map.get(v_user_clean, 0.0) + h

            df_raw["Vac_W1"] = df_raw["User_clean"].map(vac_w1_map).fillna(0.0)
            df_raw["Vac_W2"] = df_raw["User_clean"].map(vac_w2_map).fillna(0.0)
            df_raw["Vac_Month"] = df_raw["User_clean"].map(vac_month_map).fillna(0.0)

            df_raw["W1_총실공수"] = df_raw["W1_hours"] + df_raw["Vac_W1"]
            df_raw["W2_총실공수"] = df_raw["W2_hours"] + df_raw["Vac_W2"]
            df_raw["Month_총실공수"] = df_raw["Month_hours"] + df_raw["Vac_Month"]

            # 직군별 실공수 집계
            role_sum = df_raw.groupby("Role")[["Month_총실공수", "W1_총실공수", "W2_총실공수"]].sum().reset_index()
            report_df = pd.merge(mm_table, role_sum, on="Role", how="left").fillna(0.0)

            # 주차별 가동률 계산 (주 5일 기준 = 8h * MM * 5일 = 40h * MM)
            report_df["8월 1W 가동률(%)"] = report_df.apply(
                lambda r: round(r["W1_총실공수"] / (8.0 * r["MM"] * 5.0) * 100) if r["MM"] > 0 else 0, axis=1
            )
            report_df["8월 2W 가동률(%)"] = report_df.apply(
                lambda r: round(r["W2_총실공수"] / (8.0 * r["MM"] * 5.0) * 100) if r["MM"] > 0 else 0, axis=1
            )
            
            # 🔥 [수정] 2주차까지 지난 누적 기준공수: 10영업일 * 8h * MM = 80.0h * MM
            # (월말 전체 19일이 아니라, 현재 집계 기간인 10일 기준으로 계산하여 정확한 누적 가동률 도출)
            report_df["월간기준공수(h)"] = (10.0 * 8.0 * report_df["MM"]).round(1)
            report_df["월 가동률(%)"] = report_df.apply(
                lambda r: round(r["Month_총실공수"] / r["월간기준공수(h)"] * 100) if r["월간기준공수(h)"] > 0 else 0, axis=1
            )

            # 판단 규칙 (80% 미만: 여유 / 80%~120%: 적정 / 120% 초과: 초과)
            def get_status(rate, mm):
                if mm == 0:
                    return "-"
                if rate < 80:
                    return "여유"
                elif rate <= 120:
                    return "적정"
                else:
                    return "초과"

            # 최신 주차(2W) 기준 상태 판단
            report_df["판단"] = report_df.apply(lambda r: get_status(r["8월 2W 가동률(%)"], r["MM"]), axis=1)

            # 출력용 테이블
            display_df = report_df[[
                "Role", "MM", "월 가동률(%)", "8월 1W 가동률(%)", "8월 2W 가동률(%)", 
                "판단", "Month_총실공수", "월간기준공수(h)"
            ]].copy()
            display_df.columns = [
                "구분", "MM", "월 누적 가동률(%)", "8월 1W 가동률(%)", "8월 2W 가동률(%)", 
                "판단", "월간 누적 실공수(h)", "월간 누적 기준공수(h)"
            ]

            # Total 합계 행
            total_mm = display_df["MM"].sum()
            total_actual = display_df["월간 누적 실공수(h)"].sum()
            total_std = display_df["월간 누적 기준공수(h)"].sum()
            total_month_rate = round(total_actual / total_std * 100) if total_std > 0 else 0
            total_w1_rate = round(report_df["W1_총실공수"].sum() / (8.0 * total_mm * 5.0) * 100) if total_mm > 0 else 0
            total_w2_rate = round(report_df["W2_총실공수"].sum() / (8.0 * total_mm * 5.0) * 100) if total_mm > 0 else 0

            total_row = pd.DataFrame([{
                "구분": "Total",
                "MM": total_mm,
                "월 누적 가동률(%)": total_month_rate,
                "8월 1W 가동률(%)": total_w1_rate,
                "8월 2W 가동률(%)": total_w2_rate,
                "판단": get_status(total_w2_rate, total_mm),
                "월간 누적 실공수(h)": round(total_actual, 1),
                "월간 누적 기준공수(h)": round(total_std, 1)
            }])

            final_view = pd.concat([display_df, total_row], ignore_index=True)

            st.markdown("---")
            st.subheader("📊 위클리 보고 리포트")

            def highlight_status(val):
                if val == "여유":
                    return "background-color: #D9E1F2; color: #1F4E78; font-weight: bold;"
                elif val == "적정":
                    return "background-color: #E2EFDA; color: #375623; font-weight: bold;"
                elif val == "초과":
                    return "background-color: #FCE4D6; color: #C65911; font-weight: bold;"
                return ""

            st.dataframe(
                final_view.style.map(highlight_status, subset=["판단"]).format({
                    "MM": "{:.2f}",
                    "월 누적 가동률(%)": "{:d}%",
                    "8월 1W 가동률(%)": "{:d}%",
                    "8월 2W 가동률(%)": "{:d}%",
                    "월간 누적 실공수(h)": "{:,.1f}h",
                    "월간 누적 기준공수(h)": "{:,.1f}h"
                }),
                use_container_width=True,
                height=680
            )

            # 리포트 DB 저장
            st.markdown("---")
            report_name = st.text_input("보고서 저장 명칭", value="2026년 8월 2주차 위클리 보고서")
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
        st.title("📂 저장된 위클리 보고서 이력")
        reports_data = supabase.table("reports").select("id, report_title, total_mm, total_hours, created_at").order("created_at", desc=True).execute().data

        if reports_data:
            df_r = pd.DataFrame(reports_data)
            df_r.columns = ["ID", "보고서 명칭", "총 MM", "총 실공수(h)", "저장일시"]
            st.dataframe(df_r, use_container_width=True)

            selected_id = st.selectbox("상세 조회할 보고서 ID 선택", df_r["ID"])
            if st.button("보고서 불러오기"):
                detail = supabase.table("reports").select("*").eq("id", selected_id).execute().data[0]
                st.subheader(f"📄 {detail['report_title']} 상세 내용")
                st.dataframe(pd.DataFrame(detail["excel_data"]), use_container_width=True, height=680)
        else:
            st.info("저장된 보고서가 없습니다.")