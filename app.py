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

st.set_page_config(page_title="주간/월간 근무 & MM 관리 시스템", layout="wide")

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
    st.title("📊 주간/월간 근무 & MM 분석 시스템")
    st.warning("👈 왼쪽 사이드바에서 권한을 선택하고 비밀번호를 입력하여 로그인해 주세요.")
else:
    if st.session_state.user_role == "admin":
        menu = st.sidebar.selectbox("📌 메뉴 선택", ["1. 기본정보 관리 (인력/MM)", "2. 휴가/반차 수시 관리", "3. 엑셀 업로드 및 보고서 생성", "4. 과거 보고서 저장 이력 조회"])
    else:
        menu = st.sidebar.selectbox("📌 메뉴 선택", ["3. 엑셀 업로드 및 보고서 생성", "4. 과거 보고서 저장 이력 조회"])

    # =========================================================
    # 메뉴 1: 기본정보 관리 (관리자 전용 - DB 저장)
    # =========================================================
    if menu == "1. 기본정보 관리 (인력/MM)":
        st.title("⚙️ 인력 기본 정보 & MM 관리 (DB 영구 저장)")

        with st.form("add_member_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            m_name = col1.text_input("이름")
            m_role = col2.selectbox("직군", ["개발자","디자이너","기획자","퍼블리셔","RO","UI/UX", "PM","플랫폼PM","QA", "기타"])
            m_mm = col3.number_input("투입률 (MM)", min_value=0.1, max_value=1.0, value=1.0, step=0.5)
            
            if st.form_submit_button("DB에 팀원 등록"):
                if m_name:
                    supabase.table("members").insert({"name": m_name, "role": m_role, "mm": m_mm}).execute()
                    st.success(f"'{m_name}' 님이 DB에 성공적으로 저장되었습니다.")
                    st.rerun()

        st.subheader("📋 현재 저장된 팀원 목록")
        members_data = supabase.table("members").select("*").execute().data
        if members_data:
            df_m = pd.DataFrame(members_data)[["id", "name", "role", "mm"]]
            df_m.columns = ["ID", "이름", "직군", "투입률(MM)"]
            st.dataframe(df_m, use_container_width=True)
            
            # 삭제 기능
            del_id = st.number_input("삭제할 팀원 ID 번호 입력", min_value=1, step=1)
            if st.button("팀원 삭제"):
                supabase.table("members").delete().eq("id", del_id).execute()
                st.success("팀원 정보가 삭제되었습니다.")
                st.rerun()

    # =========================================================
    # 메뉴 2: 휴가/반차 수시 관리 (관리자 전용 - DB 저장)
    # =========================================================
    elif menu == "2. 휴가/반차 수시 관리":
        st.title("📅 휴가 / 반차 수시 일정 관리")
        members_data = supabase.table("members").select("name").execute().data
        member_names = [m["name"] for m in members_data]

        if member_names:
            with st.form("add_v_form", clear_on_submit=True):
                col1, col2, col3, col4 = st.columns(4)
                v_name = col1.selectbox("이름", member_names)
                v_date = col2.date_input("날짜", date.today())
                v_type = col3.selectbox("구분", ["전일휴가", "반차(오전)", "반차(오후)", "공가/병가"])
                v_reason = col4.text_input("사유", "개인사유")
                
                if st.form_submit_button("휴가 추가"):
                    supabase.table("vacations").insert({
                        "name": v_name, "v_date": str(v_date), "v_type": v_type, "reason": v_reason
                    }).execute()
                    st.success("휴가 정보가 저장되었습니다.")
                    st.rerun()

            st.subheader("📜 저장된 휴가 목록")
            v_data = supabase.table("vacations").select("*").execute().data
            if v_data:
                df_v = pd.DataFrame(v_data)[["id", "name", "v_date", "v_type", "reason"]]
                df_v.columns = ["ID", "이름", "날짜", "구분", "사유"]
                st.dataframe(df_v, use_container_width=True)

    # =========================================================
    # 메뉴 3: 엑셀 업로드 및 보고서 저장 기능
    # =========================================================
    elif menu == "3. 엑셀 업로드 및 보고서 생성":
        st.title("📈 근무시간 엑셀 분석 & 보고서 생성")
        uploaded_file = st.file_uploader("엑셀 파일 업로드", type=["xlsx", "xls"])

        if uploaded_file is not None:
            df_excel = pd.read_excel(uploaded_file)
            st.subheader("1. 원본 데이터 미리보기")
            st.dataframe(df_excel, use_container_width=True)

            if "이름" in df_excel.columns:
                date_cols = [c for c in df_excel.columns if c != "이름"]
                df_excel["총근무시간"] = df_excel[date_cols].sum(axis=1)

                members_data = supabase.table("members").select("*").execute().data
                df_m = pd.DataFrame(members_data)[["name", "role", "mm"]]
                df_m.columns = ["이름", "직군", "투입률(MM)"]
                
                merged = pd.merge(df_m, df_excel, on="이름", how="left").fillna(0)

                st.subheader("2. 📊 보고서 분석 결과")
                total_work_sum = merged["총근무시간"].sum()
                total_mm_sum = merged["투입률(MM)"].sum()

                kpi1, kpi2 = st.columns(2)
                kpi1.metric("총 투입 MM", f"{total_mm_sum:.1f} MM")
                kpi2.metric("총 근무시간", f"{total_work_sum:,.1f} 시간")

                st.dataframe(merged, use_container_width=True)

                # 💾 보고서 DB 저장 버튼
                report_title = st.text_input("💾 이 보고서의 제목/주차를 입력하세요 (예: 8월 2주차 주간보고서)")
                if st.button("이 보고서 저장하기"):
                    if report_title:
                        # 엑셀 분석 전체 데이터를 JSON으로 변환해 DB에 저장
                        json_data = merged.to_json(orient="records", force_ascii=False)
                        supabase.table("reports").insert({
                            "report_title": report_title,
                            "total_mm": total_mm_sum,
                            "total_hours": total_work_sum,
                            "excel_data": json.loads(json_data)
                        }).execute()
                        st.success(f"'{report_title}' 보고서가 성공적으로 DB에 저장되었습니다!")

    # =========================================================
    # 메뉴 4: 과거 저장된 보고서 이력 조회 (20명 공유 가능)
    # =========================================================
    elif menu == "4. 과거 보고서 저장 이력 조회":
        st.title("📂 과거 저장된 보고서 이력 목록")
        reports_data = supabase.table("reports").select("id, report_title, total_mm, total_hours, created_at").order("created_at", ascending=False).execute().data

        if reports_data:
            df_r = pd.DataFrame(reports_data)
            st.dataframe(df_r, use_container_width=True)

            selected_id = st.selectbox("상세 조회할 보고서 ID 선택", df_r["id"])
            if st.button("보고서 불러오기"):
                detail = supabase.table("reports").select("*").eq("id", selected_id).execute().data[0]
                st.subheader(f"📄 {detail['report_title']} 상세 내용")
                st.dataframe(pd.DataFrame(detail["excel_data"]))
        else:
            st.info("저장된 과거 보고서가 없습니다.")