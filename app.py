import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터포털 실시간 API 연동 (부울경 권역 맞춤형)")

API_URL_MAP = {
    "병원": "https://apis.data.go.kr/1741000/hospitals/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info"
}

# 1. 사이드바 - 지역 옵션 2종 구성
with st.sidebar:
    st.header("🔑 API 설정 및 영업 권역")
    user_api_key = st.text_input("공공데이터 API 인증키", type="password")
    selected_industry = st.selectbox("타깃 업종", list(API_URL_MAP.keys()))
    
    # 2가지 옵션으로 축소
    region_choice = st.selectbox(
        "조회 지역 선택",
        ["부울경 전체", "관할 시·구·군 직접 입력"]
    )
    
    custom_sub_region = ""
    if region_choice == "관할 시·구·군 직접 입력":
        custom_sub_region = st.text_input("관할 시·구·군 입력 (예: 부산 동구, 김해시, 울산 남구)", "부산 동구")
        
    search_rows = st.slider("전국 데이터 수집 건수 (부울경 추출용)", min_value=30, max_value=200, value=100)
    st.caption("💡 전국 데이터에서 부울경 소재지를 필터링하므로, 100건 이상 조회를 권장합니다.")

# 2. 실시간 데이터 수신
@st.cache_data(ttl=3600, show_spinner="공공데이터 서버에서 데이터를 조회하는 중입니다...")
def fetch_api_data(api_key, industry_name, num_rows):
    if not api_key:
        return None, "사이드바에 API 인증키를 입력해주세요."
    
    clean_key = urllib.parse.unquote(api_key.strip())
    target_url = API_URL_MAP[industry_name]
    
    params = {
        "serviceKey": clean_key,
        "pageNo": "1",
        "numOfRows": str(num_rows),
        "resultType": "json"
    }
    
    try:
        response = requests.get(target_url, params=params, timeout=(10, 30))
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

# 3. 정밀 데이터 정제 함수 (상호명-주소 역전 방지)
def parse_lead_columns(df):
    norm_cols = {str(c).lower().replace("_", ""): c for c in df.columns}
    
    # 1) 사업장 상호명 추출
    name_cands = [
        "사업장명", "상호명", "상호", "병원명", "의원명", "업체명", "기관명", "시설명", "법인명",
        "bplcnm", "entrpsnm", "yadmnm", "corpnm", "cmpnynm", "instnm", "facltnm", "bsnnm"
    ]
    name_col = None
    for cand in name_cands:
        c_norm = cand.lower().replace("_", "")
        if c_norm in norm_cols:
            name_col = norm_cols[c_norm]
            break
    if not name_col:
        name_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    name_series = df[name_col].astype(str).str.strip().replace(["", "None", "nan", "null"], "상호 미확인")

    # 2) 인허가/개설일자 추출 (YYYY-MM-DD 표준화)
    date_cands = [
        "개설일자", "인허가일자", "허가일자", "신고일자", "등록일자", "설립일자", "데이터기준일자", "최종수정시점",
        "opnde", "prmisnde", "apvpermymd", "estbde", "licpermymd", "prmdt", "crtrymde", "crtrymd", "permde", "lastmodts"
    ]
    date_col = None
    for cand in date_cands:
        c_norm = cand.lower().replace("_", "")
        if c_norm in norm_cols:
            date_col = norm_cols[c_norm]
            break
            
    if date_col:
        def fmt_date(v):
            if pd.isna(v) or str(v).strip() in ["", "None", "nan", "null", "-"]:
                return "-"
            cv = str(v).replace("-", "").replace(".", "").strip()
            if len(cv) >= 8 and cv[:8].isdigit():
                return f"{cv[:4]}-{cv[4:6]}-{cv[6:8]}"
            return str(v)[:10]
        date_series = df[date_col].apply(fmt_date)
    else:
        date_series = pd.Series(["-"] * len(df))

    # 3) 사업장소재지 추출 (한글명 및 행안부 표준 rdnmadr/lnmadr 지원, 상호명 컬럼 완전 배제)
    rdn_cands = [
        "도로명전체주소", "도로명주소", "소재지도로명주소", "사업장도로명주소", "도로명",
        "rdnmadr", "rdnmadres", "rnadres", "rdnwhladdr", "siterdnwhladdr", "locplcroadnmaddr", "refineroadnmaddr", "roadnmaddr"
    ]
    site_cands = [
        "소재지전체주소", "소재지주소", "소재지지번주소", "사업장소재지", "소재지", "지번주소", "주소",
        "lnmadr", "lnmadres", "adres", "sitewhladdr", "whladdr", "locplclotnoaddr", "refinelotnoaddr", "addr", "locplc"
    ]
    
    found_rdn = next((norm_cols[c.lower().replace("_", "")] for c in rdn_cands if c.lower().replace("_", "") in norm_cols), None)
    found_site = next((norm_cols[c.lower().replace("_", "")] for c in site_cands if c.lower().replace("_", "") in norm_cols), None)
    
    s_rdn = df[found_rdn].astype(str).str.strip() if found_rdn else None
    s_site = df[found_site].astype(str).str.strip() if found_site else None
    
    addr_series = None
    if s_rdn is not None and s_site is not None:
        s_rdn_c = s_rdn.replace(["", "None", "nan", "null", "-"], None)
        s_site_c = s_site.replace(["", "None", "nan", "null", "-"], None)
        addr_series = s_rdn_c.combine_first(s_site_c)
    elif s_rdn is not None:
        addr_series = s_rdn.replace(["", "None", "nan", "null", "-"], None)
    elif s_site is not None:
        addr_series = s_site.replace(["", "None", "nan", "null", "-"], None)
        
    # 후보 컬럼 누락 시 백업 감지 (상호명/날짜 컬럼 제외, 행정구역 패턴 2회 이상 일치 필수)
    if addr_series is None or addr_series.isna().all() or (addr_series == "").all():
        provinces = ["부산", "울산", "경남", "경상남도", "서울", "경기", "대구", "인천", "광주", "대전", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "제주"]
        for col in df.columns:
            if col == name_col or col == date_col:
                continue
            sample = df[col].astype(str).str.strip().dropna().head(10)
            hit = sum(1 for val in sample if any(p in val for p in provinces) and any(t in val for t in ["로", "길", "동", "읍", "면", "구", "군", "시"]))
            if hit >= 2:
                addr_series = df[col].astype(str).str.strip().replace(["", "None", "nan", "null", "-"], None)
                break

    if addr_series is None:
        addr_series = pd.Series(["주소 정보 없음"] * len(df))
    else:
        addr_series = addr_series.fillna("주소 정보 없음")

    return name_series, date_series, addr_series

