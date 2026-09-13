import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("행정안전부 자치단체코드 기반 부울경 전역 실시간 조회 시스템")

# 1. 5대 업종 API 엔드포인트
API_URL_MAP = {
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "병원": "https://apis.data.go.kr/1741000/hospitals/info",
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info"
}

# 2. 공식 엑셀 기반 부울경 전체 자치단체코드 매핑
REGION_HIERARCHY = {
    "부산광역시": {
        "부산 사상구": "3390000", "부산 강서구": "3360000", "부산 북구": "3320000",
        "부산 사하구": "3340000", "부산 부산진구": "3290000", "부산 동구": "3270000",
        "부산 남구": "3310000", "부산 중구": "3250000", "부산 서구": "3260000",
        "부산 영도구": "3280000", "부산 동래구": "3300000", "부산 금정구": "3350000",
        "부산 연제구": "3370000", "부산 수영구": "3380000", "부산 해운대구": "3330000",
        "부산 기장군": "3400000", "부산 전체": "6260000_ALL"
    },
    "울산광역시": {
        "울산 남구": "3700000", "울산 중구": "3690000", "울산 동구": "3710000",
        "울산 북구": "3720000", "울산 울주군": "3730000", "울산 전체": "6310000_ALL"
    },
    "경상남도": {
        "경남 창원시": "5670000", "경남 김해시": "5350000", "경남 양산시": "5380000",
        "경남 진주시": "5310000", "경남 거제시": "5370000", "경남 통영시": "5330000",
        "경남 사천시": "5340000", "경남 밀양시": "5360000", "경남 함안군": "5400000",
        "경남 거창군": "5470000", "경남 창녕군": "5410000", "경남 고성군": "5420000",
        "경남 하동군": "5440000", "경남 합천군": "5480000", "경남 남해군": "5430000",
        "경남 함양군": "5460000", "경남 산청군": "5450000", "경남 의령군": "5390000",
        "경남 전체": "6480000_ALL"
    }
}

# 3. 사이드바 UI
with st.sidebar:
    st.header("🔑 API 및 타깃 관할 설정")
    user_api_key = st.text_input("공공데이터 API 인증키", type="password")
    selected_industry = st.selectbox("타깃 업종", list(API_URL_MAP.keys()), index=0)
    
    # 2단계 권역 선택
    sido_choice = st.selectbox("광역 시·도 선택", list(REGION_HIERARCHY.keys()), index=0)
    selected_region_name = st.selectbox("관할 시·군·구 선택", list(REGION_HIERARCHY[sido_choice].keys()), index=0)
    target_code = REGION_HIERARCHY[sido_choice][selected_region_name]
    
    only_active = st.checkbox("영업/정상 사업장만 조회 (폐업 제외)", value=True)
    fetch_limit = st.slider("가져올 최대 건수", min_value=50, max_value=500, value=200, step=50)

# 4. 공공데이터 API 호출 함수
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_target_localdata(api_key, industry_name, gov_code, active_only, num_rows):
    if not api_key:
        return None, "사이드바에 API 인증키를 입력해주세요."
    
    clean_key = urllib.parse.unquote(api_key.strip())
    target_url = API_URL_MAP[industry_name]
    
    params = {
        "serviceKey": clean_key,
        "pageNo": "1",
        "numOfRows": str(num_rows),
        "resultType": "json",
        "opnAtmyGrpCd": gov_code
    }
    
    if active_only:
        params["salsSttsCd"] = "01"
    
    try:
        response = requests.get(target_url, params=params, timeout=(10, 30))
        if response.status_code != 200:
            return None, f"서버 오류 (HTTP {response.status_code}): {response.text[:200]}"
            
        try:
            data_json = response.json()
            items = data_json.get("response", {}).get("body", {})
            if "items" in items:
                items_data = items["items"].get("item", [])
                if isinstance(items_data, dict):
                    items_data = [items_data]
                if items_data:
                    return pd.DataFrame(items_data), None
        except Exception:
            pass

        try:
            root = ET.fromstring(response.text)
            items_xml = root.findall(".//item")
            if items_xml:
                rows = [{child.tag: child.text for child in item} for item in items_xml]
                return pd.DataFrame(rows), None
            else:
                return None, f"공공데이터 응답 내용: {response.text[:250]}"
        except ET.ParseError:
            return None, f"응답 해석 실패: {response.text[:200]}"
            
    except Exception as e:
        return None, f"연결 실패: {str(e)}"
    return None, "조회된 데이터가 없습니다."

