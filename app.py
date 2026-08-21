import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import date, timedelta, datetime
import json
import re
import io
import os
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors as _rlcolors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------------------------------------------------------
# 1. Supabase 데이터베이스 연결 설정
#    - 모든 민감정보는 st.secrets 에서만 로드 (하드코딩 없음)
#    - SUPABASE_KEY 에는 서버 전용 secret 키(sb_secret_...)를 넣을 것
#      · 이 앱은 서버(Streamlit)에서만 실행되므로 secret 키 사용이 안전
#      · secret 키는 RLS 를 우회하므로 절대 repo/코드/브라우저에 노출 금지
# ---------------------------------------------------------
def _require_secret(key):
    """st.secrets 에서 필수 값 로드. 없으면 안내 후 앱 정지."""
    try:
        val = st.secrets[key]
    except Exception:
        val = None
    if not val:
        st.error(
            f"⚠️ 필수 설정 '{key}' 가 없습니다.\n\n"
            "Streamlit Secrets(또는 로컬 `.streamlit/secrets.toml`)에 "
            "`SUPABASE_URL`, `SUPABASE_KEY`, `ADMIN_PW`, `USER_PW` 를 설정해 주세요."
        )
        st.stop()
    return val

SUPABASE_URL = _require_secret("SUPABASE_URL")
SUPABASE_KEY = _require_secret("SUPABASE_KEY")   # sb_secret_... (서버 전용)
ADMIN_PW = _require_secret("ADMIN_PW")
USER_PW = _require_secret("USER_PW")


@st.cache_resource
def init_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()


def db_query(fn, default=None, err_label="DB 작업"):
    """Supabase 호출 공통 래퍼. 실패 시 사용자 안내 후 default 반환."""
    try:
        return fn()
    except Exception as e:
        st.error(f"⚠️ {err_label} 중 오류가 발생했습니다: {e}")
        return default


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

# 미분류(매칭 실패) 인원을 담는 가상 직군 라벨
UNMATCHED_ROLE = "⚠️ 미분류(DB 미등록)"

