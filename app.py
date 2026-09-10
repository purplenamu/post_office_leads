import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미 (부울경)", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터포털 실시간 API 연동 (부산·울산·경남 전용 권역 필터 탑재)")

API_URL_MAP = {
    "병원": "https://apis.data.go.kr/1741000/hospitals/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info"
}

# 1. 사이드바 - 부울경 권역 선택
with st.sidebar:
    st.header("🔑 API 설정 및 영업 권역")
    user_api_key = st.text_input("공공데이터 API 인증키", type="password")
    selected_industry = st.selectbox("타깃 업종", list(API_URL_MAP.keys()))
    
    # 부울경 전용 권역 셀렉트박스
    region_choice = st.selectbox(
        "조회 지역 선택",
        ["부울경 전체 (부산·울산·경남)", "부산광역시", "울산광역시", "경상남도", "관할 구·군 직접 입력"]
    )
    
    custom_sub_region = ""
    if region_choice == "관할 구·군 직접 입력":
        custom_sub_region = st.text_input("상세 지역 입력 (예: 부산 동구, 김해, 창원)", "부산 동구")
        
    search_rows = st.slider("전국 데이터 수집 건수 (부울경 추출용)", min_value=30, max_value=200, value=100)
    st.caption("💡 전국 API에서 데이터를 가져와 부울경 소재지를 필터링하므로, 건수를 100건 이상으로 설정하는 것이 좋습니다.")

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

def find_matching_column(columns, candidates):
    norm_map = {str(c).lower().replace("_", ""): c for c in columns}
    for cand in candidates:
        cand_norm = cand.lower().replace("_", "")
        if cand_norm in norm_map:
            return norm_map[cand_norm]
    return None

def extract_smart_address(df):
    provinces = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
    
    rdn_col = find_matching_column(df.columns, [
        "siteRdnWhlAddr", "rdnWhlAddr", "rdnAddr", "locplcRoadnmAddr", "refineRoadnmAddr"
    ])
    site_col = find_matching_column(df.columns, [
        "siteWhlAddr", "whlAddr", "locplcLotnoAddr", "refineLotnoAddr", "addr"
    ])
    
    s_rdn = df[rdn_col].astype(str).str.strip().replace(["", "None", "nan", "null"], None) if rdn_col else pd.Series([None]*len(df))
    s_site = df[site_col].astype(str).str.strip().replace(["", "None", "nan", "null"], None) if site_col else pd.Series([None]*len(df))
    
    combined = s_rdn.combine_first(s_site)
    
    if combined.isna().all() or (combined == "").all():
        for col in df.columns:
            sample_vals = df[col].astype(str).head(10)
            if any(any(p in str(val) for p in provinces) for val in sample_vals):
                combined = df[col].astype(str).str.strip().replace(["", "None", "nan", "null"], None)
                break
                
    return combined.fillna("주소 정보 없음")

# 3. 화면 표출 및 부울경 필터링
if user_api_key:
    raw_df, err_msg = fetch_api_data(user_api_key, selected_industry, search_rows)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        df = raw_df.copy()
        
        name_col = find_matching_column(df.columns, [
            "bplcNm", "bplcnm", "entrpsNm", "entrpsnm", "yadmNm", "yadmnm", 
            "corpNm", "cmpnyNm", "instNm", "사업장명", "상호명"
        ])
        df["사업장명"] = df[name_col] if name_col else df.iloc[:, 1]
        
        date_col = find_matching_column(df.columns, [
            "prmisnDe", "prmisnde", "apvPermYmd", "apvpermymd", "opnDe", "opnde", 
            "estbDe", "estbde", "prmDt"
        ])
        df["인허가일자"] = df[date_col] if date_col else "-"
        
        df["사업장소재지"] = extract_smart_address(df)

        # 부울경 전용 필터링 로직
        if region_choice == "부울경 전체 (부산·울산·경남)":
            pattern = "부산|울산|경남|경상남도"
            filtered_df = df[df["사업장소재지"].str.contains(pattern, na=False)].copy()
        elif region_choice == "부산광역시":
            filtered_df = df[df["사업장소재지"].str.contains("부산", na=False)].copy()
        elif region_choice == "울산광역시":
            filtered_df = df[df["사업장소재지"].str.contains("울산", na=False)].copy()
        elif region_choice == "경상남도":
            filtered_df = df[df["사업장소재지"].str.contains("경남|경상남도", na=False)].copy()
        else:
            # 직접 입력
            if custom_sub_region.strip():
                filtered_df = df[df["사업장소재지"].str.contains(custom_sub_region.strip(), na=False)].copy()
            else:
                filtered_df = df.copy()

        # 우체국 마케팅 전략 자동 배정
        filtered_df["추천 우체국 상품"] = (
            "요양급여 결제계좌 + 100% 국가보장 MMDA" if selected_industry in ["병원", "의원"] 
            else "대량 급여이체 수수료 평생면제 + 법인MMDA"
        )
        filtered_df["영업상태"] = "접촉 전"
        
        # 메트릭 요약
        display_region_name = custom_sub_region if region_choice == "관할 구·군 직접 입력" else region_choice.split(" ")[0]
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{display_region_name} {selected_industry}", f"{len(filtered_df)} 건")
        c2.metric("중점 유치 상품", "요양급여/MMDA" if selected_industry in ["병원", "의원"] else "대량 급여이체")
        c3.metric("예치금 보호", "100% 국가 전액보장")
        
        st.divider()
        
        # 테이블 출력
        if not filtered_df.empty:
            view_cols = ["인허가일자", "사업장명", "사업장소재지", "영업상태", "추천 우체국 상품"]
            st.subheader(f"📋 {display_region_name} {selected_industry} 인허가 명부 ({len(filtered_df)}건)")
            
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
                label=f"📥 {display_region_name} {selected_industry} 엑셀(CSV) 다운로드",
                data=csv_data,
                file_name=f"우체국_{selected_industry}_{display_region_name}_{datetime.date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.warning(f"수집된 전국 {len(df)}건 중 '{display_region_name}' 소재 사업장이 없습니다.")
            st.info("💡 사이드바에서 **[전국 데이터 수집 건수]** 슬라이더를 150~200건으로 늘려보세요.")

    else:
        st.warning("조회된 데이터가 없습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
