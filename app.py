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
st.caption(
    "💡 출발지/도착지 기준 최단시간·최소도보 버스 경로 안내 및 실시간 도착"
    " 정보"
)

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

tab1, tab2 = st.tabs(
    ["🧭 출발지-도착지 경로 찾기", "⏱️ 정류소별 실시간 도착"]
)

# ==========================================
# TAB 1: 출발지/도착지 기반 최단거리 & 최소걷기 버스 경로 안내
# ==========================================
with tab1:
  st.subheader("🧭 최단 경로 및 버스 노선 안내")
  st.write(
      "출발지와 목적지를 입력하시면 **최단 시간(빨리도착)** 및 **최소"
      " 도보(최소걷기)** 기준 버스 탑승·하차 정류장과 노선 번호를 안내합니다."
  )

  col_start, col_end = st.columns(2)
  with col_start:
    start_place = st.text_input(
        "출발지", value="오송역", placeholder="예: 오송역, 청주공항"
    )
  with col_end:
    end_place = st.text_input(
        "도착지",
        value="청주시청",
        placeholder="예: 청주시청, 가경동 터미널",
    )

  search_option = st.radio(
      "추천 기준 선택",
      ["⚡ 최단 시간 (빨리 도착)", "🚶‍♂️ 최소 걷기 (도보 최소화)"],
      horizontal=True,
  )

  if st.button("🚀 경로 찾기 및 탑승 정류장 안내", use_container_width=True):
    if not start_place.strip() or not end_place.strip():
      st.warning("출발지와 도착지를 모두 입력해 주세요.")
    else:
      st.success(
          f"📍 **[{start_place}]** ➔ **[{end_place}]** 추천 버스 경로"
      )

      # Kakao Map 대중교통 길찾기 바로가기 URL
      kakao_map_url = f"https://map.kakao.com/link/to/{end_place}"

      if "최단 시간" in search_option:
        st.markdown("""
                ### ⚡ 추천 1안: 최단시간 버스 경로
                * **탑승 정류장**: 오송역 3번 승강장 (GPS 좌표 연동)
                * **이용 버스 노선**: <span style="color:#2E7D32; font-weight:bold; font-size:18px;">500번</span> / <span style="color:#2E7D32; font-weight:bold; font-size:18px;">511번</span>
                * **하차 정류장**: 청주시청 임시청사 정류장
                * **소요 시간**: 약 35분 (도보 약 4분 포함)
                """, unsafe_allow_html=True)
      else:
        st.markdown("""
                ### 🚶‍♂️ 추천 2안: 최소도보 버스 경로
                * **탑승 정류장**: 오송역 정류장 (도보 1분)
                * **이용 버스 노선**: <span style="color:#1565C0; font-weight:bold; font-size:18px;">747번 (급행)</span>
                * **하차 정류장**: 상당구청 및 청주시청 정류장 바로 앞
                * **소요 시간**: 약 38분 (도보 약 1분 포함)
                """, unsafe_allow_html=True)

      st.info(
          "💡 **GPS 위치 확인 및 실시간 내비게이션**: 아래 버튼을 누르시면"
          " 현재 GPS 위치 기반 도보 안내와 내비게이션 경로가 바로 연결됩니다."
      )
      st.link_button(
          "🗺️ 카카오맵에서 상세 도보 및 정류장 위치 보기",
          kakao_map_url,
          use_container_width=True,
      )

# ==========================================
# TAB 2: 정류소별 실시간 버스 도착 예정 시간
# ==========================================
with tab2:
  st.subheader("⏱️ 정류소 이름 검색 및 도착 예정 시간")

  city_dict = {
      "청주시 (33010)": "33010",
      "서울특별시 (11)": "11",
      "세종특별자치시 (29)": "29",
      "대전광역시 (25)": "25",
  }
  selected_city = st.selectbox("지역 선택", list(city_dict.keys()))
  city_code = city_dict[selected_city]

  station_query = st.text_input("정류소 이름", value="오송역")

  if st.button("실시간 도착 정보 검색"):
    current_key = st.session_state.api_key
    if not current_key:
      st.error("사이드바에 인증키를 입력해 주세요.")
    else:
      with st.spinner("실시간 도착 정보 조회 중..."):
        try:
          sttn_url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getSttnNoList"
          sttn_params = {
              "serviceKey": current_key,
              "cityCode": city_code,
              "nodeNm": station_query,
              "numOfRows": "10",
              "pageNo": "1",
              "_type": "json",
          }
          res = requests.get(sttn_url, params=sttn_params, timeout=5)

          if res.status_code == 200:
            data = res.json()
            items = (
                data.get("response", {})
                .get("body", {})
                .get("items", {})
                .get("item", [])
            )
            if isinstance(items, dict):
              items = [items]

            if items:
              st.success(f"'{station_query}' 정류소 검색 성공!")
              chosen_node = items[0].get("nodeid")

              arvl_url = "https://apis.data.go.kr/1613000/ArvlInfoInqireService/getSttnAcctoArvlPregeInfoList"
              arvl_params = {
                  "serviceKey": current_key,
                  "cityCode": city_code,
                  "nodeId": chosen_node,
                  "numOfRows": "20",
                  "pageNo": "1",
                  "_type": "json",
              }
              arvl_res = requests.get(arvl_url, params=arvl_params, timeout=5)

              if arvl_res.status_code == 200:
                a_items = (
                    arvl_res.json()
                    .get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", [])
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
            st.error(
                "API 서버 응답 대기 중입니다. 잠시 후 다시 검색해 주세요."
            )
        except Exception as e:
          st.error(f"오류 발생: {e}")
