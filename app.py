import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터포털 실시간 API 연동 (종업원수·전화번호 탑재)")

API_URL_MAP = {
    "병원": "https://apis.data.go.kr/1741000/hospitals/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info"
}

# 1. 사이드바 설정
with st.sidebar:
    st.header("🔑 API 설정 및 영업 권역")
    user_api_key = st.text_input("공공데이터 API 인증키", type="password")
    selected_industry = st.selectbox("타깃 업종", list(API_URL_MAP.keys()))
    
    region_choice = st.selectbox(
        "조회 지역 선택",
        ["부울경 전체", "관할 시·구·군 직접 입력"]
    )
    
    custom_sub_region = ""
    if region_choice == "관할 시·구·군 직접 입력":
        custom_sub_region = st.text_input("관할 시·구·군 입력 (예: 부산 사상, 김해, 창원)", "부산 사상")
        
    st.divider()
    st.subheader("📄 데이터 수집 범위 설정")
    # 부산 도달을 위해 300~1000건 지원
    search_rows = st.select_slider(
        "1회 수집 건수",
        options=[100, 300, 500, 800, 1000],
        value=500,
        help="부산/경남 데이터에 도달하려면 최소 500건 이상 조회를 권장합니다."
    )
    page_num = st.number_input("조회 페이지 번호", min_value=1, max_value=50, value=1)

