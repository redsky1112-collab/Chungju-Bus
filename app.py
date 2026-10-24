import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="스마트 대중교통 실시간 안내판",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.title("🚌 스마트 대중교통 실시간 안내판")
st.caption(
    "💡 정류소 이름만 치면 실시간 도착 정보를 바로 확인하는 사용자 중심 교통"
    " 서비스"
)

# 🔑 사이드바: API 인증키 설정
st.sidebar.header("⚙️ 환경 설정")
api_key_input = st.sidebar.text_input(
    "공공데이터포털 인증키 (Decoding 또는 Encoding)",
    value="",
    type="password",
    help="data.go.kr에서 발급받은 인증키를 입력하세요.",
)

if not api_key_input:
  st.sidebar.warning("⚠️ 원활한 조회를 위해 인증키를 입력해 주세요.")

# 주요 도시 코드 맵핑 (사용자 편의용 드롭다운)
city_dict = {
    "청주시 (33010)": "33010",
    "서울특별시 (11)": "11",
    "부산광역시 (21)": "21",
    "대구광역시 (22)": "22",
    "인천광역시 (23)": "23",
    "광주광역시 (24)": "24",
    "대전광역시 (25)": "25",
    "울산광역시 (26)": "26",
    "세종특별자치시 (29)": "29",
    "수원시 (31010)": "31010",
}

# 탭 구성: 정류소 검색 및 도착 예정 / 요금 안내
tab1, tab2 = st.tabs(["⏱️ 정류소별 도착예정 (이름 검색)", "💰 연령별 요금 안내"])

# ==========================================
# TAB 1: 정류소 이름으로 검색 및 도착 예정 시간 확인
# ==========================================
with tab1:
  st.subheader("⏱️ 정류소 이름 검색 및 실시간 도착")
  st.write(
      "복잡한 코드를 몰라도 됩니다. 지역을 고르고 정류소 이름(예: 오송역,"
      " 사창사거리)을 검색하세요!"
  )

  selected_city_label = st.selectbox("지역 선택", list(city_dict.keys()))
  city_code = city_dict[selected_city_label]

  station_name_query = st.text_input(
      "정류소 이름 검색",
      value="",
      placeholder="예: 오송역, 터미널, 시청 등",
  )

  # 400 에러 방지를 위한 안전한 API 요청 함수 (URL 직접 조합)
  def safe_api_request(url, params):
    # serviceKey 이중 인코딩 방지를 위해 수동 조합
    query_str = "&".join([f"{k}={v}" for k, v in params.items()])
    full_url = f"{url}?{query_str}"
    try:
      res = requests.get(full_url, timeout=5)
      return res
    except Exception as e:
      return None

  if st.button("정류소 및 도착 정보 검색", key="btn_search"):
    if not api_key_input:
      st.error("사이드바에 API 인증키를 먼저 입력해 주세요.")
    elif not station_name_query.strip():
      st.warning("검색할 정류소 이름을 입력해 주세요.")
    else:
      with st.spinner("정류소 정보를 찾는 중입니다..."):
        try:
          # 1단계: 정류소 이름으로 정류소 목록 조회 API 호출
          sttn_url = "http://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
          sttn_params = {
              "serviceKey": api_key_input,
              "cityCode": city_code,
              "nodeNm": station_name_query,
              "numOfRows": "20",
              "pageNo": "1",
              "_type": "json",
          }

          res = safe_api_request(sttn_url, sttn_params)

          if res and res.status_code == 200:
            data = res.json()
            body = data.get("response", {}).get("body", {})
            items_container = body.get("items", {})
            stations = (
                items_container.get("item", []) if items_container else []
            )

            if isinstance(stations, dict):
              stations = [stations]

            if stations:
              st.success(
                  f"🔍 '{station_name_query}' 검색 결과"
                  f" 총 {len(stations)}개의 정류소를 찾았습니다."
              )

              # 검색된 정류소들을 선택할 수 있도록 라디오 버튼이나 셀렉박스 제공
              station_options = {
                  f"{s.get('nodenm')} (ARS: {s.get('nodeno', '-')})": s.get(
                      "nodeid"
                  )
                  for s in stations
              }
              chosen_station_label = st.selectbox(
                  "조회할 정류소를 선택하세요", list(station_options.keys())
              )
              chosen_node_id = station_options[chosen_station_label]

              # 2단계: 선택된 정류소의 실시간 도착 정보 조회
              arvl_url = "http://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPregeInfoList"
              arvl_params = {
                  "serviceKey": api_key_input,
                  "cityCode": city_code,
                  "nodeId": chosen_node_id,
                  "numOfRows": "30",
                  "pageNo": "1",
                  "_type": "json",
              }

              arvl_res = safe_api_request(arvl_url, arvl_params)

              if arvl_res and arvl_res.status_code == 200:
                arvl_data = arvl_res.json()
                arvl_body = arvl_data.get("response", {}).get("body", {})
                arvl_items_container = arvl_body.get("items", {})
                arvl_items = (
                    arvl_items_container.get("item", [])
                    if arvl_items_container
                    else []
                )

                if isinstance(arvl_items, dict):
                  arvl_items = [arvl_items]

                if arvl_items:
                  display_list = []
                  for item in arvl_items:
                    arr_sec = int(item.get("arrtime", 0))
                    arr_min = arr_sec // 60
                    display_list.append({
                        "노선번호": item.get("routeno", "-"),
                        "남은시간": f"약 {arr_min}분 ({arr_sec}초)",
                        "남은정류장": f"{item.get('arrprevstationcnt', '-')}개 전",
                        "차량유형": item.get("vehicletp", "일반"),
                    })
                  st.markdown("### 🚍 실시간 버스 도착 예정")
                  st.dataframe(
                      pd.DataFrame(display_list), use_container_width=True
                  )
                else:
                  st.info(
                      "현재 해당 정류소에 도착 예정인 버스 운행 정보가 없습니다."
                  )
              else:
                st.error("도착 정보를 불러오는 데 실패했습니다.")
            else:
              st.warning(
                  f"'{station_name_query}'에 해당하는 정류소를 찾지"
                  " 못했습니다. 다른 검색어로 시도해 보세요."
              )
          else:
            st.error(
                "API 통신 오류가 발생했습니다. 인증키를 올바르게 입력했는지"
                " 확인해 주세요."
            )
        except Exception as e:
          st.error(f"처리 중 오류 발생: {e}")

# ==========================================
# TAB 2: 연령별 / 결제수단별 요금 안내
# ==========================================
with tab2:
  st.subheader("💰 연령별 및 결제수단별 대중교통 요금표")
  st.caption("💡 일반 시내버스 기준 요금 체계")

  fare_df = pd.DataFrame({
      "구분": [
          "성인 (만 19세 이상)",
          "청소년 (만 13세 ~ 18세)",
          "어린이 (만 6세 ~ 12세)",
          "유아 (만 6세 미만)",
      ],
      "교통카드 요금": ["1,650 원", "1,300 원", "800 원", "무료 (동승 3인까지)"],
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
      "📌 **이용 팁**: 하차하실 때 반드시 단말기에 교통카드를 태그하셔야"
      " 다음 탑승 시 환승 할인을 받으실 수 있습니다."
  )
