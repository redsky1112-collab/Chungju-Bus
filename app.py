import difflib
import math
import re
import urllib.parse
from collections import Counter
import xml.etree.ElementTree as ET

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st
from streamlit_js_eval import get_geolocation

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
            "→ 활용신청 승인 여부, 키 반영 대기(최대 1~2시간), 일일 트래픽 초과를 확인하세요.\n\n"
            f"앱이 보낸 요청 (폰에서 직접 열어 비교해 보세요): {res.url}"
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
          "→ 활용신청 승인 여부, 키 반영 대기(최대 1~2시간), 일일 트래픽 초과를 확인하세요.\n\n"
          f"앱이 보낸 요청 (폰에서 직접 열어 비교해 보세요): {res.url}"
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
  items = call_api("ArvlInfoInqireService", "getCtyCodeList")
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


@st.cache_data(ttl=300, show_spinner=False)
def search_stations(city_code, name="", ars_no=""):
  params = {"nodeNo": ars_no} if ars_no else {"nodeNm": name}
  return call_api(
      "BusSttnInfoInqireService",
      "getSttnNoList",
      cityCode=city_code,
      numOfRows=50,
      pageNo=1,
      **params,
  )


@st.cache_data(ttl=300, show_spinner=False)
def nearby_stations(lat, lon):
  return call_api(
      "BusSttnInfoInqireService",
      "getCrdntPrxmtSttnList",
      gpsLati=lat,
      gpsLong=lon,
      numOfRows=30,
      pageNo=1,
  )


def get_arrivals(city_code, node_id):
  return call_api(
      "ArvlInfoInqireService",
      "getSttnAcctoArvlPrearngeInfoList",
      cityCode=city_code,
      nodeId=node_id,
      numOfRows=50,
      pageNo=1,
  )


def get_bus_locations(city_code, route_id):
  return call_api(
      "BusLcInfoInqireService",
      "getRouteAcctoBusLcList",
      cityCode=city_code,
      routeId=route_id,
      numOfRows=100,
      pageNo=1,
  )


@st.cache_data(ttl=86400, show_spinner=False)
def get_route_stops(city_code, route_id):
  stops = call_api(
      "BusRouteInfoInqireService",
      "getRouteAcctoThrghSttnList",
      cityCode=city_code,
      routeId=route_id,
      numOfRows=500,
      pageNo=1,
  )
  return sorted(stops, key=lambda x: _to_int(x.get("nodeord")))


def _to_int(value):
  try:
    return int(value)
  except (TypeError, ValueError):
    return 0


def _to_float(value):
  try:
    return float(value)
  except (TypeError, ValueError):
    return None


def distance_m(lat1, lon1, lat2, lon2):
  """두 좌표 사이 직선거리(m)."""
  if None in (lat1, lon1, lat2, lon2):
    return None
  r = 6371000
  p1, p2 = math.radians(lat1), math.radians(lat2)
  dp, dl = p2 - p1, math.radians(lon2 - lon1)
  a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
  return 2 * r * math.asin(math.sqrt(a))


def _fmt_dist(m):
  if m is None:
    return "-"
  return f"{m / 1000:.1f}km" if m >= 1000 else f"{int(m)}m"


def _query_variants(query):
  """오타·띄어쓰기·접미어가 있어도 찾을 수 있도록 검색어 후보를 만든다."""
  q = query.strip()
  compact = q.replace(" ", "")
  exact = [q, compact] + [t for t in q.split() if len(t) >= 2]
  # '오송역앞' → '오송역' → '오송' 처럼 뒤에서부터 줄이고, 앞글자 오타 대비 뒤쪽도 시도
  loose = [compact[:n] for n in range(len(compact) - 1, 1, -1)]
  loose += [compact[n:] for n in range(1, len(compact) - 1)]
  dedupe = lambda xs: list(dict.fromkeys(x for x in xs if x))
  return dedupe(exact), dedupe(loose)[:8]


@st.cache_data(ttl=86400, show_spinner=False)
def all_stations(city_code):
  """도시의 전체 정류장 목록 (하루 캐시)."""
  stations, page_size = [], None
  for page in range(1, 31):
    items = call_api(
        "BusSttnInfoInqireService",
        "getSttnNoList",
        cityCode=city_code,
        numOfRows=1000,
        pageNo=page,
    )
    stations.extend(items)
    # 서버가 한 페이지 최대 건수를 1000보다 작게 제한할 수도 있어 첫 페이지 크기를 기준으로 판단
    page_size = page_size or len(items)
    if not items or len(items) < page_size:
      break
  return stations


