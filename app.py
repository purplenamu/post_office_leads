import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import datetime
import urllib.parse
import xml.etree.ElementTree as ET
import re

st.set_page_config(page_title="우체국 B2B 신규 법인 결제계좌 알리미", layout="wide")

st.title("📮 우체국 B2B 신규 법인 결제계좌 & 급여이체 알리미")
st.caption("공공데이터 실시간 API 연동 (부울경 전역 16칸 우편 라벨지 출력 탑재)")

# 1. 5대 업종 API 엔드포인트
API_URL_MAP = {
    "건물위생관리업": "https://apis.data.go.kr/1741000/building_sanitation/info",
    "소독업": "https://apis.data.go.kr/1741000/disinfection_companies/info",
    "승강기유지관리업체": "https://apis.data.go.kr/1741000/elevator_maintenance/info",
    "의원": "https://apis.data.go.kr/1741000/clinics/info",
    "병원": "https://apis.data.go.kr/1741000/hospitals/info"
}

# 2. 공식 엑셀 기반 부울경 전체 자치단체코드 매핑
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
    
    only_active = st.checkbox("영업/정상 사업장만 조회", value=True)
    
    st.divider()
    st.subheader("🔍 전국 데이터 탐색 범위")
    scan_pages = st.slider("자동 스캔 페이지 수 (페이지당 100건)", min_value=1, max_value=10, value=10)

