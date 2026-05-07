"""
后续接入「昨日销售」独立数据源时的扩展点。

当前严格模式下的净销量仍来自 BI 单品字段 sales_qty；
等你提供新数据源后，可在此实现拉取/解析，并在 bi_data_service 中
合并到 product 记录（例如写入 sales_qty 或单独字段再聚合）。
"""


def load_sales_env_hint() -> str:
    """部署检查用：提示运维需配置的环境变量名。"""
    return "SALES_DATA_MODE / SALES_DATA_CSV_PATH / SALES_DATA_API_*（见 .env.example）"