def _norm(text):
  return re.sub(r"[\s().\-·]", "", str(text or ""))


def match_score(query, name):
  """0~1. 포함 관계 > 공통 부분 문자열 > 전체 유사도 순으로 점수를 준다."""
  q, n = _norm(query), _norm(name)
  if not q or not n:
    return 0.0
  if q == n:
    return 1.0
  if q in n or n in q:
    return 0.5 + 0.4 * min(len(q), len(n)) / max(len(q), len(n))
  matcher = difflib.SequenceMatcher(None, q, n)
  common = matcher.find_longest_match(0, len(q), 0, len(n)).size
  partial = common / len(q) if common >= 2 else 0
  return 0.85 * max(matcher.ratio(), partial)


def fuzzy_search_stations(city_code, query, limit=20):
  q = query.strip()
  try:
    stations = all_stations(city_code)
  except ApiError:
    stations = []

  if stations:
    if q.isdigit():
      hits = [s for s in stations if q in str(s.get("nodeno", ""))]
      hits.sort(key=lambda s: str(s.get("nodeno")) != q)
      return hits[:limit], q
    scored = [(match_score(q, s.get("nodenm")), s) for s in stations]
    scored = [x for x in scored if x[0] >= 0.45]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:limit]], q

  # 전체 목록을 못 받으면 검색어를 바꿔 가며 API로 찾는다
  if q.isdigit():
    return search_stations(city_code, ars_no=q), q
  exact, loose = _query_variants(q)
  found = {}
  for variant in exact:
    for s in search_stations(city_code, name=variant):
      found.setdefault(s.get("nodeid"), s)
  used = q
  if not found:
    for variant in loose:
      for s in search_stations(city_code, name=variant):
        found.setdefault(s.get("nodeid"), s)
      if found:
        used = variant
        break
  ranked = sorted(
      found.values(), key=lambda s: match_score(q, s.get("nodenm")), reverse=True
  )
  return ranked, used


def _station(s, city_code, dist=None):
  return {
      "citycode": str(s.get("citycode") or city_code),
      "nodeid": s.get("nodeid"),
      "nodenm": s.get("nodenm"),
      "nodeno": s.get("nodeno") or "-",
      "lat": _to_float(s.get("gpslati")),
      "lon": _to_float(s.get("gpslong")),
      "dist": dist,
  }


def _pick(stations, key, label_fn):
  options = {}
  for st_ in stations:
    label = label_fn(st_)
    if label in options:
      label = f"{label} [{st_['nodeid']}]"
    options[label] = st_
  label = st.selectbox(
      "조회할 정확한 승강장을 선택하세요", list(options.keys()), key=key
  )
  return options[label]


def pick_station_by_name(city_code, query, key):
  try:
    with st.spinner("정류소 검색 중..."):
      items, used = fuzzy_search_stations(city_code, query)
  except ApiError as e:
    st.error(str(e))
    return None

  if not items:
    st.warning(
        f"'{query}'와(과) 비슷한 정류소를 찾지 못했습니다. 정류소 이름의 일부만"
        " 입력하거나 ARS 번호(숫자)로 검색해 보세요."
    )
    return None

  if used != query.strip():
    st.info(f"'{query}'와(과) 정확히 일치하는 정류소가 없어 '{used}'(으)로 찾았습니다.")
  st.success(f"📍 '{query}'와(과) 비슷한 정류소 {len(items)}개 (비슷한 순)")
  stations = [_station(s, city_code) for s in items]
  return _pick(stations, key, lambda s: f"{s['nodenm']} (ARS: {s['nodeno']})")


