import streamlit as st
import pandas as pd
import requests
import datetime
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("행정안전부 지방행정인허가 실시간 API 연동 시스템")

# 1. B2B 9대 업종별 공공데이터 엔드포인트 URL 매핑
API_URL_MAP = {
    # [의료·보건]
    "의료법인": "http://apis.data.go.kr/1741000/MedicalInstitutionService/getMedicalCorporationList",
    "병원": "http://apis.data.go.kr/1741000/MedicalInstitutionService/getHospitalList",
    "의원": "http://apis.data.go.kr/1741000/MedicalInstitutionService/getClinicList",
    # [시설·용역]
    "건물위생관리업": "http://apis.data.go.kr/1741000/BuildingSanitationService/getBuildingSanitationList",
    "승강기유지관리업체": "http://apis.data.go.kr/1741000/ElevatorMaintenanceService/getElevatorMaintenanceList",
    "소독업": "http://apis.data.go.kr/1741000/DisinfectionService/getDisinfectionList",
    # [제조·환경]
    "식품제조가공업": "http://apis.data.go.kr/1741000/FoodManufactureService/getFoodManufactureList",
    "환경전문공사업": "http://apis.data.go.kr/1741000/EnvironmentalBusinessService/getEnvironmentalBusinessList",
    "건설폐기물처리업": "http://apis.data.go.kr/1741000/ConstructionWasteService/getConstructionWasteList"
}

# 2. 사이드바 설정
with st.sidebar:
    st.header("🔑 API 설정 및 관할 선택")
    user_api_key = st.text_input(
        "공공데이터포털 일반 인증키 (Decoding)", 
        type="password",
        help="공공데이터포털 마이페이지의 개발계정 일반인증키(Decoding)를 붙여넣으세요."
    )
    
    selected_industry = st.selectbox("타깃 법인 업종 (9종)", list(API_URL_MAP.keys()))
    target_region = st.text_input("관할 시·군·구 (필터용)", "부산광역시 동구")
    search_rows = st.slider("조회 건수 (최신순)", min_value=10, max_value=100, value=30)

# 3. 공공데이터 API 실제 호출 함수
def fetch_localdata_api(api_key, industry, num_rows):
    if not api_key:
        return None, "사이드바에 공공데이터포털 인증키를 입력해주세요."
    
    url = API_URL_MAP.get(industry)
    params = {
        "serviceKey": api_key,
        "pageNo": "1",
        "numOfRows": str(num_rows),
        "resultType": "json"  # 기본 JSON 요청
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        
        # 1) JSON 응답 파싱 시도
        try:
            data_json = response.json()
            # 표준 공공데이터 JSON 구조 파싱
            items = data_json.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if items:
                df = pd.DataFrame(items)
                return df, None
        except Exception:
            pass

        # 2) XML 응답 파싱 시도 (JSON 파싱 실패 시 대비)
        root = ET.fromstring(response.text)
        items_xml = root.findall(".//item")
        if items_xml:
            parsed_list = []
            for item in items_xml:
                row_dict = {child.tag: child.text for child in item}
                parsed_list.append(row_dict)
            return pd.DataFrame(parsed_list), None
        
        return None, f"데이터가 없거나 응답 형식 오류입니다: {response.text[:200]}"
        
    except Exception as e:
        return None, f"API 호출 중 네트워크 오류 발생: {str(e)}"

# 4. 데이터 로드 및 정제
if user_api_key:
    raw_df, err_msg = fetch_localdata_api(user_api_key, selected_industry, search_rows)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        # 공공데이터 표준 필드명 매핑 (영문 -> 직관적 한글)
        field_map = {
            "prmisnDe": "인허가일자",
            "bplcNm": "법인/상호명",
            "siteRdnWhlAddr": "도로명주소",
            "siteWhlAddr": "지번주소",
            "dtlStateNm": "영업상태",
            "trdStateGbn": "상태코드"
        }
        
        # 존재하는 컬럼만 리네임
        view_df = raw_df.rename(columns={k: v for k, v in field_map.items() if k in raw_df.columns})
        
        # 주소 통합 처리
        if "도로명주소" in view_df.columns and "지번주소" in view_df.columns:
            view_df["사업장소재지"] = view_df["도로명주소"].fillna(view_df["지번주소"])
        elif "도로명주소" in view_df.columns:
            view_df["사업장소재지"] = view_df["도로명주소"]
        else:
            view_df["사업장소재지"] = target_region
            
        # 관할 구역 필터링
        if target_region:
            filtered_df = view_df[view_df["사업장소재지"].str.contains(target_region, na=False)].copy()
        else:
            filtered_df = view_df.copy()
            
        # 우체국 B2B 마케팅 자동 제안 부여
        filtered_df["추천 우체국 상품"] = (
            "요양급여 결제계좌 + 100% 국가보장 MMDA" if "의" in selected_industry or "병원" in selected_industry 
            else "대량 급여이체 수수료 평생면제 + 법인MMDA"
        )
        filtered_df["영업상태"] = "접촉 전"
        
        # 화면 표출용 컬럼 정리
        final_cols = [c for c in ["인허가일자", "법인/상호명", "사업장소재지", "영업상태", "추천 우체국 상품"] if c in filtered_df.columns]
        display_df = filtered_df[final_cols]
        
        # 5. 요약 통계 및 메트릭
        c1, c2, c3 = st.columns(3)
        c1.metric(f"관내 {selected_industry} 발굴", f"{len(display_df)} 건")
        c2.metric("중점 유치 상품", "법인MMDA / 급여이체")
        c3.metric("예치금 보호", "100% 국가 전액보장")
        
        st.divider()
        
        # 6. 인터랙티브 데이터 테이블
        st.subheader(f"📋 {target_region} {selected_industry} 실시간 인허가 명부")
        
        edited_df = st.data_editor(
            display_df,
            column_config={
                "영업상태": st.column_config.SelectboxColumn(
                    "진행 단계",
                    options=["접촉 전", "방문 예정", "상담 진행중", "계좌 개설 완료", "보류"],
                    required=True
                )
            },
            disabled=["인허가일자", "법인/상호명", "사업장소재지", "추천 우체국 상품"],
            hide_index=True,
            use_container_width=True
        )
        
        # 7. 엑셀 다운로드
        csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 타깃 리스트 엑셀(CSV) 다운로드",
            data=csv_data,
            file_name=f"우체국_B2B영업_{selected_industry}_{datetime.date.today()}.csv",
            mime="text/csv"
        )
    else:
        st.warning(f"'{target_region}' 관내에 해당하는 최근 {selected_industry} 데이터가 없습니다. 관할 구역 명칭을 확인하거나 조회 건수를 늘려보세요.")
else:
    st.info("👈 왼쪽 사이드바에 [공공데이터포털 인증키(Decoding)]를 입력하면 실시간 인허가 법인 데이터가 조회됩니다.")
