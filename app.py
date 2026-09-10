import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

# 1. 페이지 설정
st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터포털 실시간 API 연동 (병원·의원·시설관리 5대 업종 통합)")

# 2. 검증된 5대 핵심 업종 API 엔드포인트 매핑
API_URL_MAP = {
    "병원": "https://apis.data.go.kr/1741000/hospitals/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info"
}

# 3. 사이드바 설정
with st.sidebar:
    st.header("🔑 API 설정 및 영업 관할")
    user_api_key = st.text_input(
        "공공데이터 API 인증키", 
        type="password",
        help="발급받으신 일반 인증키를 입력하세요."
    )
    
    # 5대 업종 드롭다운 선택
    selected_industry = st.selectbox("타깃 법인 업종 선택", list(API_URL_MAP.keys()))
    target_region = st.text_input("관할 시·군·구 (주소 필터)", "부산광역시 동구")
    search_rows = st.slider("가져올 데이터 건수 (서버 부하 고려 20~50건 권장)", min_value=10, max_value=100, value=30)

# 4. 공공데이터 API 실시간 호출 함수 (캐싱 및 30초 타임아웃 적용)
@st.cache_data(ttl=3600, show_spinner="공공데이터 서버에서 실시간 데이터를 수신 중입니다...")
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
            return None, f"서버 응답 오류 (HTTP {response.status_code}): {response.text[:200]}"
            
        # 1) JSON 응답 파싱
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

        # 2) XML 응답 파싱 (JSON 실패 시 대비)
        try:
            root = ET.fromstring(response.text)
            items_xml = root.findall(".//item")
            if items_xml:
                rows = []
                for item in items_xml:
                    rows.append({child.tag: child.text for child in item})
                return pd.DataFrame(rows), None
            else:
                return None, f"공공데이터 응답 에러: {response.text[:200]}"
        except ET.ParseError:
            return None, f"응답 해석 불가: {response.text[:200]}"
            
    except requests.exceptions.Timeout:
        return None, "공공데이터포털 서버 지연으로 응답 시간이 초과되었습니다. 건수를 줄여 다시 시도해주세요."
    except Exception as e:
        return None, f"네트워크 연결 실패: {str(e)}"

# 5. 메인 화면 데이터 가공 및 표출
if user_api_key:
    raw_df, err_msg = fetch_api_data(user_api_key, selected_industry, search_rows)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        # 공통 컬럼 한글 표준화 매핑
        col_map = {
            "prmisnDe": "인허가일자",
            "bplcNm": "사업장명/법인명",
            "siteRdnWhlAddr": "도로명주소",
            "siteWhlAddr": "지번주소",
            "dtlStateNm": "영업상태"
        }
        df = raw_df.rename(columns={k: v for k, v in col_map.items() if k in raw_df.columns})
        
        # 도로명/지번 주소 병합
        if "도로명주소" in df.columns and "지번주소" in df.columns:
            df["사업장소재지"] = df["도로명주소"].fillna(df["지번주소"])
        elif "도로명주소" in df.columns:
            df["사업장소재지"] = df["도로명주소"]
        else:
            df["사업장소재지"] = "-"
            
        # 관할 구역 필터링
        if target_region:
            filtered_df = df[df["사업장소재지"].str.contains(target_region, na=False)].copy()
        else:
            filtered_df = df.copy()
            
        # 업종별 맞춤형 우체국 금융 영업 전략 자동 부여
        if selected_industry in ["병원", "의원"]:
            filtered_df["추천 우체국 상품"] = "건보공단 요양급여 결제계좌 + 원금 100% 국가보장 MMDA"
        else:
            filtered_df["추천 우체국 상품"] = "근로자 대량 급여이체 수수료 평생면제 + 법인MMDA"
            
        filtered_df["영업상태"] = "접촉 전"
        
        # 표출용 컬럼 선별
        display_cols = [c for c in ["인허가일자", "사업장명/법인명", "사업장소재지", "영업상태", "추천 우체국 상품"] if c in filtered_df.columns]
        display_df = filtered_df[display_cols]
        
        # 요약 메트릭 카드
        c1, c2, c3 = st.columns(3)
        c1.metric(f"관내 {selected_industry} 발굴", f"{len(display_df)} 개소")
        c2.metric("중점 유치 대상", "요양급여 계좌" if selected_industry in ["병원", "의원"] else "대량 급여이체 계좌")
        c3.metric("자금 안정성", "100% 국가 전액보장")
        
        st.divider()
        
        st.subheader(f"📋 {target_region} {selected_industry} 인허가 리스트")
        
        # 영업 단계 수정 테이블
        edited_df = st.data_editor(
            display_df,
            column_config={
                "영업상태": st.column_config.SelectboxColumn(
                    "진행 단계",
                    options=["접촉 전", "방문 예정", "상담 진행중", "계좌 개설 완료", "보류"],
                    required=True
                )
            },
            disabled=["인허가일자", "사업장명/법인명", "사업장소재지", "추천 우체국 상품"],
            hide_index=True,
            use_container_width=True
        )
        
        # 외근용 엑셀 다운로드
        csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label=f"📥 {selected_industry} 영업 리스트 엑셀(CSV) 다운로드",
            data=csv_data,
            file_name=f"우체국_B2B_{selected_industry}_{target_region}_{datetime.date.today()}.csv",
            mime="text/csv"
        )
    else:
        st.warning(f"최근 데이터 중 '{target_region}' 관내에 해당하는 {selected_industry} 사업장이 없습니다. 슬라이더로 조회 건수를 늘려보세요.")
else:
    st.info("👈 왼쪽 사이드바에 API 인증키를 입력하고 원하는 업종을 선택하세요.")