# 2. 실시간 데이터 호출
@st.cache_data(ttl=3600, show_spinner="공공데이터 서버에서 실시간 데이터를 수신 중입니다...")
def fetch_api_data(api_key, industry_name, num_rows, page):
    if not api_key:
        return None, "사이드바에 API 인증키를 입력해주세요."
    
    clean_key = urllib.parse.unquote(api_key.strip())
    target_url = API_URL_MAP[industry_name]
    
    params = {
        "serviceKey": clean_key,
        "pageNo": str(page),
        "numOfRows": str(num_rows),
        "resultType": "json"
    }
    
    try:
        response = requests.get(target_url, params=params, timeout=(10, 40))
        if response.status_code != 200:
            return None, f"서버 오류 (HTTP {response.status_code}): {response.text[:200]}"
            
        try:
            data_json = response.json()
            body = data_json.get("response", {}).get("body", {})
            items = body.get("items", {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            if items:
                return pd.DataFrame(items), None
        except Exception:
            pass

        try:
            root = ET.fromstring(response.text)
            items_xml = root.findall(".//item")
            if items_xml:
                rows = [{child.tag: child.text for child in item} for item in items_xml]
                return pd.DataFrame(rows), None
            else:
                return None, f"공공데이터 응답 메시지: {response.text[:250]}"
        except ET.ParseError:
            return None, f"응답 해석 불가: {response.text[:200]}"
            
    except Exception as e:
        return None, f"연결 실패: {str(e)}"

# 3. 실데이터 기반 정밀 컬럼 추출 함수
def parse_verified_data(df):
    norm_cols = {str(c).upper().replace("_", ""): c for c in df.columns}
    
    # 1) 사업장 상호명 (BPLC_NM 우선)
    col_name = norm_cols.get("BPLCNM", df.columns[0])
    name_series = df[col_name].astype(str).str.strip().replace(["", "None", "nan", "null"], "상호 미확인")

    # 2) 인허가일자 (LCPMT_YMD -> YYYY-MM-DD 변환)
    col_date = norm_cols.get("LCPMTYMD", norm_cols.get("PRMISNDE", None))
    if col_date:
        def fmt_date(v):
            if pd.isna(v) or str(v).strip() in ["", "None", "nan", "null", "-"]:
                return "-"
            cv = str(v).replace("-", "").replace(".", "").strip()
            if len(cv) >= 8 and cv[:8].isdigit():
                return f"{cv[:4]}-{cv[4:6]}-{cv[6:8]}"
            return str(v)[:10]
        date_series = df[col_date].apply(fmt_date)
    else:
        date_series = pd.Series(["-"] * len(df))

    # 3) 사업장소재지 (ROAD_NM_ADDR 우선, 없으면 LOTNO_ADDR)
    col_road = norm_cols.get("ROADNMADDR", None)
    col_lot = norm_cols.get("LOTNOADDR", None)
    
    s_road = df[col_road].astype(str).str.strip().replace(["", "None", "nan", "null", "-"], None) if col_road else None
    s_lot = df[col_lot].astype(str).str.strip().replace(["", "None", "nan", "null", "-"], None) if col_lot else None
    
    if s_road is not None and s_lot is not None:
        addr_series = s_road.combine_first(s_lot)
    elif s_road is not None:
        addr_series = s_road
    elif s_lot is not None:
        addr_series = s_lot
    else:
        addr_series = pd.Series(["주소 정보 없음"] * len(df))
    addr_series = addr_series.fillna("주소 정보 없음")

    # 4) 종업원수/의료인수 (HCWKR_CNT)
    col_emp = norm_cols.get("HCWKRCNT", None)
    if col_emp:
        emp_series = pd.to_numeric(df[col_emp], errors="coerce").fillna(0).astype(int)
    else:
        emp_series = pd.Series([0] * len(df))

    # 5) 전화번호 (TELNO)
    col_tel = norm_cols.get("TELNO", None)
    if col_tel:
        tel_series = df[col_tel].astype(str).str.strip().replace(["", "None", "nan", "null"], "-")
    else:
        tel_series = pd.Series(["-"] * len(df))

    # 6) 병상수 (SCKBD_CNT)
    col_bed = norm_cols.get("SCKBDCNT", None)
    if col_bed:
        bed_series = pd.to_numeric(df[col_bed], errors="coerce").fillna(0).astype(int)
    else:
        bed_series = pd.Series([0] * len(df))

    return name_series, date_series, addr_series, emp_series, tel_series, bed_series

# 4. 화면 표출 및 필터링
if user_api_key:
    raw_df, err_msg = fetch_api_data(user_api_key, selected_industry, search_rows, page_num)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        df = raw_df.copy()
        
        # 검증된 컬럼 매핑 반영
        (
            df["사업장명"], 
            df["인허가일자"], 
            df["사업장소재지"], 
            df["종업원(의료인)수"], 
            df["전화번호"], 
            df["병상수"]
        ) = parse_verified_data(df)

        # 다중 단어 스마트 검색 (예: '부산 사상' 입력 시 둘 다 포함된 주소 추출)
        if region_choice == "부울경 전체":
            pattern = "부산|울산|경남|경상남도"
            filtered_df = df[df["사업장소재지"].str.contains(pattern, na=False)].copy()
            display_title = "부울경 전체"
        else:
            if custom_sub_region.strip():
                keywords = custom_sub_region.strip().split()
                # 모든 검색 키워드가 주소에 포함되어 있는지 검사
                cond = df["사업장소재지"].apply(lambda addr: all(k in str(addr) for k in keywords))
                filtered_df = df[cond].copy()
                display_title = custom_sub_region.strip()
            else:
                filtered_df = df.copy()
                display_title = "전체"

        # 우체국 마케팅 전략 자동 부여
        if selected_industry in ["병원", "의원"]:
            filtered_df["추천 우체국 상품"] = "요양급여 결제계좌 + 100% 국가보장 MMDA"
        else:
            filtered_df["추천 우체국 상품"] = "대량 급여이체 수수료 평생면제 + 법인MMDA"
            
        filtered_df["영업상태"] = "접촉 전"
        
        # 상단 핵심 메트릭
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{display_title} 발굴", f"{len(filtered_df)} 건")
        total_emp = filtered_df["종업원(의료인)수"].sum() if not filtered_df.empty else 0
        c2.metric("잠재 급여이체 대상", f"{total_emp:,} 명")
        c3.metric("중점 유치 상품", "요양급여/MMDA" if selected_industry in ["병원", "의원"] else "급여이체")
        c4.metric("예치금 안전성", "100% 국가 전액보장")
        
        st.divider()
        
        # 메인 테이블
        if not filtered_df.empty:
            view_cols = [
                "인허가일자", "사업장명", "종업원(의료인)수", "전화번호", "사업장소재지", "영업상태", "추천 우체국 상품"
            ]
            st.subheader(f"📋 {display_title} {selected_industry} 명부 ({len(filtered_df)}건 발굴)")
            
            edited_df = st.data_editor(
                filtered_df[view_cols],
                column_config={
                    "종업원(의료인)수": st.column_config.NumberColumn("종업원(의료인)수", format="%d명"),
                    "영업상태": st.column_config.SelectboxColumn(
                        "진행 단계",
                        options=["접촉 전", "전화(TM) 완료", "방문 예정", "상담 진행중", "계좌 개설 완료", "보류"],
                        required=True
                    )
                },
                disabled=["인허가일자", "사업장명", "종업원(의료인)수", "전화번호", "사업장소재지", "추천 우체국 상품"],
                hide_index=True,
                use_container_width=True
            )
            
            # 엑셀 다운로드 (전화번호, 종업원수 포함)
            csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label=f"📥 {display_title} {selected_industry} TM/방문 영업 리스트(CSV) 다운로드",
                data=csv_data,
                file_name=f"우체국_B2B_{selected_industry}_{display_title}_{datetime.date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.warning(f"수집된 전국 {len(df)}건 중 '{display_title}' 소재 사업장이 없습니다.")
            st.info("💡 **해결 팁:** 1) 사이드바의 **[1회 수집 건수]**를 500~1000건으로 올리거나, 2) **[조회 페이지 번호]**를 2 또는 3으로 변경해 보세요. (의원, 소독업은 모수가 많아 바로 검색됩니다.)")

    else:
        st.warning("조회된 데이터가 없습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
