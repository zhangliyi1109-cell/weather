"""
天气数据分析系统 - 配置文件
使用 Open-Meteo 免费天气 API (无需 API Key)
"""
import os

# Open-Meteo API 是免费的，无需 API Key
# 文档: https://open-meteo.com/

# 飞书：密钥仅从环境变量读取（本地复制 .env.example → .env；生产环境填环境变量）
# https://open.feishu.cn/app/
FEISHU_CONFIG = {
    "app_id": os.getenv("FEISHU_APP_ID", ""),
    "app_secret": os.getenv("FEISHU_APP_SECRET", ""),
}

FEISHU_BITABLE = {
    "app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN", ""),
    "table_id": os.getenv("FEISHU_BITABLE_TABLE_ID", ""),
}

# 城市配置 (使用经纬度坐标，供 Open-Meteo API 使用)
CITIES = {
    "北京": {"location": "101010100", "lat": 39.904989, "lon": 116.405285},
    "上海": {"location": "101020100", "lat": 31.231706, "lon": 121.472644},
    "广州": {"location": "101280101", "lat": 23.125178, "lon": 113.280637},
    "江苏": {"location": "101190101", "lat": 32.060255, "lon": 118.796877},
    "浙江": {"location": "101210101", "lat": 30.274084, "lon": 120.155070}
}

# 服务器配置（部署时可用环境变量覆盖，见 .env.example）
_server_port = os.getenv("PORT") or os.getenv("SERVER_PORT", "5002")
SERVER_CONFIG = {
    "host": os.getenv("SERVER_HOST", "0.0.0.0"),
    "port": int(_server_port),
    "debug": os.getenv("FLASK_DEBUG", "true").lower() in ("1", "true", "yes"),
}
