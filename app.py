import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📣우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터포털 실시간 API 연동 (부울경 권역 맞춤형)")

API_URL_MAP = {
    "병원": "https://apis.data.go.kr/1741000/hospitals/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info"
}

# 1. 사이드바 - 지역 옵션 2종으로 단일화
with st.sidebar:
    st.header("🔑 API 설정 및 영업 권역")
    user_api_key = st.text_input("공공데이터 API 인증키", type="password")
    selected_industry = st.selectbox("타깃 업종", list(API_URL_MAP.keys()))
    
    # 2가지 옵션으로 구성
    region_choice = st.selectbox(
        "조회 지역 선택",
        ["부울경 전체", "관할 시·구·군 직접 입력"]
    )
    
    custom_sub_region = ""
    if region_choice == "관할 시·구·군 직접 입력":
        custom_sub_region = st.text_input("관할 시·구·군 입력 (예: 부산 동구, 창원시, 김해시, 울산 남구)", "부산 동구")
        
    search_rows = st.slider("전국 데이터 수집 건수 (부울경 추출용)", min_value=30, max_value=200, value=100)
    st.caption("💡 전국 데이터에서 부울경 소재지를 필터링하므로, 건수를 100건 이상으로 유지하는 것을 권장합니다.")

# 2. 실시간 데이터 호출
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

# 3. 정밀 데이터 추출 함수군
def extract_clean_name(df):
    """사업장 상호명만 정확히 추출"""
    name_candidates = ["bplcnm", "entrpsnm", "yadmnm", "corpnm", "cmpnynm", "instnm", "사업장명", "상호명", "병원명"]
    norm_cols = {str(c).lower().replace("_", ""): c for c in df.columns}
    for cand in name_candidates:
        if cand in norm_cols:
            s = df[norm_cols[cand]].astype(str).str.strip().replace(["", "None", "nan", "null"], None)
            if s.dropna().shape[0] > 0:
                return s
    return df.iloc[:, 1] if df.shape[1] > 1 else df.iloc[:, 0]

def extract_valid_date(df):
    """병원 개설일자(opnDe) 및 일반 인허가일자(prmisnDe/apvPermYmd) 통합 추출"""
    date_candidates = [
        "opnde", "prmisnde", "apvpermymd", "estbde", "licpermymd", "prmdt", "crtrymde", "crtrymd"
    ]
    norm_cols = {str(c).lower().replace("_", ""): c for c in df.columns}
    valid_series = None
    
    for cand in date_candidates:
        if cand in norm_cols:
            s = df[norm_cols[cand]].astype(str).str.strip().replace(["", "None", "nan", "null"], None)
            if s.dropna().shape[0] > 0:
                valid_series = s if valid_series is None else valid_series.combine_first(s)
                
    if valid_series is not None:
        # YYYYMMDD -> YYYY-MM-DD 변환
        def format_date(v):
            if pd.isna(v) or v in ["", "None", "nan", "null", "-"]:
                return "-"
            clean_v = str(v).replace("-", "").strip()
            if len(clean_v) == 8 and clean_v.isdigit():
                return f"{clean_v[:4]}-{clean_v[4:6]}-{clean_v[6:]}"
            return str(v)
        return valid_series.apply(format_date)
        
    return pd.Series(["-"] * len(df))

def extract_clean_address(df):
    """상호명이 섞이지 않도록 순수 주소 필드만 정제 추출"""
    blacklist = ["nm", "name", "bplc", "corp", "상호", "명칭", "tel", "phone", "no", "code", "cd"]
    norm_cols = {str(c).lower().replace("_", ""): c for c in df.columns}
    
    # 1순위 도로명주소
    rdn_series = None
    for cand in ["siterdnwhladdr", "rdnwhladdr", "locplcroadnmaddr", "refineroadnmaddr", "rdnaddr"]:
        if cand in norm_cols:
            s = df[norm_cols[cand]].astype(str).str.strip().replace(["", "None", "nan", "null"], None)
            if s.dropna().shape[0] > 0:
                rdn_series = s
                break
                
    # 2순위 지번주소
    site_series = None
    for cand in ["sitewhladdr", "whladdr", "locplclotnoaddr", "refinelotnoaddr", "addr", "locplc"]:
        if cand in norm_cols:
            s = df[norm_cols[cand]].astype(str).str.strip().replace(["", "None", "nan", "null"], None)
            if s.dropna().shape[0] > 0:
                site_series = s
                break
                
    if rdn_series is not None and site_series is not None:
        combined = rdn_series.combine_first(site_series)
    elif rdn_series is not None:
        combined = rdn_series
    elif site_series is not None:
        combined = site_series
    else:
        combined = pd.Series([None] * len(df))
        
    # 예외 탐색: 순수 주소 필드가 비어있을 때만 띄어쓰기 및 번지수 패턴 검증
    if combined.isna().all():
        for col in df.columns:
            col_low = str(col).lower()
            if any(bad in col_low for bad in blacklist):
                continue
            sample = df[col].astype(str).str.strip().dropna().head(10)
            # 주소 특징 (공백 포함 및 행정구역 명칭)
            if any(" " in val and any(token in val for token in ["로", "길", "동", "읍", "면", "구", "군", "시", "도"]) for val in sample):
                combined = df[col].astype(str).str.strip().replace(["", "None", "nan", "null"], None)
                break
                
    return combined.fillna("주소 정보 없음")

# 4. 화면 표출 및 필터링
if user_api_key:
    raw_df, err_msg = fetch_api_data(user_api_key, selected_industry, search_rows)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        df = raw_df.copy()
        
        # 보정된 추출 함수 적용
        df["사업장명"] = extract_clean_name(df)
        df["인허가일자"] = extract_valid_date(df)
        df["사업장소재지"] = extract_clean_address(df)

        # 2개 옵션 필터링
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
        
        # 상단 메트릭
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{display_title} {selected_industry}", f"{len(filtered_df)} 건")
        c2.metric("중점 유치 상품", "요양급여/MMDA" if selected_industry in ["병원", "의원"] else "대량 급여이체")
        c3.metric("예치금 보호", "100% 국가 전액보장")
        
        st.divider()
        
        # 메인 테이블
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

    else:
        st.warning("조회된 데이터가 없습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
