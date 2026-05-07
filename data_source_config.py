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
    返回 { page_id, card_id, card_name_keyword }，均为字符串；未设置则为 ""。
    JSON 中若显式写了 null/空字符串，视为有效覆盖（例如 keyword 置空不走名称匹配）。
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
