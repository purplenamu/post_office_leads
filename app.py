import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터포털 실시간 API 연동 (자동 컬럼 매핑 탑재)")

API_URL_MAP = {
    "병원": "https://apis.data.go.kr/1741000/hospitals/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info"
}

with st.sidebar:
    st.header("🔑 API 설정 및 관할")
    user_api_key = st.text_input("공공데이터 API 인증키", type="password")
    selected_industry = st.selectbox("타깃 업종", list(API_URL_MAP.keys()))
    target_region = st.text_input("관할 시·군·구 (필터)", "")
    search_rows = st.slider("조회 건수", min_value=10, max_value=100, value=50)

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
            
        # JSON 파싱 시도
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

        # XML 파싱 시도
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

# 대소문자/언더바 무시하고 가장 적합한 컬럼을 찾는 함수
def find_matching_column(columns, candidates):
    norm_map = {str(c).lower().replace("_", ""): c for c in columns}
    for cand in candidates:
        cand_norm = cand.lower().replace("_", "")
        if cand_norm in norm_map:
            return norm_map[cand_norm]
    return None

if user_api_key:
    raw_df, err_msg = fetch_api_data(user_api_key, selected_industry, search_rows)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        df = raw_df.copy()
        
        # 1. 상호명 자동 탐색 (모든 변형 지원)
        name_col = find_matching_column(df.columns, [
            "bplcNm", "bplcnm", "entrpsNm", "entrpsnm", "yadmNm", "yadmnm", 
            "corpNm", "cmpnyNm", "instNm", "사업장명", "상호명", "병원명"
        ])
        df["사업장명"] = df[name_col] if name_col else df.iloc[:, 1]  # 못 찾으면 2번째 열 자동 배정
        
        # 2. 인허가일자 자동 탐색
        date_col = find_matching_column(df.columns, [
            "prmisnDe", "prmisnde", "apvPermYmd", "apvpermymd", "opnDe", "opnde", 
            "estbDe", "estbde", "prmDt", "인허가일자", "개설일자"
        ])
        df["인허가일자"] = df[date_col] if date_col else "-"
        
        # 3. 주소 자동 탐색 (도로명 우선, 지번 차선)
        rdn_col = find_matching_column(df.columns, [
            "siteRdnWhlAddr", "siterdnwhladdr", "rdnWhlAddr", "rdnwhladdr", 
            "rdnAddr", "도로명주소", "도로명전체주소"
        ])
        site_col = find_matching_column(df.columns, [
            "siteWhlAddr", "sitewhladdr", "whlAddr", "whladdr", 
            "addr", "locAddr", "지번주소", "소재지전체주소"
        ])
        
        if rdn_col and site_col:
            df["사업장소재지"] = df[rdn_col].fillna(df[site_col])
        elif rdn_col:
            df["사업장소재지"] = df[rdn_col]
        elif site_col:
            df["사업장소재지"] = df[site_col]
        else:
            df["사업장소재지"] = "주소 확인 필요"

        # 지역 필터링 (공백이면 전국 전체 출력)
        if target_region.strip():
            filtered_df = df[df["사업장소재지"].str.contains(target_region.strip(), na=False)].copy()
        else:
            filtered_df = df.copy()

        # 우체국 마케팅 전략 자동 부여
        filtered_df["추천 우체국 상품"] = (
            "요양급여 결제계좌 + 100% 국가보장 MMDA" if selected_industry in ["병원", "의원"] 
            else "대량 급여이체 수수료 평생면제 + 법인MMDA"
        )
        filtered_df["영업상태"] = "접촉 전"
        
        # 메인 테이블 표출
        if not filtered_df.empty:
            view_cols = ["인허가일자", "사업장명", "사업장소재지", "영업상태", "추천 우체국 상품"]
            region_title = target_region if target_region.strip() else "전국"
            st.subheader(f"📋 {region_title} {selected_industry} 명부 ({len(filtered_df)}건)")
            
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
            
            csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label="📥 엑셀(CSV) 다운로드",
                data=csv_data,
                file_name=f"우체국_{selected_industry}_{datetime.date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.warning(f"조회된 {len(df)}건 중 '{target_region}' 관내 사업장이 없습니다.")

        # 하단 실제 수신 데이터 확인창 (항목명 검증용)
        with st.expander("🔍 공공데이터 서버 실제 수신 항목명 확인 (클릭)"):
            st.write("서버에서 받은 실제 컬럼 목록:", list(raw_df.columns))
            st.dataframe(raw_df.head(3), use_container_width=True)
            
    else:
        st.warning("조회된 데이터가 없습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