# 4. 화면 표출 및 권역 필터
if user_api_key:
    raw_df, err_msg = fetch_api_data(user_api_key, selected_industry, search_rows)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        df = raw_df.copy()
        
        # 정제된 3대 핵심 정보 매핑
        df["사업장명"], df["인허가일자"], df["사업장소재지"] = parse_lead_columns(df)

        # 2대 권역 필터링
        if region_choice == "부울경 전체":
            pattern = "부산|울산|경남|경상남도"
            filtered_df = df[df["사업장소재지"].str.contains(pattern, na=False)].copy()
            display_title = "부울경 전체"
        else:
            if custom_sub_region.strip():
                filtered_df = df[df["사업장소재지"].str.contains(custom_sub_region.strip(), na=False)].copy()
                display_title = custom_sub_region.strip()
            else:
                filtered_df = df.copy()
                display_title = "전체"

        # 우체국 마케팅 전략 자동 부여
        filtered_df["추천 우체국 상품"] = (
            "요양급여 결제계좌 + 100% 국가보장 MMDA" if selected_industry in ["병원", "의원"] 
            else "대량 급여이체 수수료 평생면제 + 법인MMDA"
        )
        filtered_df["영업상태"] = "접촉 전"
        
        # 메트릭 표시
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{display_title} {selected_industry}", f"{len(filtered_df)} 건")
        c2.metric("중점 유치 상품", "요양급여/MMDA" if selected_industry in ["병원", "의원"] else "대량 급여이체")
        c3.metric("예치금 보호", "100% 국가 전액보장")
        
        st.divider()
        
        # 메인 데이터 테이블
        if not filtered_df.empty:
            view_cols = ["인허가일자", "사업장명", "사업장소재지", "영업상태", "추천 우체국 상품"]
            st.subheader(f"📋 {display_title} {selected_industry} 인허가 명부 ({len(filtered_df)}건)")
            
            edited_df = st.data_editor(
                filtered_df[view_cols],
                column_config={
                    "영업상태": st.column_config.SelectboxColumn(
                        "진행 단계",
                        options=["접촉 전", "방문 예정", "상담 진행중", "계좌 개설 완료", "보류"],
                        required=True
                    )
                },
                disabled=["인허가일자", "사업장명", "사업장소재지", "추천 우체국 상품"],
                hide_index=True,
                use_container_width=True
            )
            
            # 엑셀 다운로드
            csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label=f"📥 {display_title} {selected_industry} 엑셀(CSV) 다운로드",
                data=csv_data,
                file_name=f"우체국_{selected_industry}_{display_title}_{datetime.date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.warning(f"수집된 전국 {len(df)}건 중 '{display_title}' 소재 사업장이 없습니다.")
            st.info("💡 사이드바의 **[전국 데이터 수집 건수]**를 150~200건으로 늘려보세요.")

        # 디버깅 및 컬럼 검증용 원본 뷰어
        with st.expander("🔍 공공데이터 서버 실제 수신 항목 확인 (검증용)"):
            st.write("실제 수신된 컬럼 목록:", list(raw_df.columns))
            st.dataframe(raw_df.head(2), use_container_width=True)

    else:
        st.warning("조회된 데이터가 없습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
