import difflib
import math
import re
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
st.caption("💡 실시간 정류소 및 버스 번호 안내 서비스 (네이버지도 길찾기 연동)")

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
  stations, page_size = {}, None
  for page in range(1, 31):
    items = call_api(
        "BusSttnInfoInqireService",
        "getSttnNoList",
        cityCode=city_code,
        numOfRows=1000,
        pageNo=page,
    )
    before = len(stations)
    for item in items:
      stations.setdefault(item.get("nodeid"), item)
    # 서버가 한 페이지 최대 건수를 1000보다 작게 제한할 수도 있어 첫 페이지 크기를 기준으로 판단
    page_size = page_size or len(items)
    if not items or len(items) < page_size or len(stations) == before:
      break
  return list(stations.values())


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


@st.cache_data(ttl=86400, show_spinner=False)
def station_routes(city_code, node_id):
  return call_api(
      "BusSttnInfoInqireService",
      "getSttnThrghRouteList",
      cityCode=city_code,
      nodeid=node_id,
      numOfRows=100,
      pageNo=1,
  )


@st.cache_data(ttl=86400, show_spinner=False)
def station_direction(city_code, node_id):
  """정류장을 지나는 노선들의 다음 정류장 중 가장 많은 것을 방향으로 본다."""
  routes = station_routes(city_code, node_id)
  nexts = []
  for route in routes[:3]:
    stops = get_route_stops(city_code, route.get("routeid"))
    for i, stop in enumerate(stops):
      if stop.get("nodeid") == node_id:
        if i + 1 < len(stops):
          nexts.append(stops[i + 1].get("nodenm"))
        break
  return Counter(nexts).most_common(1)[0][0] if nexts else ""


def add_directions(stations, limit=10):
  """후보 정류장들의 진행 방향을 병렬로 구해 station['dir']에 넣는다."""
  targets = stations[:limit]

  def work(station):
    try:
      return station_direction(station["citycode"], station["nodeid"])
    except ApiError:
      return ""

  with st.spinner("승강장 방향 확인 중..."):
    with ThreadPoolExecutor(max_workers=8) as pool:
      for station, direction in zip(targets, pool.map(work, targets)):
        station["dir"] = direction


def _station_label(s):
  label = f"{s['nodenm']} (ARS: {s['nodeno']})"
  if s.get("dir"):
    label += f" → {s['dir']} 방향"
  if s.get("dist") is not None:
    label += f" · {_fmt_dist(s['dist'])}"
  return label


