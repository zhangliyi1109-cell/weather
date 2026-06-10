"""
二十四节气历法模块

用于弥补 Open-Meteo 仅 16 天数值预报的局限：节气提供约 15 天一节气的
中长期气候与穿搭/备货节奏参考，与短期数值预报互补。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# 按公历年中出现顺序（小寒通常跨年，表中按「当年」节气序列存储）
SOLAR_TERM_NAMES: Tuple[str, ...] = (
    "小寒", "大寒", "立春", "雨水", "惊蛰", "春分",
    "清明", "谷雨", "立夏", "小满", "芒种", "夏至",
    "小暑", "大暑", "立秋", "处暑", "白露", "秋分",
    "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
)

# 权威历表摘录（中国气象局/万年历，用于 2024–2031；其余年份走近似公式）
_YEAR_TERM_DATES: Dict[int, List[Tuple[str, str]]] = {
    2024: [
        ("小寒", "2024-01-06"), ("大寒", "2024-01-20"), ("立春", "2024-02-04"),
        ("雨水", "2024-02-19"), ("惊蛰", "2024-03-05"), ("春分", "2024-03-20"),
        ("清明", "2024-04-04"), ("谷雨", "2024-04-19"), ("立夏", "2024-05-05"),
        ("小满", "2024-05-20"), ("芒种", "2024-06-05"), ("夏至", "2024-06-21"),
        ("小暑", "2024-07-06"), ("大暑", "2024-07-22"), ("立秋", "2024-08-07"),
        ("处暑", "2024-08-22"), ("白露", "2024-09-07"), ("秋分", "2024-09-22"),
        ("寒露", "2024-10-08"), ("霜降", "2024-10-23"), ("立冬", "2024-11-07"),
        ("小雪", "2024-11-22"), ("大雪", "2024-12-06"), ("冬至", "2024-12-21"),
    ],
    2025: [
        ("小寒", "2025-01-05"), ("大寒", "2025-01-20"), ("立春", "2025-02-03"),
        ("雨水", "2025-02-18"), ("惊蛰", "2025-03-05"), ("春分", "2025-03-20"),
        ("清明", "2025-04-04"), ("谷雨", "2025-04-20"), ("立夏", "2025-05-05"),
        ("小满", "2025-05-21"), ("芒种", "2025-06-05"), ("夏至", "2025-06-21"),
        ("小暑", "2025-07-07"), ("大暑", "2025-07-22"), ("立秋", "2025-08-07"),
        ("处暑", "2025-08-23"), ("白露", "2025-09-07"), ("秋分", "2025-09-23"),
        ("寒露", "2025-10-08"), ("霜降", "2025-10-23"), ("立冬", "2025-11-07"),
        ("小雪", "2025-11-22"), ("大雪", "2025-12-07"), ("冬至", "2025-12-21"),
    ],
    2026: [
        ("小寒", "2026-01-05"), ("大寒", "2026-01-20"), ("立春", "2026-02-04"),
        ("雨水", "2026-02-18"), ("惊蛰", "2026-03-05"), ("春分", "2026-03-20"),
        ("清明", "2026-04-05"), ("谷雨", "2026-04-20"), ("立夏", "2026-05-05"),
        ("小满", "2026-05-21"), ("芒种", "2026-06-05"), ("夏至", "2026-06-21"),
        ("小暑", "2026-07-07"), ("大暑", "2026-07-23"), ("立秋", "2026-08-07"),
        ("处暑", "2026-08-23"), ("白露", "2026-09-07"), ("秋分", "2026-09-23"),
        ("寒露", "2026-10-08"), ("霜降", "2026-10-23"), ("立冬", "2026-11-07"),
        ("小雪", "2026-11-22"), ("大雪", "2026-12-07"), ("冬至", "2026-12-22"),
    ],
    2027: [
        ("小寒", "2027-01-05"), ("大寒", "2027-01-20"), ("立春", "2027-02-04"),
        ("雨水", "2027-02-19"), ("惊蛰", "2027-03-06"), ("春分", "2027-03-21"),
        ("清明", "2027-04-05"), ("谷雨", "2027-04-20"), ("立夏", "2027-05-06"),
        ("小满", "2027-05-21"), ("芒种", "2027-06-06"), ("夏至", "2027-06-21"),
        ("小暑", "2027-07-07"), ("大暑", "2027-07-23"), ("立秋", "2027-08-08"),
        ("处暑", "2027-08-23"), ("白露", "2027-09-08"), ("秋分", "2027-09-23"),
        ("寒露", "2027-10-08"), ("霜降", "2027-10-23"), ("立冬", "2027-11-07"),
        ("小雪", "2027-11-22"), ("大雪", "2027-12-07"), ("冬至", "2027-12-22"),
    ],
    2028: [
        ("小寒", "2028-01-06"), ("大寒", "2028-01-20"), ("立春", "2028-02-04"),
        ("雨水", "2028-02-19"), ("惊蛰", "2028-03-05"), ("春分", "2028-03-20"),
        ("清明", "2028-04-04"), ("谷雨", "2028-04-19"), ("立夏", "2028-05-05"),
        ("小满", "2028-05-20"), ("芒种", "2028-06-05"), ("夏至", "2028-06-21"),
        ("小暑", "2028-07-06"), ("大暑", "2028-07-22"), ("立秋", "2028-08-07"),
        ("处暑", "2028-08-22"), ("白露", "2028-09-07"), ("秋分", "2028-09-22"),
        ("寒露", "2028-10-08"), ("霜降", "2028-10-23"), ("立冬", "2028-11-07"),
        ("小雪", "2028-11-22"), ("大雪", "2028-12-06"), ("冬至", "2028-12-21"),
    ],
    2029: [
        ("小寒", "2029-01-05"), ("大寒", "2029-01-20"), ("立春", "2029-02-03"),
        ("雨水", "2029-02-18"), ("惊蛰", "2029-03-05"), ("春分", "2029-03-20"),
        ("清明", "2029-04-04"), ("谷雨", "2029-04-20"), ("立夏", "2029-05-05"),
        ("小满", "2029-05-21"), ("芒种", "2029-06-05"), ("夏至", "2029-06-21"),
        ("小暑", "2029-07-07"), ("大暑", "2029-07-22"), ("立秋", "2029-08-07"),
        ("处暑", "2029-08-23"), ("白露", "2029-09-07"), ("秋分", "2029-09-23"),
        ("寒露", "2029-10-08"), ("霜降", "2029-10-23"), ("立冬", "2029-11-07"),
        ("小雪", "2029-11-22"), ("大雪", "2029-12-07"), ("冬至", "2029-12-21"),
    ],
    2030: [
        ("小寒", "2030-01-05"), ("大寒", "2030-01-20"), ("立春", "2030-02-04"),
        ("雨水", "2030-02-18"), ("惊蛰", "2030-03-05"), ("春分", "2030-03-20"),
        ("清明", "2030-04-05"), ("谷雨", "2030-04-20"), ("立夏", "2030-05-05"),
        ("小满", "2030-05-21"), ("芒种", "2030-06-05"), ("夏至", "2030-06-21"),
        ("小暑", "2030-07-07"), ("大暑", "2030-07-23"), ("立秋", "2030-08-07"),
        ("处暑", "2030-08-23"), ("白露", "2030-09-07"), ("秋分", "2030-09-23"),
        ("寒露", "2030-10-08"), ("霜降", "2030-10-23"), ("立冬", "2030-11-07"),
        ("小雪", "2030-11-22"), ("大雪", "2030-12-07"), ("冬至", "2030-12-22"),
    ],
    2031: [
        ("小寒", "2031-01-05"), ("大寒", "2031-01-20"), ("立春", "2031-02-04"),
        ("雨水", "2031-02-18"), ("惊蛰", "2031-03-05"), ("春分", "2031-03-20"),
        ("清明", "2031-04-05"), ("谷雨", "2031-04-20"), ("立夏", "2031-05-05"),
        ("小满", "2031-05-21"), ("芒种", "2031-06-05"), ("夏至", "2031-06-21"),
        ("小暑", "2031-07-07"), ("大暑", "2031-07-23"), ("立秋", "2031-08-07"),
        ("处暑", "2031-08-23"), ("白露", "2031-09-07"), ("秋分", "2031-09-23"),
        ("寒露", "2031-10-08"), ("霜降", "2031-10-23"), ("立冬", "2031-11-07"),
        ("小雪", "2031-11-22"), ("大雪", "2031-12-07"), ("冬至", "2031-12-22"),
    ],
}

# 每节气的穿搭/备货指导（中长期，非逐日气温）
TERM_GUIDANCE: Dict[str, Dict[str, Any]] = {
    "小寒": {"temp_band": "严寒", "focus": ["羽绒服", "大衣", "针织衫"], "tip": "一年中最冷时段之一，厚羽绒与大衣为主力。"},
    "大寒": {"temp_band": "严寒", "focus": ["羽绒服", "大衣", "卫衣"], "tip": "岁末严寒，清仓冬装与春装预告可并行准备。"},
    "立春": {"temp_band": "偏冷", "focus": ["风衣", "针织衫", "西装"], "tip": "万物复苏，薄外套与针织过渡，南北温差大需分货。"},
    "雨水": {"temp_band": "偏冷", "focus": ["风衣", "衬衫", "针织衫"], "tip": "降水增多，防泼水外套与快干内搭权重上升。"},
    "惊蛰": {"temp_band": "偏凉", "focus": ["风衣", "短外套", "衬衫"], "tip": "乍暖还寒，可叠穿；虫害苏醒象征春季营销节点。"},
    "春分": {"temp_band": "温和", "focus": ["西装", "衬衫", "连衣裙"], "tip": "昼夜平分，春装主力波段，连衣裙与半裙加大曝光。"},
    "清明": {"temp_band": "温和", "focus": ["风衣", "衬衫", "休闲裤"], "tip": "踏青出行，轻薄外套与舒适裤装需求旺。"},
    "谷雨": {"temp_band": "温和", "focus": ["衬衫", "T恤", "连衣裙"], "tip": "雨生百谷，雨具与透气面料并重。"},
    "立夏": {"temp_band": "偏热", "focus": ["T恤", "连衣裙", "衬衫"], "tip": "正式入夏信号，短袖与裙装占比提升。"},
    "小满": {"temp_band": "偏热", "focus": ["T恤", "连衣裙", "半身裙"], "tip": "气温爬升，薄款针织与短袖并行。"},
    "芒种": {"temp_band": "炎热", "focus": ["T恤", "背心/吊带", "连衣裙"], "tip": "梅雨前后南方闷热，透气速干优先。"},
    "夏至": {"temp_band": "炎热", "focus": ["T恤", "背心/吊带", "连衣裙"], "tip": "白昼最长，防晒与超薄面料旺季。"},
    "小暑": {"temp_band": "炎热", "focus": ["T恤", "背心/吊带", "休闲裤"], "tip": "初伏前后，盛夏爆款冲刺窗口。"},
    "大暑": {"temp_band": "酷热", "focus": ["T恤", "背心/吊带", "半身裙"], "tip": "一年最热，清凉款与高转化低价引流款。"},
    "立秋": {"temp_band": "偏热", "focus": ["衬衫", "连衣裙", "针织衫"], "tip": "秋老虎，短袖仍卖但需预告秋装。"},
    "处暑": {"temp_band": "温和", "focus": ["针织衫", "衬衫", "风衣"], "tip": "暑气渐消，针织与薄风衣开始起量。"},
    "白露": {"temp_band": "偏凉", "focus": ["风衣", "针织衫", "西装"], "tip": "昼夜温差大，叠穿与外套组合推荐。"},
    "秋分": {"temp_band": "偏凉", "focus": ["风衣", "卫衣", "牛仔裤"], "tip": "秋装主力，牛仔与卫衣转化窗口。"},
    "寒露": {"temp_band": "偏冷", "focus": ["风衣", "大衣", "针织衫"], "tip": "露气寒冷，外套厚度明显提升。"},
    "霜降": {"temp_band": "偏冷", "focus": ["大衣", "风衣", "针织衫"], "tip": "深秋向冬过渡，大衣与羽绒预售。"},
    "立冬": {"temp_band": "寒冷", "focus": ["大衣", "羽绒服", "针织衫"], "tip": "入冬节点，羽绒与大衣为核心备货。"},
    "小雪": {"temp_band": "寒冷", "focus": ["羽绒服", "大衣", "卫衣"], "tip": "北方供暖前后，保暖品类加大备货。"},
    "大雪": {"temp_band": "严寒", "focus": ["羽绒服", "大衣", "配饰"], "tip": "深冬将至，厚款与围巾手套类搭配销售。"},
    "冬至": {"temp_band": "严寒", "focus": ["羽绒服", "大衣", "针织衫"], "tip": "数九开始，冬装清仓与春装样衣可同步规划。"},
}

SPRING_TERMS = frozenset({"立春", "雨水", "惊蛰", "春分", "清明", "谷雨"})
SUMMER_TERMS = frozenset({"立夏", "小满", "芒种", "夏至", "小暑", "大暑"})
AUTUMN_TERMS = frozenset({"立秋", "处暑", "白露", "秋分", "寒露", "霜降"})
WINTER_TERMS = frozenset({"立冬", "小雪", "大雪", "冬至", "小寒", "大寒"})


def _parse_ymd(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _approximate_year_terms(year: int) -> List[Tuple[str, date]]:
    """无历表年份：以 2025 为基准平移（误差通常 ±1 天，仅作兜底）。"""
    base_year = 2025
    base = _YEAR_TERM_DATES[base_year]
    delta_years = year - base_year
    out: List[Tuple[str, date]] = []
    for name, ds in base:
        d = _parse_ymd(ds)
        try:
            shifted = d.replace(year=year)
        except ValueError:
            shifted = d.replace(year=year, day=28)
        # 粗略闰年校正：每 4 年节气整体略漂移
        shifted += timedelta(days=delta_years // 4)
        out.append((name, shifted))
    return out


def get_year_term_events(year: int) -> List[Tuple[str, date]]:
    """返回某年 24 个节气的 (名称, 日期)，按时间升序。"""
    if year in _YEAR_TERM_DATES:
        return [(n, _parse_ymd(d)) for n, d in _YEAR_TERM_DATES[year]]
    return _approximate_year_terms(year)


def _build_timeline(around: date) -> List[Tuple[str, date]]:
    """跨年连续时间线：用于定位「当前节气」。"""
    events: List[Tuple[str, date]] = []
    for y in (around.year - 1, around.year, around.year + 1):
        events.extend(get_year_term_events(y))
    events.sort(key=lambda x: x[1])
    # 去重：同名同年只保留一次
    seen = set()
    uniq: List[Tuple[str, date]] = []
    for name, d in events:
        key = (name, d)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((name, d))
    return uniq


def get_solar_term_on(day: date) -> Dict[str, Any]:
    """
    查询某日所处的节气区间。
    返回当前节气名、起始日、下一节气、在节内第几天等。
    """
    timeline = _build_timeline(day)
    current_name = timeline[0][0]
    current_start = timeline[0][1]
    next_name: Optional[str] = None
    next_start: Optional[date] = None

    for i, (name, start) in enumerate(timeline):
        if start <= day:
            current_name = name
            current_start = start
            if i + 1 < len(timeline):
                next_name, next_start = timeline[i + 1]
        else:
            break

    if next_start is None:
        # 年末：取下一年小寒
        nxt = get_year_term_events(day.year + 1)[0]
        next_name, next_start = nxt[0], nxt[1]

    days_in_term = (day - current_start).days + 1
    days_until_next = (next_start - day).days if next_start else None
    term_length = (next_start - current_start).days if next_start else 15

    guidance = TERM_GUIDANCE.get(current_name, {})
    return {
        "name": current_name,
        "start_date": current_start.isoformat(),
        "day_in_term": days_in_term,
        "term_length_days": term_length,
        "next_name": next_name,
        "next_start_date": next_start.isoformat() if next_start else None,
        "days_until_next": days_until_next,
        "temp_band": guidance.get("temp_band", ""),
        "clothing_focus": guidance.get("focus", []),
        "guidance_tip": guidance.get("tip", ""),
    }


def infer_season_from_solar_term(term_name: str) -> str:
    """由节气推断 merchandising 季节（spring/summer/autumn/winter）。"""
    if term_name in SPRING_TERMS:
        return "spring"
    if term_name in SUMMER_TERMS:
        return "summer"
    if term_name in AUTUMN_TERMS:
        return "autumn"
    if term_name in WINTER_TERMS:
        return "winter"
    return "spring"


def get_upcoming_terms(from_day: date, limit: int = 4) -> List[Dict[str, Any]]:
    """未来若干节气节点（含当日所处节气之后的节点）。"""
    timeline = _build_timeline(from_day)
    upcoming: List[Dict[str, Any]] = []
    for name, start in timeline:
        if start < from_day:
            continue
        if start == from_day:
            continue
        g = TERM_GUIDANCE.get(name, {})
        upcoming.append({
            "name": name,
            "start_date": start.isoformat(),
            "days_away": (start - from_day).days,
            "temp_band": g.get("temp_band", ""),
            "clothing_focus": g.get("focus", []),
            "guidance_tip": g.get("tip", ""),
        })
        if len(upcoming) >= limit:
            break
    return upcoming


def build_solar_term_context(
    today: Optional[date] = None,
    forecast_horizon_days: int = 16,
    temp_trend: str = "stable",
) -> Dict[str, Any]:
    """
    构建节气上下文 + 超越数值预报窗口的中长期展望。

    forecast_horizon_days: Open-Meteo 可提供的日数（默认 16）
    """
    today = today or date.today()
    current = get_solar_term_on(today)
    season = infer_season_from_solar_term(current["name"])
    upcoming = get_upcoming_terms(today, limit=5)

    forecast_end = today + timedelta(days=forecast_horizon_days - 1)
    beyond_forecast: List[Dict[str, Any]] = []
    for item in upcoming:
        term_date = _parse_ymd(item["start_date"])
        if term_date > forecast_end:
            beyond_forecast.append(item)

    trend_note = {
        "rising": "数值预报显示短期升温，若与节气偏凉指引冲突，以近 7 日实况温度规则为准。",
        "falling": "数值预报显示短期降温，可与节气换季指引相互印证，加大外套/针织权重。",
        "stable": "短期气温平稳，节气节点可作为下一波段备货节奏的主要参考。",
    }.get(temp_trend, "")

    outlook_parts = [
        f"当前「{current['name']}」（第 {current['day_in_term']} 天），"
        f"{current.get('guidance_tip', '')}",
    ]
    if current.get("days_until_next") is not None:
        outlook_parts.append(
            f"约 {current['days_until_next']} 天后进入「{current['next_name']}」。"
        )
    if beyond_forecast:
        names = "、".join(f"「{t['name']}」({t['days_away']}天后)" for t in beyond_forecast[:3])
        outlook_parts.append(
            f"超出 {forecast_horizon_days} 天数值预报后，近期节气节点：{names}。"
        )
    if trend_note:
        outlook_parts.append(trend_note)

    return {
        "current": current,
        "season": season,
        "season_label": {"spring": "春季", "summer": "夏季", "autumn": "秋季", "winter": "冬季"}.get(season, season),
        "upcoming_terms": upcoming,
        "beyond_forecast_terms": beyond_forecast,
        "forecast_horizon_days": forecast_horizon_days,
        "outlook_summary": "".join(outlook_parts),
    }


def annotate_forecast_days(forecast: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """为逐日预报附加节气名称（若跨节气则标注新节气）。"""
    if not forecast:
        return forecast
    annotated = []
    prev_term: Optional[str] = None
    for day in forecast:
        ds = day.get("date") or day.get("fxDate")
        if not ds:
            annotated.append(day)
            continue
        try:
            d = _parse_ymd(str(ds)[:10])
        except ValueError:
            annotated.append(day)
            continue
        term = get_solar_term_on(d)
        name = term["name"]
        is_term_start = name != prev_term
        prev_term = name
        enriched = dict(day)
        enriched["solar_term"] = name
        enriched["solar_term_start"] = is_term_start
        annotated.append(enriched)
    return annotated
