"""
天气数据分析与智能产品推荐系统 V2
Flask后端应用
"""
from flask import Flask, render_template, jsonify, request, session
from flask_cors import CORS
from datetime import datetime
import threading
import time
import json
import os

from dotenv import load_dotenv

load_dotenv()

from weather_service import get_weather_service
from bi_data_service import get_bi_service, reset_bi_service
from feishu_service import get_feishu_service
from config import FEISHU_BITABLE

app = Flask(__name__)
CORS(app)
# 若 .env 里写了 APP_SECRET_KEY= 但留空，getenv 会得到 ""，Flask 会报 session 不可用
_secret = (os.getenv("APP_SECRET_KEY") or "").strip()
app.secret_key = _secret or "weather-v2-dev-secret"

USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "user": {"password": "user123", "role": "user"}
}

# 全局服务实例
weather_service = get_weather_service()

# 使用BI数据（已修复数据抓取问题）
# 设置为 False 使用模拟数据，True 使用BI数据（可用环境变量 USE_BI_DATA 覆盖）
USE_BI_DATA = os.getenv("USE_BI_DATA", "true").lower() in ("1", "true", "yes")
bi_service = reset_bi_service(use_bi_data=USE_BI_DATA)

feishu_service = get_feishu_service()

# 清除BI缓存，确保使用最新的映射关系
bi_service.clear_cache()

# 缓存数据
weather_cache = {}
cache_time = None
weather_last_refresh_date = None
bi_last_refresh_date = None


def get_cached_weather():
    """获取缓存的天气数据"""
    global weather_cache, cache_time
    
    # 缓存1小时
    if cache_time and (datetime.now() - cache_time).seconds < 3600 and weather_cache:
        return weather_cache
    
    # 获取新数据
    weather_cache = weather_service.get_all_cities_weather()
    cache_time = datetime.now()
    
    return weather_cache


def infer_season_by_month(month: int) -> str:
    """按月份推断季节"""
    if month in [12, 1, 2]:
        return "winter"
    if month in [3, 4, 5]:
        return "spring"
    if month in [6, 7, 8]:
        return "summer"
    return "autumn"


def calculate_avg_wind_scale(city_daily: list) -> float:
    """计算城市未来天气的平均风力等级"""
    values = []
    for d in city_daily:
        try:
            values.append(float(d.get("windScaleDay", 0)))
        except Exception:
            continue
    if not values:
        return 0
    return round(sum(values) / len(values), 2)


def calculate_national_rainy_city_count(weather_data: dict) -> int:
    """
    计算未来7天雨天数>=2的重点城市数量
    重点城市清单：北京、上海、广州、杭州、江苏
    注：当前配置城市以内的数据会参与统计。
    """
    major_cities = {"北京", "上海", "江苏", "浙江"}
    count = 0
    for city, data in weather_data.items():
        if city not in major_cities:
            continue
        daily = data.get("daily", [])[:7]
        rain_days = sum(1 for d in daily if int(d.get("precip", 0)) > 30)
        if rain_days >= 2:
            count += 1
    return count


def get_national_city_weights(city_names: list) -> dict:
    """
    全国推荐城市权重（直播大盘导向）：
    - 北京/上海/江苏/浙江为核心成交城市，给予更高权重
    - 其他城市作为补充信号，给予较低基础权重
    """
    focus_weights = {
        "北京": 0.30,
        "上海": 0.30,
        "江苏": 0.20,
        "浙江": 0.20
    }
    default_weight = 0.10

    raw_weights = {c: focus_weights.get(c, default_weight) for c in city_names}
    total = sum(raw_weights.values()) or 1.0
    return {c: raw_weights[c] / total for c in city_names}


