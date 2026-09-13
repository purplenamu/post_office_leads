import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터포털 실시간 API 연동 (자동 다중 페이지 일괄 수집)")

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
        ["관할 시·구·군 직접 입력", "부울경 전체"]
    )
    
    custom_sub_region = ""
    if region_choice == "관할 시·구·군 직접 입력":
        custom_sub_region = st.text_input("관할 시·구·군 입력", "부산 사상")
        
    st.divider()
    st.subheader("🚀 일괄 자동 수집 설정")
    # 여러 페이지를 한 번에 순회
    page_range = st.slider("자동 스캔할 페이지 수", min_value=1, max_value=10, value=5, 
                           help="5페이지 설정 시 1페이지부터 5페이지까지 자동으로 연속 조회해 관내 데이터를 모두 합칩니다.")
    rows_per_page = st.selectbox("페이지당 수집량", [300, 500, 1000], index=1)

# 단일 페이지 호출 함수
def fetch_single_page(api_key, target_url, num_rows, page):
    params = {
        "serviceKey": api_key,
        "pageNo": str(page),
        "numOfRows": str(num_rows),
        "resultType": "json"
    }
    try:
        response = requests.get(target_url, params=params, timeout=(10, 30))
        if response.status_code != 200:
            return None
            
        try:
            data_json = response.json()
            items = data_json.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            if items:
                return pd.DataFrame(items)
        except Exception:
            pass

        try:
            root = ET.fromstring(response.text)
            items_xml = root.findall(".//item")
            if items_xml:
                rows = [{child.tag: child.text for child in item} for item in items_xml]
                return pd.DataFrame(rows)
        except Exception:
            pass
            
    except Exception:
        return None
    return None

# 2. 다중 페이지 연속 자동 수집 함수 (캐싱 적용)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_pages_data(api_key, industry_name, rows_per_p, total_pages):
    if not api_key:
        return None, "사이드바에 API 인증키를 입력해주세요."
    
    clean_key = urllib.parse.unquote(api_key.strip())
    target_url = API_URL_MAP[industry_name]
    
    all_dfs = []
    progress_bar = st.progress(0, text="전국 데이터 자동 순회 수집 중...")
    
    for p in range(1, total_pages + 1):
        progress_bar.progress(p / total_pages, text=f"전국 데이터 {p}/{total_pages} 페이지 자동 수집 중...")
        page_df = fetch_single_page(clean_key, target_url, rows_per_p, p)
        if page_df is not None and not page_df.empty:
            all_dfs.append(page_df)
            
    progress_bar.empty()
    
    if all_dfs:
        combined_df = pd.concat(all_dfs, ignore_index=True)
        # 중복 데이터 제거
        dup_col = next((c for c in ["MNG_NO", "mng_no", "OPN_ATMY_GRP_CD"] if c in combined_df.columns), None)
        if dup_col:
            combined_df = combined_df.drop_duplicates(subset=[dup_col])
        return combined_df, None
    else:
        return None, "데이터 수신에 실패했습니다. 인증키를 확인해주세요."

# 3. 실데이터 기반 정밀 컬럼 추출 함수
def parse_verified_data(df):
    norm_cols = {str(c).upper().replace("_", ""): c for c in df.columns}
    
    # 1) 사업장 상호명
    col_name = norm_cols.get("BPLCNM", df.columns[0])
    name_series = df[col_name].astype(str).str.strip().replace(["", "None", "nan", "null"], "상호 미확인")

    # 2) 인허가일자
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

    # 3) 사업장소재지
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

    # 4) 종업원수/의료인수
    col_emp = norm_cols.get("HCWKRCNT", None)
    if col_emp:
        emp_series = pd.to_numeric(df[col_emp], errors="coerce").fillna(0).astype(int)
    else:
        emp_series = pd.Series([0] * len(df))

    # 5) 전화번호
    col_tel = norm_cols.get("TELNO", None)
    if col_tel:
        tel_series = df[col_tel].astype(str).str.strip().replace(["", "None", "nan", "null"], "-")
    else:
        tel_series = pd.Series(["-"] * len(df))

    return name_series, date_series, addr_series, emp_series, tel_series

# 4. 화면 표출 및 필터링
if user_api_key:
    raw_df, err_msg = fetch_all_pages_data(user_api_key, selected_industry, rows_per_page, page_range)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        df = raw_df.copy()
        
        (
            df["사업장명"], 
            df["인허가일자"], 
            df["사업장소재지"], 
            df["종업원(의료인)수"], 
            df["전화번호"]
        ) = parse_verified_data(df)

        # 권역 필터링
        if region_choice == "부울경 전체":
            pattern = "부산|울산|경남|경상남도"
            filtered_df = df[df["사업장소재지"].str.contains(pattern, na=False)].copy()
            display_title = "부울경 전체"
        else:
            if custom_sub_region.strip():
                keywords = custom_sub_region.strip().split()
                cond = df["사업장소재지"].apply(lambda addr: all(k in str(addr) for k in keywords))
                filtered_df = df[cond].copy()
                display_title = custom_sub_region.strip()
            else:
                filtered_df = df.copy()
                display_title = "전체"

        # 우체국 마케팅 전략 자동 배정
        if selected_industry in ["병원", "의원"]:
            filtered_df["추천 우체국 상품"] = "요양급여 결제계좌 + 100% 국가보장 MMDA"
        else:
            filtered_df["추천 우체국 상품"] = "대량 급여이체 수수료 평생면제 + 법인MMDA"
            
        filtered_df["영업상태"] = "접촉 전"
        
        # 상단 요약 카드
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{display_title} 총 발굴", f"{len(filtered_df)} 건")
        total_emp = filtered_df["종업원(의료인)수"].sum() if not filtered_df.empty else 0
        c2.metric("잠재 급여이체 대상", f"{total_emp:,} 명")
        c3.metric("중점 유치 상품", "요양급여/MMDA" if selected_industry in ["병원", "의원"] else "급여이체")
        c4.metric("전국 수집 총 모수", f"{len(df):,} 건")
        
        st.divider()
        
        # 메인 테이블 표출
        if not filtered_df.empty:
            view_cols = [
                "인허가일자", "사업장명", "종업원(의료인)수", "전화번호", "사업장소재지", "영업상태", "추천 우체국 상품"
            ]
            st.subheader(f"📋 {display_title} {selected_industry} 일괄 명부 ({len(filtered_df)}건 확보)")
            
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
            
            # 엑셀 다운로드
            csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label=f"📥 {display_title} {selected_industry} 전체 통합 리스트(CSV) 다운로드",
                data=csv_data,
                file_name=f"우체국_B2B_{selected_industry}_{display_title}_통합_{datetime.date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.warning(f"전국 {len(df):,}건 데이터 중 '{display_title}' 소재 사업장이 없습니다.")
            st.info("💡 사이드바의 **[자동 스캔할 페이지 수]**를 7~10페이지로 늘려보세요.")

    else:
        st.warning("조회된 데이터가 없습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
