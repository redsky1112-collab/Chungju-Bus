import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="스마트 대중교통 길찾기 & 실시간 안내판",
    page_icon="🚌",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.title("🚌 스마트 대중교통 경로 & 실시간 안내판")
st.caption("💡 출발 정류소 맞춤형 실시간 버스 번호 및 도착 정보 조회")

# 세션 상태에 API 키 유지
if "api_key" not in st.session_state:
  st.session_state.api_key = (
      "6e4f3ef02b705a609c52db54bb93f9399b194946978c606d2a6fbb4ac6242223"
  )

# 사이드바: API 설정
with st.sidebar:
  st.header("⚙️ 환경 설정")
  st.session_state.api_key = st.text_input(
      "공공데이터포털 인증키", value=st.session_state.api_key, type="password"
  )

tab1, tab2 = st.tabs(["🧭 출발 정류소 맞춤 버스 조회", "⏱️ 일반 정류소 실시간 검색"])

# ==========================================
# TAB 1: 출발 정류소 기반 실시간 버스 번호 조회
# ==========================================
with tab1:
  st.subheader("🧭 출발 정류소 실시간 버스 번호 찾기")
  st.write(
      "탑승하실 **출발 정류소 이름**을 입력하시면, 해당 정류소를 경유하는 실시간"
      " 버스 번호와 도착 예정 시간을 바로 확인하실 수 있습니다."
  )

  city_dict_tab1 = {
      "청주시 (33010)": "33010",
      "서울특별시 (11)": "11",
      "세종특별자치시 (29)": "29",
      "대전광역시 (25)": "25",
  }
  selected_city_t1 = st.selectbox(
      "지역 선택 (출발지)", list(city_dict_tab1.keys()), key="city_t1"
  )
  city_code_t1 = city_dict_tab1[selected_city_t1]

  start_station = st.text_input(
      "출발 정류소 이름 입력",
      value="오송대광로제비앙",
      placeholder="예: 오송대광로제비앙, 오송역",
      key="start_stn",
  )
  destination = st.text_input(
      "도착지 (참고용)",
      value="청주롯데아울렛",
      placeholder="예: 청주롯데아울렛, 청주시청",
      key="dest_stn",
  )

  if st.button(
      "🚀 출발 정류소 경유 버스 번호 조회",
      use_container_width=True,
      key="btn_t1",
  ):
    current_key = st.session_state.api_key
    if not current_key:
      st.error("사이드바에 인증키를 입력해 주세요.")
    elif not start_station.strip():
      st.warning("출발 정류소 이름을 입력해 주세요.")
    else:
      with st.spinner("출발 정류소의 실시간 버스 번호 조회 중..."):
        try:
          import urllib.parse

          encoded_node_nm = urllib.parse.quote(start_station)

          # URL에 인증키를 직접 결합하여 인코딩 변형 차단
          sttn_url = (
              "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
              f"?serviceKey={current_key}&cityCode={city_code_t1}&nodeNm={encoded_node_nm}&numOfRows=10&pageNo=1&_type=json"
          )

          res = requests.get(sttn_url, timeout=5)

          if res.status_code == 200:
            try:
              data = res.json()
              body = data.get("response", {}).get("body", {})
              items_container = body.get("items", {})
              items = (
                  items_container.get("item", []) if items_container else []
              )
              if isinstance(items, dict):
                items = [items]

              if items:
                st.success(
                    f"📍 '{start_station}' 관련 정류소를 찾았습니다! (총"
                    f" {len(items)}개소)"
                )

                station_options = {
                    f"{s.get('nodenm')} (ARS: {s.get('nodeno', '-')})": s.get(
                        "nodeid"
                    )
                    for s in items
                }
                chosen_label = st.selectbox(
                    "조회할 정확한 승강장을 선택하세요",
                    list(station_options.keys()),
                )
                chosen_node_id = station_options[chosen_label]

                # 도착 정보 조회 URL 직접 결합
                arvl_url = (
                    "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPregeInfoList"
                    f"?serviceKey={current_key}&cityCode={city_code_t1}&nodeId={chosen_node_id}&numOfRows=20&pageNo=1&_type=json"
                )
                arvl_res = requests.get(arvl_url, timeout=5)

                if arvl_res.status_code == 200:
                  a_data = arvl_res.json()
                  a_body = a_data.get("response", {}).get("body", {})
                  a_items_container = a_body.get("items", {})
                  a_items = (
                      a_items_container.get("item", [])
                      if a_items_container
                      else []
                  )
                  if isinstance(a_items, dict):
                    a_items = [a_items]

                  if a_items:
                    st.markdown(
                        f"### 🚍 [{chosen_label}] 경유 실시간 버스 도착 정보"
                    )
                    rows = []
                    for item in a_items:
                      sec = int(item.get("arrtime", 0))
                      rows.append({
                          "탑승 버스번호": item.get("routeno"),
                          "남은 시간": f"약 {sec // 60}분 ({sec}초 후)",
                          "남은 정류장": f"{item.get('arrprevstationcnt')}개 전",
                          "차량 유형": item.get("vehicletp", "일반"),
                      })
                    st.dataframe(
                        pd.DataFrame(rows), use_container_width=True
                    )

                    kakao_map_url = f"https://map.kakao.com/?sName={start_station}&eName={destination}"
                    st.link_button(
                        "🗺️ 카카오맵에서 목적지까지 상세 경로 보기",
                        kakao_map_url,
                        use_container_width=True,
                    )
                  else:
                    st.info(
                        "현재 해당 출발 정류소에 도착 예정인 버스 노선이 없습니다."
                    )
                else:
                  st.error(
                      f"도착 정보 통신 오류 (상태 코드: {arvl_res.status_code})"
                  )
                  st.code(arvl_res.text)
              else:
                st.warning(
                    f"'{start_station}'에 해당하는 정류소를 찾지 못했습니다."
                    " 정류소 이름을 다르게(예: 오송역) 검색해 보세요."
                )
            except Exception as json_err:
              st.error(f"데이터 파싱 오류: {json_err}")
              st.code(res.text)
          else:
            st.error(f"API 통신 오류 (상태 코드: {res.status_code})")
            st.code(res.text)
        except Exception as e:
          st.error(f"시스템 오류 발생: {e}")

