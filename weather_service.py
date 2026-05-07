"""
天气数据服务模块
使用 Open-Meteo 免费天气 API (无需 API Key)
"""
import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from config import CITIES


class WeatherService:
    """天气数据服务类 - Open-Meteo 版本"""
    
    # Open-Meteo API 基础地址
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    
    # WMO 天气代码映射到中文
    WMO_WEATHER_CODES = {
        0: "晴",
        1: "多云",
        2: "多云",
        3: "阴",
        45: "雾",
        48: "雾凇",
        51: "毛毛雨",
        53: "小雨",
        55: "中雨",
        56: "冻雨",
        57: "冻雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "阵雨",
        81: "阵雨",
        82: "暴雨",
        85: "阵雪",
        86: "阵雪",
        95: "雷雨",
        96: "雷雨伴冰雹",
        99: "雷雨伴冰雹"
    }
    
    # 风向角度映射
    WIND_DIRECTIONS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    
    def __init__(self):
        self.weather_cache = {}
        self.cache_time = None
    
    def _wmo_to_chinese(self, code: int) -> str:
        """将 WMO 天气代码转换为中文描述"""
        return self.WMO_WEATHER_CODES.get(code, "未知")
    
    def _degree_to_direction(self, degree: float) -> str:
        """将风向角度转换为中文方向"""
        if degree is None:
            return "未知"
        index = round(degree / 45) % 8
        return self.WIND_DIRECTIONS[index]
    
    def _get_wind_scale(self, speed: float) -> str:
        """根据风速(m/s)计算风力等级"""
        if speed < 0.3:
            return "0"
        elif speed < 1.6:
            return "1"
        elif speed < 3.4:
            return "2"
        elif speed < 5.5:
            return "3"
        elif speed < 8.0:
            return "4"
        elif speed < 10.8:
            return "5"
        elif speed < 13.9:
            return "6"
        elif speed < 17.2:
            return "7"
        else:
            return "8"
    
    def _get_uv_index(self, uv_max: float) -> str:
        """根据紫外线指数返回等级"""
        if uv_max is None or uv_max < 0:
            return "0"
        elif uv_max < 3:
            return "1"  # 低
        elif uv_max < 6:
            return "3"  # 中等
        elif uv_max < 8:
            return "5"  # 高
        elif uv_max < 11:
            return "7"  # 很高
        else:
            return "10"  # 极高
    
    def get_7day_forecast(self, city_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定城市7天天气预报
        
        Args:
            city_name: 城市名称（北京/上海/广州）
        
        Returns:
            天气数据字典
        """
        if city_name not in CITIES:
            print(f"不支持的城市: {city_name}")
            return None
        
        city_info = CITIES[city_name]
        lat = city_info["lat"]
        lon = city_info["lon"]
        
        # Open-Meteo API 参数
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "relative_humidity_2m_mean",
                "wind_direction_10m_dominant",
                "wind_speed_10m_max",
                "uv_index_max",
                "sunrise",
                "sunset"
            ],
            "timezone": "Asia/Shanghai",
            "forecast_days": 16
        }
        
        try:
            print(f"正在从 Open-Meteo 获取 {city_name} 的天气数据...")
            response = requests.get(self.BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            daily_data = data.get("daily", {})
            if not daily_data:
                print(f"未获取到 {city_name} 的每日数据")
                return self._generate_mock_weather(city_name)
            
            # 解析每日数据
            dates = daily_data.get("time", [])
            weather_codes = daily_data.get("weather_code", [])
            temp_max = daily_data.get("temperature_2m_max", [])
            temp_min = daily_data.get("temperature_2m_min", [])
            precip_prob = daily_data.get("precipitation_probability_max", [])
            humidity = daily_data.get("relative_humidity_2m_mean", [])
            wind_dir = daily_data.get("wind_direction_10m_dominant", [])
            wind_speed = daily_data.get("wind_speed_10m_max", [])
            uv_index = daily_data.get("uv_index_max", [])
            sunrise = daily_data.get("sunrise", [])
            sunset = daily_data.get("sunset", [])
            
            daily = []
            for i in range(len(dates)):
                date_str = dates[i]
                # 格式化日期
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    formatted_date = dt.strftime("%Y-%m-%d")
                except:
                    formatted_date = date_str
                
                daily.append({
                    "fxDate": formatted_date,
                    "tempMax": str(round(temp_max[i])) if i < len(temp_max) else "25",
                    "tempMin": str(round(temp_min[i])) if i < len(temp_min) else "15",
                    "textDay": self._wmo_to_chinese(weather_codes[i]) if i < len(weather_codes) else "多云",
                    "textNight": self._wmo_to_chinese(weather_codes[i]) if i < len(weather_codes) else "多云",
                    "precip": str(precip_prob[i]) if i < len(precip_prob) else "0",
                    "humidity": str(round(humidity[i])) if i < len(humidity) else "50",
                    "windDirDay": self._degree_to_direction(wind_dir[i]) if i < len(wind_dir) else "北",
                    "windDirNight": self._degree_to_direction(wind_dir[i]) if i < len(wind_dir) else "北",
                    "windScaleDay": self._get_wind_scale(wind_speed[i]) if i < len(wind_speed) else "3",
                    "windScaleNight": self._get_wind_scale(wind_speed[i]) if i < len(wind_speed) else "2",
                    "uvIndex": self._get_uv_index(uv_index[i]) if i < len(uv_index) else "5",
                    "vis": "10",
                    "sunrise": sunrise[i][11:16] if i < len(sunrise) and len(sunrise[i]) > 16 else "05:50",
                    "sunset": sunset[i][11:16] if i < len(sunset) and len(sunset[i]) > 16 else "19:10"
                })
            
            return {
                "city": city_name,
                "location_id": f"{lat},{lon}",
                "update_time": datetime.now().isoformat(),
                "daily": daily
            }
                
        except Exception as e:
            print(f"Open-Meteo API 请求失败: {e}")
            print(f"使用备用数据...")
            return self._generate_mock_weather(city_name)
    
    def _generate_mock_weather(self, city_name: str) -> Dict[str, Any]:
        """生成模拟天气数据（API失败时使用）"""
        today = datetime.now()
        city_info = CITIES[city_name]
        
        # 城市基础温度配置（仅在API失败时兜底）
        city_configs = {
            "北京": {"base_max": 22, "base_min": 10},
            "上海": {"base_max": 24, "base_min": 16},
            "广州": {"base_max": 30, "base_min": 24}
        }
        
        config = city_configs.get(city_name, {"base_max": 25, "base_min": 15})
        # 避免“每天递增”的伪趋势误导分析
        day_offsets_max = [0, 2, 1, -1, 0, 1, -2]
        day_offsets_min = [0, 1, 0, -1, 0, 0, -1]
        
        daily = []
        weather_types = ["晴", "多云", "阴", "小雨", "多云", "晴", "多云", "阴"]
        precip_pattern = [0, 10, 0, 40, 20, 0, 10, 15]

        for i in range(16):
            date = (today + timedelta(days=i)).strftime("%Y-%m-%d")
            temp_max = config["base_max"] + day_offsets_max[i % len(day_offsets_max)]
            temp_min = config["base_min"] + day_offsets_min[i % len(day_offsets_min)]
            weather = weather_types[i % len(weather_types)]
            
            daily.append({
                "fxDate": date,
                "tempMax": str(temp_max),
                "tempMin": str(temp_min),
                "textDay": weather,
                "textNight": "多云" if weather == "晴" else "晴",
                "precip": str(precip_pattern[i % len(precip_pattern)]),
                "humidity": str(50 + i * 3),
                "windDirDay": ["北", "东北", "南", "东南", "东", "北", "西北", "西"][i % 8],
                "windDirNight": "北",
                "windScaleDay": "3",
                "windScaleNight": "2",
                "uvIndex": "5",
                "vis": "10",
                "sunrise": "05:50",
                "sunset": "19:10"
            })
        
        return {
            "city": city_name,
            "location_id": city_info.get("location", f"{city_info['lat']},{city_info['lon']}"),
            "update_time": today.isoformat(),
            "daily": daily
        }
    
    def get_all_cities_weather(self) -> Dict[str, Any]:
        """获取所有配置城市的天气数据"""
        result = {}
        
        for city_name in CITIES.keys():
            data = self.get_7day_forecast(city_name)
            if data:
                result[city_name] = data
        
        self.weather_cache = result
        self.cache_time = datetime.now()
        
        return result
    
    def analyze_weather_trends(self, weather_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析天气趋势
        
        Args:
            weather_data: 天气数据字典
        
        Returns:
            趋势分析结果
        """
        analysis = {}
        
        for city, data in weather_data.items():
            daily = data.get("daily", [])
            if not daily:
                continue
            
            # 计算平均温度
            # 只使用未来7天窗口，避免长窗口摊薄业务判断
            window = daily[:7]
            temps_max = [int(d.get("tempMax", 0)) for d in window]
            temps_min = [int(d.get("tempMin", 0)) for d in window]
            avg_temp_max = sum(temps_max) / len(temps_max)
            avg_temp_min = sum(temps_min) / len(temps_min)
            
            # 计算温度趋势
            temp_trend = "stable"
            if len(temps_max) >= 2:
                if temps_max[-1] > temps_max[0] + 3:
                    temp_trend = "rising"
                elif temps_max[-1] < temps_max[0] - 3:
                    temp_trend = "falling"
            
            # 统计降雨天数（降水概率 > 30%）
            rain_days = sum(1 for d in window if int(d.get("precip", 0)) > 30)
            
            # 统计天气类型
            weather_types = {}
            for d in window:
                w_type = d.get("textDay", "未知")
                weather_types[w_type] = weather_types.get(w_type, 0) + 1
            
            # 平均湿度
            humidities = [int(d.get("humidity", 50)) for d in window]
            avg_humidity = sum(humidities) / len(humidities)
            
            analysis[city] = {
                "avg_temp_max": round(avg_temp_max, 1),
                "avg_temp_min": round(avg_temp_min, 1),
                "avg_temp": round((avg_temp_max + avg_temp_min) / 2, 1),
                "temp_trend": temp_trend,
                "temp_trend_desc": self._get_trend_desc(temp_trend),
                "rain_days": rain_days,
                "weather_types": weather_types,
                "avg_humidity": round(avg_humidity, 1),
                "hottest_day": max(window, key=lambda x: int(x.get("tempMax", 0))) if window else None,
                "coldest_day": min(window, key=lambda x: int(x.get("tempMin", 0))) if window else None
            }
        
        return analysis
    
    def _get_trend_desc(self, trend: str) -> str:
        """获取趋势描述"""
        trend_map = {
            "rising": "升温趋势",
            "falling": "降温趋势",
            "stable": "气温平稳"
        }
        return trend_map.get(trend, "未知")
    
    def format_for_api(self, weather_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        格式化数据供前端API使用
        """
        formatted = {
            "cities": [],
            "update_time": datetime.now().isoformat()
        }
        
        for city, data in weather_data.items():
            city_data = {
                "name": city,
                "location_id": data.get("location_id"),
                "forecast": []
            }
            
            for day in data.get("daily", []):
                city_data["forecast"].append({
                    "date": day.get("fxDate"),
                    "week": self._get_weekday(day.get("fxDate")),
                    "temp_max": int(day.get("tempMax", 0)),
                    "temp_min": int(day.get("tempMin", 0)),
                    "weather_day": day.get("textDay"),
                    "weather_night": day.get("textNight"),
                    "precip": int(day.get("precip", 0)),
                    "humidity": int(day.get("humidity", 50)),
                    "wind_dir": day.get("windDirDay"),
                    "wind_scale": day.get("windScaleDay"),
                    "uv_index": day.get("uvIndex", "0"),
                    "vis": day.get("vis", "10"),
                    "sunrise": day.get("sunrise"),
                    "sunset": day.get("sunset")
                })
            
            formatted["cities"].append(city_data)
        
        return formatted
    
    def _get_weekday(self, date_str: str) -> str:
        """获取星期几"""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            return weekdays[dt.weekday()]
        except:
            return ""
    
    def format_for_feishu(self, weather_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        格式化数据供飞书多维表使用
        字段名必须与飞书多维表字段名完全匹配
        """
        records = []
        
        for city, data in weather_data.items():
            city_info = CITIES.get(city, {})
            for day in data.get("daily", []):
                # 计算温度范围字符串
                temp_max = int(day.get("tempMax", 0))
                temp_min = int(day.get("tempMin", 0))
                temp_range = f"{temp_min}°C ~ {temp_max}°C"
                
                records.append({
                    "城市": city,
                    "城市ID": city_info.get("location", ""),
                    "日期": day.get("fxDate"),
                    "星期": self._get_weekday(day.get("fxDate")),
                    "天气白天": day.get("textDay"),
                    "天气夜间": day.get("textNight"),
                    "最高温度": temp_max,
                    "最低温度": temp_min,
                    "温度范围": temp_range,
                    "风向白天": day.get("windDirDay"),
                    "风向夜间": day.get("windDirNight"),
                    "风力白天": day.get("windScaleDay"),
                    "风力夜间": day.get("windScaleNight"),
                    "降水概率": int(day.get("precip", 0)),
                    "湿度": int(day.get("humidity", 50)),
                    "紫外线强度": day.get("uvIndex", "0"),
                    "能见度": day.get("vis", "10"),
                    "日出时间": day.get("sunrise"),
                    "日落时间": day.get("sunset"),
                    "数据更新时间": data.get("update_time", datetime.now().isoformat()),
                    "导入时间": datetime.now().isoformat()
                })
        
        return records


# 单例模式
_weather_service = None

def get_weather_service() -> WeatherService:
    """获取天气服务实例"""
    global _weather_service
    if _weather_service is None:
        _weather_service = WeatherService()
    return _weather_service


if __name__ == "__main__":
    # 测试
    service = WeatherService()
    
    print("=" * 60)
    print("Open-Meteo 天气服务测试")
    print("=" * 60)
    
    # 获取所有城市数据
    weather_data = service.get_all_cities_weather()
    
    print(f"\n成功获取 {len(weather_data)} 个城市数据")
    
    # 显示详细数据
    for city, data in weather_data.items():
        print(f"\n{city}:")
        for day in data.get("daily", [])[:3]:  # 只显示前3天
            print(f"  {day['fxDate']}: {day['textDay']} {day['tempMin']}°C ~ {day['tempMax']}°C, 降水{day['precip']}%")
    
    # 分析趋势
    analysis = service.analyze_weather_trends(weather_data)
    
    print("\n" + "=" * 60)
    print("天气趋势分析:")
    print("=" * 60)
    for city, data in analysis.items():
        print(f"\n{city}:")
        print(f"  平均温度: {data['avg_temp']}°C")
        print(f"  温度趋势: {data['temp_trend_desc']}")
        print(f"  降雨天数: {data['rain_days']}天")
        print(f"  天气分布: {data['weather_types']}")
    
    # 格式化API数据
    api_data = service.format_for_api(weather_data)
    print(f"\nAPI格式数据包含 {len(api_data['cities'])} 个城市")
    
    # 格式化飞书数据
    feishu_data = service.format_for_feishu(weather_data)
    print(f"飞书格式数据包含 {len(feishu_data)} 条记录")
