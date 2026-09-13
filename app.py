import streamlit as st
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET
import math

st.set_page_config(page_title="우체국 B2B 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터 실시간 API 연동 (정상영업 필터 · 지도 위치 시각화 탑재)")

# 1. 5대 업종 API 엔드포인트
API_URL_MAP = {
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "병원": "https://apis.data.go.kr/1741000/hospitals/info"
}

# 2. 부울경 전체 자치단체코드 매핑
REGION_HIERARCHY = {
    "부산광역시": {
        "부산 동구": "3270000", "부산 사상구": "3390000", "부산 강서구": "3360000",
        "부산 북구": "3320000", "부산 사하구": "3340000", "부산 부산진구": "3290000",
        "부산 남구": "3310000", "부산 중구": "3250000", "부산 서구": "3260000",
        "부산 영도구": "3280000", "부산 동래구": "3300000", "부산 금정구": "3350000",
        "부산 연제구": "3370000", "부산 수영구": "3380000", "부산 해운대구": "3330000",
        "부산 기장군": "3400000", "부산 전체": "BUSAN_ALL"
    },
    "울산광역시": {
        "울산 남구": "3700000", "울산 중구": "3690000", "울산 동구": "3710000",
        "울산 북구": "3720000", "울산 울주군": "3730000", "울산 전체": "ULSAN_ALL"
    },
    "경상남도": {
        "경남 창원시": "5670000", "경남 김해시": "5350000", "경남 양산시": "5380000",
        "경남 진주시": "5310000", "경남 거제시": "5370000", "경남 통영시": "5330000",
        "경남 사천시": "5340000", "경남 밀양시": "5360000", "경남 함안군": "5400000",
        "경남 거창군": "5470000", "경남 창녕군": "5410000", "경남 고성군": "5420000",
        "경남 하동군": "5440000", "경남 합천군": "5480000", "경남 남해군": "5430000",
        "경남 함양군": "5460000", "경남 산청군": "5450000", "경남 의령군": "5390000",
        "경남 전체": "GYEONGNAM_ALL"
    },
    "부울경 전체 권역": {
        "부울경 전체 (부산·울산·경남)": "BUULGYEONG_ALL"
    }
}

# 3. 사이드바 UI
with st.sidebar:
    st.header("🔑 API 및 타깃 관할 설정")
    user_api_key = st.text_input("공공데이터 API 인증키", type="password")
    selected_industry = st.selectbox("타깃 업종", list(API_URL_MAP.keys()), index=0)
    
    sido_choice = st.selectbox("광역 시·도 선택", list(REGION_HIERARCHY.keys()), index=0)
    selected_region_name = st.selectbox("관할 시·군·구 선택", list(REGION_HIERARCHY[sido_choice].keys()), index=0)
    target_code = REGION_HIERARCHY[sido_choice][selected_region_name]
    
    st.success("🔒 **영업/정상 사업장만 자동 선별** (폐업·휴업 원천 차단)")
    
    st.divider()
    st.subheader("🔍 전국 데이터 탐색 범위")
    scan_pages = st.slider("자동 스캔 페이지 수 (페이지당 100건)", min_value=1, max_value=10, value=10)

