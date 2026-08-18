import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date
import json

# ---------------------------------------------------------
# 1. Supabase 데이터베이스 연결 설정
# ---------------------------------------------------------
SUPABASE_URL = "https://fpwlptevwscomkbwcxxb.supabase.co"
SUPABASE_KEY = "sb_publishable_7KeBb_WPYe3_Rhx1fOcgPQ_TKPCJbWW" 

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# 직군별 기본 MM 기준표
DEFAULT_ROLE_MM = {
    "운영 총괄PM": 1.0,
    "거버넌스": 0.5,
    "SEO 검수": 0.5,
    "플랫폼PM(브랜드웹 ICS+카페24)": 1.0,
    "플랫폼PM(브랜드웹 Shopify)": 1.0,
    "플랫폼PM(D2C Shopify)": 1.0,
    "플랫폼PM(D2C magento)": 1.0,
    "통합 플랫폼•솔루션 컨설턴트": 0.5,
    "Shopify Front-end 유지보수": 1.0,
    "PDP Generator 유지보수 개발": 1.0,
    "R/O": 3.0,
    "디자인": 2.75,
    "퍼블리싱": 2.5,
    "UXUI 기획": 0.25,
    "UXUI+QA": 1.0,
    "AMC": 1.0
}

ROLE_LIST = list(DEFAULT_ROLE_MM.keys())

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
    # 메뉴 1: 기본정보 관리 (관리자 전용)
    # =========================================================
    if menu == "1. 기본정보 관리 (인력/MM)":
        st.title("⚙️ 인력 기본 정보 & 직군별 MM 관리")

        with st.form("add_member_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            m_name = col1.text_input("이름 (예: 강민경)")
            m_role = col2.selectbox("직군", ROLE_LIST)
            m_mm = col3.number_input("개별 MM", min_value=0.1, max_value=5.0, value=1.0, step=0.25)
            
            if st.form_submit_button("DB에 팀원 등록"):
                if m_name:
                    supabase.table("members").insert({"name": m_name.strip(), "role": m_role, "mm": m_mm}).execute()
                    st.success(f"'{m_name}' ({m_role}) 등록 완료")
                    st.rerun()

        st.subheader("📋 현재 DB에 등록된 인력 목록")
        members_data = supabase.table("members").select("*").order("id").execute().data
        if members_data:
            df_m = pd.DataFrame(members_data)[["id", "name", "role", "mm"]]
            df_m.columns = ["ID", "User", "구분(직군)", "MM"]
            st.dataframe(df_m, use_container_width=True)
            
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
            col1, col2, col3, col4 = st.columns(4)
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
    # 메뉴 3: 엑셀 업로드 및 위클리 보고서 생성 (앞 3자리 매칭 적용)
    # =========================================================
    elif menu == "3. 엑셀 업로드 및 위클리 리포트 생성":
        st.title("📈 위클리 근무 공수 & 가동률 리포트")
        uploaded_file = st.file_uploader("근무시간 엑셀 파일(raw_report.xlsx) 업로드", type=["xlsx", "xls"])

        if uploaded_file is not None:
            excel_file = pd.ExcelFile(uploaded_file)
            sheet_target = "Sheet1" if "Sheet1" in excel_file.sheet_names else ("Data" if "Data" in excel_file.sheet_names else excel_file.sheet_names[0])
            df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_target)

            st.success(f"'{sheet_target}' 시트 데이터를 불러왔습니다.")

            user_col = "User" if "User" in df_raw.columns else df_raw.columns[0]
            df_raw["User_str"] = df_raw[user_col].astype(str).str.strip()

            # DB에서 등록된 인력 정보 불러오기
            db_members = supabase.table("members").select("*").execute().data

            # 앞 3자리(Prefix) 매칭 함수
            def match_role_from_db(excel_name):
                ex_name = str(excel_name).strip()
                prefix = ex_name[:3] # 앞 3자리 추출 (예: '강민경', '강AB')
                for m in db_members:
                    db_name = m["name"].strip()
                    if db_name[:3] == prefix or ex_name.startswith(db_name) or db_name.startswith(ex_name[:2]):
                        return m["role"]
                return None

            # 매핑 적용
            if db_members:
                df_raw["Role"] = df_raw["User_str"].apply(match_role_from_db)
            else:
                df_raw["Role"] = None

            # DB에 없는 경우 '인력 기준 및 양식' 시트에서 백업 매핑
            if df_raw["Role"].isnull().any() and "인력 기준 및 양식" in excel_file.sheet_names:
                df_info_sheet = pd.read_excel(uploaded_file, sheet_name="인력 기준 및 양식")
                backup_map = df_info_sheet.iloc[1:28, [0, 1]].dropna()
                backup_map.columns = ["User_b", "Role_b"]
                backup_dict = dict(zip(backup_map["User_b"].astype(str).str.strip().str[:3], backup_map["Role_b"].astype(str).str.strip()))
                df_raw["Role"] = df_raw["Role"].fillna(df_raw["User_str"].str[:3].map(backup_dict))

            # 주차별/월간 컬럼 추출
            date_cols = [c for c in df_raw.columns if any(m in str(c) for m in ["Aug", "8월", "Mon", "Tue", "Wed", "Thu", "Fri"]) and c not in ["Total (h)", "8월 1W", "8월 2W"]]
            w1_cols = [c for c in df_raw.columns if any(k in str(c) for k in ["03 Aug", "04 Aug", "05 Aug", "06 Aug", "07 Aug"])]
            w2_cols = [c for c in df_raw.columns if any(k in str(c) for k in ["10 Aug", "11 Aug", "12 Aug", "13 Aug", "14 Aug"])]

            if "8월 1W" in df_raw.columns:
                df_raw["W1_hours"] = pd.to_numeric(df_raw["8월 1W"], errors="coerce").fillna(0)
            else:
                df_raw["W1_hours"] = df_raw[w1_cols].sum(axis=1) if w1_cols else 0.0

            if "8월 2W" in df_raw.columns:
                df_raw["W2_hours"] = pd.to_numeric(df_raw["8월 2W"], errors="coerce").fillna(0)
            else:
                df_raw["W2_hours"] = df_raw[w2_cols].sum(axis=1) if w2_cols else 0.0

            if "Total (h)" in df_raw.columns:
                df_raw["Month_hours"] = pd.to_numeric(df_raw["Total (h)"], errors="coerce").fillna(0)
            else:
                df_raw["Month_hours"] = df_raw[date_cols].sum(axis=1)

            # 직군별 실공수 집계
            role_sum = df_raw.groupby("Role")[["Month_hours", "W1_hours", "W2_hours"]].sum().reset_index()

            # MM 기준 테이블 생성
            mm_table = pd.DataFrame(list(DEFAULT_ROLE_MM.items()), columns=["Role", "MM"])
            report_df = pd.merge(mm_table, role_sum, on="Role", how="left").fillna(0.0)

            # 엑셀 공식 수식 적용
            report_df["8월 1W 가동률(%)"] = (report_df["W1_hours"] / (8.0 * report_df["MM"] * 5.0) * 100).round(1)
            report_df["8월 2W 가동률(%)"] = (report_df["W2_hours"] / (8.0 * report_df["MM"] * 5.0) * 100).round(1)
            
            # 월 기준공수: 19일 (20일 - 공휴일 1일) * 8h * MM = 152h * MM
            report_df["월간기준공수(h)"] = (19.0 * 8.0 * report_df["MM"]).round(1)
            report_df["월 가동률(%)"] = (report_df["Month_hours"] / report_df["월간기준공수(h)"] * 100).round(1)

            def calc_status(rate):
                if rate < 80.0:
                    return "여유"
                elif rate <= 120.0:
                    return "적정"
                else:
                    return "초과"

            report_df["판단"] = report_df["월 가동률(%)"].apply(calc_status)

            # 출력 화면 구성
            display_df = report_df[[
                "Role", "MM", "월 가동률(%)", "8월 1W 가동률(%)", "8월 2W 가동률(%)", 
                "판단", "Month_hours", "월간기준공수(h)"
            ]].copy()
            display_df.columns = [
                "구분", "MM", "월 가동률(%)", "8월 1W 가동률(%)", "8월 2W 가동률(%)", 
                "판단", "월간 실공수(h)", "월간 기준공수(h)"
            ]

            # Total 행 추가
            total_mm = display_df["MM"].sum()
            total_actual = display_df["월간 실공수(h)"].sum()
            total_std = display_df["월간 기준공수(h)"].sum()
            total_rate = round((total_actual / total_std * 100), 1) if total_std > 0 else 0.0

            total_row = pd.DataFrame([{
                "구분": "Total",
                "MM": total_mm,
                "월 가동률(%)": total_rate,
                "8월 1W 가동률(%)": round((report_df["W1_hours"].sum() / (8.0 * total_mm * 5.0) * 100), 1),
                "8월 2W 가동률(%)": round((report_df["W2_hours"].sum() / (8.0 * total_mm * 5.0) * 100), 1),
                "판단": calc_status(total_rate),
                "월간 실공수(h)": round(total_actual, 1),
                "월간 기준공수(h)": round(total_std, 1)
            }])

            final_view = pd.concat([display_df, total_row], ignore_index=True)

            st.markdown("---")
            st.subheader("📊 위클리 보고 리포트 (이름 앞 3자리 자동 매칭)")

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
                    "월 가동률(%)": "{:.1f}%",
                    "8월 1W 가동률(%)": "{:.1f}%",
                    "8월 2W 가동률(%)": "{:.1f}%",
                    "월간 실공수(h)": "{:,.1f}h",
                    "월간 기준공수(h)": "{:,.1f}h"
                }),
                use_container_width=True
            )

            # 직군별 가동률 차트
            st.subheader("📈 직군별 월 가동률(%) 현황")
            chart_df = display_df[display_df["구분"] != "Total"]
            st.bar_chart(data=chart_df, x="구분", y="월 가동률(%)")

            # 리포트 DB 저장
            st.markdown("---")
            report_name = st.text_input("보고서 저장 명칭", value="2026년 8월 위클리 가동률 보고서")
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
                st.dataframe(pd.DataFrame(detail["excel_data"]), use_container_width=True)
        else:
            st.info("저장된 보고서가 없습니다.")