def build_national_weather_context(weather_data: dict, trends: dict) -> dict:
    """
    构建全国综合天气上下文（用于全国统一直播推荐）
    - 不按单城市给不同方案
    - 基于所有城市未来天气综合得出一套推荐参数
    """
    if not weather_data:
        return {
            "avg_temp": 25,
            "rain_days": 0,
            "temp_trend": "stable",
            "temp_trend_desc": "气温平稳",
            "avg_humidity": 60,
            "avg_wind_scale": 3
        }

    city_names = list(weather_data.keys())
    city_count = len(city_names)
    city_weights = get_national_city_weights(city_names)

    # 1) 加权平均温度/湿度（重点城市权重更高）
    avg_temp = round(
        sum(city_weights[c] * trends.get(c, {}).get("avg_temp", 25) for c in city_names),
        1
    )
    avg_humidity = round(
        sum(city_weights[c] * trends.get(c, {}).get("avg_humidity", 60) for c in city_names),
        1
    )

    # 2) 加权全国雨天数
    rain_days = round(
        sum(city_weights[c] * trends.get(c, {}).get("rain_days", 0) for c in city_names)
    )

    # 3) 加权全国风力
    avg_wind_scale = round(
        sum(city_weights[c] * calculate_avg_wind_scale(weather_data[c].get("daily", [])) for c in city_names),
        2
    )

    # 4) 全国温度趋势（按“逐日全国平均最高温”计算）
    daily_temp_max_series = []
    for day_idx in range(16):
        day_values = []
        for c in city_names:
            daily = weather_data[c].get("daily", [])
            if day_idx < len(daily):
                try:
                    day_values.append(float(daily[day_idx].get("tempMax", 0)))
                except Exception:
                    continue
        if day_values:
            # 逐日“加权”全国平均最高温
            weighted_day_avg = 0.0
            weighted_sum = 0.0
            for c in city_names:
                daily = weather_data[c].get("daily", [])
                if day_idx < len(daily):
                    try:
                        tmax = float(daily[day_idx].get("tempMax", 0))
                    except Exception:
                        continue
                    w = city_weights.get(c, 0.0)
                    weighted_day_avg += tmax * w
                    weighted_sum += w
            if weighted_sum > 0:
                daily_temp_max_series.append(weighted_day_avg / weighted_sum)

    temp_trend = "stable"
    if len(daily_temp_max_series) >= 2:
        if daily_temp_max_series[-1] > daily_temp_max_series[0] + 3:
            temp_trend = "rising"
        elif daily_temp_max_series[-1] < daily_temp_max_series[0] - 3:
            temp_trend = "falling"

    trend_desc_map = {
        "rising": "升温趋势",
        "falling": "降温趋势",
        "stable": "气温平稳"
    }

    return {
        "avg_temp": avg_temp,
        "rain_days": rain_days,
        "temp_trend": temp_trend,
        "temp_trend_desc": trend_desc_map.get(temp_trend, "气温平稳"),
        "avg_humidity": avg_humidity,
        "avg_wind_scale": avg_wind_scale,
        "city_count": city_count,
        "city_weights": city_weights
    }


def refresh_weather_cache(force: bool = False):
    """刷新天气缓存（支持按天刷新）"""
    global weather_cache, cache_time, weather_last_refresh_date

    today = datetime.now().date()
    if not force and weather_last_refresh_date == today:
        return

    weather_cache = weather_service.get_all_cities_weather()
    cache_time = datetime.now()
    weather_last_refresh_date = today
    print(f"✓ 天气数据已刷新: {cache_time.isoformat()}")


def refresh_bi_cache(force: bool = False):
    """刷新BI缓存（支持按天刷新）"""
    global bi_last_refresh_date

    today = datetime.now().date()
    if not force and bi_last_refresh_date == today:
        return

    bi_service.clear_cache()
    # 预热一次，避免首次接口请求延迟
    _ = bi_service.fetch_bi_inventory_data()
    bi_last_refresh_date = today
    print(f"✓ BI数据已刷新: {datetime.now().isoformat()}")


def _daily_refresh_loop():
    """
    后台每日刷新任务：
    - 每天 06:00 刷新天气和 BI 数据
    """
    refresh_weather_cache(force=True)
    refresh_bi_cache(force=True)

    while True:
        now = datetime.now()
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if now >= target:
            # 次日 06:00
            seconds_until_next = (24 * 3600) - (
                now.hour * 3600 + now.minute * 60 + now.second
            ) + (6 * 3600)
        else:
            seconds_until_next = int((target - now).total_seconds())

        time.sleep(max(seconds_until_next, 60))

        try:
            refresh_weather_cache(force=True)
            refresh_bi_cache(force=True)
        except Exception as e:
            print(f"⚠️ 每日刷新失败: {e}")
            # 失败后 10 分钟重试
            time.sleep(600)


def start_background_scheduler():
    """启动后台每日刷新线程（仅启动一次）"""
    if getattr(app, "_daily_scheduler_started", False):
        return
    app._daily_scheduler_started = True
    t = threading.Thread(target=_daily_refresh_loop, daemon=True)
    t.start()


# 模块加载后即启动后台任务，兼容 gunicorn/uwsgi 启动方式
start_background_scheduler()


@app.route("/")
def index():
    """首页 - 渲染仪表板"""
    return render_template("index.html")


def _current_user():
    username = session.get("username")
    role = session.get("role")
    if not username or not role:
        return None
    return {"username": username, "role": role}