# 4. 단일 페이지 호출
def fetch_single_page(clean_key, target_url, page):
    params = {
        "serviceKey": clean_key,
        "pageNo": str(page),
        "numOfRows": "100",
        "resultType": "json"
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

# 5. 다중 페이지 수집 함수 (캐싱 적용)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_data(api_key, industry_name, total_pages):
    if not api_key:
        return None, "사이드바에 API 인증키를 입력해주세요."
    
    clean_key = urllib.parse.unquote(api_key.strip())
    target_url = API_URL_MAP[industry_name]
    
    all_dfs = []
    pbar = st.progress(0, text="공공데이터 서버에서 전국 최신 데이터 수집 중...")
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

# 6. 정밀 데이터 가공 및 지역 필터링
def process_and_filter(df, sido, reg_name, code, active_only):
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

    # 우편번호
    zr_col = norm.get("ROADNMZIP", None)
    zl_col = norm.get("LCTNZIP", None)
    s_zr = df[zr_col].astype(str).str.strip().replace(["", "None", "nan", "null", "-"], None) if zr_col else None
    s_zl = df[zl_col].astype(str).str.strip().replace(["", "None", "nan", "null", "-"], None) if zl_col else None
    
    if s_zr is not None and s_zl is not None:
        df["우편번호"] = s_zr.combine_first(s_zl)
    elif s_zr is not None:
        df["우편번호"] = s_zr
    elif s_zl is not None:
        df["우편번호"] = s_zl
    else:
        df["우편번호"] = "-"
    df["우편번호"] = df["우편번호"].fillna("-")

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

# 7. 16칸 라벨지 (A4 / 2열 8행 - 폼텍 3107 호환) HTML 생성기
def generate_16_labels_html(df_target):
    html = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>우체국 B2B DM 우편 발송 라벨 (16칸)</title>
<style>
  @page {
    size: A4 portrait;
    margin: 12.5mm 5.9mm;
  }
  * {
    box-sizing: border-box;
  }
  body {
    margin: 0;
    padding: 0;
    font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    background: #ffffff;
  }
  .print-bar {
    text-align: center;
    padding: 12px;
    background: #f1f3f5;
    border-bottom: 1px solid #ced4da;
    margin-bottom: 15px;
  }
  .print-btn {
    background-color: #d32f2f;
    color: white;
    padding: 10px 24px;
    font-size: 15px;
    font-weight: bold;
    border: none;
    border-radius: 6px;
    cursor: pointer;
  }
  @media print {
    .print-bar { display: none; }
  }
  .page {
    width: 198.2mm;
    height: 272mm;
    display: grid;
    grid-template-columns: 99.1mm 99.1mm;
    grid-template-rows: repeat(8, 34mm);
    page-break-after: always;
  }
  .label-box {
    width: 99.1mm;
    height: 34mm;
    padding: 4mm 6mm 3mm 6mm;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    overflow: hidden;
    line-height: 1.35;
  }
  .address-line {
    font-size: 11px;
    color: #212529;
    word-break: keep-all;
  }
  .recipient-tag {
    font-weight: bold;
    color: #000000;
    margin-right: 4px;
  }
  .company-line {
    font-size: 13px;
    font-weight: bold;
    color: #000000;
    margin-top: 2px;
  }
  .zipcode-line {
    font-size: 13px;
    font-weight: bold;
    color: #000000;
    letter-spacing: 2px;
    text-align: right;
  }
</style>
</head>
<body>
<div class="print-bar">
  <button class="print-btn" onclick="window.print()">🖨️ 16칸 라벨지 바로 인쇄 (Ctrl + P)</button>
  <p style="margin: 6px 0 0 0; font-size: 12px; color: #495057;">
    * 브라우저 인쇄 설정에서 <b>여백: 없음(None)</b> 및 <b>배율: 100% (기본값)</b>으로 지정하시면 16칸 라벨지에 정확히 출력됩니다.
  </p>
</div>
"""
    records = df_target.to_dict('records')
    for i in range(0, len(records), 16):
        chunk = records[i:i+16]
        html += '<div class="page">\n'
        for item in chunk:
            raw_zip = str(item.get('우편번호', ''))
            # 우편번호는 숫자만 추출
            clean_zip = re.sub(r'[^0-9]', '', raw_zip)
            addr_val = item.get('사업장소재지', '-')
            comp_val = item.get('사업장명', '-')
            
            html += f"""  <div class="label-box">
    <div class="address-line"><span class="recipient-tag">받는사람</span> {addr_val}</div>
    <div class="company-line">{comp_val} <span style="font-weight: normal; font-size: 11px; color: #495057;">대표님 귀하</span></div>
    <div class="zipcode-line">{clean_zip}</div>
  </div>\n"""
        for _ in range(16 - len(chunk)):
            html += '  <div class="label-box"></div>\n'
        html += '</div>\n'

    html += "</body></html>"
    return html

# 8. 메인 화면 표출부
if user_api_key:
    raw_df, err_msg = fetch_all_data(user_api_key, selected_industry, scan_pages)
    
    if err_msg:
        st.error(err_msg)
    elif raw_df is not None and not raw_df.empty:
        filtered_df = process_and_filter(raw_df, sido_choice, selected_region_name, target_code, only_active)
        filtered_df["영업상태"] = "접촉 전"
        
        # 상단 요약 카드
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"{selected_region_name} 발굴", f"{len(filtered_df)} 개소")
        tot_emp = filtered_df["종업원(의료인)수"].sum() if not filtered_df.empty else 0
        c2.metric("잠재 급여이체 대상", f"{tot_emp:,} 명")
        c3.metric("중점 유치 대상", "대량 급여계좌" if selected_industry not in ["병원", "의원"] else "요양급여 계좌")
        c4.metric("전국 스캔 모수", f"{len(raw_df):,} 건")
        
        st.divider()
        
        # 데이터 테이블
        if not filtered_df.empty:
            view_cols = ["인허가일자", "사업장명", "우편번호", "사업장소재지", "종업원(의료인)수", "전화번호", "영업상태"]
            st.subheader(f"📋 {selected_region_name} {selected_industry} 실시간 명부 ({len(filtered_df)}건 확보)")
            
            edited_df = st.data_editor(
                filtered_df[view_cols],
                column_config={
                    "인허가일자": st.column_config.TextColumn("개설(인허가)일자"),
                    "우편번호": st.column_config.TextColumn("우편번호"),
                    "종업원(의료인)수": st.column_config.NumberColumn("종업원(의료인)수", format="%d명"),
                    "영업상태": st.column_config.SelectboxColumn(
                        "영업 단계",
                        options=["접촉 전", "전화(TM) 완료", "방문 예정", "상담 진행중", "계좌 개설 완료", "보류"],
                        required=True
                    )
                },
                disabled=["인허가일자", "사업장명", "우편번호", "사업장소재지", "종업원(의료인)수", "전화번호"],
                hide_index=True,
                use_container_width=True
            )
            
            st.divider()

            # 16칸 주소 라벨지 생성 (접촉 전 업체 대상)
            pre_contact_df = edited_df[edited_df["영업상태"] == "접촉 전"]
            
            st.subheader("🖨️ 16칸 DM 주소 라벨 인쇄 (접촉 전 업체 대상)")
            
            if not pre_contact_df.empty:
                req_pages = (len(pre_contact_df) + 15) // 16
                m1, m2, m3 = st.columns(3)
                m1.metric("라벨 출력 대상", f"{len(pre_contact_df)} 건")
                m2.metric("필요 16칸 라벨지(A4)", f"{req_pages} 장")
                m3.metric("규격 호환", "폼텍 3107 / 2열 8행")
                
                label_html_content = generate_16_labels_html(pre_contact_df)
                
                st.download_button(
                    label=f"📄 {selected_region_name} '접촉 전' 16칸 주소라벨 파일(HTML) 다운로드 / 인쇄",
                    data=label_html_content,
                    file_name=f"우체국_16주소라벨_{selected_region_name}_{datetime.date.today()}.html",
                    mime="text/html"
                )
                
                st.caption("💡 **인쇄 요령:** 다운로드한 HTML 파일을 열고 상단 **[16칸 라벨지 바로 인쇄]** 버튼을 누르세요. 인쇄 설정에서 **'여백: 없음'**, **'배율: 100%'**로 설정하시면 라벨 칸에 맞게 출력됩니다.")
                
                with st.expander("👀 16칸 라벨 인쇄 화면 미리보기"):
                    components.html(label_html_content, height=450, scrolling=True)
            else:
                st.info("현재 모든 업체의 진행 단계가 변경되어 '접촉 전' 상태인 업체가 없습니다.")
                
        else:
            st.warning(f"전국 최신 {len(raw_df):,}건 중 '{selected_region_name}' 소재 {selected_industry} 사업장이 없습니다.")
    else:
        st.warning("데이터를 가져오지 못했습니다.")
else:
    st.info("👈 사이드바에 공공데이터 API 인증키를 입력하세요.")
