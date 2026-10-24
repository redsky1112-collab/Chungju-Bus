import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="모바일 대중교통 실시간 안내판",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.title("🚌 스마트 대중교통 실시간 종합 안내판")
st.caption(
    "💡 국토교통부(TAGO) 공식 공공 API 연동 — 버스 도착 예정 시간, 실시간 위치"
    " 및 연령별 요금 안내"
)

# 🔑 사이드바: API 인증키 설정
st.sidebar.header("⚙️ 환경 설정")
api_key_input = st.sidebar.text_input(
    "공공데이터포털 인증키 (Decoding)",
    value="",
    type="password",
    help=(
        "공공데이터포털에서 발급받은 일반 인증키(Decoding Key)를 입력하세요."
    ),
)

if not api_key_input:
  st.sidebar.warning(
      "⚠️ 정상적인 조회를 위해 왼쪽 사이드바에 API 인증키를 입력해 주세요."
  )

# 메인 화면 탭 구성
tab1, tab2, tab3 = st.tabs(
    ["⏱️ 정류소별 도착예정", "📍 노선별 실시간위치", "💰 연령별 요금 안내"]
)

# ==========================================
# TAB 1: 정류소별 실시간 버스 도착 예정 시간
# ==========================================
with tab1:
  st.subheader("⏱️ 정류소별 버스 도착 예정 시간 조회")
  st.markdown(
      "원하시는 지역의 **도시코드**와 **정류소 ID**를 입력하여 실시간 도착"
      " 정보를 확인하세요."
  )

  col1, col2 = st.columns(2)
  with col1:
    # 기본값으로 청주(33010) 설정
    city_code = st.text_input(
        "도시코드 (예: 청주 33010, 서울 11)", value="33010"
    )
  with col2:
    node_id = st.text_input(
        "정류소 ID (ARS-ID 또는 정류소고유번호)", value="CBB330000001"
    )

  if st.button("도착 정보 조회하기", key="btn_arrival"):
    if not api_key_input:
      st.error("사이드바에 API 인증키를 먼저 입력해 주세요.")
    else:
      with st.spinner("실시간 버스 정보를 불러오는 중입니다..."):
        try:
          url = "http://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPregeInfoList"
          params = {
              "serviceKey": api_key_input,
              "cityCode": city_code,
              "nodeId": node_id,
              "numOfRows": "50",
              "pageNo": "1",
              "_type": "json",
          }
          response = requests.get(url, params=params, timeout=5)

          if response.status_code == 200:
            data = response.json()
            body = data.get("response", {}).get("body", {})
            items_container = body.get("items", {})
            items = (
                items_container.get("item", []) if items_container else []
            )

            if isinstance(items, dict):
              items = [items]

            if items:
              display_list = []
              for item in items:
                arr_sec = int(item.get("arrtime", 0))
                arr_min = arr_sec // 60

                display_list.append({
                    "노선번호": item.get("routeno", "-"),
                    "버스차종": item.get("vehicletp", "일반"),
                    "남은시간": f"약 {arr_min} 분 ({arr_sec}초)",
                    "남은정류장": f"{item.get('arrprevstationcnt', '-')} 개 전",
                    "노선유형": item.get("routetp", "-"),
                })

              st.success(
                  f"✅ 총 {len(display_list)}개 노선의 도착 정보를 확인했습니다."
              )
              st.dataframe(pd.DataFrame(display_list), use_container_width=True)
            else:
              st.warning(
                  "현재 도착 예정인 버스 정보가 없거나, 입력하신 정류소 ID가"
                  " 올바르지 않습니다."
              )
          else:
            st.error(
                f"API 서버 통신 오류 (상태 코드: {response.status_code}). 인증키를"
                " 확인해 주세요."
            )
        except Exception as e:
          st.error(f"데이터 처리 중 에러가 발생했습니다: {e}")

# ==========================================
# TAB 2: 버스 노선별 실시간 위치 추적
# ==========================================
with tab2:
  st.subheader("📍 버스 노선별 실시간 위치 추적")
  st.markdown("특정 노선 번호의 버스들이 현재 어디를 지나고 있는지 추적합니다.")

  col_a, col_b = st.columns(2)
  with col_a:
    r_city_code = st.text_input("도시코드", value="33010", key="r_city")
  with col_b:
    route_id = st.text_input(
        "노선 ID (예: 노선 고유 ID)", value="CBB330000001", key="r_id"
    )

  if st.button("실시간 위치 조회하기", key="btn_location"):
    if not api_key_input:
      st.error("사이드바에 API 인증키를 먼저 입력해 주세요.")
    else:
      with st.spinner("운행 중인 차량 위치를 조회하는 중입니다..."):
        try:
          url = "http://apis.data.go.kr/1613000/BusLocationInfoInqireService/getBusLocList"
          params = {
              "serviceKey": api_key_input,
              "cityCode": r_city_code,
              "routeId": route_id,
              "_type": "json",
          }
          response = requests.get(url, params=params, timeout=5)

          if response.status_code == 200:
            data = response.json()
            body = data.get("response", {}).get("body", {})
            items_container = body.get("items", {})
            items = (
                items_container.get("item", []) if items_container else []
            )

            if isinstance(items, dict):
              items = [items]

            if items:
              loc_list = []
              for item in items:
                v_type = item.get("vectp", "일반")
                low_bus = (
                    "저상버스"
                    if str(v_type) == "1" or "저상" in str(v_type)
                    else "일반버스"
                )

                loc_list.append({
                    "차량번호": item.get("vehicleno", "-"),
                    "현재위치(정류소)": item.get("nodenm", "-"),
                    "정류소순번": item.get("nodeord", "-"),
                    "차량유형": low_bus,
                })

              st.success(
                  f"🚌 현재 운행 중인 차량 {len(loc_list)}대를 발견했습니다."
              )
              st.dataframe(pd.DataFrame(loc_list), use_container_width=True)
            else:
              st.warning(
                  "현재 운행 중인 해당 노선 차량이 없거나 노선 ID가 올바르지"
                  " 않습니다."
              )
          else:
            st.error("API 요청에 실패했습니다. 입력값을 다시 확인해 주세요.")
        except Exception as e:
          st.error(f"조회 중 오류 발생: {e}")

# ==========================================
# TAB 3: 연령별 / 결제수단별 요금 안내
# ==========================================
with tab3:
  st.subheader("💰 연령별 및 결제수단별 대중교통 요금표")
  st.caption("💡 일반 시내버스 기준 (지자체 및 교통카드 종류에 따라 일부 상이)")

  fare_df = pd.DataFrame({
      "구분": [
          "성인 (만 19세 이상)",
          "청소년 (만 13세 ~ 18세)",
          "어린이 (만 6세 ~ 12세)",
          "유아 (만 6세 미만)",
      ],
      "교통카드 요금": ["1,650 원", "1,300 원", "800 원", "무료 (보호자 동반 시 최대 3인)"],
      "현금 요금": ["1,700 원", "1,350 원", "850 원", "무료"],
      "환승 혜택": [
          "하차 후 40분 이내 (최대 3회)",
          "하차 후 40분 이내 (최대 3회)",
          "하차 후 40분 이내 (최대 3회)",
          "적용 안 함",
      ],
  })

  st.table(fare_df)

  st.info(
      "📌 **알아두 팁**: 대중교통 이용 시 반드시 승차 및 **하차 시 단말기에 태그**를"
      " 하셔야 다음 탑승 시 환승 할인이 정상 적용됩니다!"
  )
