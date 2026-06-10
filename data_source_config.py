"""
观远多数据源配置：不同业务数据可来自不同「页面 + 卡片」。

配置文件：默认项目根目录下 guandata_sources.json（可用环境变量 GUANDATA_SOURCES_FILE 覆盖）。
未配置的字段回退到 .env 中的 GUANDATA_PAGE_ID / GUANDATA_CARD_ID / GUANDATA_CARD_NAME_KEYWORD。

后续扩展：在 JSON 的 sources 下增加新 key（如 sales、inventory_snapshot），服务层按 key 取数即可。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_CONFIG_MTIME: float = 0.0


def _config_path() -> str:
    raw = os.getenv("GUANDATA_SOURCES_FILE", "guandata_sources.json").strip()
    if os.path.isabs(raw):
        return raw
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, raw)


def load_sources_file(force_reload: bool = False) -> Dict[str, Any]:
    global _CONFIG_CACHE, _CONFIG_MTIME
    path = _config_path()
    if not os.path.isfile(path):
        _CONFIG_CACHE = {}
        _CONFIG_MTIME = 0.0
        return {}
    mtime = os.path.getmtime(path)
    if not force_reload and _CONFIG_CACHE is not None and mtime == _CONFIG_MTIME:
        return _CONFIG_CACHE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _CONFIG_CACHE = data if isinstance(data, dict) else {}
        _CONFIG_MTIME = mtime
    except Exception:
        _CONFIG_CACHE = {}
        _CONFIG_MTIME = mtime
    return _CONFIG_CACHE


def get_source_config(
    logical_name: str,
    *,
    default_page_id: str = "",
    default_keyword: str = "",
    env_page_key: str = "GUANDATA_PAGE_ID",
    env_card_key: str = "GUANDATA_CARD_ID",
    env_keyword_key: str = "GUANDATA_CARD_NAME_KEYWORD",
) -> Dict[str, str]:
    """
    返回数据源配置。字符串字段未设置则为 ""。
    额外支持 mode=dataset|card、dataset_id、field_mapping（见 get_inventory_source_config）。
    """
    data = load_sources_file()
    src = {}
    if isinstance(data.get("sources"), dict):
        raw = data["sources"].get(logical_name)
        if isinstance(raw, dict):
            src = raw

    def from_json(key: str) -> Optional[str]:
        if key not in src:
            return None
        v = src.get(key)
        if v is None:
            return ""
        return str(v).strip()

    page_id = from_json("page_id")
    if page_id is None:
        page_id = os.getenv(env_page_key, default_page_id).strip()

    card_id = from_json("card_id")
    if card_id is None:
        card_id = os.getenv(env_card_key, "").strip()

    keyword = from_json("card_name_keyword")
    if keyword is None:
        keyword = os.getenv(env_keyword_key, default_keyword).strip()

    return {
        "page_id": page_id,
        "card_id": card_id,
        "card_name_keyword": keyword,
    }


def get_inventory_source_config() -> Dict[str, Any]:
    """
    inventory 数据源完整配置：
    - mode: card（页面卡片，默认）| dataset（观远数据集）
    - dataset_id: 数据集 dsId
    - field_mapping: 原卡片字段逻辑名 → 新数据集列名
    - aggregate_by: 按款式编码聚合时的分组列
    """
    data = load_sources_file()
    src: Dict[str, Any] = {}
    if isinstance(data.get("sources"), dict):
        raw = data["sources"].get("inventory")
        if isinstance(raw, dict):
            src = raw

    mode = str(src.get("mode") or os.getenv("GUANDATA_INVENTORY_MODE", "card")).strip().lower()
    if mode not in ("card", "dataset"):
        mode = "card"

    dataset_id = str(
        src.get("dataset_id")
        or os.getenv("GUANDATA_INVENTORY_DATASET_ID", "")
        or ""
    ).strip()

    default_mapping = {
        "style_code": "款式编码",
        "short_name": "小名",
        "product_name": "产品名称",
        "category": "产品分类",
        "image_url": "图片(到款式)",
        "style_tag": "款虚拟分类",
        "price_position": "价格定位",
        "brand": "品牌",
        "main_stock": "主仓实际库存",
        "sales_return_stock": "销退仓库存",
        "procurement_inbound": "采购在途数",
        "sales_return_inbound": "销退在途数",
        "virtual_cloud_stock": "虚拟云仓库存",
        "order_occupied": "订单占有数",
        "net_sales_qty": "款净销量",
        "sales_qty": "款销售数量",
        "return_rate": "发货后退货率判定值（款）",
        "conversion_rate": "支付转化率(款)",
        "retail_price": "销售价",
        "unit_cost": "总成本",
        "price_ratio": "倍率",
    }
    mapping = src.get("field_mapping")
    if not isinstance(mapping, dict):
        mapping = {}
    field_mapping = {**default_mapping, **{k: str(v) for k, v in mapping.items() if v}}

    aggregate_by = str(
        src.get("aggregate_by")
        or field_mapping.get("style_code")
        or "款式编码"
    ).strip()

    return {
        "mode": mode,
        "dataset_id": dataset_id,
        "field_mapping": field_mapping,
        "aggregate_by": aggregate_by,
        "page_id": str(src.get("page_id") or os.getenv("GUANDATA_PAGE_ID", "")).strip(),
        "card_id": str(src.get("card_id") or os.getenv("GUANDATA_CARD_ID", "")).strip(),
        "card_name_keyword": str(
            src.get("card_name_keyword")
            if src.get("card_name_keyword") is not None
            else os.getenv("GUANDATA_CARD_NAME_KEYWORD", "拉新")
        ).strip(),
    }