def _pick(stations, key):
  add_directions(stations)
  options = {}
  for st_ in stations:
    label = _station_label(st_)
    if label in options:
      label = f"{label} [{st_['nodeid']}]"
    options[label] = st_
  label = st.selectbox(
      "탑승할 승강장을 선택하세요 (→ 진행 방향)", list(options.keys()), key=key
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
  return _pick(stations, key)


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
  return _pick(stations, key)


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


def show_bus_location(station, arrivals, contexts, key, preferred_route=None):
  st.markdown("### 🗺️ 버스 위치 보기")
  options = {}
  # 경로 안내에서 고른 버스를 맨 앞에
  arrivals = sorted(arrivals, key=lambda a: a.get("routeid") != preferred_route)
  for item in arrivals:
    sec = _to_int(item.get("arrtime"))
    label = f"{item.get('routeno')}번 · 약 {sec // 60}분 후 도착"
    options.setdefault(label, item)
  label = st.selectbox(
      "위치를 볼 버스를 선택하세요",
      list(options.keys()),
      key=f"{key}_{preferred_route}",
  )
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
    # 이미 지나간 버스는 가장 최근에 지나간 1대만 남긴다
    passed = [b for b in buses if b["_ord"] > ctx["ord"]]
    if passed:
      last_passed = min(passed, key=lambda b: b["_ord"])
      buses = [b for b in buses if b["_ord"] <= ctx["ord"] or b is last_passed]

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


@st.cache_data(ttl=86400, show_spinner=False)
def _geocode(query, near):
  lat, lon = near
  res = requests.get(
      "https://nominatim.openstreetmap.org/search",
      params={
          "q": query,
          "format": "json",
          "countrycodes": "kr",
          "limit": 5,
          "accept-language": "ko",
          # 출발지 주변(약 ±50km) 결과를 우선
          "viewbox": f"{lon - 0.5},{lat + 0.5},{lon + 0.5},{lat - 0.5}",
          "bounded": 0,
      },
      headers={"User-Agent": "chungju-bus-streamlit-app"},
      timeout=TIMEOUT,
  )
  res.raise_for_status()
  return [
      {
          "name": r.get("name") or query,
          "addr": ", ".join(r.get("display_name", "").split(", ")[1:4]),
          "lat": float(r["lat"]),
          "lon": float(r["lon"]),
      }
      for r in res.json()
  ]


def geocode(query, near):
  """도착지 이름 → 좌표 후보 (OpenStreetMap). 실패 시 빈 목록 (캐시하지 않음)."""
  try:
    return _geocode(query, (round(near[0], 1), round(near[1], 1)))
  except (requests.RequestException, ValueError, KeyError):
    return []


def naver_route_url(station, place):
  params = urllib.parse.urlencode({
      "slat": station["lat"],
      "slng": station["lon"],
      "sname": station["nodenm"],
      "dlat": place["lat"],
      "dlng": place["lon"],
      "dname": place["name"],
      "appname": "chungju-bus.streamlit.app",
  })
  user_agent = st.context.headers.get("User-Agent", "")
  if "Android" in user_agent:
    # 앱이 없으면 플레이스토어 네이버지도 페이지로 이동
    return (
        f"intent://route/public?{params}"
        "#Intent;scheme=nmap;package=com.nhn.android.nmap;end"
    )
  if any(k in user_agent for k in ("iPhone", "iPad", "iPod")):
    return f"nmap://route/public?{params}"
  return None


def dest_stops_by_name(city_code, query, limit=8):
  """이름에 도착지 이름이 들어간 정류장 (예: '오창' → 오창터미널, 오창읍사무소)."""
  q = _norm(query)
  if len(q) < 2:
    return []
  try:
    stations = all_stations(city_code)
  except ApiError:
    return []
  hits = []
  for s in stations:
    n = _norm(s.get("nodenm"))
    if q in n or (len(n) >= 3 and n in q):
      hits.append((match_score(query, s.get("nodenm")), s))
  hits.sort(key=lambda x: x[0], reverse=True)
  stops = [_station(s, city_code) for _, s in hits[:limit]]
  return [s for s in stops if s["lat"] and s["lon"]]


def pick_destination(station, destination):
  """도착지 이름을 좌표와 도착 후보 정류장으로 바꾼다. 못 찾으면 네이버지도 검색 버튼만."""
  dest = destination.strip()
  if not dest:
    st.caption("도착지를 입력하면 경로 안내와 네이버지도 길찾기를 볼 수 있습니다.")
    return None
  if not (station["lat"] and station["lon"]):
    return None

  places = geocode(dest, (station["lat"], station["lon"]))
  name_stops = dest_stops_by_name(station["citycode"], dest)

  if places:
    place = places[0]
    if len(places) > 1:
      options = {f"{p['name']} · {p['addr']}": p for p in places}
      place = options[
          st.selectbox("도착지를 선택하세요", list(options.keys()), key="dest_pick")
      ]
    place = dict(place)
  elif name_stops:
    first = name_stops[0]
    place = {"name": dest, "addr": "", "lat": first["lat"], "lon": first["lon"]}
  else:
    st.link_button(
        f"🗺️ 네이버지도에서 '{dest}' 찾기",
        "https://map.naver.com/p/search/" + urllib.parse.quote(dest),
        width="stretch",
    )
    return None

  # 도착 지점: 지도 위치 + 이름이 맞는 정류장들 (지역 이름으로 검색해도 찾도록)
  place["dest_stops"] = name_stops
  return place


def show_naver_buttons(station, place):
  url = naver_route_url(station, place)
  if url:
    st.link_button(
        f"🧭 네이버지도로 길찾기: {station['nodenm']} → {place['name']}",
        url,
        width="stretch",
    )
  st.link_button(
      f"🗺️ 네이버지도 웹에서 '{place['name']}' 찾기",
      "https://map.naver.com/p/search/" + urllib.parse.quote(place["name"]),
      width="stretch",
  )


# ------------------------------------------
# 시내버스 경로 계산 (직행 + 1회 환승)
# ------------------------------------------
MAX_WALK_M = 800  # 하차 후 도착지까지 최대 도보
TRANSFER_WALK_M = 200  # 환승 시 최대 도보
SIBLING_STOP_M = 200  # 함께 고려할 근처 승강장 범위
MAX_RIDE_STOPS = 70
MIN_PER_STOP = 1.5
WALK_M_PER_MIN = 70
TRANSFER_PENALTY_MIN = 8


def _fetch_all(fn, args_list):
  """API 함수를 병렬 호출한다. 실패한 호출은 None."""

  def safe(args):
    try:
      return fn(*args)
    except ApiError:
      return None

  with ThreadPoolExecutor(max_workers=8) as pool:
    return list(pool.map(safe, args_list))


def _pt(stop):
  return _to_float(stop.get("gpslati")), _to_float(stop.get("gpslong"))


def _dist(a, b):
  d = distance_m(a[0], a[1], b[0], b[1])
  return 1e9 if d is None else d


def _routes_through(stations):
  """정류장들을 지나는 노선과 노선별 정류장 목록. {(city, routeid): (route, stops)}"""
  route_lists = _fetch_all(
      station_routes, [(s["citycode"], s["nodeid"]) for s in stations]
  )
  routes = {}
  for s, rs in zip(stations, route_lists):
    for r in rs or []:
      routes.setdefault((s["citycode"], r.get("routeid")), r)
  keys = list(routes)
  stop_lists = _fetch_all(get_route_stops, keys)
  return {
      k: (routes[k], stops) for k, stops in zip(keys, stop_lists) if stops
  }


def _nearby(lat, lon, limit):
  try:
    items = nearby_stations(round(lat, 4), round(lon, 4))
  except ApiError:
    return []
  stations = [_station(s, "") for s in items]
  stations = [s for s in stations if s["lat"] and s["citycode"]]
  stations.sort(key=lambda s: distance_m(lat, lon, s["lat"], s["lon"]))
  return stations[:limit]


def _leg(route, stops, i, j, city):
  return {
      "routeno": route.get("routeno"),
      "routeid": route.get("routeid"),
      "city": city,
      "stops": stops[i : j + 1],
  }


@st.cache_data(ttl=600, show_spinner=False)
def plan_routes(start, place):
  """출발 승강장 → 도착지 시내버스 경로 후보 (최대 3개)."""
  targets = [(place["lat"], place["lon"])] + [
      (s["lat"], s["lon"]) for s in place.get("dest_stops", [])
  ]

  def walk_to_dest(stop):
    p = _pt(stop)
    return min(_dist(p, t) for t in targets)

  # 출발: 선택한 승강장 + 길 건너 등 근처 승강장
  starts = [start] + [
      s
      for s in _nearby(start["lat"], start["lon"], 6)
      if s["nodeid"] != start["nodeid"]
      and distance_m(start["lat"], start["lon"], s["lat"], s["lon"]) <= SIBLING_STOP_M
  ]
  start_by_id = {s["nodeid"]: s for s in starts}
  a_routes = _routes_through(starts)

  # 도착지 근처 정류장과 이름이 맞는 정류장을 지나는 노선 (환승용)
  dest_side = _nearby(place["lat"], place["lon"], 6)
  seen_ids = {s["nodeid"] for s in dest_side}
  dest_side += [s for s in place.get("dest_stops", []) if s["nodeid"] not in seen_ids]
  b_routes = _routes_through(dest_side)

  options = []

  # 출발 노선별로 승차 지점과 앞으로 지날 정류장
  a_legs = []
  for (city, _), (route, stops) in a_routes.items():
    for i, stop in enumerate(stops):
      if stop.get("nodeid") in start_by_id:
        a_legs.append((city, route, stops, i, start_by_id[stop.get("nodeid")]))
        break

  def walk_from_start(board):
    return distance_m(start["lat"], start["lon"], board["lat"], board["lon"]) or 0

  # 직행
  for city, route, stops, i, board in a_legs:
    ahead = range(i + 1, min(len(stops), i + 1 + MAX_RIDE_STOPS))
    if not ahead:
      continue
    j = min(ahead, key=lambda j: walk_to_dest(stops[j]))
    walk_end = walk_to_dest(stops[j])
    if walk_end > MAX_WALK_M:
      continue
    walk_start = walk_from_start(board)
    cost = (j - i) * MIN_PER_STOP + (walk_end + walk_start) / WALK_M_PER_MIN
    options.append({
        "legs": [_leg(route, stops, i, j, city)],
        "board": board,
        "walk_start": walk_start,
        "walk_transfer": 0,
        "walk_end": walk_end,
        "cost": cost,
    })

  # 1회 환승: 도착지 쪽 노선의 하차 지점과 그 이전 정류장 격자 색인
  grid = {}
  b_info = []
  for (city, _), (route, stops) in b_routes.items():
    k = min(range(len(stops)), key=lambda k: walk_to_dest(stops[k]))
    walk_end = walk_to_dest(stops[k])
    if walk_end > MAX_WALK_M or k == 0:
      continue
    b_idx = len(b_info)
    b_info.append((city, route, stops, k, walk_end))
    for i2 in range(max(0, k - MAX_RIDE_STOPS), k):
      lat, lon = _pt(stops[i2])
      if lat is None:
        continue
      cell = (round(lat / 0.002), round(lon / 0.002))
      grid.setdefault(cell, []).append((b_idx, i2))

  best_transfer = {}
  for city, route, stops, i, board in a_legs:
    walk_start = walk_from_start(board)
    for j in range(i + 1, min(len(stops), i + 1 + MAX_RIDE_STOPS)):
      lat, lon = _pt(stops[j])
      if lat is None:
        continue
      cy, cx = round(lat / 0.002), round(lon / 0.002)
      for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
          for b_idx, i2 in grid.get((cy + dy, cx + dx), []):
            b_city, b_route, b_stops, k, walk_end = b_info[b_idx]
            # 두 번째 버스를 출발지에서 바로 탈 수 있으면 환승할 이유가 없다
            if (b_city, b_route.get("routeid")) in a_routes:
              continue
            walk_tr = _dist((lat, lon), _pt(b_stops[i2]))
            if walk_tr > TRANSFER_WALK_M:
              continue
            cost = (
                ((j - i) + (k - i2)) * MIN_PER_STOP
                + (walk_start + walk_tr + walk_end) / WALK_M_PER_MIN
                + TRANSFER_PENALTY_MIN
            )
            key = (route.get("routeid"), b_route.get("routeid"))
            if key not in best_transfer or cost < best_transfer[key]["cost"]:
              best_transfer[key] = {
                  "legs": [
                      _leg(route, stops, i, j, city),
                      _leg(b_route, b_stops, i2, k, b_city),
                  ],
                  "board": board,
                  "walk_start": walk_start,
                  "walk_transfer": walk_tr,
                  "walk_end": walk_end,
                  "cost": cost,
              }
  options.extend(best_transfer.values())

  # 첫 버스가 같은 후보는 가장 좋은 것만, 최대 3개
  options.sort(key=lambda o: o["cost"])
  picked, seen = [], set()
  for o in options:
    sig = tuple(leg["routeno"] for leg in o["legs"])
    if sig in seen:
      continue
    seen.add(sig)
    picked.append(o)
    if len(picked) == 3:
      break
  return picked


def _stop_label(stop):
  no = stop.get("nodeno")
  return f"{stop.get('nodenm')}" + (f" (ARS {no})" if no else "")


def _fmt_walk(m):
  return f"약 {int(round(m / 10) * 10)}m (도보 {max(1, round(m / WALK_M_PER_MIN))}분)"


def _option_title(o):
  buses = " → ".join(f"{leg['routeno']}번" for leg in o["legs"])
  kind = "직행" if len(o["legs"]) == 1 else "1회 환승"
  n = sum(len(leg["stops"]) - 1 for leg in o["legs"])
  return f"{buses} ({kind}) · {n}개 정류장 · 약 {round(o['cost'])}분"


ROUTE_COLORS = {
    "board": [20, 170, 60],  # 초록: 승차
    "transfer": [255, 140, 0],  # 주황: 환승
    "alight": [230, 30, 30],  # 빨강: 하차
    "dest": [130, 60, 200],  # 보라: 도착지
}
LEG_COLORS = [[20, 100, 230], [0, 170, 170]]  # 1번째 버스 파랑, 2번째 버스 청록


def show_route_guide(station, place, arrivals):
  """출발 승강장 → 도착지 시내버스 경로 안내. 선택한 경로의 첫 노선 id를 돌려준다."""
  st.markdown(f"### 🚏 경로 안내: {station['nodenm']} → {place['name']}")
  if not (station["lat"] and station["lon"]):
    st.info("이 정류장의 위치 정보가 없어 경로를 계산할 수 없습니다.")
    return None

  with st.spinner("시내버스 경로 찾는 중... (처음에는 10초 정도 걸릴 수 있어요)"):
    try:
      options = plan_routes(station, place)
    except Exception as e:  # 경로 계산 실패가 화면 전체를 멈추지 않도록
      st.warning(f"경로를 계산하지 못했습니다: {e}")
      return None

  if not options:
    st.info(
        "시내버스로 갈 수 있는 경로(직행 또는 1회 환승)를 찾지 못했습니다."
        " 다른 지역이나 먼 곳이라면 아래 네이버지도 길찾기를 이용하세요."
    )
    return None

  titles = [f"{n}. {_option_title(o)}" for n, o in enumerate(options, 1)]
  choice = st.radio("경로 선택", titles, key="route_choice")
  o = options[titles.index(choice)]

  arrival_by_route = {}
  for a in arrivals:
    arrival_by_route.setdefault(a.get("routeid"), a)

  steps = []
  board = o["board"]
  first = o["legs"][0]
  if board["nodeid"] != station["nodeid"]:
    steps.append(
        f"🚶 근처 **{board['nodenm']}** 승강장(ARS {board['nodeno']})으로 이동하세요"
        f" — {_fmt_walk(o['walk_start'])}"
    )

  for n, leg in enumerate(o["legs"]):
    on, off = leg["stops"][0], leg["stops"][-1]
    rides = len(leg["stops"]) - 1
    toward = leg["stops"][1].get("nodenm") if rides >= 1 else ""
    if n == 0:
      wait = ""
      a = arrival_by_route.get(leg["routeid"]) if board["nodeid"] == station["nodeid"] else None
      if a:
        wait = f" — ⏱ 약 {_to_int(a.get('arrtime')) // 60}분 후 도착"
      steps.append(
          f"🟢 **{_stop_label(on)}**에서 **{leg['routeno']}번** 승차"
          f" ({toward} 방향){wait}"
      )
    else:
      prev_off = o["legs"][n - 1]["stops"][-1]
      if prev_off.get("nodeid") == on.get("nodeid"):
        where = "같은 정류장에서"
      else:
        where = f"{_fmt_walk(o['walk_transfer'])} 걸어서 **{_stop_label(on)}**에서"
      steps.append(
          f"🟠 **환승**: {where} **{leg['routeno']}번** 승차 ({toward} 방향)"
      )
    before = leg["stops"][-2].get("nodenm") if rides >= 2 else None
    bell = f" — 🔔 '{before}' 지나면 하차벨" if before else ""
    icon = "🔴" if n == len(o["legs"]) - 1 else "🟠"
    steps.append(
        f"🚌 {rides}개 정류장 이동 → {icon} **{_stop_label(off)}** 하차{bell}"
    )
  if o["walk_end"] < 50:
    steps.append(f"🏁 **{place['name']}** 도착")
  else:
    steps.append(
        f"🏁 **{place['name']}**까지 걸어서 {_fmt_walk(o['walk_end'])}"
    )
  st.markdown("\n".join(f"{n}. {step}" for n, step in enumerate(steps, 1)))

  for leg in o["legs"]:
    with st.expander(f"🚌 {leg['routeno']}번 지나는 정류장 보기 ({len(leg['stops']) - 1}개)"):
      names = [s.get("nodenm") for s in leg["stops"]]
      st.markdown(
          "\n".join(
              f"- {'**' + nm + '** (승차)' if i == 0 else '**' + nm + '** (하차)' if i == len(names) - 1 else nm}"
              for i, nm in enumerate(names)
          )
      )

  show_route_map(o, place)
  return first["routeid"] if board["nodeid"] == station["nodeid"] else None


def show_route_map(o, place):
  layers, points = [], []
  for n, leg in enumerate(o["legs"]):
    path = [[p[1], p[0]] for p in map(_pt, leg["stops"]) if p[0] is not None]
    if len(path) >= 2:
      layers.append(
          pdk.Layer(
              "PathLayer",
              data=[{"path": path, "label": f"{leg['routeno']}번"}],
              get_path="path",
              get_color=LEG_COLORS[n % 2],
              width_min_pixels=5,
              pickable=True,
          )
      )
    on, off = leg["stops"][0], leg["stops"][-1]
    last = n == len(o["legs"]) - 1
    for stop, kind, text in (
        (on, "board" if n == 0 else "transfer", f"{leg['routeno']}번 승차"),
        (off, "alight" if last else "transfer", f"{leg['routeno']}번 하차"),
    ):
      lat, lon = _pt(stop)
      if lat is not None:
        points.append({
            "lat": lat, "lon": lon, "kind": kind,
            "label": f"{text} · {stop.get('nodenm')}",
        })
  if o["walk_end"] >= 50:  # 하차 정류장이 곧 도착지면 따로 표시하지 않음
    points.append({
        "lat": place["lat"], "lon": place["lon"], "kind": "dest",
        "label": f"도착지 · {place['name']}",
    })
  pts = pd.DataFrame(points)
  for kind in ("board", "transfer", "alight", "dest"):
    group = pts[pts["kind"] == kind]
    if group.empty:
      continue
    layers.append(
        pdk.Layer(
            "ScatterplotLayer",
            data=group,
            get_position=["lon", "lat"],
            get_fill_color=ROUTE_COLORS[kind],
            get_radius=40,
            radius_min_pixels=9,
            radius_max_pixels=15,
            stroked=True,
            get_line_color=[255, 255, 255],
            line_width_min_pixels=2,
            pickable=True,
        )
    )
  legend = "🟢 **승차** · 🔴 **하차** · 🟣 **도착지** · 🟦 **버스 노선**"
  if len(o["legs"]) > 1:
    legend = "🟢 **승차** · 🟠 **환승** · 🔴 **하차** · 🟣 **도착지** · 🟦 **1번째 버스** · 🩵 **2번째 버스**"
  st.markdown("경로 지도: " + legend)
  st.pydeck_chart(
      pdk.Deck(
          layers=layers,
          initial_view_state=pdk.ViewState(
              latitude=pts["lat"].mean(), longitude=pts["lon"].mean(), zoom=12
          ),
          tooltip={"text": "{label}"},
      )
  )


city_dict, city_err = get_city_list()
if city_err:
  st.warning(f"도시 목록을 불러오지 못해 기본 목록을 사용합니다.\n\n{city_err}")

default_idx = 0
for idx, name in enumerate(city_dict.keys()):
  if "청주" in name:
    default_idx = idx
    break

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
    "도착지 (네이버지도 대중교통 길찾기용)",
    value="",
    placeholder="예: 대전역, 서울고속버스터미널, 청주롯데아울렛",
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
  preferred = None
  place = pick_destination(station, destination)
  if place:
    preferred = show_route_guide(station, place, arrivals)
    show_naver_buttons(station, place)
  if arrivals:
    show_bus_location(
        station, arrivals, contexts, key="bus_t1", preferred_route=preferred
    )
  if st.button("🔄 새로고침", key="refresh_t1"):
    st.rerun()
