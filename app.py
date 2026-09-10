import streamlit as st
import pandas as pd
import requests
import datetime

st.set_page_config(page_title="우체국 B2B 법인·급여계좌 영업 대시보드", layout="wide")

st.title("📮 우체국 B2B 법인 결제계좌 & 급여이체 타깃 알리미")
st.caption("행안부 인허가 + 금융위 기업기본정보(종업원수) 연계 영업 우선순위 선별 시스템")

# 1. 사이드바 - 관할 및 필터
with st.sidebar:
    st.header("⚙️ 법인 타깃 필터")
    region = st.selectbox("관할 구역", ["부산광역시 동구", "부산광역시 중구", "부산광역시 부산진구", "직접 입력"])
    if region == "직접 입력":
        region = st.text_input("관할 시·군·구", "부산광역시 남구")
        
    industry_group = st.selectbox(
        "타깃 법인 업종",
        ["전체 법인", "의료·병원 법인", "시설·용역관리 법인", "제조·환경 법인"]
    )
    
    # 핵심 기능: 종업원 수 슬라이더
    min_employees = st.slider("최소 종업원 수 (급여계좌 타깃)", min_value=1, max_value=200, value=10)
    st.caption(f"💡 종업원 {min_employees}인 이상 법인을 최우선 방문 타깃으로 정렬합니다.")

# 2. 금융위 기업기본정보 API 연동 함수 예시
def fetch_fsc_company_info(corp_name, service_key):
    """
    실제 운영 시: 금융위원회 기업개요조회 API 호출부
    URL: http://apis.data.go.kr/1160100/service/GetCorpBasicInfoService_V2/getCorpOutline_V2
    파라미터: corpNm=corp_name, serviceKey=service_key
    반환 XML/JSON에서 <enpPnpeCscnt>(종업원수) 추출
    """
    pass

# 3. 데이터 로딩 (인허가 + 금융위 데이터 결합 시뮬레이션)
def get_enriched_leads(reg, ind, min_emp):
    today = datetime.date.today()
    
    # 인허가 정보에 금융위 기업개요(종업원수, 자본금)가 머지된 데이터
    raw_leads = [
        {
            "인허가일자": (today - datetime.timedelta(days=2)).strftime("%Y-%m-%d"),
            "법인명": "(주)태평양환경종합관리",
            "업종": "시설·용역관리",
            "종업원수": 120,
            "사업장소재지": f"{reg} 중앙대로 150",
            "예상 월 급여이체액": "약 3억 6천만 원",
            "우체국 중점 유치 상품": "대량 급여이체 펌뱅킹 + 법인MMDA",
            "영업 우선순위": "Tier 1 (최우선)",
            "영업상태": "접촉 전"
        },
        {
            "인허가일자": (today - datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
            "법인명": "의료법인 동구중앙의료재단",
            "업종": "의료·병원",
            "종업원수": 65,
            "사업장소재지": f"{reg} 범일로 88",
            "예상 월 급여이체액": "약 2억 5천만 원",
            "우체국 중점 유치 상품": "요양급여 입금통장 + 전액보장 법인예금",
            "영업 우선순위": "Tier 1 (최우선)",
            "영업상태": "방문 예정"
        },
        {
            "인허가일자": (today - datetime.timedelta(days=12)).strftime("%Y-%m-%d"),
            "법인명": "(주)동백바이오식품",
            "업종": "제조·환경",
            "종업원수": 25,
            "사업장소재지": f"{reg} 충장대로 210",
            "예상 월 급여이체액": "약 8천만 원",
            "우체국 중점 유치 상품": "원자재 결제통장 + 법인체크카드",
            "영업 우선순위": "Tier 2",
            "영업상태": "상담 진행중"
        },
        {
            "인허가일자": (today - datetime.timedelta(days=18)).strftime("%Y-%m-%d"),
            "법인명": "스타트테크(유)",
            "업종": "소프트웨어/IT",
            "종업원수": 6,
            "사업장소재지": f"{reg} 초량상로 12",
            "예상 월 급여이체액": "약 2천만 원",
            "우체국 중점 유치 상품": "운영비 결제계좌 + 수수료 면제",
            "영업 우선순위": "Tier 3",
            "영업상태": "접촉 전"
        }
    ]
    df = pd.DataFrame(raw_leads)
    
    # 업종 필터
    if ind != "전체 법인":
        ind_keyword = ind.split("·")[0]
        df = df[df["업종"].str.contains(ind_keyword)]
        
    # 종업원 수 필터 적용
    return df[df["종업원수"] >= min_emp]

leads_df = get_enriched_leads(region, industry_group, min_employees)

# 4. 현황 메트릭 요약
c1, c2, c3 = st.columns(3)
c1.metric("타깃 발굴 법인", f"{len(leads_df)} 개사")
total_employees = leads_df["종업원수"].sum() if not leads_df.empty else 0
c2.metric("잠재 급여이체 계좌 수", f"{total_employees:,} 계좌")
c3.metric("최우선 방문(Tier 1) 타깃", f"{len(leads_df[leads_df['영업 우선순위']=='Tier 1 (최우선)'])} 개사")

st.divider()

# 5. 영업 리스트 그리드 (종업원 수 내림차순 정렬)
st.subheader(f"📋 {region} 신규 법인 영업 리스트 (종업원 {min_employees}인 이상)")

if not leads_df.empty:
    sorted_df = leads_df.sort_values(by="종업원수", ascending=False)
    
    edited_df = st.data_editor(
        sorted_df,
        column_config={
            "종업원수": st.column_config.NumberColumn(
                "상시 종업원수",
                format="%d 명",
                help="금융위 기업개요 기준 고용 인원"
            ),
            "영업상태": st.column_config.SelectboxColumn(
                "영업 단계",
                options=["접촉 전", "방문 예정", "상담 진행중", "계좌 개설 완료", "보류"],
                required=True
            )
        },
        disabled=["인허가일자", "법인명", "업종", "사업장소재지", "예상 월 급여이체액", "우체국 중점 유치 상품", "영업 우선순위"],
        hide_index=True,
        use_container_width=True
    )

    # 엑셀 다운로드 버튼
    csv = edited_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        label="📥 타깃 법인 영업 리스트 다운로드 (급여이체 대상)",
        data=csv,
        file_name=f"우체국_급여계좌영업_{region}_{datetime.date.today()}.csv",
        mime="text/csv"
    )
else:
    st.info("선택한 조건(업종 및 최소 종업원 수)에 해당하는 신규 법인이 없습니다. 사이드바 필터를 완화해 보세요.")