# 4. 공공데이터 좌표(TM/GRS80/Bessel) -> WGS84 위경도 변환 엔진
def tm_to_wgs84(x_val, y_val):
    try:
        if pd.isna(x_val) or pd.isna(y_val):
            return None, None
        x = float(str(x_val).strip())
        y = float(str(y_val).strip())
        if x <= 0 or y <= 0:
            return None, None
        
        # 이미 WGS84 좌표계인 경우
        if 124.0 <= x <= 132.0 and 33.0 <= y <= 39.0:
            return round(y, 6), round(x, 6)
        if 124.0 <= y <= 132.0 and 33.0 <= x <= 39.0:
            return round(x, 6), round(y, 6)
            
        # 행안부 표준 TM 중부원점(Bessel 1841) 좌표 변환
        if x > 10000 and y > 10000:
            a = 6377397.155
            f = 1 / 299.1528128
            b = a * (1 - f)
            e2 = (a**2 - b**2) / (a**2)
            e_prime2 = (a**2 - b**2) / (b**2)
            
            lat0 = math.radians(38.0)
            lon0 = math.radians(127.0028902777778)
            x0 = 200000.0
            y0 = 500000.0
            k0 = 1.0
            
            dx = x - x0
            dy = y - y0
            
            e4 = e2 * e2
            e6 = e4 * e2
            A0 = 1 - (e2 / 4) - (3 * e4 / 64) - (5 * e6 / 256)
            A2 = (3 / 8) * (e2 + (e4 / 4) + (15 * e6 / 128))
            A4 = (15 / 256) * (e4 + (3 * e6 / 4))
            A6 = 35 * e6 / 3072
            
            M0 = a * (A0 * lat0 - A2 * math.sin(2 * lat0) + A4 * math.sin(4 * lat0) - A6 * math.sin(6 * lat0))
            M = M0 + dy / k0
            
            e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
            mu = M / (a * (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256))
            
            phi1 = mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu) + \
                   (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu) + \
                   (151 * e1**3 / 96) * math.sin(6 * mu) + (1097 * e1**4 / 512) * math.sin(8 * mu)
                   
            C1 = e_prime2 * math.cos(phi1)**2
            T1 = math.tan(phi1)**2
            N1 = a / math.sqrt(1 - e2 * math.sin(phi1)**2)
            R1 = a * (1 - e2) / ((1 - e2 * math.sin(phi1)**2)**1.5)
            D = dx / (N1 * k0)
            
            phi = phi1 - (N1 * math.tan(phi1) / R1) * (
                D**2 / 2 - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * e_prime2) * D**4 / 24 +
                (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * e_prime2 - 3 * C1**2) * D**6 / 720
            )
            lam = lon0 + (
                D - (1 + 2 * T1 + C1) * D**3 / 6 +
                (5 - 2 * C1 + 28 * T1 - 3 * C1**2 + 8 * e_prime2 + 24 * T1**2) * D**5 / 120
            ) / math.cos(phi1)
            
            lat_wgs = math.degrees(phi) - 0.0030
            lon_wgs = math.degrees(lam) + 0.0024
            
            if 33.0 <= lat_wgs <= 39.0 and 124.0 <= lon_wgs <= 132.0:
                return round(lat_wgs, 6), round(lon_wgs, 6)
    except Exception:
        pass
    return None, None

# 5. API 호출 함수
def fetch_single_page(clean_key, target_url, page):
    params = {
        "serviceKey": clean_key,
        "pageNo": str(page),
        "numOfRows": "100",
        "resultType": "json",
        "salsSttsCd": "01"  # API 레벨에서 1차 정상영업만 필터
    }
    try:
        res = requests.get(target_url, params=params, timeout=(10, 30))
        if res.status_code != 200:
            return None
        try:
            data = res.json()
            items = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
            if isinstance(items, dict):
                items = [items]
            if items:
                return pd.DataFrame(items)
        except Exception:
            pass

        try:
            root = ET.fromstring(res.text)
            items_xml = root.findall(".//item")
            if items_xml:
                return pd.DataFrame([{c.tag: c.text for c in item} for item in items_xml])
        except Exception:
            pass
    except Exception:
        return None
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_data(api_key, industry_name, total_pages):
    if not api_key:
        return None, "사이드바에 API 인증키를 입력해주세요."
    
    clean_key = urllib.parse.unquote(api_key.strip())
    target_url = API_URL_MAP[industry_name]
    
    all_dfs = []
    pbar = st.progress(0, text="공공데이터 서버에서 전국 최신 정상영업 데이터 수집 중...")
    for p in range(1, total_pages + 1):
        pbar.progress(p / total_pages, text=f"전국 데이터 {p}/{total_pages} 페이지 수집 중...")
        pdf = fetch_single_page(clean_key, target_url, p)
        if pdf is not None and not pdf.empty:
            all_dfs.append(pdf)
    pbar.empty()
    
    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        dup_col = next((c for c in ["MNG_NO", "mng_no", "OPN_ATMY_GRP_CD"] if c in combined.columns), None)
        if dup_col:
            combined = combined.drop_duplicates(subset=[dup_col])
        return combined, None
    return None, "데이터 수신에 실패했습니다. API 키를 확인해주세요."