def pick_station_by_gps(key, trigger):
  if trigger:
    st.session_state[f"{key}_nonce"] = st.session_state.get(f"{key}_nonce", 0) + 1
    st.session_state.pop(f"{key}_coords", None)

  nonce = st.session_state.get(f"{key}_nonce")
  if nonce and f"{key}_coords" not in st.session_state:
    loc = get_geolocation(component_key=f"{key}_geo_{nonce}")
    if loc is None:
      st.info("위치 정보를 가져오는 중입니다... 브라우저에서 위치 권한을 허용해 주세요.")
      return None
    if "error" in loc:
      st.error(
          "위치 정보를 가져오지 못했습니다. 브라우저/휴대폰 설정에서 이 사이트의"
          f" 위치 권한을 허용해 주세요. ({loc['error'].get('message', '')})"
      )
      return None
    st.session_state[f"{key}_coords"] = (
        loc["coords"]["latitude"],
        loc["coords"]["longitude"],
    )

  coords = st.session_state.get(f"{key}_coords")
  if not coords:
    return None

  lat, lon = coords
  try:
    with st.spinner("가까운 정류장 검색 중..."):
      items = nearby_stations(round(lat, 4), round(lon, 4))
  except ApiError as e:
    st.error(str(e))
    return None

  if not items:
    st.warning("근처(약 500m 이내)에 정류장이 없습니다.")
    return None

  stations = []
  for s in items:
    station = _station(s, "")
    station["dist"] = distance_m(lat, lon, station["lat"], station["lon"])
    station["me"] = (lat, lon)
    stations.append(station)
  stations.sort(key=lambda s: s["dist"] if s["dist"] is not None else 1e9)
  st.success(f"📍 현재 위치 근처 정류장 {len(stations)}개 (가까운 순)")
  return _pick(
      stations,
      key,
      lambda s: f"{s['nodenm']} (ARS: {s['nodeno']}) · {_fmt_dist(s['dist'])}",
  )


ROUTE_API_HINT = (
    "정류장 방향과 '곧 도착할 버스' 표시는 공공데이터포털에서"
    " 「국토교통부_(TAGO)_버스노선정보」를 추가로 활용신청하면 나타납니다."
)


def route_context(station, route_id):
  """노선 경유 정류장 목록에서 이 정류장의 순번과 다음 정류장을 찾는다."""
  stops = get_route_stops(station["citycode"], route_id)
  for i, stop in enumerate(stops):
    if stop.get("nodeid") == station["nodeid"]:
      nxt = stops[i + 1].get("nodenm") if i + 1 < len(stops) else "종점"
      return {"ord": _to_int(stop.get("nodeord")), "next": nxt, "stops": stops}
  return None


def route_contexts(station, arrivals):
  """도착 예정 노선별 진행 방향 정보. 노선정보 API 미신청 시 빈 dict."""
  contexts = {}
  for route_id in dict.fromkeys(a.get("routeid") for a in arrivals):
    try:
      ctx = route_context(station, route_id)
    except ApiError as e:
      if "코드 30" in str(e):
        st.info(ROUTE_API_HINT)
        return {}
      continue
    if ctx:
      contexts[route_id] = ctx
  return contexts


def show_direction(contexts):
  nexts = [c["next"] for c in contexts.values() if c["next"] != "종점"]
  if not nexts:
    return
  main_next = Counter(nexts).most_common(1)[0][0]
  st.info(
      f"🧭 이 승강장은 **{main_next}** 방향입니다 (다음 정류장 기준)."
      " 반대 방향이면 위에서 같은 이름의 다른 승강장을 선택하세요."
  )


def show_arrivals(station):
  try:
    with st.spinner("실시간 도착 정보 조회 중..."):
      a_items = get_arrivals(station["citycode"], station["nodeid"])
  except ApiError as e:
    st.error(str(e))
    return [], {}

  if not a_items:
    st.info("현재 해당 정류소에 도착 예정인 버스가 없습니다.")
    return [], {}

  with st.spinner("진행 방향 확인 중..."):
    contexts = route_contexts(station, a_items)
  show_direction(contexts)

  a_items.sort(key=lambda x: _to_int(x.get("arrtime")))
  rows = []
  for item in a_items:
    sec = _to_int(item.get("arrtime"))
    row = {
        "버스번호": item.get("routeno"),
        "남은 시간": f"약 {sec // 60}분 ({sec}초 후)",
        "남은 정류장": f"{item.get('arrprevstationcnt', '-')}개 전",
    }
    if contexts:
      ctx = contexts.get(item.get("routeid"))
      row["다음 정류장(방향)"] = ctx["next"] if ctx else "-"
    row["차량 유형"] = item.get("vehicletp", "일반")
    rows.append(row)
  st.markdown(f"### 🚍 [{station['nodenm']}] 실시간 버스 도착 정보")
  st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
  return a_items, contexts


