import urllib.parse
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
st.caption("💡 실시간 정류소 및 버스 번호 안내 서비스 (카카오맵 연동 복구)")

FIXED_API_KEY = (
    "9dee46a7fb260691759bcc48c371d7c750807ac380b0555594a696840e11bafe"
)


@st.cache_data(ttl=3600)
def get_city_list():
  try:
    url = f"https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getCityList?serviceKey={FIXED_API_KEY}&_type=json"
    res = requests.get(url, timeout=5)
    if res.status_code == 200:
      items = (
          res.json()
          .get("response", {})
          .get("body", {})
          .get("items", {})
          .get("item", [])
      )
      if isinstance(items, dict):
        items = [items]
      if items:
        return {
            f"{item.get('cityname')} ({item.get('citycode')})": str(
                item.get("citycode")
            )
            for item in items
        }
  except Exception:
    pass
  return {"청주시 (33010)": "33010", "세종특별자치시 (12)": "12"}


city_dict = get_city_list()

tab1, tab2 = st.tabs(["🧭 출발 정류소 맞춤 버스 조회", "⏱️ 일반 정류소 실시간 검색"])

# ==========================================
# TAB 1: 출발 정류소 기반 실시간 버스 번호 조회
# ==========================================
with tab1:
  st.subheader("🧭 출발 정류소 실시간 버스 번호 찾기")
  st.write(
      "탑승하실 **출발 정류소 이름**을 입력하시면, 해당 정류소를 경유하는 실시간"
      " 버스 번호와 도착 예정 시간을 확인하실 수 있습니다."
  )

  default_idx = 0
  for idx, name in enumerate(city_dict.keys()):
    if "청주" in name:
      default_idx = idx
      break

  selected_city_t1 = st.selectbox(
      "지역 선택 (출발지)",
      list(city_dict.keys()),
      index=default_idx,
      key="city_t1",
  )
  city_code_t1 = city_dict[selected_city_t1]

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
    if not start_station.strip():
      st.warning("출발 정류소 이름을 입력해 주세요.")
    else:
      with st.spinner("출발 정류소의 실시간 버스 번호 조회 중..."):
        try:
          encoded_node_nm = urllib.parse.quote(start_station)
          sttn_url = (
              "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
              f"?serviceKey={FIXED_API_KEY}&cityCode={city_code_t1}&nodeNm={encoded_node_nm}&numOfRows=10&pageNo=1&_type=json"
          )

          res = requests.get(sttn_url, timeout=5)

          if res.status_code == 200:
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

              arvl_url = (
                  "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPregeInfoList"
                  f"?serviceKey={FIXED_API_KEY}&cityCode={city_code_t1}&nodeId={chosen_node_id}&numOfRows=20&pageNo=1&_type=json"
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

                  # 🗺️ 카카오맵 연동 버튼 복구 완료
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
                  " 정류소 이름을 다시 확인해 주세요."
              )
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

  selected_city_t2 = st.selectbox(
      "지역 선택", list(city_dict.keys()), index=default_idx, key="city_t2"
  )
  city_code_t2 = city_dict[selected_city_t2]

  station_query = st.text_input(
      "정류소 이름", value="오송역", key="query_t2"
  )

  if st.button("실시간 도착 정보 검색", key="btn_t2"):
    with st.spinner("실시간 도착 정보 조회 중..."):
      try:
        encoded_q = urllib.parse.quote(station_query)
        sttn_url = (
            "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
            f"?serviceKey={FIXED_API_KEY}&cityCode={city_code_t2}&nodeNm={encoded_q}&numOfRows=10&pageNo=1&_type=json"
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
                f"?serviceKey={FIXED_API_KEY}&cityCode={city_code_t2}&nodeId={chosen_node}&numOfRows=20&pageNo=1&_type=json"
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