# 5. 데이터 가공 및 정렬
def process_dataframe(df, active_only):
    norm = {str(c).upper().replace("_", ""): c for c in df.columns}
    
    # 상호명
    name_col = norm.get("BPLCNM", df.columns[0])
    df["사업장명"] = df[name_col].astype(str).str.strip()

    # 인허가일자
    date_col = norm.get("LCPMTYMD", norm.get("PRMISNDE", None))
    if date_col:
        def fmt_d(v):
            if pd.isna(v) or str(v).strip() in ["", "None", "nan", "null", "-"]:
                return "-"
            cv = str(v).replace("-", "").replace(".", "").strip()
            if len(cv) >= 8 and cv[:8].isdigit():
                return f"{cv[:4]}-{cv[4:6]}-{cv[6:8]}"
            return str(v)[:10]
        df["인허가일자"] = df[date_col].apply(fmt_d)
    else:
        df["인허가일자"] = "-"

    # 주소
    r_col = norm.get("ROADNMADDR", None)
    l_col = norm.get("LOTNOADDR", None)
    s_road = df[r_col].astype(str).str.strip().replace(["", "None", "nan", "null", "-"], None) if r_col else None
    s_lot = df[l_col].astype(str).str.strip().replace(["", "None", "nan", "null", "-"], None) if l_col else None
    
    if s_road is not None and s_lot is not None:
        df["사업장소재지"] = s_road.combine_first(s_lot)
    elif s_road is not None:
        df["사업장소재지"] = s_road
    elif s_lot is not None:
        df["사업장소재지"] = s_lot
    else:
        df["사업장소재지"] = "주소 확인 필요"
    df["사업장소재지"] = df["사업장소재지"].fillna("주소 확인 필요")

    # 종업원(의료인)수
    emp_col = norm.get("HCWKRCNT", None)
    df["종업원(의료인)수"] = pd.to_numeric(df[emp_col], errors="coerce").fillna(0).astype(int) if emp_col else 0

    # 전화번호
    tel_col = norm.get("TELNO", None)
    df["전화번호"] = df[tel_col].astype(str).str.strip().replace(["", "None", "nan", "null"], "-") if tel_col else "-"

    # 영업상태
    stts_col = norm.get("SALSSTTSNM", norm.get("DTLSALSSTTSNM", None))
    df["영업상태명"] = df[stts_col].astype(str).str.strip() if stts_col else "정상"

    if active_only and stts_col:
        df = df[df["영업상태명"].str.contains("영업|정상", na=False)]

    # 최신 등록순 내림차순 정렬
    df = df.sort_values(by="인허가일자", ascending=False)
    return df

# 6. 화면 표출부
if user_api_key:
    raw_df, err_msg = fetch_target_localdata(user_api_key, selected_industry, target_code, only_active, fetch_limit)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        df = process_dataframe(raw_df, only_active)
        
        # B2B 추천 상품 자동 배정
        if selected_industry in ["병원", "의원"]:
            df["추천 우체국 상품"] = "요양급여 결제계좌 + 100% 국가보장 MMDA"
        else:
            df["추천 우체국 상품"] = "대량 급여이체 수수료 평생면제 + 법인MMDA"
        df["영업상태"] = "접촉 전"
        
        # 상단 요약 카드
        region_clean_name = selected_region_name
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{region_clean_name} {selected_industry}", f"{len(df)} 개소")
        c2.metric("잠재 급여이체 대상", f"{df['종업원(의료인)수'].sum():,} 명")
        c3.metric("중점 유치 상품", "요양급여/급여통장")
        c4.metric("자금 안전성", "100% 국가 전액보장")
        
        st.divider()
        
        # 메인 데이터 테이블
        view_cols = ["인허가일자", "사업장명", "종업원(의료인)수", "전화번호", "사업장소재지", "영업상태", "추천 우체국 상품"]
        st.subheader(f"📋 {region_clean_name} {selected_industry} 실시간 명부 ({len(df)}건 확보)")
        
        edited_df = st.data_editor(
            df[view_cols],
            column_config={
                "인허가일자": st.column_config.TextColumn("개설(인허가)일자"),
                "종업원(의료인)수": st.column_config.NumberColumn("종업원(의료인)수", format="%d명"),
                "영업상태": st.column_config.SelectboxColumn(
                    "영업 단계",
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
            label=f"📥 {region_clean_name} {selected_industry} TM/방문 영업 리스트(CSV) 다운로드",
            data=csv_data,
            file_name=f"우체국_B2B_{selected_industry}_{region_clean_name}_{datetime.date.today()}.csv",
            mime="text/csv"
        )
    else:
        st.warning(f"선택하신 '{selected_region_name}' 관내에 해당하는 데이터가 없습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
