import urllib.parse
import xml.etree.ElementTree as ET

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
st.caption("💡 실시간 정류소 및 버스 번호 안내 서비스 (카카오맵 연동)")

API_KEY = "9dee46a7fb260691759bcc48c371d7c750807ac380b0555594a696840e11bafe"

BASE_URL = "apis.data.go.kr/1613000"
TIMEOUT = 15


class ApiError(Exception):
  pass


def _parse_xml_error(text):
  """data.go.kr은 키/권한 오류를 _type=json이어도 XML로 돌려준다."""
  try:
    root = ET.fromstring(text)
  except ET.ParseError:
    return None
  for tag in ("returnAuthMsg", "errMsg", "resultMsg"):
    node = root.find(f".//{tag}")
    if node is not None and node.text:
      code = root.find(".//returnReasonCode")
      code = code.text if code is not None else ""
      return f"{node.text.strip()} {f'(코드 {code})' if code else ''}".strip()
  return None


def call_api(service, operation, **params):
  """공공데이터 API를 호출하고 item 리스트를 돌려준다. 실패 시 ApiError."""
  query = {"serviceKey": API_KEY, "_type": "json", **params}
  last_err = None
  # 해외 서버(Streamlit Cloud 등)에서 https 연결이 막히는 경우가 있어 http로 한 번 더 시도
  for scheme in ("https", "http"):
    url = f"{scheme}://{BASE_URL}/{service}/{operation}"
    try:
      res = requests.get(url, params=query, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
      last_err = f"{scheme} 연결 실패: {type(e).__name__}"
      continue

    try:
      data = res.json()
    except ValueError:
      msg = _parse_xml_error(res.text)
      if msg:
        raise ApiError(
            f"API 인증/권한 오류: {msg}\n"
            "→ 활용신청 승인 여부, 키 반영 대기(최대 1~2시간), 일일 트래픽 초과를 확인하세요."
        )
      raise ApiError(
          f"알 수 없는 응답 (HTTP {res.status_code}): {res.text[:300]}"
      )

    # 키 오류가 JSON 형식(OpenAPI_ServiceResponse)으로 오는 경우
    auth = data.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader")
    if auth:
      code = auth.get("returnReasonCode", "")
      msg = auth.get("returnAuthMsg") or auth.get("errMsg")
      raise ApiError(
          f"API 인증/권한 오류: {msg} (코드 {code}, HTTP {res.status_code})\n"
          "→ 활용신청 승인 여부, 키 반영 대기(최대 1~2시간), 일일 트래픽 초과를 확인하세요."
      )

    header = data.get("response", {}).get("header", {})
    if header.get("resultCode") not in (None, "00", "0"):
      raise ApiError(
          f"API 오류 {header.get('resultCode')}: {header.get('resultMsg')}"
      )

    items = (data.get("response", {}).get("body", {}).get("items") or {})
    items = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(items, dict):
      items = [items]
    return items

  raise ApiError(
      f"서버에 연결할 수 없습니다 ({last_err}).\n"
      "→ Streamlit Cloud처럼 해외 서버에서 실행 중이면 공공데이터포털 접속이"
      " 차단될 수 있습니다. 로컬(국내)에서 실행해 확인해 보세요."
  )


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_city_list():
  items = call_api("BusSttnInfoInqireService", "getCityList")
  return {
      f"{item.get('cityname')} ({item.get('citycode')})": str(
          item.get("citycode")
      )
      for item in items
  }


def get_city_list():
  try:
    cities = _fetch_city_list()
    if cities:
      return cities, None
    err = "도시 목록이 비어 있습니다."
  except ApiError as e:
    err = str(e)
  # 실패 결과는 캐시하지 않고 기본값으로 동작
  return {"청주시 (33010)": "33010", "세종특별자치시 (12)": "12"}, err


@st.cache_data(ttl=60, show_spinner=False)
def search_stations(city_code, name):
  return call_api(
      "BusSttnInfoInqireService",
      "getSttnNoList",
      cityCode=city_code,
      nodeNm=name,
      numOfRows=30,
      pageNo=1,
  )


def get_arrivals(city_code, node_id):
  return call_api(
      "ArvlInfoInqireService",
      "getSttnAcctoArvlPregeInfoList",
      cityCode=city_code,
      nodeId=node_id,
      numOfRows=50,
      pageNo=1,
  )


def _to_int(value):
  try:
    return int(value)
  except (TypeError, ValueError):
    return 0


def show_arrivals(city_code, node_id, label):
  try:
    with st.spinner("실시간 도착 정보 조회 중..."):
      a_items = get_arrivals(city_code, node_id)
  except ApiError as e:
    st.error(str(e))
    return False

  if not a_items:
    st.info("현재 해당 정류소에 도착 예정인 버스가 없습니다.")
    return False

  a_items.sort(key=lambda x: _to_int(x.get("arrtime")))
  rows = []
  for item in a_items:
    sec = _to_int(item.get("arrtime"))
    rows.append({
        "버스번호": item.get("routeno"),
        "남은 시간": f"약 {sec // 60}분 ({sec}초 후)",
        "남은 정류장": f"{item.get('arrprevstationcnt', '-')}개 전",
        "차량 유형": item.get("vehicletp", "일반"),
    })
  st.markdown(f"### 🚍 [{label}] 실시간 버스 도착 정보")
  st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
  return True


def station_picker(city_code, query, key):
  """검색 결과를 session_state에 보관해 승강장 선택 시 결과가 사라지지 않게 한다."""
  try:
    with st.spinner("정류소 검색 중..."):
      items = search_stations(city_code, query.strip())
  except ApiError as e:
    st.error(str(e))
    return None, None

  if not items:
    st.warning(
        f"'{query}'에 해당하는 정류소를 찾지 못했습니다. 정류소 이름을 다시"
        " 확인해 주세요."
    )
    return None, None

  st.success(f"📍 '{query}' 관련 정류소 {len(items)}개를 찾았습니다.")
  options = {
      f"{s.get('nodenm')} (ARS: {s.get('nodeno', '-')})": s.get("nodeid")
      for s in items
  }
  label = st.selectbox(
      "조회할 정확한 승강장을 선택하세요", list(options.keys()), key=key
  )
  return options[label], label


city_dict, city_err = get_city_list()
if city_err:
  st.warning(f"도시 목록을 불러오지 못해 기본 목록을 사용합니다.\n\n{city_err}")

default_idx = 0
for idx, name in enumerate(city_dict.keys()):
  if "청주" in name:
    default_idx = idx
    break

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
      width="stretch",
      key="btn_t1",
  ):
    if not start_station.strip():
      st.warning("출발 정류소 이름을 입력해 주세요.")
      st.session_state.pop("search_t1", None)
    else:
      st.session_state["search_t1"] = (city_code_t1, start_station.strip())

  if "search_t1" in st.session_state:
    s_city, s_name = st.session_state["search_t1"]
    node_id, label = station_picker(s_city, s_name, key="pick_t1")
    if node_id:
      if show_arrivals(s_city, node_id, label):
        kakao_map_url = "https://map.kakao.com/?" + urllib.parse.urlencode(
            {"sName": s_name, "eName": destination}
        )
        st.link_button(
            "🗺️ 카카오맵에서 목적지까지 상세 경로 보기",
            kakao_map_url,
            width="stretch",
        )
      if st.button("🔄 새로고침", key="refresh_t1"):
        st.rerun()

# ==========================================
# TAB 2: 일반 정류소별 실시간 버스 도착 예정 시간
# ==========================================
with tab2:
  st.subheader("⏱️ 정류소 이름 검색 및 도착 예정 시간")

  selected_city_t2 = st.selectbox(
      "지역 선택", list(city_dict.keys()), index=default_idx, key="city_t2"
  )
  city_code_t2 = city_dict[selected_city_t2]

  station_query = st.text_input("정류소 이름", value="오송역", key="query_t2")

  if st.button("실시간 도착 정보 검색", key="btn_t2"):
    if station_query.strip():
      st.session_state["search_t2"] = (city_code_t2, station_query.strip())
    else:
      st.warning("정류소 이름을 입력해 주세요.")
      st.session_state.pop("search_t2", None)

  if "search_t2" in st.session_state:
    s_city, s_name = st.session_state["search_t2"]
    node_id, label = station_picker(s_city, s_name, key="pick_t2")
    if node_id:
      show_arrivals(s_city, node_id, label)
      if st.button("🔄 새로고침", key="refresh_t2"):
        st.rerun()