# 한국 법정 공휴일 (대체공휴일 포함 2026~2027)
HOLIDAYS_KR = {
    # 2026년
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

    # 2027년
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


# ============================================================
# 위클리 리포트 계산 로직 (개별 날짜 컬럼 기반, 엑셀 양식 준거)
#   - 월 가동률 = 실공수 / (8 × MM × NETWORKDAYS(첫날,마지막날) − 월휴가)
#   - 주 가동률 = 주실공수 / (8 × MM × 그주근무일 − 그주휴가)
#   - NETWORKDAYS/주근무일: 공휴일 제외 (count_working_days)
#   - 연차: 분모 차감(B), MM 가중, v_date로 월/주 배분
# ============================================================
def parse_date_columns(columns):
    """컬럼명에서 'DD Mon YYYY' 형식 날짜 추출 → {컬럼명: date}"""
    date_cols = {}
    for col in columns:
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", str(col))
        if m:
            try:
                dt = datetime.strptime(
                    f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y"
                ).date()
                date_cols[col] = dt
            except ValueError:
                pass
    return date_cols


def find_last_filled_date(df, date_cols):
    """값이 실제로 채워진(>0) 마지막 날짜. 없으면 None."""
    last = None
    for col, dt in date_cols.items():
        series = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if (series > 0).any():
            if last is None or dt > last:
                last = dt
    return last


def build_weeks(first, last):
    """
    (가) 방식: 첫날이 속한 주부터, 첫날/마지막날로 범위 클램프. 월~금 기준.
    첫날이 무슨 요일이든 1일 근무가 1주차에 포함되어 증발하지 않음.
    반환: [(주번호, 주시작date, 주종료date), ...]
    """
    weeks = []
    cur_mon = first - timedelta(days=first.weekday())  # 첫날 주의 월요일
    wnum = 1
    while cur_mon <= last:
        wk_start = max(cur_mon, first)
        wk_end = min(cur_mon + timedelta(days=4), last)  # 금요일 또는 마지막날
        if wk_start <= wk_end:
            weeks.append((wnum, wk_start, wk_end))
            wnum += 1
        cur_mon += timedelta(days=7)
    return weeks


def compute_vacation_map(vac_data, clean_name_fn, user_mm_map, first, last, weeks):
    """
    휴가 → {user_clean: {'month': h, 주번호: h, ...}}  (분모 차감용, MM 가중)
    - 전일 8h / 반차 4h, × 개인 MM
    - v_date가 데이터 기간 밖이거나 주말/공휴일이면 무시
    """
    result = {}
    for v in (vac_data or []):
        u = clean_name_fn(v["name"])
        mm = user_mm_map.get(u, 1.0)
        base = 4.0 if "반차" in str(v.get("v_type", "")) else 8.0
        h = base * mm
        try:
            vd = pd.to_datetime(v["v_date"]).date()
        except Exception:
            continue
        if not (first <= vd <= last):
            continue
        if vd.weekday() >= 5 or vd.strftime("%Y-%m-%d") in HOLIDAYS_KR:
            continue
        d = result.setdefault(u, {"month": 0.0})
        d["month"] += h
        for wn, s, e in weeks:
            if s <= vd <= e:
                d[wn] = d.get(wn, 0.0) + h
                break
    return result


def week_label_to_range(year, month, wnum):
    """
    'N월 MW' 라벨을 실제 날짜 범위(월~금)로 역산.
    업로드 경로의 주차 공식과 동일한 규칙을 사용해 두 입력 방식의 주차 정의를 일치시킴.
      dom_adjusted = day + first_day.weekday()
      w_num = (dom_adjusted - 1)//7 + 1
    반환: (해당 주차의 첫 평일, 마지막 평일) 또는 None
    """
    try:
        first = date(year, month, 1)
    except ValueError:
        return None
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    days_in_month = (nxt - first).days

    matched = []
    for dd in range(1, days_in_month + 1):
        d = date(year, month, dd)
        dom_adjusted = dd + first.weekday()
        wn = (dom_adjusted - 1) // 7 + 1
        if wn == wnum and d.weekday() < 5:  # 평일만
            matched.append(d)
    if not matched:
        return None
    return (min(matched), max(matched))


def parse_week_label(label, default_year=None):
    """
    'N월 MW' 형태 라벨에서 (year, month, wnum) 추출. 실패 시 None.
    연도 정보가 없으면 default_year(기본: 올해) 사용.
    """
    s = str(label)
    m = re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*W", s, re.IGNORECASE)
    if not m:
        return None
    month = int(m.group(1))
    wnum = int(m.group(2))
    # 라벨에 연도가 들어있으면 사용
    ym = re.search(r"(20\d{2})", s)
    year = int(ym.group(1)) if ym else (default_year or date.today().year)
    if not (1 <= month <= 12):
        return None
    return (year, month, wnum)


def build_role_matcher(db_members, clean_fn):
    """
    2-pass 이름 매칭기 생성.
      1차: 정확 일치(==)
      2차: 최장 접두 우선 fallback (양방향 startswith)
    반환: match(cleaned_user) -> role or None
    """
    exact = {}
    prefix_list = []
    for m in db_members:
        dn = clean_fn(m["name"])
        exact.setdefault(dn, m["role"])
        prefix_list.append((dn, m["role"]))
    prefix_list.sort(key=lambda x: len(x[0]), reverse=True)  # 최장 접두 우선

    def match(cleaned_user):
        if cleaned_user in exact:
            return exact[cleaned_user]
        for dn, role in prefix_list:
            if not dn:
                continue
            if cleaned_user.startswith(dn) or dn.startswith(cleaned_user):
                return role
        return None

    return match


# ============================================================
# PDF 리포트 생성 (reportlab + 나눔고딕 임베딩)
# ============================================================
_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
_FONTS_REGISTERED = False


def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    try:
        pdfmetrics.registerFont(TTFont("Nanum", os.path.join(_FONT_DIR, "NanumGothic-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("Nanum-Bold", os.path.join(_FONT_DIR, "NanumGothic-Bold.ttf")))
        _FONTS_REGISTERED = True
    except Exception:
        # 폰트 파일이 없으면 기본 폰트로 폴백 (한글 깨질 수 있음)
        _FONTS_REGISTERED = False


_PDF_STATUS_COLORS = {
    "여유": (_rlcolors.HexColor("#D9E1F2"), _rlcolors.HexColor("#1F4E78")),
    "적정": (_rlcolors.HexColor("#E2EFDA"), _rlcolors.HexColor("#375623")),
    "초과": (_rlcolors.HexColor("#FCE4D6"), _rlcolors.HexColor("#C65911")),
}
_PDF_BRAND = _rlcolors.HexColor("#4A5A8A")
_PDF_BRAND_LIGHT = _rlcolors.HexColor("#EEF1F8")
_PDF_GRID = _rlcolors.HexColor("#D0D4DD")


def build_report_pdf(title, rows, columns, meta=None):
    """저장된 리포트를 예쁜 PDF(bytes)로 생성. landscape A4."""
    _register_fonts()
    fn = "Nanum" if _FONTS_REGISTERED else "Helvetica"
    fnb = "Nanum-Bold" if _FONTS_REGISTERED else "Helvetica-Bold"
    meta = meta or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=13 * mm, bottomMargin=13 * mm, title=title,
    )
    styles = getSampleStyleSheet()
    h_title = ParagraphStyle("T", parent=styles["Title"], fontName=fnb,
                             fontSize=18, textColor=_PDF_BRAND, spaceAfter=2, leading=22)
    h_sub = ParagraphStyle("S", parent=styles["Normal"], fontName=fn,
                           fontSize=9, textColor=_rlcolors.HexColor("#666666"), spaceAfter=2)
    cell = ParagraphStyle("C", fontName=fn, fontSize=8.5, leading=11, alignment=1)
    cell_left = ParagraphStyle("CL", fontName=fn, fontSize=8.5, leading=11, alignment=0)
    legend_style = ParagraphStyle("L", fontName=fn, fontSize=8,
                                  textColor=_rlcolors.HexColor("#555555"))

    story = [Paragraph(title, h_title)]
    sub_bits = []
    if meta.get("기간"):
        sub_bits.append(f"기간: {meta['기간']}")
    if meta.get("생성일"):
        sub_bits.append(f"생성일: {meta['생성일']}")
    if sub_bits:
        story.append(Paragraph("  |  ".join(sub_bits), h_sub))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.2, color=_PDF_BRAND, spaceAfter=8))

    # 요약 박스
    summary_items = [(k, str(meta[k])) for k in ["총 MM", "총 실공수", "Total 가동률"]
                     if k in meta and meta[k] not in (None, "")]
    if summary_items:
        sum_data = [
            [Paragraph(f"<b>{v}</b>", ParagraphStyle("sv", fontName=fnb, fontSize=13,
                       alignment=1, textColor=_PDF_BRAND)) for _, v in summary_items],
            [Paragraph(k, ParagraphStyle("sk", fontName=fn, fontSize=8, alignment=1,
                       textColor=_rlcolors.HexColor("#888888"))) for k, _ in summary_items],
        ]
        sum_tbl = Table(sum_data, colWidths=[45 * mm] * len(summary_items))
        sum_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _PDF_BRAND_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, _PDF_GRID),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, _rlcolors.white),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(sum_tbl)
        story.append(Spacer(1, 10))

    # 본 표
    header = [Paragraph(f"<b>{c}</b>", ParagraphStyle("hd", fontName=fnb, fontSize=8.5,
              alignment=1, textColor=_rlcolors.white)) for c in columns]
    table_data = [header]
    status_row_idx = []
    for i, row in enumerate(rows, start=1):
        line = []
        for c in columns:
            val = row.get(c, "")
            val = "" if val is None else str(val)
            line.append(Paragraph(val, cell_left if c == "구분" else cell))
        table_data.append(line)
        if "판단" in row and row["판단"] in _PDF_STATUS_COLORS:
            status_row_idx.append((i, row["판단"]))

    ncol = len(columns)
    total_w = 269 * mm
    first_w = 46 * mm
    rest_w = (total_w - first_w) / (ncol - 1) if ncol > 1 else total_w
    col_widths = [first_w] + [rest_w] * (ncol - 1)

    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), _PDF_BRAND),
        ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 4), ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.4, _PDF_GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_rlcolors.white, _rlcolors.HexColor("#F7F8FB")]),
    ]
    if "판단" in columns:
        jcol = columns.index("판단")
        for ridx, sval in status_row_idx:
            bg, fg = _PDF_STATUS_COLORS[sval]
            ts.append(("BACKGROUND", (jcol, ridx), (jcol, ridx), bg))
            ts.append(("TEXTCOLOR", (jcol, ridx), (jcol, ridx), fg))
    if rows and str(rows[-1].get("구분", "")) == "Total":
        last = len(rows)
        ts.append(("BACKGROUND", (0, last), (-1, last), _rlcolors.HexColor("#E8EBF3")))
        ts.append(("FONTNAME", (0, last), (-1, last), fnb))
    tbl.setStyle(TableStyle(ts))
    story.append(tbl)

    # 범례
    story.append(Spacer(1, 10))

    def _legend_cell(label, color):
        hexcode = "#" + color.hexval()[2:]
        return Paragraph(f'<font color="{hexcode}">■</font> {label}',
                         ParagraphStyle("lg", fontName=fn, fontSize=8.5,
                                        textColor=_rlcolors.HexColor("#444444")))

    legend = Table([[
        _legend_cell("여유 (80% 미만)", _PDF_STATUS_COLORS["여유"][1]),
        _legend_cell("적정 (80~120%)", _PDF_STATUS_COLORS["적정"][1]),
        _legend_cell("초과 (120% 초과)", _PDF_STATUS_COLORS["초과"][1]),
    ]], colWidths=[45 * mm, 45 * mm, 45 * mm])
    legend.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(legend)
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "※ 가동률 = 실공수 ÷ (8h × MM × 근무일 − 휴가시간). 근무일은 주말·공휴일 제외.",
        legend_style))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()