# 6. 정밀 데이터 가공 및 정상영업/지역 2중 필터링
def process_and_filter(df, sido, reg_name, code):
    norm = {str(c).upper().replace("_", ""): c for c in df.columns}
    
    # 1) 영업/정상 사업장만 엄격 선별 (폐업, 휴업, 취소 완전 차단)
    stts_name_col = norm.get("SALSSTTSNM", norm.get("DTLSALSSTTSNM", None))
    stts_cd_col = norm.get("SALSSTTSCD", norm.get("DTLSALSSTTSCD", None))
    
    if stts_name_col:
        cond_active = df[stts_name_col].astype(str).str.contains("영업|정상", na=False) & \
                     ~df[stts_name_col].astype(str).str.contains("폐업|휴업|취소|말소|정지", na=False)
        df = df[cond_active].copy()
    elif stts_cd_col:
        df = df[df[stts_cd_col].astype(str).str.strip().isin(["01", "1"])].copy()

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

    # 좌표 변환 (지도용)
    cx_col = norm.get("CRDINFOX", None)
    cy_col = norm.get("CRDINFOY", None)
    if cx_col and cy_col:
        coords = [tm_to_wgs84(x, y) for x, y in zip(df[cx_col], df[cy_col])]
        df["latitude"] = [c[0] for c in coords]
        df["longitude"] = [c[1] for c in coords]
    else:
        df["latitude"] = None
        df["longitude"] = None

    # 자치단체코드 필터링
    gov_col = norm.get("OPNATMYGRPCD", None)
    df["지자체코드"] = df[gov_col].astype(str).str.strip() if gov_col else ""

    busan_codes = set([str(c) for c in range(3250000, 3410000, 10000)] + ["6260000", "6260000_ALL"])
    ulsan_codes = set([str(c) for c in range(3690000, 3740000, 10000)] + ["6310000", "6310000_ALL"])
    gn_codes = set([
        "5310000", "5330000", "5340000", "5350000", "5360000", "5370000", "5380000",
        "5390000", "5400000", "5410000", "5420000", "5430000", "5440000", "5450000",
        "5460000", "5470000", "5480000", "5670000", "6480000", "6480000_ALL"
    ])

    if code == "BUULGYEONG_ALL":
        c_code = df["지자체코드"].isin(busan_codes | ulsan_codes | gn_codes)
        c_addr = df["사업장소재지"].str.contains(r"부산|울산|경남|경상남도", na=False)
        filtered = df[c_code | c_addr].copy()
    elif code == "BUSAN_ALL":
        c_code = df["지자체코드"].isin(busan_codes)
        c_addr = df["사업장소재지"].str.contains(r"부산", na=False)
        filtered = df[c_code | c_addr].copy()
    elif code == "ULSAN_ALL":
        c_code = df["지자체코드"].isin(ulsan_codes)
        c_addr = df["사업장소재지"].str.contains(r"울산", na=False)
        filtered = df[c_code | c_addr].copy()
    elif code == "GYEONGNAM_ALL":
        c_code = df["지자체코드"].isin(gn_codes)
        c_addr = df["사업장소재지"].str.contains(r"경남|경상남도", na=False)
        filtered = df[c_code | c_addr].copy()
    else:
        c_code = (df["지자체코드"] == str(code))
        if "부산" in sido or "부산" in reg_name:
            sido_prefix = "부산"
        elif "울산" in sido or "울산" in reg_name:
            sido_prefix = "울산"
        else:
            sido_prefix = r"(?:경남|경상남도)"
            
        dist_name = reg_name.split(" ")[-1]
        addr_regex = rf"{sido_prefix}.*(?<![가-힣]){dist_name}(?![가-힣])"
        c_addr = df["사업장소재지"].str.contains(addr_regex, regex=True, na=False)
        filtered = df[c_code | c_addr].copy()

    filtered = filtered.sort_values(by="인허가일자", ascending=False)
    return filtered

