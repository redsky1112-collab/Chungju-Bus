import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="스마트 대중교통 실시간 안내판",
    layout="centered",
    initial_sidebar_state="expanded",
)

st.title("🚌 스마트 대중교통 실시간 안내판")
st.caption("💡 인증키 자동 반영 및 정류소 이름 실시간 검색 서비스")

# 📌 세션 상태(Session State)를 활용해 인증키가 세션 동안 영구 유지되도록 설정
if "api_key" not in st.session_state:
  st.session_state.api_key = (
      "6e4f3ef02b705a609c52db54bb93f9399b194946978c606d2a6fbb4ac6242223"
  )

# 사이드바: API 인증키 설정
st.sidebar.header("⚙️ 환경 설정")
st.session_state.api_key = st.sidebar.text_input(
    "공공데이터포털 인증키", value=st.session_state.api_key, type="password"
)

# 주요 도시 코드 맵핑
city_dict = {
    "청주시 (33010)": "33010",
    "서울특별시 (11)": "11",
    "부산광역시 (21)": "21",
    "대전광역시 (25)": "25",
    "세종특별자치시 (29)": "29",
}

selected_city_label = st.selectbox("지역 선택", list(city_dict.keys()))
city_code = city_dict[selected_city_label]

station_name_query = st.text_input(
    "정류소 이름 검색",
    value="",
    placeholder="예: 오송역, 터미널 등 입력 후 검색",
)


def safe_api_request(url, params):
  query_str = "&".join([f"{k}={v}" for k, v in params.items()])
  full_url = f"{url}?{query_str}"
  try:
    res = requests.get(full_url, timeout=5)
    return res
  except Exception:
    return None


if st.button("실시간 버스 도착 정보 검색", key="btn_search"):
  current_key = st.session_state.api_key

  if not current_key:
    st.error("사이드바에 인증키를 입력해 주세요.")
  elif not station_name_query.strip():
    st.warning("정류소 이름을 입력해 주세요.")
  else:
    with st.spinner("정류소 및 실시간 도착 정보를 불러오는 중입니다..."):
      sttn_url = "http://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
      sttn_params = {
          "serviceKey": current_key,
          "cityCode": city_code,
          "nodeNm": station_name_query,
          "numOfRows": "20",
          "pageNo": "1",
          "_type": "json",
      }

      res = safe_api_request(sttn_url, sttn_params)

      if res and res.status_code == 200:
        try:
          data = res.json()
          body = data.get("response", {}).get("body", {})
          items_container = body.get("items", {})
          stations = items_container.get("item", []) if items_container else []

          if isinstance(stations, dict):
            stations = [stations]

          if stations:
            st.success(
                f"🔍 '{station_name_query}' 검색 결과 총 {len(stations)}개의"
                " 정류소를 찾았습니다."
            )

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

            arvl_url = "http://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPregeInfoList"
            arvl_params = {
                "serviceKey": current_key,
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
                st.info("현재 해당 정류소에 도착 예정인 버스 정보가 없습니다.")
          else:
            st.warning(
                f"'{station_name_query}'에 해당하는 정류소를 찾지 못했습니다."
            )
        except Exception as e:
          st.error(f"데이터 처리 중 오류 발생: {e}")
          st.code(res.text)
      else:
        st.error(
            "API 서버 통신에 실패했습니다. 인증키 승인 상태를 다시 확인해"
            " 주세요."
        )
        if res:
          st.code(res.text)