MARKER_COLORS = {
    "station": [230, 30, 30],  # 빨강: 출발 정류장
    "next": [255, 140, 0],  # 주황: 곧 도착할 버스
    "bus": [20, 100, 230],  # 파랑: 운행 중인 버스
    "me": [20, 170, 60],  # 초록: 내 현재 위치
}
MARKER_PIXELS = {"station": 11, "next": 10, "bus": 8, "me": 7}


def show_bus_location(station, arrivals, contexts, key):
  st.markdown("### 🗺️ 버스 위치 보기")
  options = {}
  for item in arrivals:
    sec = _to_int(item.get("arrtime"))
    label = f"{item.get('routeno')}번 · 약 {sec // 60}분 후 도착"
    options.setdefault(label, item)
  label = st.selectbox("위치를 볼 버스를 선택하세요", list(options.keys()), key=key)
  item = options[label]
  routeno = item.get("routeno")

  try:
    with st.spinner("버스 위치 조회 중..."):
      buses = get_bus_locations(station["citycode"], item.get("routeid"))
  except ApiError as e:
    st.error(str(e))
    if "코드 30" in str(e):
      st.info(
          "버스 위치를 보려면 공공데이터포털에서 「국토교통부_(TAGO)_버스위치정보」를"
          " 추가로 활용신청해야 합니다."
      )
    return

  if not buses:
    st.info(f"{routeno}번 버스의 현재 운행 위치 정보가 없습니다.")
    return

  # 내 정류장보다 앞(순번이 작거나 같은) 버스 중 가장 가까운 차량 = 곧 도착할 버스
  ctx = contexts.get(item.get("routeid"))
  ord_by_node = {}
  if ctx:
    ord_by_node = {s.get("nodeid"): _to_int(s.get("nodeord")) for s in ctx["stops"]}
  next_bus = None
  if ctx:
    best = -1
    for b in buses:
      b_ord = _to_int(b.get("nodeord")) or ord_by_node.get(b.get("nodeid"), 0)
      b["_ord"] = b_ord
      if b_ord <= ctx["ord"] and b_ord > best:
        best, next_bus = b_ord, b

  st.caption(
      f"가장 먼저 오는 {routeno}번은 약 {_to_int(item.get('arrtime')) // 60}분 후,"
      f" {item.get('arrprevstationcnt', '-')}개 전 정류장에 있습니다."
  )

  rows, points = [], []
  for b in buses:
    lat, lon = _to_float(b.get("gpslati")), _to_float(b.get("gpslong"))
    dist = distance_m(lat, lon, station["lat"], station["lon"])
    is_next = b is next_bus
    if ctx and "_ord" in b:
      status = (
          "🟠 곧 도착" if is_next
          else ("오는 중" if b["_ord"] <= ctx["ord"] else "지나감")
      )
    else:
      status = "-"
    rows.append({
        "상태": status,
        "차량번호": b.get("vehicleno"),
        "현재 위치(정류장)": b.get("nodenm"),
        "내 정류장까지 직선거리": _fmt_dist(dist),
        "_sort": (
            ["🟠 곧 도착", "오는 중", "-", "지나감"].index(status),
            dist if dist is not None else 1e9,
        ),
    })
    if lat and lon:
      points.append({
          "lat": lat,
          "lon": lon,
          "kind": "next" if is_next else "bus",
          "label": f"{'🟠 곧 도착 ' if is_next else '🔵 '}{routeno}번 {b.get('vehicleno', '')}"
                   f" · {b.get('nodenm', '')}",
      })

  df = pd.DataFrame(rows).sort_values("_sort").drop(columns="_sort")
  if not ctx:
    df = df.drop(columns="상태")
  st.dataframe(df, width="stretch", hide_index=True)

  if station["lat"] and station["lon"]:
    points.append({
        "lat": station["lat"],
        "lon": station["lon"],
        "kind": "station",
        "label": f"🔴 출발 정류장 · {station['nodenm']}",
    })
  if station.get("me"):
    points.append({
        "lat": station["me"][0],
        "lon": station["me"][1],
        "kind": "me",
        "label": "🟢 내 현재 위치",
    })
  if not points:
    return

  legend = ["🔴 **출발 정류장**", "🔵 **운행 중인 버스**"]
  if next_bus is not None:
    legend.insert(1, "🟠 **곧 도착할 버스**")
  if station.get("me"):
    legend.append("🟢 **내 현재 위치**")
  st.markdown("지도 표시: " + " · ".join(legend))

  pts = pd.DataFrame(points)
  center_lat = station["lat"] or pts["lat"].mean()
  center_lon = station["lon"] or pts["lon"].mean()
  layers = []
  # 내 위치 → 버스 → 곧 도착 버스 → 정류장 순으로 그려 정류장이 가장 위에 보이게 한다
  for kind in ("me", "bus", "next", "station"):
    group = pts[pts["kind"] == kind]
    if group.empty:
      continue
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=group,
            get_position=["lon", "lat"],
            get_fill_color=MARKER_COLORS[kind],
            get_radius=40,
            radius_min_pixels=MARKER_PIXELS[kind],
            radius_max_pixels=MARKER_PIXELS[kind] + 6,
            stroked=True,
            get_line_color=[255, 255, 255],
            line_width_min_pixels=2,
            pickable=True,
        )
    )
  st.pydeck_chart(
      pdk.Deck(
          layers=layers,
          initial_view_state=pdk.ViewState(
              latitude=center_lat, longitude=center_lon, zoom=13
          ),
          tooltip={"text": "{label}"},
      )
  )
  st.caption("점을 누르면 무엇인지 표시됩니다.")


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
      "**출발지**에 정류장 이름(일부만 입력해도 됨)이나 ARS 번호를 입력하거나,"
      " **내 위치**로 가까운 정류장을 찾으세요."
  )

  selected_city_t1 = st.selectbox(
      "지역 선택 (이름 검색용)",
      list(city_dict.keys()),
      index=default_idx,
      key="city_t1",
  )
  start_station = st.text_input(
      "출발지 (입력 후 엔터)",
      value="",
      placeholder="예: 오송역, 대광로제비앙, 3223",
      key="start_stn",
  )
  destination = st.text_input(
      "도착지 (카카오맵 경로용)",
      value="청주롯데아울렛",
      placeholder="예: 청주롯데아울렛, 청주시청",
      key="dest_stn",
  )

  col_search, col_gps = st.columns(2)
  search_clicked = col_search.button(
      "🔎 출발지로 검색", width="stretch", key="btn_t1"
  )
  gps_clicked = col_gps.button(
      "📍 내 위치로 찾기", width="stretch", key="gps_t1_btn"
  )

  # 엔터로 입력을 바꿔도 바로 검색
  typed = start_station.strip() and start_station != st.session_state.get("last_q_t1")
  st.session_state["last_q_t1"] = start_station
  if search_clicked or typed:
    if start_station.strip():
      st.session_state["src_t1"] = (
          "name",
          city_dict[selected_city_t1],
          start_station.strip(),
      )
    else:
      st.warning("출발지를 입력하거나 '📍 내 위치로 찾기'를 눌러 주세요.")
      st.session_state.pop("src_t1", None)
  if gps_clicked:
    st.session_state["src_t1"] = ("gps",)

  station = None
  src = st.session_state.get("src_t1")
  if src and src[0] == "gps":
    station = pick_station_by_gps("gps_t1", trigger=gps_clicked)
  elif src:
    station = pick_station_by_name(src[1], src[2], key="pick_t1")

  if station:
    arrivals, contexts = show_arrivals(station)
    if arrivals:
      kakao_map_url = "https://map.kakao.com/?" + urllib.parse.urlencode(
          {"sName": station["nodenm"], "eName": destination}
      )
      st.link_button(
          "🗺️ 카카오맵에서 목적지까지 상세 경로 보기",
          kakao_map_url,
          width="stretch",
      )
      show_bus_location(station, arrivals, contexts, key="bus_t1")
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

  station_query = st.text_input(
      "정류소 이름 또는 ARS 번호", value="오송역", key="query_t2"
  )

  if st.button("실시간 도착 정보 검색", key="btn_t2"):
    if station_query.strip():
      st.session_state["search_t2"] = (city_code_t2, station_query.strip())
    else:
      st.warning("정류소 이름을 입력해 주세요.")
      st.session_state.pop("search_t2", None)

  if "search_t2" in st.session_state:
    s_city, s_name = st.session_state["search_t2"]
    station2 = pick_station_by_name(s_city, s_name, key="pick_t2")
    if station2:
      arrivals2, contexts2 = show_arrivals(station2)
      if arrivals2:
        show_bus_location(station2, arrivals2, contexts2, key="bus_t2")
      if st.button("🔄 새로고침", key="refresh_t2"):
        st.rerun()