# ==========================================
# TAB 2: 일반 정류소별 실시간 버스 도착 예정 시간
# ==========================================
with tab2:
  st.subheader("⏱️ 정류소 이름 검색 및 도착 예정 시간")

  city_dict = {
      "청주시 (33010)": "33010",
      "서울특별시 (11)": "11",
      "세종특별자치시 (29)": "29",
      "대전광역시 (25)": "25",
  }
  selected_city = st.selectbox(
      "지역 선택", list(city_dict.keys()), key="city_t2"
  )
  city_code = city_dict[selected_city]

  station_query = st.text_input(
      "정류소 이름", value="오송역", key="query_t2"
  )

  if st.button("실시간 도착 정보 검색", key="btn_t2"):
    current_key = st.session_state.api_key
    if not current_key:
      st.error("사이드바에 인증키를 입력해 주세요.")
    else:
      with st.spinner("실시간 도착 정보 조회 중..."):
        try:
          import urllib.parse

          encoded_q = urllib.parse.quote(station_query)
          sttn_url = (
              "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
              f"?serviceKey={current_key}&cityCode={city_code}&nodeNm={encoded_q}&numOfRows=10&pageNo=1&_type=json"
          )
          res = requests.get(sttn_url, timeout=5)

          if res.status_code == 200:
            data = res.json()
            body = data.get("response", {}).get("body", {})
            items_container = body.get("items", {})
            items = items_container.get("item", []) if items_container else []
            if isinstance(items, dict):
              items = [items]

            if items:
              st.success(f"'{station_query}' 정류소 검색 성공!")
              chosen_node = items[0].get("nodeid")

              arvl_url = (
                  "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPregeInfoList"
                  f"?serviceKey={current_key}&cityCode={city_code}&nodeId={chosen_node}&numOfRows=20&pageNo=1&_type=json"
              )
              arvl_res = requests.get(arvl_url, timeout=5)

              if arvl_res.status_code == 200:
                a_data = arvl_res.json()
                a_body = a_data.get("response", {}).get("body", {})
                a_items_container = a_body.get("items", {})
                a_items = (
                    a_items_container.get("item", [])
                    if a_items_container
                    else []
                )
                if isinstance(a_items, dict):
                  a_items = [a_items]

                if a_items:
                  rows = []
                  for item in a_items:
                    sec = int(item.get("arrtime", 0))
                    rows.append({
                        "노선번호": item.get("routeno"),
                        "남은시간": f"약 {sec // 60}분 ({sec}초)",
                        "남은정류장": f"{item.get('arrprevstationcnt')}개 전",
                        "차량종류": item.get("vehicletp", "일반"),
                    })
                  st.dataframe(pd.DataFrame(rows), use_container_width=True)
                else:
                  st.info("현재 도착 예정인 버스가 없습니다.")
              else:
                st.error(f"도착 정보 통신 오류 ({arvl_res.status_code})")
                st.code(arvl_res.text)
            else:
              st.warning(f"'{station_query}' 정류소를 찾지 못했습니다.")
          else:
            st.error(f"API 통신 오류 ({res.status_code})")
            st.code(res.text)
        except Exception as e:
          st.error(f"오류 발생: {e}")