# 7. 화면 표출부
if user_api_key:
    raw_df, err_msg = fetch_all_data(user_api_key, selected_industry, scan_pages)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        filtered_df = process_and_filter(raw_df, sido_choice, selected_region_name, target_code)
        
        # 상단 요약 카드
        is_medical = selected_industry in ["병원", "의원"]
        focus_prod = "요양급여/MMDA" if is_medical else "대량 급여이체/MMDA"
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{selected_region_name} 정상영업 발굴", f"{len(filtered_df)} 개소")
        tot_emp = filtered_df["종업원(의료인)수"].sum() if not filtered_df.empty else 0
        c2.metric("잠재 급여이체 대상", f"{tot_emp:,} 명")
        c3.metric("중점 유치 대상", focus_prod)
        c4.metric("자금 안전성", "100% 국가 전액보장")
        
        st.divider()
        
        # --- 상품 유치 전략 가이드 블록 ---
        with st.expander(f"💡 [우체국 B2B 세일즈 플레이북] {selected_industry} 맞춤 유치 전략", expanded=True):
            if is_medical:
                st.markdown("""
                * **1. 건강보험공단 요양급여 결제계좌 지정 유치**: 병원·의원 최대 현금 유입 통로인 건보공단 지급계좌를 우체국으로 지정하도록 유도합니다.
                * **2. 법인 MMDA (단기 유동자금 운용)**: 요양급여 입금 후 의약품 대금 결제, 급여일 전까지 며칠간 머무는 단기 자금을 하루만 맡겨도 고금리를 제공하는 법인 MMDA로 유치합니다.
                * **3. 원금·이자 100% 국가 전액보장 소구**: 일반 시중은행의 5천만 원 예금자보호 한도와 차별화하여 국가 전액 지급보증 안전성을 핵심 셀링포인트로 강조합니다.
                * **4. 의료인·직원 급여이체 연계**: 병원 결제계좌 개설과 동시에 간호사, 조무사, 원무과 직원의 급여통장 유치(타행 이체수수료 평생 면제 혜택)를 패키지로 제안합니다.
                """)
            else:
                st.markdown("""
                * **1. 대량 급여이체 수수료 평생 면제**: 청소·소독·승강기 정비 기사 등 다수 현장 근로자 급여 일괄 이체 시 건당 수수료 0원 혜택으로 연간 금융비용 절감 효과를 제시합니다.
                * **2. 아파트·빌딩 관리용역 대금 수납 전용계좌**: 아파트 입대의나 빌딩 관리단으로부터 정기 입금받는 용역대금 수납 계좌를 우체국으로 단일화하도록 유도합니다.
                * **3. 기업 인터넷뱅킹 이체수수료 전액 면제**: 자재 구매, 외주비 송금 등 법인 결제성 이체 수수료를 전액 면제하여 주거래 은행 전환 장벽을 제거합니다.
                * **4. 법인 MMDA 예비비 운용**: 매월 적립되는 퇴직급여 충당금 및 장기수선/소모품 구매 예비 자금을 수시입출식 고금리 MMDA로 운용하도록 제안합니다.
                """)
        
        # --- 위치 지도 표출 ---
        map_df = filtered_df.dropna(subset=["latitude", "longitude"])
        if not map_df.empty:
            st.subheader(f"🗺️ {selected_region_name} 사업장 위치 분포 ({len(map_df)}개소 지도 표시)")
            st.map(map_df[["latitude", "longitude"]], zoom=12, use_container_width=True)
        
        # --- 메인 데이터 테이블 (추천 우체국 상품 컬럼 제거) ---
        if not filtered_df.empty:
            filtered_df["진행 단계"] = "접촉 전"
            view_cols = ["인허가일자", "사업장명", "종업원(의료인)수", "전화번호", "사업장소재지", "진행 단계"]
            
            st.subheader(f"📋 {selected_region_name} {selected_industry} 명부 ({len(filtered_df)}건)")
            
            edited_df = st.data_editor(
                filtered_df[view_cols],
                column_config={
                    "인허가일자": st.column_config.TextColumn("개설(인허가)일자"),
                    "종업원(의료인)수": st.column_config.NumberColumn("종업원(의료인)수", format="%d명"),
                    "진행 단계": st.column_config.SelectboxColumn(
                        "영업 진행 단계",
                        options=["접촉 전", "전화(TM) 완료", "방문 예정", "상담 진행중", "계좌 개설 완료", "보류"],
                        required=True
                    )
                },
                disabled=["인허가일자", "사업장명", "종업원(의료인)수", "전화번호", "사업장소재지"],
                hide_index=True,
                use_container_width=True
            )
            
            csv_data = edited_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                label=f"📥 {selected_region_name} {selected_industry} 영업 리스트(CSV) 다운로드",
                data=csv_data,
                file_name=f"우체국_B2B_{selected_industry}_{selected_region_name}_{datetime.date.today()}.csv",
                mime="text/csv"
            )
        else:
            st.warning(f"전국 최신 정상영업 사업장 중 '{selected_region_name}' 소재 {selected_industry} 사업장이 없습니다.")
    else:
        st.warning("데이터를 가져오지 못했습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