def resolve_role_mm(role_mm_rows, cutoff_date):
    """
    role_mm 테이블에서 apply_date <= cutoff_date 중 각 직군별 가장 최근 MM 조회.
    반환: {role: mm}  (해당 없으면 빈 dict → 호출측에서 members sum fallback)
    """
    best = {}  # role -> (apply_date, mm)
    for r in (role_mm_rows or []):
        ad = r.get("apply_date")
        if isinstance(ad, str):
            try:
                ad = date.fromisoformat(ad[:10])
            except Exception:
                continue
        if ad is None:
            continue
        if ad <= cutoff_date:
            role = r.get("role")
            mm = r.get("mm")
            if role is None or mm is None:
                continue
            if role not in best or ad > best[role][0]:
                best[role] = (ad, float(mm))
    return {role: mm for role, (ad, mm) in best.items()}


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
        if role_choice == "관리자 (기본정보/보고서 생성)" and password_input == ADMIN_PW:
            st.session_state.user_role = "admin"
            st.rerun()
        elif role_choice == "일반 사용자 (보고서 조회 전용)" and password_input == USER_PW:
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
                    ok = db_query(
                        lambda: supabase.table("members").insert(
                            {"name": m_name.strip(), "role": m_role, "mm": m_mm}
                        ).execute(),
                        default=None, err_label="팀원 등록"
                    )
                    if ok is not None:
                        st.success(f"'{m_name}' ({m_role}, {m_mm} MM) 등록 완료")
                        st.rerun()

        st.subheader("📋 현재 DB에 등록된 인력 목록")
        members_data = db_query(
            lambda: supabase.table("members").select("*").order("id").execute().data,
            default=[], err_label="인력 목록 조회"
        )
        if members_data:
            df_m = pd.DataFrame(members_data)[["id", "name", "role", "mm"]]
            df_m.columns = ["ID", "User", "구분(직군)", "MM"]
            st.dataframe(df_m, use_container_width=True)

            st.markdown("#### 💡 DB 집계 직군별 총 MM 합계")
            db_role_summary = df_m.groupby("구분(직군)")["MM"].sum().reset_index()
            st.dataframe(db_role_summary, use_container_width=True)

            del_id = st.number_input("삭제할 ID 입력", min_value=1, step=1)
            if st.button("팀원 삭제"):
                ok = db_query(
                    lambda: supabase.table("members").delete().eq("id", del_id).execute(),
                    default=None, err_label="팀원 삭제"
                )
                if ok is not None:
                    st.success("삭제되었습니다.")
                    st.rerun()

        # ─────────────────────────────────────────────
        # 직군별 MM 기준 관리 (시점별, 가동률 분모용)
        # ─────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🎯 직군별 MM 기준 관리 (가동률 산정 기준)")
        st.caption(
            "직군별 MM을 적용일자와 함께 등록합니다. 리포트는 '데이터 마지막날 이전의 가장 최근 등록값'을 사용합니다. "
            "(예: 9월 리포트인데 9월 등록이 없으면 8월 등록값 적용). "
            "※ 등록값이 하나도 없으면 인력 목록의 MM 합계로 자동 대체됩니다."
        )

        with st.form("add_role_mm_form", clear_on_submit=True):
            rc1, rc2, rc3 = st.columns(3)
            rm_date = rc1.date_input("적용일자", date.today())
            rm_role = rc2.selectbox("직군", ROLE_LIST, key="role_mm_role")
            rm_mm = rc3.number_input("직군 MM", min_value=0.0, max_value=50.0, value=1.0, step=0.05, key="role_mm_val")

            if st.form_submit_button("직군 MM 등록"):
                ok = db_query(
                    lambda: supabase.table("role_mm").insert(
                        {"apply_date": str(rm_date), "role": rm_role, "mm": rm_mm}
                    ).execute(),
                    default=None, err_label="직군 MM 등록"
                )
                if ok is not None:
                    st.success(f"'{rm_role}' MM={rm_mm} ({rm_date}) 등록 완료")
                    st.rerun()

        role_mm_data = db_query(
            lambda: supabase.table("role_mm").select("*").order("apply_date", desc=True).order("role").execute().data,
            default=[], err_label="직군 MM 목록 조회"
        )
        if role_mm_data:
            df_rm = pd.DataFrame(role_mm_data)[["id", "apply_date", "role", "mm"]]
            df_rm.columns = ["ID", "적용일자", "직군", "MM"]
            st.dataframe(df_rm, use_container_width=True)

            del_rm_id = st.number_input("삭제할 직군MM ID 입력", min_value=1, step=1, key="del_role_mm")
            if st.button("직군 MM 삭제"):
                ok = db_query(
                    lambda: supabase.table("role_mm").delete().eq("id", del_rm_id).execute(),
                    default=None, err_label="직군 MM 삭제"
                )
                if ok is not None:
                    st.success("삭제되었습니다.")
                    st.rerun()
        else:
            st.info("등록된 직군별 MM 기준이 없습니다. (현재는 인력 목록 MM 합계로 대체 계산됩니다)")

    # =========================================================
    # 메뉴 2: 휴가/반차 수시 관리 (관리자 전용)
    # =========================================================
    elif menu == "2. 휴가/반차 수시 관리":
        st.title("📅 휴가 / 반차 수시 일정 관리")
        members_data = db_query(
            lambda: supabase.table("members").select("name").execute().data,
            default=[], err_label="인력 목록 조회"
        )
        member_names = [m["name"] for m in members_data] if members_data else []

        with st.form("add_v_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            v_name = col1.selectbox("이름 선택", member_names) if member_names else col1.text_input("이름 입력")
            v_date = col2.date_input("날짜", date.today())
            v_type = col3.selectbox("구분", ["전일휴가 (8h)", "반차(오전) (4h)", "반차(오후) (4h)", "공가/병가 (8h)"])
            v_reason = st.text_input("사유", "개인사유")

            if st.form_submit_button("휴가 추가"):
                if v_name:
                    ok = db_query(
                        lambda: supabase.table("vacations").insert({
                            "name": v_name, "v_date": str(v_date), "v_type": v_type, "reason": v_reason
                        }).execute(),
                        default=None, err_label="휴가 저장"
                    )
                    if ok is not None:
                        st.success("휴가 정보가 저장되었습니다.")
                        st.rerun()

        st.subheader("📜 등록된 휴가 내역")
        v_data = db_query(
            lambda: supabase.table("vacations").select("*").order("v_date", desc=True).execute().data,
            default=[], err_label="휴가 내역 조회"
        )
        if v_data:
            df_v = pd.DataFrame(v_data)[["id", "name", "v_date", "v_type", "reason"]]
            df_v.columns = ["ID", "이름", "날짜", "구분", "사유"]
            st.dataframe(df_v, use_container_width=True)

            col_v1, col_v2 = st.columns([1, 4])
            del_v_id = col_v1.number_input("삭제할 휴가 ID 입력", min_value=1, step=1)
            if col_v2.button("휴가 삭제"):
                ok = db_query(
                    lambda: supabase.table("vacations").delete().eq("id", del_v_id).execute(),
                    default=None, err_label="휴가 삭제"
                )
                if ok is not None:
                    st.success("휴가 내역이 삭제되었습니다.")
                    st.rerun()

    # =========================================================
    # 메뉴 3: 엑셀 데이터 입력 및 위클리 보고서 생성 (동적 분석)
    # =========================================================
    elif menu == "3. 엑셀 데이터 입력 및 위클리 리포트 생성":
        st.title("📈 위클리 근무 공수 & 가동률 리포트 생성")

        input_method = st.radio(
            "📥 데이터 입력 방식 선택",
            ["📋 엑셀 시트 복사해서 붙여넣기 (추천)", "📁 엑셀 파일(.xlsx) 업로드"],
            horizontal=True
        )

        df_raw = None

        if input_method == "📋 엑셀 시트 복사해서 붙여넣기 (추천)":
            st.info("💡 엑셀 시트에서 헤더(User, 주차/일자별 컬럼, Total 등)를 포함하여 복사(Ctrl+C) 후 붙여넣기(Ctrl+V)하세요.")
            pasted_text = st.text_area(
                "엑셀 데이터 붙여넣기", height=180,
                placeholder="User\t8월 1W\t8월 2W\tTotal (h)\n강민경() / 컨센트릭스\t36.16\t29.83\t66.00\n..."
            )

            if pasted_text.strip():
                try:
                    # 엑셀 붙여넣기는 항상 탭 구분 → 탭 고정 (Sniffer 오작동 방지)
                    df_raw = pd.read_csv(io.StringIO(pasted_text.strip()), sep="\t", engine="python")
                    st.success(f"총 {len(df_raw)}명의 인력 데이터를 성공적으로 불러왔습니다.")
                except Exception as e:
                    st.error(f"데이터 파싱 오류: {e}")

        else:
            uploaded_file = st.file_uploader("근무시간 엑셀 파일(raw_report.xlsx) 업로드", type=["xlsx", "xls"])
            if uploaded_file is not None:
                try:
                    excel_file = pd.ExcelFile(uploaded_file)
                    sheet_target = "Sheet1" if "Sheet1" in excel_file.sheet_names else (
                        "Data" if "Data" in excel_file.sheet_names else excel_file.sheet_names[0])
                    df_raw = pd.read_excel(uploaded_file, sheet_name=sheet_target)
                    st.success(f"'{sheet_target}' 시트 데이터를 성공적으로 불러왔습니다.")
                except Exception as e:
                    st.error(f"엑셀 파일 읽기 오류: {e}")

        if df_raw is not None and not df_raw.empty:
            def clean_name(val):
                s = str(val).strip()
                match = re.match(r"^([가-힣a-zA-Z0-9]+)", s)
                return match.group(1) if match else s

            user_col = "User" if "User" in df_raw.columns else df_raw.columns[0]
            df_raw["User_clean"] = df_raw[user_col].apply(clean_name)

            db_members = db_query(
                lambda: supabase.table("members").select("*").execute().data,
                default=[], err_label="인력 정보 조회"
            ) or []

            user_mm_map = {}
            db_role_mm_sum = {}  # members 기반 직군 MM 합 (fallback용)
            if db_members:
                df_db_m = pd.DataFrame(db_members)
                df_db_m["mm"] = pd.to_numeric(df_db_m["mm"], errors="coerce").fillna(0.0)
                db_role_mm_sum = df_db_m.groupby("role")["mm"].sum().to_dict()
                for m in db_members:
                    user_mm_map[clean_name(m["name"])] = float(m.get("mm", 1.0))

            # 2-pass 매칭기 (정확 일치 우선 → 최장 접두 fallback)
            role_matcher = build_role_matcher(db_members, clean_name) if db_members else (lambda x: None)
            df_raw["Role"] = df_raw["User_clean"].apply(role_matcher)

            # ── 매칭 실패(미분류) 인원 처리: 경고 + '미분류' 직군으로 편입 ──
            unmatched_mask = df_raw["Role"].isna()
            unmatched_names = df_raw.loc[unmatched_mask, "User_clean"].tolist()
            has_unmatched = bool(unmatched_names)
            if has_unmatched:
                st.warning(
                    f"⚠️ DB에 매칭되지 않은 인원 {len(unmatched_names)}명이 있습니다: "
                    f"**{', '.join(unmatched_names)}**\n\n"
                    f"→ 이 인원은 '{UNMATCHED_ROLE}' 항목으로 집계에 포함되며, MM=0으로 처리되어 가동률(%)은 '-'로 표시됩니다. "
                    f"정확한 가동률 산출을 위해 [메뉴 1]에서 해당 인원을 등록하거나 이름 표기를 맞춰주세요."
                )
                df_raw.loc[unmatched_mask, "Role"] = UNMATCHED_ROLE

            # ── 개별 날짜 컬럼 파싱 (Data 시트 형식: 'Sat, 01 Aug 2026 (h)') ──
            date_cols = parse_date_columns(df_raw.columns)

            if not date_cols:
                st.error(
                    "⚠️ 날짜 컬럼을 찾지 못했습니다. 'Sat, 01 Aug 2026 (h)'처럼 "
                    "개별 일자 컬럼이 포함된 데이터(Data 시트 형식)를 넣어주세요."
                )
                st.stop()

            for col in date_cols:
                df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce").fillna(0.0)

            first_date = min(date_cols.values())
            last_date = find_last_filled_date(df_raw, date_cols)
            if last_date is None:
                last_date = max(date_cols.values())

            # ── 직군별 MM 결정: role_mm(시점기준) 우선, 없으면 members 합 fallback ──
            role_mm_rows = db_query(
                lambda: supabase.table("role_mm").select("*").execute().data,
                default=[], err_label="직군 MM 조회"
            ) or []
            resolved_mm = resolve_role_mm(role_mm_rows, last_date)  # {role: mm}

            if resolved_mm:
                mm_source_label = f"직군별 MM 기준 (≤ {last_date} 최신 등록값)"
                mm_table = pd.DataFrame(
                    [{"Role": r, "MM": resolved_mm.get(r, db_role_mm_sum.get(r, 0.0))}
                     for r in ROLE_LIST]
                )
            elif db_members:
                mm_source_label = "인력 목록 MM 합계 (직군 MM 기준 미등록)"
                mm_table = pd.DataFrame(
                    [{"Role": r, "MM": db_role_mm_sum.get(r, 0.0)} for r in ROLE_LIST]
                )
            else:
                mm_source_label = "MM 정보 없음"
                mm_table = pd.DataFrame([{"Role": r, "MM": 0.0} for r in ROLE_LIST])

            # 미분류 직군 행 추가 (MM=0)
            if has_unmatched and UNMATCHED_ROLE not in mm_table["Role"].values:
                mm_table = pd.concat(
                    [mm_table, pd.DataFrame([{"Role": UNMATCHED_ROLE, "MM": 0.0}])],
                    ignore_index=True
                )

            weeks = build_weeks(first_date, last_date)          # [(주번호, s, e), ...]
            month_networkdays = max(count_working_days(first_date, last_date), 1)
            month_label = f"{first_date.month}월"

            st.caption(
                f"📆 기간: {first_date} ~ {last_date}  |  "
                f"근무일(공휴일 제외) {month_networkdays}일  |  {len(weeks)}개 주차  |  "
                f"MM 기준: {mm_source_label}"
            )

            # ── 각 인원의 월/주 실공수 계산 ──
            def _sum_range(row, s, e):
                return sum(row[c] for c, dt in date_cols.items() if s <= dt <= e)

            df_raw["월실공수"] = df_raw.apply(lambda r: _sum_range(r, first_date, last_date), axis=1)
            week_val_cols = []
            for wn, s, e in weeks:
                col = f"__W{wn}__"
                df_raw[col] = df_raw.apply(lambda r, s=s, e=e: _sum_range(r, s, e), axis=1)
                week_val_cols.append((wn, col, s, e))

            # ── 휴가(연차) 로드 → 분모 차감맵 (MM 가중, 월/주 배분) ──
            vac_data = db_query(
                lambda: supabase.table("vacations").select("*").execute().data,
                default=[], err_label="휴가 정보 조회"
            ) or []
            vac_map = compute_vacation_map(
                vac_data, clean_name, user_mm_map, first_date, last_date, weeks
            )

            # 직군별 휴가 합산 (분모 차감용)
            role_vac_month = {}
            role_vac_week = {}
            for _, r in df_raw.iterrows():
                u = r["User_clean"]
                rl = r["Role"]
                if u in vac_map and rl:
                    role_vac_month[rl] = role_vac_month.get(rl, 0.0) + vac_map[u]["month"]
                    for wn, _c, _s, _e in week_val_cols:
                        if wn in vac_map[u]:
                            role_vac_week.setdefault(rl, {}).setdefault(wn, 0.0)
                            role_vac_week[rl][wn] += vac_map[u][wn]

            # ── 직군별 집계 ──
            agg_cols = ["월실공수"] + [c for _wn, c, _s, _e in week_val_cols]
            role_sum = df_raw.groupby("Role")[agg_cols].sum().reset_index()
            report_df = pd.merge(mm_table, role_sum, on="Role", how="left").fillna(0.0)

            def get_status(rate_num, mm):
                if mm == 0:
                    return "-"
                if rate_num < 80:
                    return "여유"
                elif rate_num <= 120:
                    return "적정"
                else:
                    return "초과"

            # ── 월 목표 공수 (안 B: 8×MM×근무일 − 월휴가) & 월 가동률 ──
            def _month_target(r):
                mm = r["MM"]
                if mm <= 0:
                    return 0.0
                return max(8.0 * mm * month_networkdays - role_vac_month.get(r["Role"], 0.0), 0.0)

            report_df["월목표공수"] = report_df.apply(_month_target, axis=1)

            def _month_rate_num(r):
                if r["MM"] <= 0:
                    return 0
                den = r["월목표공수"]
                return round(r["월실공수"] / den * 100) if den > 0 else 0

            report_df["월 누적 가동률_num"] = report_df.apply(_month_rate_num, axis=1)
            report_df["월 누적 가동률(%)"] = report_df.apply(
                lambda r: f"{int(r['월 누적 가동률_num'])}%" if r["MM"] > 0 else "-", axis=1
            )

            # ── 주차별 가동률 (분모: 8×MM×그주근무일 − 그주휴가) ──
            calculated_week_cols = []
            week_meta = []  # (표시컬럼명, 값컬럼, 주번호, s, e, 근무일)
            for wn, vcol, s, e in week_val_cols:
                wd = max(count_working_days(s, e), 1)
                disp = f"{first_date.month}월 {wn}W"

                def _wrate(r, vcol=vcol, wd=wd, wn=wn):
                    mm = r["MM"]
                    if mm <= 0:
                        return "-"
                    den = 8.0 * mm * wd - role_vac_week.get(r["Role"], {}).get(wn, 0.0)
                    return f"{round(r[vcol] / den * 100)}%" if den > 0 else "-"

                report_df[disp] = report_df.apply(_wrate, axis=1)
                calculated_week_cols.append(disp)
                week_meta.append((disp, vcol, wn, s, e, wd))

            report_df["판단"] = report_df.apply(
                lambda r: get_status(r["월 누적 가동률_num"], r["MM"]), axis=1
            )

            # ── 표 구성: MM | 구분 | 월 목표공수 | 누적 실공수 | 월 가동률 | 판단 | 주차들 ──
            month_col = f"{month_label} 가동률(%)"
            report_df[month_col] = report_df["월 누적 가동률(%)"]

            final_cols = (
                ["MM", "Role", "월목표공수", "월실공수", month_col, "판단"]
                + calculated_week_cols
            )
            display_df = report_df[final_cols].copy()
            display_df.rename(columns={
                "Role": "구분",
                "월목표공수": "월 목표공수(h)",
                "월실공수": "누적 실공수(h)",
            }, inplace=True)

            # ── Total 행 ──
            total_mm = report_df["MM"].sum()
            total_actual = report_df["월실공수"].sum()
            total_target = report_df["월목표공수"].sum()
            total_month_rate = round(total_actual / total_target * 100) if total_target > 0 else 0

            total_dict = {
                "구분": "Total",
                "MM": total_mm,
                "월 목표공수(h)": round(total_target, 1),
                "누적 실공수(h)": round(total_actual, 1),
                month_col: f"{total_month_rate}%" if total_mm > 0 else "-",
            }
            for disp, vcol, wn, s, e, wd in week_meta:
                w_sum = report_df[vcol].sum()
                w_vac = sum(role_vac_week.get(rl, {}).get(wn, 0.0) for rl in role_vac_week)
                w_den = 8.0 * total_mm * wd - w_vac
                total_dict[disp] = f"{round(w_sum / w_den * 100)}%" if w_den > 0 else "-"

            total_dict["판단"] = get_status(total_month_rate, total_mm)

            total_row = pd.DataFrame([total_dict])
            final_view = pd.concat([display_df, total_row], ignore_index=True)


            st.markdown("---")
            st.subheader("📊 위클리 보고 리포트")

            st.dataframe(
                final_view.style.map(highlight_status, subset=["판단"]).format({
                    "MM": "{:.2f}",
                    "월 목표공수(h)": "{:,.1f}h",
                    "누적 실공수(h)": "{:,.1f}h"
                }),
                use_container_width=True,
                height=680
            )

            default_report_title = (
                f"{first_date.year}년 {first_date.month}월 위클리 가동률 보고서 "
                f"({len(weeks)}주차, ~{last_date.strftime('%m/%d')})"
            )
            report_name = st.text_input("보고서 저장 명칭", value=default_report_title)

            save_disabled = has_unmatched
            if has_unmatched:
                st.caption("⚠️ 미분류 인원이 있는 상태에서도 저장은 가능하지만, 가동률 정확도를 위해 먼저 인력 등록을 권장합니다.")

            if st.button("💾 이 위클리 보고서 DB에 저장하기"):
                json_data = final_view.to_json(orient="records", force_ascii=False)
                ok = db_query(
                    lambda: supabase.table("reports").insert({
                        "report_title": report_name,
                        "total_mm": float(total_mm),
                        "total_hours": float(total_actual),
                        "excel_data": json.loads(json_data)
                    }).execute(),
                    default=None, err_label="보고서 저장"
                )
                if ok is not None:
                    st.success(f"'{report_name}'가 DB에 성공적으로 저장되었습니다!")

    # =========================================================
    # 메뉴 4: 과거 보고서 조회
    # =========================================================
    elif menu == "4. 과거 보고서 저장 이력 조회":
        st.title("📂 저장된 위클리 보고서 이력 조회")
        reports_data = db_query(
            lambda: supabase.table("reports").select(
                "id, report_title, total_mm, total_hours, created_at"
            ).order("created_at", desc=True).execute().data,
            default=[], err_label="보고서 이력 조회"
        )

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
                detail_list = db_query(
                    lambda: supabase.table("reports").select("*").eq("id", selected_id).execute().data,
                    default=[], err_label="보고서 상세 조회"
                )
                if detail_list:
                    detail = detail_list[0]
                    st.subheader(f"📄 {detail['report_title']} 상세 내용")

                    df_detail = pd.DataFrame(detail["excel_data"])

                    # 옛/새 컬럼명 모두 지원 (과거 저장분 호환)
                    hours_col = None
                    for cand in ["누적 실공수(h)", "월간 누적 실공수(h)"]:
                        if cand in df_detail.columns:
                            hours_col = cand
                            break

                    if "MM" in df_detail.columns:
                        df_detail["MM"] = pd.to_numeric(df_detail["MM"], errors="coerce").fillna(0.0)
                    if hours_col:
                        df_detail[hours_col] = pd.to_numeric(
                            df_detail[hours_col], errors="coerce").fillna(0.0)

                    st_view = df_detail.style
                    if "판단" in df_detail.columns:
                        st_view = st_view.map(highlight_status, subset=["판단"])

                    format_dict = {}
                    if "MM" in df_detail.columns:
                        format_dict["MM"] = "{:.2f}"
                    if hours_col:
                        format_dict[hours_col] = "{:,.1f}h"

                    if format_dict:
                        st_view = st_view.format(format_dict)

                    st.dataframe(st_view, use_container_width=True, height=680)

                    # ── PDF 다운로드 ──
                    st.markdown("---")
                    try:
                        pdf_columns = list(df_detail.columns)
                        pdf_rows = df_detail.to_dict(orient="records")
                        # 값 문자열화 (MM/실공수 포맷 유지)
                        for r in pdf_rows:
                            for k, v in list(r.items()):
                                if k == "MM" and isinstance(v, (int, float)):
                                    r[k] = f"{v:.2f}"
                                elif hours_col and k == hours_col and isinstance(v, (int, float)):
                                    r[k] = f"{v:,.1f}h"
                                elif v is None:
                                    r[k] = ""
                                else:
                                    r[k] = str(v)

                        # 메타 구성
                        total_row_data = next(
                            (r for r in pdf_rows if r.get("구분") == "Total"), {})
                        pdf_meta = {
                            "생성일": str(detail.get("created_at", ""))[:10],
                            "총 MM": f"{detail.get('total_mm', 0):.2f}",
                            "총 실공수": f"{detail.get('total_hours', 0):,.1f}h",
                        }
                        # Total 가동률 (월 컬럼에서 추출)
                        month_col_name = next(
                            (c for c in pdf_columns if "가동률" in c and "월" in c), None)
                        if month_col_name and total_row_data:
                            pdf_meta["Total 가동률"] = total_row_data.get(month_col_name, "")

                        pdf_bytes = build_report_pdf(
                            detail["report_title"], pdf_rows, pdf_columns, pdf_meta
                        )
                        safe_name = re.sub(r"[^\w가-힣\-]", "_", detail["report_title"])
                        st.download_button(
                            "📄 PDF로 다운로드",
                            data=pdf_bytes,
                            file_name=f"{safe_name}.pdf",
                            mime="application/pdf",
                        )
                    except Exception as e:
                        st.warning(f"PDF 생성 중 문제가 발생했습니다: {e}")
        else:
            st.info("저장된 보고서가 없습니다.")