def _require_admin():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "error": "请先登录"}), 401
    if user.get("role") != "admin":
        return jsonify({"success": False, "error": "仅管理员可访问"}), 403
    return None


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    """登录接口"""
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    user = USERS.get(username)
    if not user or user.get("password") != password:
        return jsonify({"success": False, "error": "用户名或密码错误"}), 401

    session["username"] = username
    session["role"] = user.get("role", "user")
    return jsonify({
        "success": True,
        "data": {"username": username, "role": session["role"]}
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    """退出登录"""
    session.clear()
    return jsonify({"success": True})


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    """获取当前登录用户"""
    user = _current_user()
    if not user:
        return jsonify({"success": False, "error": "未登录"}), 401
    return jsonify({"success": True, "data": user})


@app.route("/api/weather")
def api_weather():
    """
    获取天气数据API
    
    Query Params:
        city: 城市名称（可选，默认返回所有城市）
    
    Returns:
        JSON格式的天气数据
    """
    try:
        city = request.args.get("city")
        
        # 获取天气数据
        weather_data = get_cached_weather()
        
        if not weather_data:
            return jsonify({
                "success": False,
                "error": "获取天气数据失败"
            }), 500
        
        # 如果指定了城市，只返回该城市数据
        if city and city in weather_data:
            weather_data = {city: weather_data[city]}
        
        # 格式化数据
        formatted_data = weather_service.format_for_api(weather_data)
        
        # 添加趋势分析
        trends = weather_service.analyze_weather_trends(weather_data)
        
        return jsonify({
            "success": True,
            "data": formatted_data,
            "trends": trends,
            "update_time": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/recommendations")
def api_recommendations():
    """
    获取智能产品推荐API
    
    Query Params:
        city: 城市名称（默认北京）
        avg_temp: 平均温度（可选，自动计算）
        rain_days: 降雨天数（可选，自动计算）
        temp_trend: 温度趋势（可选，自动计算）
    
    Returns:
        JSON格式的推荐数据
    """
    try:
        city = request.args.get("city", "北京")
        brand = request.args.get("brand", "all")
        
        # 获取天气数据
        weather_data = get_cached_weather()
        
        if city not in weather_data:
            return jsonify({
                "success": False,
                "error": f"未找到城市: {city}"
            }), 404

        # 全国综合趋势（统一方案）
        trends = weather_service.analyze_weather_trends(weather_data)
        national_context = build_national_weather_context(weather_data, trends)
        avg_humidity = national_context.get("avg_humidity", 60)
        avg_wind_scale = national_context.get("avg_wind_scale", 3)
        season = infer_season_by_month(datetime.now().month)
        national_rainy_city_count = calculate_national_rainy_city_count(weather_data)
        
        # 获取参数（如果没有提供，使用自动计算的值）
        avg_temp = request.args.get("avg_temp", type=float)
        if avg_temp is None:
            avg_temp = national_context.get("avg_temp", 25)
        
        rain_days = request.args.get("rain_days", type=int)
        if rain_days is None:
            rain_days = national_context.get("rain_days", 0)
        
        temp_trend = request.args.get("temp_trend")
        if temp_trend is None:
            temp_trend = national_context.get("temp_trend", "stable")
        
        # 获取BI推荐
        recommendations = bi_service.get_weather_recommendations(
            avg_temp=avg_temp,
            rain_days=rain_days,
            temp_trend=temp_trend,
            city=city,
            avg_humidity=avg_humidity,
            avg_wind_scale=avg_wind_scale,
            season=season,
            national_rainy_city_count=national_rainy_city_count,
            brand=brand
        )
        
        # 添加城市信息
        recommendations["city"] = city
        recommendations["scope"] = "national"
        recommendations["weather_summary"] = {
            "avg_temp": avg_temp,
            "rain_days": rain_days,
            "temp_trend": temp_trend,
            "temp_trend_desc": national_context.get("temp_trend_desc", ""),
            "city_count": national_context.get("city_count", 0),
            "city_weights": national_context.get("city_weights", {})
        }
        
        return jsonify({
            "success": True,
            "data": recommendations,
            "update_time": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/bi/inventory")
def api_bi_inventory():
    """
    获取BI库存数据API
    
    Returns:
        JSON格式的库存数据
    """
    try:
        products = bi_service.fetch_bi_inventory_data()
        
        return jsonify({
            "success": True,
            "data": {
                "products": products,
                "total_count": len(products)
            },
            "update_time": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/sync/feishu", methods=["POST"])
def api_sync_feishu():
    """
    同步天气数据到飞书多维表
    
    Returns:
        同步结果
    """
    try:
        # 获取天气数据
        weather_data = get_cached_weather()
        
        if not weather_data:
            return jsonify({
                "success": False,
                "error": "没有可同步的天气数据"
            }), 400
        
        # 格式化为飞书格式
        records = weather_service.format_for_feishu(weather_data)
        
        # 同步到飞书
        success = feishu_service.sync_weather_data(records)
        
        if success:
            return jsonify({
                "success": True,
                "message": f"成功同步 {len(records)} 条记录到飞书",
                "sync_count": len(records),
                "sync_time": datetime.now().isoformat()
            })
        else:
            return jsonify({
                "success": False,
                "error": "同步失败"
            }), 500
            
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/dashboard")
def api_dashboard():
    """
    获取仪表板完整数据
    
    Returns:
        包含天气、推荐、库存的完整数据
    """
    try:
        brand = request.args.get("brand", "all")
        # 获取所有城市天气
        weather_data = get_cached_weather()
        formatted_weather = weather_service.format_for_api(weather_data)
        trends = weather_service.analyze_weather_trends(weather_data)
        
        # 全国综合趋势（统一推荐方案）
        national_context = build_national_weather_context(weather_data, trends)

        # 为每个城市写入同一套推荐（直播面对所有城市）
        recommendations = {}
        for city in weather_data.keys():
            rec = bi_service.get_weather_recommendations(
                avg_temp=national_context.get("avg_temp", 25),
                rain_days=national_context.get("rain_days", 0),
                temp_trend=national_context.get("temp_trend", "stable"),
                city=city,
                avg_humidity=national_context.get("avg_humidity", 60),
                avg_wind_scale=national_context.get("avg_wind_scale", 3),
                season=infer_season_by_month(datetime.now().month),
                national_rainy_city_count=calculate_national_rainy_city_count(weather_data),
                brand=brand
            )
            rec["scope"] = "national"
            rec["weather_summary"] = {
                "avg_temp": national_context.get("avg_temp"),
                "rain_days": national_context.get("rain_days"),
                "temp_trend": national_context.get("temp_trend"),
                "temp_trend_desc": national_context.get("temp_trend_desc"),
                "city_count": national_context.get("city_count", 0),
                "city_weights": national_context.get("city_weights", {})
            }
            recommendations[city] = rec
        
        return jsonify({
            "success": True,
            "data": {
                "weather": formatted_weather,
                "trends": trends,
                "recommendations": recommendations
            },
            "update_time": datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/refresh-data", methods=["POST"])
def api_refresh_data():
    """手动触发天气和BI缓存刷新"""
    try:
        refresh_weather_cache(force=True)
        refresh_bi_cache(force=True)
        return jsonify({
            "success": True,
            "message": "天气与BI数据已刷新",
            "update_time": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/health")
def api_health():
    """健康检查接口"""
    return jsonify({
        "status": "healthy",
        "time": datetime.now().isoformat(),
        "version": "2.0.0"
    })


@app.route("/api/rule-framework")
def api_rule_framework():
    """获取天气推荐框架配置（用于业务讨论与规则确认）"""
    try:
        framework = bi_service.get_recommendation_framework()
        return jsonify({
            "success": True,
            "data": framework,
            "update_time": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/rules", methods=["GET"])
def api_rules_get():
    """获取完整推荐规则配置"""
    try:
        auth_error = _require_admin()
        if auth_error:
            return auth_error
        return jsonify({
            "success": True,
            "data": bi_service.get_rules_config(),
            "update_time": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/api/rules", methods=["POST"])
def api_rules_save():
    """保存完整推荐规则配置"""
    try:
        auth_error = _require_admin()
        if auth_error:
            return auth_error
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({
                "success": False,
                "error": "请求体必须是 JSON 对象"
            }), 400

        saved = bi_service.update_rules_config(payload)
        return jsonify({
            "success": True,
            "data": saved,
            "message": "规则配置已保存并生效",
            "update_time": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "success": False,
        "error": "接口不存在"
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "success": False,
        "error": "服务器内部错误"
    }), 500


if __name__ == "__main__":
    from config import SERVER_CONFIG
    start_background_scheduler()
    
    print("=" * 60)
    print("天气数据分析与智能产品推荐系统 V2")
    print("=" * 60)
    print(f"\n服务启动中...")
    print(f"访问地址: http://{SERVER_CONFIG['host']}:{SERVER_CONFIG['port']}")
    print(f"调试模式: {SERVER_CONFIG['debug']}")
    print("\nAPI端点:")
    print("  GET  /              - 仪表板页面")
    print("  GET  /api/weather   - 天气数据")
    print("  GET  /api/recommendations - 产品推荐")
    print("  GET  /api/dashboard - 完整仪表板数据")
    print("  POST /api/sync/feishu - 同步到飞书")
    print("=" * 60)
    
    app.run(
        host=SERVER_CONFIG["host"],
        port=SERVER_CONFIG["port"],
        debug=SERVER_CONFIG["debug"]
    )
