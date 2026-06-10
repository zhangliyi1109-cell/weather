"""
BI 库存数据服务 V4 — 从观远数据集「商品全表」拉取

将原卡片数据源（款级字段）一一映射到新数据集列，并按款式编码聚合 SKU 行。
新增字段：销售价、总成本、倍率（用于利润款判定）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from guandata import create_bi
from data_source_config import get_inventory_source_config


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _to_int(val: Any) -> int:
    f = _to_float(val)
    if f is None:
        return 0
    return int(f)


def _pick_text(row: Dict[str, Any], col: str, fallback: str = "") -> str:
    v = row.get(col)
    if v is None or str(v).strip() in ("", "None", "null"):
        return fallback
    return str(v).strip()


class BIInventoryServiceV4:
    """从观远数据集拉取库存（字段映射 + 款式聚合）"""

    def __init__(self):
        self._cache: Optional[List[Dict[str, Any]]] = None
        self._cache_time: Optional[datetime] = None
        self._snapshot_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "bi_inventory_last_success.json",
        )

    def clear_cache(self):
        self._cache = None
        self._cache_time = None
        print("✓ BI 数据集缓存已清除")

    def _cfg(self) -> Dict[str, Any]:
        return get_inventory_source_config()

    def _save_snapshot(self, data: List[Dict[str, Any]]) -> None:
        try:
            payload = {
                "saved_at": datetime.now().isoformat(),
                "source": "dataset",
                "count": len(data),
                "data": data,
            }
            with open(self._snapshot_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 快照保存失败: {e}")

    def _snapshot_has_role_fields(self, data: List[Dict[str, Any]]) -> bool:
        """引流/利润款依赖价格定位或倍率；旧卡片快照常缺这两项。"""
        if not data:
            return False
        sample = data[: min(len(data), 80)]
        for item in sample:
            if str(item.get("price_position") or "").strip():
                return True
            if item.get("bi_price_ratio") is not None:
                return True
            raw = item.get("raw_data")
            if isinstance(raw, dict) and (
                str(raw.get("价格定位") or "").strip() or raw.get("倍率")
            ):
                return True
        return False

    def _load_snapshot(self) -> List[Dict[str, Any]]:
        try:
            if not os.path.exists(self._snapshot_file):
                return []
            with open(self._snapshot_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            data = payload.get("data", [])
            if not isinstance(data, list):
                return []
            src = payload.get("source", "unknown")
            if not self._snapshot_has_role_fields(data):
                print(
                    f"⚠️ 忽略过期快照（{len(data)} 条，source={src}）："
                    "缺少价格定位/倍率，无法生成引流款与利润款。请刷新 BI 数据。"
                )
                return []
            print(f"✓ 使用最近成功快照: {len(data)} 条（source={src}）")
            return data
        except Exception as e:
            print(f"⚠️ 快照读取失败: {e}")
            return []

    def _fetch_raw_rows(self) -> List[Dict[str, Any]]:
        cfg = self._cfg()
        ds_id = cfg.get("dataset_id") or ""
        if not ds_id:
            raise RuntimeError(
                "未配置 inventory.dataset_id：请在 guandata_sources.json 设置 "
                "sources.inventory.mode=dataset 与 dataset_id。"
            )
        fm = cfg.get("field_mapping") or {}
        page_size = int(os.getenv("GUANDATA_DATASET_PAGE_SIZE", "5000") or 5000)
        bi = create_bi()
        print(f"✓ 从数据集 {ds_id} 拉取（字段映射 {len(fm)} 项）…")
        rows = bi.fetch_dataset_rows(ds_id, page_size=page_size)
        print(f"✓ 数据集原始行数: {len(rows)}")
        return rows

    def _aggregate_by_style(
        self, rows: List[Dict[str, Any]], fm: Dict[str, str], group_col: str
    ) -> List[Dict[str, Any]]:
        """SKU 行 → 款式级一条（库存求和；款级指标取 max / 首条非空）。"""
        sum_keys = {
            fm.get("main_stock", ""),
            fm.get("sales_return_stock", ""),
            fm.get("procurement_inbound", ""),
            fm.get("sales_return_inbound", ""),
            fm.get("virtual_cloud_stock", ""),
            fm.get("order_occupied", ""),
        }
        sum_keys.discard("")
        max_keys = {
            fm.get("net_sales_qty", ""),
            fm.get("sales_qty", ""),
            fm.get("price_ratio", ""),
            fm.get("retail_price", ""),
            fm.get("unit_cost", ""),
            fm.get("conversion_rate", ""),
            fm.get("return_rate", ""),
        }
        max_keys.discard("")
        text_keys = {
            fm.get("price_position", ""),
            fm.get("short_name", ""),
            fm.get("product_name", ""),
            fm.get("category", ""),
            fm.get("image_url", ""),
            fm.get("style_tag", ""),
            fm.get("brand", ""),
        }
        text_keys.discard("")

        buckets: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []

        for row in rows:
            style = _pick_text(row, group_col)
            if not style:
                continue
            if style not in buckets:
                buckets[style] = {"_first_row": dict(row)}
                order.append(style)
            acc = buckets[style]
            for col in sum_keys:
                acc[col] = acc.get(col, 0) + _to_int(row.get(col))
            for col in max_keys:
                val = _to_float(row.get(col))
                if val is not None:
                    prev = acc.get(col)
                    if prev is None or val > prev:
                        acc[col] = val
            for col in text_keys:
                text = _pick_text(row, col)
                if text and not acc.get(col):
                    acc[col] = text

        out: List[Dict[str, Any]] = []
        for style in order:
            acc = buckets[style]
            merged = dict(acc.get("_first_row") or {})
            for col in sum_keys:
                if col in acc:
                    merged[col] = acc[col]
            for col in max_keys:
                if col in acc:
                    merged[col] = acc[col]
            for col in text_keys:
                if col in acc:
                    merged[col] = acc[col]
            out.append(merged)
        return out

    def _fallback_card_inventory(self) -> List[Dict[str, Any]]:
        """数据集不可用时回退页面卡片（保留款级库存/销量）。"""
        from bi_inventory_service_v3 import BIInventoryServiceV3

        print("○ 数据集拉取失败，回退页面卡片数据源 …")
        card = BIInventoryServiceV3().fetch_inventory_data(use_cache=False)
        if card and self._snapshot_has_role_fields(card):
            return card
        if card:
            print("○ 卡片数据缺价格定位/倍率，跳过旧卡片结果")
        return []

    def _map_row(self, row: Dict[str, Any], fm: Dict[str, str]) -> Dict[str, Any]:
        style_code = _pick_text(row, fm.get("style_code", "款式编码"))
        main_stock = _to_int(row.get(fm.get("main_stock", "")))
        sales_return_stock = _to_int(row.get(fm.get("sales_return_stock", "")))
        inbound = _to_int(row.get(fm.get("procurement_inbound", "")))
        sales_return_inbound = _to_int(row.get(fm.get("sales_return_inbound", "")))
        virtual_cloud = _to_int(row.get(fm.get("virtual_cloud_stock", "")))
        order_occupied = _to_int(row.get(fm.get("order_occupied", "")))
        total_stock = main_stock + sales_return_stock + inbound + sales_return_inbound
        available = total_stock - virtual_cloud - order_occupied

        rr_raw = _to_float(row.get(fm.get("return_rate", "")))
        if rr_raw is not None:
            return_rate = rr_raw if rr_raw <= 1 else rr_raw / 100.0
        else:
            sales = _to_int(row.get(fm.get("sales_qty", "")))
            returns = _to_int(row.get("退货数量", 0))
            return_rate = (returns / sales) if sales > 0 else 0.15

        cvr_raw = _to_float(row.get(fm.get("conversion_rate", "")))
        if cvr_raw is not None:
            conversion_rate = cvr_raw if cvr_raw <= 1 else cvr_raw / 100.0
        else:
            conversion_rate = 0.05

        retail_price = _to_float(row.get(fm.get("retail_price", ""))) or 0.0
        unit_cost = _to_float(row.get(fm.get("unit_cost", "")))
        price_ratio = _to_float(row.get(fm.get("price_ratio", "")))

        brand_raw = _pick_text(row, fm.get("brand", ""))

        return {
            "sku_id": style_code,
            "name": _pick_text(row, fm.get("short_name", "")),
            "product_name": _pick_text(row, fm.get("product_name", "")),
            "style_tag": _pick_text(row, fm.get("style_tag", ""), _pick_text(row, "虚拟分类", "")),
            "price_position": _pick_text(row, fm.get("price_position", "")),
            "image_url": _pick_text(row, fm.get("image_url", "")),
            "category": _pick_text(row, fm.get("category", ""), "其他"),
            "brand_raw": brand_raw,
            "stock": main_stock,
            "sales_return_stock": sales_return_stock,
            "inbound": inbound,
            "sales_return_inbound": sales_return_inbound,
            "virtual_cloud_stock": virtual_cloud,
            "order_occupied": order_occupied,
            "total_stock": total_stock,
            "available_stock": available,
            "sales_qty": _to_int(row.get(fm.get("sales_qty", ""))),
            "net_sales_qty": _to_int(row.get(fm.get("net_sales_qty", ""))),
            "return_rate": return_rate,
            "conversion_rate": conversion_rate,
            "price": retail_price,
            "bi_unit_cost": unit_cost,
            "bi_price_ratio": price_ratio,
            "size_completeness": 0.85,
            "raw_data": row,
        }

    def fetch_inventory_data(
        self,
        use_cache: bool = True,
        cache_minutes: int = 30,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        if force_refresh:
            self._cache = None
            self._cache_time = None

        if use_cache and self._cache and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds() / 60
            if elapsed < cache_minutes:
                print(f"✓ 使用数据集缓存（{elapsed:.1f} 分钟前）")
                return self._cache

        # 全量数据集约 5 万行，首次 API 拉取常超过 2 分钟；有有效快照时先快速返回
        if use_cache and not force_refresh and not self._cache:
            snap = self._load_snapshot()
            if snap:
                self._cache = snap
                self._cache_time = datetime.now()
                return snap

        try:
            cfg = self._cfg()
            fm = cfg.get("field_mapping") or {}
            group_col = cfg.get("aggregate_by") or fm.get("style_code", "款式编码")
            raw_rows = self._fetch_raw_rows()
            if not raw_rows:
                card = self._fallback_card_inventory()
                if card:
                    return card
                return self._load_snapshot()

            style_rows = self._aggregate_by_style(raw_rows, fm, group_col)
            parsed = [self._map_row(r, fm) for r in style_rows if _pick_text(r, group_col)]
            parsed = [p for p in parsed if p.get("sku_id")]

            print(f"✓ 款式聚合后 {len(parsed)} 条（原 SKU 行 {len(raw_rows)}）")
            if not parsed:
                card = self._fallback_card_inventory()
                if card:
                    return card
                return self._load_snapshot()

            self._cache = parsed
            self._cache_time = datetime.now()
            self._save_snapshot(parsed)
            return parsed
        except Exception as e:
            print(f"⚠️ 数据集拉取失败: {e}")
            import traceback
            traceback.print_exc()
            card = self._fallback_card_inventory()
            if card:
                return card
            return self._load_snapshot()


_bi_inventory_service_v4: Optional[BIInventoryServiceV4] = None


def get_bi_inventory_service_v4() -> BIInventoryServiceV4:
    global _bi_inventory_service_v4
    if _bi_inventory_service_v4 is None:
        _bi_inventory_service_v4 = BIInventoryServiceV4()
    return _bi_inventory_service_v4
