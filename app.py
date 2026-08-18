import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date
import json
import re

# ---------------------------------------------------------
# 1. Supabase 연결 설정
# ---------------------------------------------------------
SUPABASE_URL = "https://fpwlptevwscomkbwcxxb.supabase.co"
SUPABASE_KEY = "sb_publishable_7KeBb_WPYe3_Rhx1fOcgPQ_TKPCJbWW" 

@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

ROLE_LIST = [
    "운영 총괄PM", "거버넌스", "SEO 검수",
    "플랫폼PM(브랜드웹 ICS+카페24)", "플랫폼PM(브랜드웹 Shopify)",
    "플랫폼PM(D2C Shopify)", "플랫폼PM(D2C magento)",
    "통합 플랫폼•솔루션 컨설턴트", "Shopify Front-end 유지보수",
    "PDP Generator 유지보수 개발", "R/O", "디자인",
    "퍼블리싱", "UXUI 기획", "UXUI+QA", "AMC"
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
    # 메뉴 1: 기본정보 관리 (관리자 전용)
    # =========================================================
    if menu == "1. 기본정보 관리 (인력/MM)":
        st.title("⚙️ 인력 기본 정보 & MM 관리")

        with st.form("add_member_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            m_name = col1.text_input("이름 (예: 강AB() / con)")
            m_role = col2.selectbox("직군", ROLE_LIST)
            m_mm = col3.number_input("투입률 (MM)", min_value=0.1, max_value=5.0, value=1.0, step=0.25)
            
            if st.form_submit_button("DB에 팀원 등록"):
                if m_name:
                    supabase.table("members").insert({"name": m_name, "role": m_role, "mm": m_mm}).execute()
                    st.success(f"'{m_name}' ({m_role}) 등록 완료")
                    st.rerun()

        st.subheader("📋 현재 등록된 인력 기초 정보")
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
    # 메뉴 2: 휴가/반차 관리 (관리자 전용)
    # =========================================================
    elif menu == "2. 휴가/반차 수시 관리":
        st.title("📅 휴가 / 반차 수시 관리")
        members_data = supabase.table("members").select("name").execute().data
        member_names = [m["name"] for m in members_data]

        if member_names:
            with st.form("add_v_form", clear_on_submit=True):
                col1, col2, col3, col4 = st.columns(4)
                v_name = col1.selectbox("이름", member_names)
                v_date = col2.date_input("날짜", date.today())
                v_type = col3.selectbox("구분", ["전일휴가 (8h)", "반차(오전) (4h)", "반차(오후) (4h)", "공가/병가 (8h)"])
                v_reason = col4.text_input("사유", "개인사유")
                
                if st.form_submit_button("휴가 추가"):
                    supabase.table("vacations").insert({
                        "name": v_name, "v_date": str(v_date), "v_type": v_type, "reason": v_reason
                    }).execute()
                    st.success("휴가 정보가 저장되었습니다.")
                    st.rerun()

            st.subheader("📜 등록된 휴가 내역")
           reports_data = supabase.table("reports").select("...").order("created_at", desc=True).execute().data
                if v_data:
                df_v = pd.DataFrame(v_data)[["id", "name", "v_date", "v_type", "reason"]]
                df_v.columns = ["ID", "이름", "날짜", "구분", "사유"]
                st.dataframe(df_v, use_container_width=True)

    # =========================================================
    # 메뉴 3: 엑셀 업로드 및 위클리 보고서 생성
    # =========================================================
    elif menu == "3. 엑셀 업로드 및 위클리 리포트 생성":
        st.title("📈 위클리 보고서 자동 생성")
        uploaded_file = st.file_uploader("근무시간 원본 엑셀(raw_report.xlsx) 업로드", type=["xlsx", "xls"])

        if uploaded_file is not None:
            excel_file = pd.ExcelFile(uploaded_file)
            
            # 'Data' 시트 우선 로드, 없으면 첫 번째 시트 로드
            sheet_target = "Data" if "Data" in excel_file.sheet_names else excel_file.sheet_names[0]
            df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_target)

            st.success(f"'{sheet_target}' 시트 데이터를 성공적으로 불러왔습니다.")

            # DB 인력 매핑 정보 가져오기
            members_data = supabase.table("members").select("*").execute().data
            if not members_data:
                # DB 데이터가 없을 경우 기본 템플릿 직군 기준 매핑
                df_m = pd.DataFrame([{"name": u, "role": "기타", "mm": 1.0} for u in df_raw["User"]])
            else:
                df_m = pd.DataFrame(members_data)[["name", "role", "mm"]]

            # 일자 컬럼 추출
            user_col = "User" if "User" in df_raw.columns else df_raw.columns[0]
            date_cols = [c for c in df_raw.columns if any(day in str(c) for day in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "월", "화", "수", "목", "금"])]
            
            # 주차별 그룹핑 (5영업일 단위 자동 계산)
            w1_cols = [c for c in date_cols if any(k in str(c) for k in ["03 Aug", "04 Aug", "05 Aug", "06 Aug", "07 Aug"])]
            w2_cols = [c for c in date_cols if any(k in str(c) for k in ["10 Aug", "11 Aug", "12 Aug", "13 Aug", "14 Aug"])]
            
            df_raw["8월_실공수"] = df_raw[date_cols].sum(axis=1)
            df_raw["8월_1W"] = df_raw[w1_cols].sum(axis=1) if w1_cols else 0.0
            df_raw["8월_2W"] = df_raw[w2_cols].sum(axis=1) if w2_cols else 0.0

            # 인력 직군 병합
            merged_raw = pd.merge(df_m, df_raw[[user_col, "8월_실공수", "8월_1W", "8월_2W"]], left_on="name", right_on=user_col, how="right")

            # =========================================================
            # 위클리 보고 양식 집계 테이블 생성
            # =========================================================
            report_rows = []
            for role in ROLE_LIST:
                role_members = merged_raw[merged_raw["role"] == role]
                mm_val = role_members["mm"].sum() if not role_members.empty else 1.0
                
                actual_month = role_members["8월_실공수"].sum()
                actual_w1 = role_members["8월_1W"].sum()
                actual_w2 = role_members["8월_2W"].sum()
                
                # 기준 공수 계산 (수식 기준: 주별 8*MM*5, 월별 누적 워킹데이 기준)
                std_w1 = 8.0 * mm_val * 5.0
                std_w2 = 8.0 * mm_val * 5.0
                std_month = (8.0 * mm_val * 20.0) - (8.0 * mm_val)  # 공휴일 제외 월간 기준
                
                rate_month = (actual_month / std_month * 100) if std_month > 0 else 0.0
                rate_w1 = (actual_w1 / std_w1 * 100) if std_w1 > 0 else 0.0
                rate_w2 = (actual_w2 / std_w2 * 100) if std_w2 > 0 else 0.0
                
                # 판단 지표
                if rate_month < 80.0:
                    status = "여유"
                elif rate_month <= 120.0:
                    status = "적정"
                else:
                    status = "초과"

                report_rows.append({
                    "구분": role,
                    "MM": mm_val,
                    "월 가동률(%)": round(rate_month, 1),
                    "8월 1W 가동률(%)": round(rate_w1, 1),
                    "8월 2W 가동률(%)": round(rate_w2, 1),
                    "판단": status,
                    "월간 실공수(h)": round(actual_month, 1),
                    "월간 기준공수(h)": round(std_month, 1)
                })

            df_report = pd.DataFrame(report_rows)

            st.markdown("---")
            st.subheader("📊 위클리 보고 리포트 (양식 수식 적용 결과)")

            # 스타일 서식 적용 함수
            def highlight_status(val):
                if val == "여유":
                    return "background-color: #D9E1F2; color: #1F4E78; font-weight: bold;"
                elif val == "적정":
                    return "background-color: #E2EFDA; color: #375623; font-weight: bold;"
                elif val == "초과":
                    return "background-color: #FCE4D6; color: #C65911; font-weight: bold;"
                return ""

            st.dataframe(
                df_report.style.applymap(highlight_status, subset=["판단"]),
                use_container_width=True
            )

            # 직군별 가동률 차트
            st.subheader("📈 직군별 월간 가동률(%) 현황")
            st.bar_chart(data=df_report, x="구분", y="월 가동률(%)")

            # 리포트 DB 저장
            st.markdown("---")
            report_name = st.text_input("보고서 저장 명칭", value="2026년 8월 2주차 위클리 보고서")
            if st.button("💾 이 위클리 보고서 DB에 저장하기"):
                json_data = df_report.to_json(orient="records", force_ascii=False)
                supabase.table("reports").insert({
                    "report_title": report_name,
                    "total_mm": float(df_report["MM"].sum()),
                    "total_hours": float(df_report["월간 실공수(h)"].sum()),
                    "excel_data": json.loads(json_data)
                }).execute()
                st.success(f"'{report_name}'가 DB에 성공적으로 저장되었습니다!")

    # =========================================================
    # 메뉴 4: 과거 보고서 조회
    # =========================================================
    elif menu == "4. 과거 보고서 저장 이력 조회":
        st.title("📂 저장된 위클리 보고서 이력")
        reports_data = supabase.table("reports").select("id, report_title, total_mm, total_hours, created_at").order("created_at", ascending=False).execute().data

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