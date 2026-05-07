"""
BI 库存数据服务模块 V3
从"淘宝店铺拉新款式表现"卡片获取所有数据：
- 库存数
- 在途数  
- 退款率
- 转化率

仅使用观远 Public API（/public-api/card/.../data）拉取；无数据时使用本地快照 `bi_inventory_last_success.json`。
"""
import sys
import os
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# 添加 guandata.py 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guandata import create_bi, GuanBI
from data_source_config import get_source_config
from style_code import pick_style_code_from_dim_titles


class BIInventoryServiceV3:
    """BI 库存数据服务类 V3 - 从观远页面卡片拉取库存（Public API）"""

    # 默认页面（可被 GUANDATA_PAGE_ID 覆盖）：与观远「页面」URL 中 /page/ 后一段一致
    DEFAULT_PAGE_ID = "x340e4c117103479ebe5d1e5"

    def __init__(self):
        self._cache = None
        self._cache_time = None
        self._resolved_card_id: str = ""
        self._snapshot_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "bi_inventory_last_success.json"
        )

    def _inventory_source(self) -> Dict[str, str]:
        """inventory 逻辑数据源：优先 guandata_sources.json，缺项回退环境变量。"""
        return get_source_config(
            "inventory",
            default_page_id=self.DEFAULT_PAGE_ID,
            default_keyword="拉新",
        )

    def _resolve_card_id(self, bi: GuanBI) -> str:
        """显式卡片 ID 优先；否则按页面 ID 拉取卡片列表并自动挑选。"""
        cfg = self._inventory_source()
        explicit = (cfg.get("card_id") or "").strip()
        if explicit:
            print(f"✓ 使用配置中的 inventory.card_id / GUANDATA_CARD_ID={explicit}")
            return explicit

        page_id = (cfg.get("page_id") or "").strip()
        if not page_id:
            raise RuntimeError(
                "未配置 inventory 页面或卡片：请在 guandata_sources.json 的 sources.inventory "
                "中设置 page_id，或设置环境变量 GUANDATA_PAGE_ID / GUANDATA_CARD_ID。"
            )

        cards = bi.get_page_cards_summary(page_id)
        if not cards:
            raise RuntimeError(
                f"页面 {page_id} 未返回任何卡片。请检查 GUANDATA_APP_TOKEN / GUANDATA_X_AUTH_TOKEN，"
                "或在配置中设置 inventory.card_id / GUANDATA_CARD_ID（观远卡片 cdId）。"
            )

        kw_raw = (cfg.get("card_name_keyword") or "").strip()
        keywords = [k.strip() for k in kw_raw.split(",") if k.strip()]
        if keywords:
            for c in cards:
                name = c.get("name") or ""
                if any(k in name for k in keywords):
                    cid = c["cdId"]
                    shown = " / ".join(f"「{k}」" for k in keywords)
                    print(f"✓ 按名称关键字 {shown} 选中卡片: {name} ({cid})")
                    return cid
            print(
                "⚠️ 未在页面卡片标题中匹配到关键字 "
                + " / ".join(f"「{k}」" for k in keywords)
                + "（已合并多 Tab / setting 等字段）。将按类型/首张回退。"
            )
            for c in cards[:40]:
                nm = (c.get("name") or "")[:100]
                print(f"    · {nm} ({c.get('cdId')}) type={c.get('type', '')}")
            if len(cards) > 40:
                print(f"    · … 共 {len(cards)} 张卡片")
            print(
                "  请核对观远卡片名是否含上述关键字；或直接设置 GUANDATA_CARD_ID / "
                "guandata_sources.json 中 inventory.card_id 为目标卡片 cdId。"
            )

        prefer = ("TABLE", "DETAIL", "GRID", "MERGE", "LIST", "PIVOT", "明细", "列表", "表格")
        for c in cards:
            t = (c.get("type") or "").upper()
            if any(p in t for p in prefer):
                cid = c["cdId"]
                print(f"✓ 按卡片类型选中: {c.get('name', '')} ({cid}) type={t}")
                return cid

        c0 = cards[0]
        print(f"✓ 使用页面首张卡片: {c0.get('name', '')} ({c0['cdId']})")
        return c0["cdId"]

    def _card_views_to_try(self) -> List[str]:
        """观远卡片 /data 的 view；不同卡片在 GRAPH 下可能无 row.values，需换 TABLE 等。"""
        raw = (os.getenv("GUANDATA_CARD_VIEW") or "").strip()
        if raw:
            return [v.strip() for v in raw.split(",") if v.strip()]
        return ["GRAPH", "TABLE", "LIST", "DETAIL", "GRID"]

    def _chart_rows_pair(self, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], list, list]:
        """从卡片原始响应取出 (row_values, data_rows)；兼容少量字段差异。"""
        chart = raw.get("chartMain", {}) or raw.get("chart", {}) or {}
        row_block = chart.get("row") or {}
        row_values = row_block.get("values") or row_block.get("value") or []
        data_rows = chart.get("data") or []
        return chart, row_values, data_rows

    def _log_chart_diagnosis(self, card_id: str, raw: Dict[str, Any]) -> None:
        chart, rv, dr = self._chart_rows_pair(raw)
        print(
            f"⚠️ 卡片 {card_id} 诊断: chartMain.keys={list(chart.keys())[:12]}, "
            f"row.keys={list((chart.get('row') or {}).keys())}, "
            f"len(row.values)={len(rv) if rv else 0}, len(data)={len(dr) if dr else 0}"
        )

    def _get_effective_card_id(self, bi: GuanBI) -> str:
        if self._resolved_card_id:
            return self._resolved_card_id
        self._resolved_card_id = self._resolve_card_id(bi)
        return self._resolved_card_id

    def clear_cache(self):
        """清除缓存"""
        self._cache = None
        self._cache_time = None
        self._resolved_card_id = ""
        print("✓ BI 缓存已清除")

    def _save_snapshot(self, data: List[Dict[str, Any]]) -> None:
        """保存最近一次成功抓取快照（真实数据）"""
        try:
            payload = {
                "saved_at": datetime.now().isoformat(),
                "count": len(data),
                "data": data
            }
            with open(self._snapshot_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 快照保存失败: {e}")

    def _load_snapshot(self) -> List[Dict[str, Any]]:
        """加载最近一次成功抓取快照"""
        try:
            if not os.path.exists(self._snapshot_file):
                return []
            with open(self._snapshot_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            data = payload.get("data", [])
            print(f"✓ 使用最近成功快照数据: {len(data)} 条")
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"⚠️ 快照读取失败: {e}")
            return []

    def _fetch_bi_data_via_api(self) -> List[Dict[str, Any]]:
        """
        使用观远 Public API：/public-api/page/{pageId} 解析卡片，
        再 /public-api/card/{cardId}/data 取数。
        页面/卡片来自 guandata_sources.json → sources.inventory，缺项回退 GUANDATA_* 环境变量。
        """
        bi = create_bi()
        card_id = self._get_effective_card_id(bi)
        raw: Dict[str, Any] = {}
        last_exc: Optional[Exception] = None
        for view in self._card_views_to_try():
            try:
                cand = bi.get_card_raw(card_id, view=view)
            except Exception as e:
                last_exc = e
                print(f"○ 卡片 {card_id} view={view} 请求异常: {e}")
                continue
            _, row_values, data_rows = self._chart_rows_pair(cand)
            if row_values and data_rows:
                raw = cand
                print(f"✓ 卡片 {card_id} 使用 view={view}，原始行 row={len(row_values)}, data={len(data_rows)}")
                break
            print(
                f"○ 卡片 {card_id} view={view} 无对齐数据: "
                f"row_values={len(row_values) if row_values else 0}, data={len(data_rows) if data_rows else 0}"
            )

        if not raw:
            if last_exc:
                print(f"⚠️ 观远卡片数据请求失败 (card_id={card_id}): {last_exc}")
                raise last_exc
            print(f"⚠️ 卡片 {card_id} 所有 view 均无有效行列结构")
            return []

        _, row_values, data_rows = self._chart_rows_pair(raw)

        if len(row_values) != len(data_rows):
            n = min(len(row_values), len(data_rows))
            if n == 0:
                self._log_chart_diagnosis(card_id, raw)
                print(
                    f"⚠️ 卡片 {card_id} row/data 长度不一致且无法截断: "
                    f"{len(row_values)} vs {len(data_rows)}。请设置 GUANDATA_CARD_ID 指向明细表卡片。"
                )
                return []
            print(
                f"⚠️ 卡片 {card_id} row/data 长度不一致 ({len(row_values)} vs {len(data_rows)})，"
                f"按前 {n} 行截断解析"
            )
            row_values = row_values[:n]
            data_rows = data_rows[:n]

        if not row_values or not data_rows:
            self._log_chart_diagnosis(card_id, raw)
            print(
                f"⚠️ 卡片 {card_id} 返回结构异常: row={len(row_values) if row_values else 0}, "
                f"data={len(data_rows) if data_rows else 0}。可设置 GUANDATA_CARD_ID 指定正确明细表卡片。"
            )
            return []

        parsed_rows: List[Dict[str, Any]] = []
        skipped_short = 0
        for idx, dims in enumerate(row_values):
            metrics = data_rows[idx]
            if len(dims) < 7 or len(metrics) < 14:
                skipped_short += 1
                continue

            try:
                product_id = str(dims[0].get("title", "")).strip()
                short_name = str(dims[1].get("title", "")).strip()
                style_code = pick_style_code_from_dim_titles(dims)
                category = str(dims[5].get("title", "")).strip()
                product_name = str(dims[6].get("title", "")).strip()

                # 指标列映射（来自 column.values）：
                # 1=款销退仓库存, 2=款主仓实际库存, 3=款销退在途数, 4=款采购在途数,
                # 5=款销售数量, 6=款净销量, 7=总退货率, 13=支付转化率
                stock = int(float(metrics[2].get("v", 0) or 0))
                sales_return_stock = int(float(metrics[1].get("v", 0) or 0))
                sales_return_inbound = int(float(metrics[3].get("v", 0) or 0))
                inbound = int(float(metrics[4].get("v", 0) or 0))
                sales_qty = int(float(metrics[5].get("v", 0) or 0)) if len(metrics) > 5 else 0
                net_sales_qty = int(float(metrics[6].get("v", 0) or 0)) if len(metrics) > 6 else 0

                return_rate_raw = float(metrics[7].get("v", 0) or 0)        # 总退货率
                conversion_rate_raw = float(metrics[13].get("v", 0) or 0)    # 支付转化率

                # API 里可能是 0-1，也可能是百分值，统一转字符串百分比
                return_rate_percent = return_rate_raw * 100 if return_rate_raw <= 1 else return_rate_raw
                conversion_percent = conversion_rate_raw * 100 if conversion_rate_raw <= 1 else conversion_rate_raw

                parsed_rows.append({
                    "商品ID": product_id,
                    "款式编码": style_code or product_id,
                    "小名": short_name,
                    "图片(到款式)": str(dims[4].get("title", "")).strip(),
                    "产品名称": product_name,
                    "产品分类": category or "其他",
                    "款虚拟分类": str(dims[7].get("title", "")).strip() if len(dims) > 7 else "",
                    "款销退仓库存": sales_return_stock,
                    "款主仓实际库存": stock,
                    "款销退在途数": sales_return_inbound,
                    "款采购在途数": inbound,
                    "款销售数量": sales_qty,
                    "款净销量": net_sales_qty,
                    "总退货率": f"{return_rate_percent:.2f}%",
                    "支付转化率": f"{conversion_percent:.2f}%",
                })
            except Exception:
                continue

        if not parsed_rows and skipped_short:
            print(
                f"⚠️ 卡片 {card_id} 有 {skipped_short} 行因维度/指标列数不足被跳过 "
                f"（需 dim≥7 且 metrics≥14）。请确认 GUANDATA_CARD_ID 是否为「拉新款式表现」类明细表。"
            )
        print(f"✓ API路径获取到 {len(parsed_rows)} 条记录")
        return parsed_rows

    def fetch_inventory_data(self, use_cache: bool = True, cache_minutes: int = 30) -> List[Dict[str, Any]]:
        """
        从 BI 获取库存数据
        
        Returns:
            商品列表，包含：
            - sku_id: 款式编码
            - name: 商品名称（小名）
            - category: 品类
            - stock: 现货库存（款主仓实际库存）
            - inbound: 采购在途（款采购在途数）
            - return_rate: 退货率
            - conversion_rate: 转化率
        """
        # 检查缓存
        if use_cache and self._cache and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds() / 60
            if elapsed < cache_minutes:
                print(f"✓ 使用缓存数据（{elapsed:.1f}分钟前更新）")
                return self._cache
        
        try:
            print("正在从 BI API 获取数据...")
            raw_data = self._fetch_bi_data_via_api()
            if len(raw_data) == 0:
                print("⚠️ API 无有效数据，将尝试使用最近一次成功快照。")
            
            # 转换为标准格式
            parsed_data = []
            for row in raw_data:
                # 转换百分比为小数
                return_rate_str = row.get('总退货率', '0%').replace('%', '')
                conversion_rate_str = row.get('支付转化率', '0%').replace('%', '')
                
                try:
                    return_rate = float(return_rate_str) / 100
                except:
                    return_rate = 0.15
                
                try:
                    conversion_rate = float(conversion_rate_str) / 100
                except:
                    conversion_rate = 0.05
                
                # 可售库存口径（业务新规则）:
                # 主仓实际库存 + 销退仓库存 + 采购在途数 + 销退在途数 - 虚拟云仓库存 - 订单占有数
                main_stock = int(row.get('款主仓实际库存', 0))
                sales_return_stock = int(row.get('款销退仓库存', 0))
                inbound = int(row.get('款采购在途数', 0))
                sales_return_inbound = int(row.get('款销退在途数', 0))
                virtual_cloud_stock = int(row.get('虚拟云仓库存', 0))
                order_occupied = int(row.get('订单占有数', 0))
                total_stock = main_stock + sales_return_stock + inbound + sales_return_inbound
                available_stock = total_stock - virtual_cloud_stock - order_occupied
                
                item = {
                    'sku_id': row.get('款式编码', row.get('商品ID', '')),
                    'name': row.get('小名', ''),
                    'product_name': row.get('产品名称', ''),
                    'style_tag': row.get('款虚拟分类', ''),
                    'image_url': row.get('图片(到款式)', ''),
                    'category': row.get('产品分类', '其他'),
                    'stock': main_stock,
                    'sales_return_stock': sales_return_stock,
                    'inbound': inbound,
                    'sales_return_inbound': sales_return_inbound,
                    'sales_qty': int(row.get('款销售数量', 0) or 0),
                    'net_sales_qty': int(row.get('款净销量', 0) or 0),
                    'virtual_cloud_stock': virtual_cloud_stock,
                    'order_occupied': order_occupied,
                    'total_stock': total_stock,
                    'available_stock': available_stock,  # 可售库存
                    'return_rate': return_rate,
                    'conversion_rate': conversion_rate,
                    'size_completeness': 0.85,
                    'price': 0,
                    # 原始数据
                    'raw_data': row
                }
                parsed_data.append(item)
            
            print(f"✓ 获取到 {len(parsed_data)} 条记录")
            
            # 如果获取到的数据为空，返回空（不使用模拟数据污染真实结果）
            if len(parsed_data) == 0:
                print("⚠️ BI 返回数据为空")
                snapshot_data = self._load_snapshot()
                if snapshot_data:
                    return snapshot_data
                return []
            
            # 更新缓存
            self._cache = parsed_data
            self._cache_time = datetime.now()
            self._save_snapshot(parsed_data)
            
            return parsed_data
            
        except Exception as e:
            print(f"⚠️ BI 数据获取失败: {e}")
            import traceback
            traceback.print_exc()
            snapshot_data = self._load_snapshot()
            if snapshot_data:
                return snapshot_data
            print("返回空数据（无可用快照）")
            return []
    
    def _get_mock_inventory_data(self) -> List[Dict[str, Any]]:
        """获取模拟库存数据（BI 获取失败时使用）
        
        品类与BI产品分类字段保持一致：
        POLO衫、T恤、休闲裤、半身裙、卫衣、大衣、小香风、牛仔裤、
        皮草、皮衣、短外套、组合套、羽绒服、背心/吊带、衬衫、
        西装、连衣裙、配饰、针织衫、风衣、马夹/马夹裙
        """
        print("使用模拟库存数据...")
        
        mock_data = [
            # 超薄档相关（均温≥25°C）
            {"sku_id": "SS2409029", "name": "肯豆背心", "product_name": "U领针织背心", "category": "针织衫", "price": 189, "stock": 1887, "inbound": 302, "order_occupied": 150, "size_completeness": 0.85, "return_rate": 0.47, "conversion_rate": 0.028},
            {"sku_id": "MD56DF002", "name": "六色打底", "product_name": "半高领针织打底衫", "category": "针织衫", "price": 199, "stock": 1201, "inbound": 210, "order_occupied": 80, "size_completeness": 0.85, "return_rate": 0.55, "conversion_rate": 0.066},
            {"sku_id": "ME07DC104", "name": "野兽派", "product_name": "印花松紧腰半身裙", "category": "半身裙", "price": 299, "stock": 822, "inbound": 77, "order_occupied": 120, "size_completeness": 0.85, "return_rate": 0.75, "conversion_rate": 0.055},
            {"sku_id": "ME07DC084", "name": "野兽派", "product_name": "印花松紧腰短裙", "category": "半身裙", "price": 329, "stock": 982, "inbound": 95, "order_occupied": 90, "size_completeness": 0.85, "return_rate": 0.78, "conversion_rate": 0.055},
            {"sku_id": "ME07DC083", "name": "野兽派", "product_name": "豹纹印花中短裙", "category": "半身裙", "price": 259, "stock": 460, "inbound": 46, "order_occupied": 45, "size_completeness": 0.85, "return_rate": 0.76, "conversion_rate": 0.055},
            {"sku_id": "ME10DC001", "name": "T恤款", "product_name": "纯棉基础款T恤", "category": "T恤", "price": 199, "stock": 1200, "inbound": 300, "order_occupied": 200, "size_completeness": 0.85, "return_rate": 0.50, "conversion_rate": 0.050},
            {"sku_id": "ME13DC001", "name": "背心款", "product_name": "基础款背心", "category": "背心/吊带", "price": 149, "stock": 2100, "inbound": 400, "order_occupied": 300, "size_completeness": 0.85, "return_rate": 0.45, "conversion_rate": 0.055},
            {"sku_id": "ME08DC001", "name": "连衣裙", "product_name": "碎花连衣裙", "category": "连衣裙", "price": 499, "stock": 678, "inbound": 180, "order_occupied": 150, "size_completeness": 0.85, "return_rate": 0.62, "conversion_rate": 0.038},
            
            # 薄档相关（均温15~25°C）
            {"sku_id": "ME05DC026", "name": "流浪诗人", "product_name": "花苞裤", "category": "休闲裤", "price": 299, "stock": 230, "inbound": 35, "order_occupied": 50, "size_completeness": 0.85, "return_rate": 0.77, "conversion_rate": 0.023},
            {"sku_id": "ME01DV084", "name": "流浪诗人", "product_name": "亚麻宽松小领西装", "category": "西装", "price": 599, "stock": 125, "inbound": 797, "order_occupied": 100, "size_completeness": 0.85, "return_rate": 0.80, "conversion_rate": 0.023},
            {"sku_id": "ME04DC005", "name": "流浪诗人", "product_name": "亚麻马甲", "category": "马夹/马夹裙", "price": 399, "stock": 319, "inbound": 153, "order_occupied": 193, "size_completeness": 0.85, "return_rate": 0.79, "conversion_rate": 0.023},
            {"sku_id": "ME09DC001", "name": "衬衫款", "product_name": "亚麻衬衫", "category": "衬衫", "price": 299, "stock": 445, "inbound": 95, "order_occupied": 80, "size_completeness": 0.85, "return_rate": 0.58, "conversion_rate": 0.042},
            {"sku_id": "ME06DC001", "name": "牛仔裤", "product_name": "修身牛仔裤", "category": "牛仔裤", "price": 399, "stock": 890, "inbound": 150, "order_occupied": 120, "size_completeness": 0.85, "return_rate": 0.55, "conversion_rate": 0.045},
            {"sku_id": "ME11DC001", "name": "短外套", "product_name": "牛仔外套", "category": "短外套", "price": 459, "stock": 334, "inbound": 78, "order_occupied": 60, "size_completeness": 0.85, "return_rate": 0.68, "conversion_rate": 0.032},
            
            # 中等档相关（均温<15°C）
            {"sku_id": "ME02DV001", "name": "风衣款", "product_name": "经典风衣", "category": "风衣", "price": 699, "stock": 456, "inbound": 120, "order_occupied": 90, "size_completeness": 0.85, "return_rate": 0.65, "conversion_rate": 0.035},
            {"sku_id": "ME02DV002", "name": "大衣款", "product_name": "羊毛大衣", "category": "大衣", "price": 899, "stock": 234, "inbound": 89, "order_occupied": 70, "size_completeness": 0.85, "return_rate": 0.70, "conversion_rate": 0.030},
            {"sku_id": "ME03DV003", "name": "卫衣款", "product_name": "连帽卫衣", "category": "卫衣", "price": 359, "stock": 567, "inbound": 200, "order_occupied": 150, "size_completeness": 0.85, "return_rate": 0.60, "conversion_rate": 0.040},
            {"sku_id": "ME12DC001", "name": "羽绒服", "product_name": "轻薄羽绒服", "category": "羽绒服", "price": 799, "stock": 123, "inbound": 45, "order_occupied": 40, "size_completeness": 0.85, "return_rate": 0.72, "conversion_rate": 0.025},
            
            # 其他品类
            {"sku_id": "ME14DC001", "name": "POLO衫", "product_name": "经典POLO衫", "category": "POLO衫", "price": 259, "stock": 567, "inbound": 120, "order_occupied": 80, "size_completeness": 0.85, "return_rate": 0.52, "conversion_rate": 0.048},
            {"sku_id": "ME15DC001", "name": "皮草款", "product_name": "仿皮草外套", "category": "皮草", "price": 1299, "stock": 45, "inbound": 20, "order_occupied": 15, "size_completeness": 0.85, "return_rate": 0.75, "conversion_rate": 0.020},
            {"sku_id": "ME16DC001", "name": "皮衣款", "product_name": "机车皮衣", "category": "皮衣", "price": 899, "stock": 78, "inbound": 30, "order_occupied": 25, "size_completeness": 0.85, "return_rate": 0.70, "conversion_rate": 0.025},
        ]
        
        # 计算可售库存
        for item in mock_data:
            item['total_stock'] = item['stock'] + item['inbound']
            item['available_stock'] = item['total_stock'] - item.get('order_occupied', 0)
        
        return mock_data
    
    def get_category_summary(self) -> Dict[str, Dict[str, Any]]:
        """获取品类汇总数据"""
        inventory = self.fetch_inventory_data()
        
        category_summary = {}
        for item in inventory:
            cat = item['category']
            if cat not in category_summary:
                category_summary[cat] = {
                    'total_stock': 0,
                    'total_inbound': 0,
                    'sku_count': 0,
                    'avg_return_rate': 0,
                    'avg_conversion_rate': 0
                }
            
            category_summary[cat]['total_stock'] += item['stock']
            category_summary[cat]['total_inbound'] += item['inbound']
            category_summary[cat]['sku_count'] += 1
            category_summary[cat]['avg_return_rate'] += item['return_rate']
            category_summary[cat]['avg_conversion_rate'] += item['conversion_rate']
        
        # 计算平均值
        for cat in category_summary:
            count = category_summary[cat]['sku_count']
            if count > 0:
                category_summary[cat]['avg_return_rate'] /= count
                category_summary[cat]['avg_conversion_rate'] /= count
        
        return category_summary


# 单例模式
_bi_inventory_service_v3 = None

def get_bi_inventory_service_v3() -> BIInventoryServiceV3:
    """获取 BI 库存服务 V3 实例"""
    global _bi_inventory_service_v3
    if _bi_inventory_service_v3 is None:
        _bi_inventory_service_v3 = BIInventoryServiceV3()
    return _bi_inventory_service_v3


if __name__ == "__main__":
    # 测试
    print("=" * 60)
    print("BI 库存数据服务 V3 测试")
    print("=" * 60)
    
    service = BIInventoryServiceV3()
    
    # 获取库存数据
    print("\n1. 获取库存数据...")
    inventory = service.fetch_inventory_data(use_cache=False)
    
    print(f"\n获取到 {len(inventory)} 条记录")
    print("\n前5条数据预览:")
    for item in inventory[:5]:
        print(f"  {item['sku_id']} | {item['name'][:20]:<20} | 库存:{item['stock']:<8} | 在途:{item['inbound']:<8} | 退货率:{item['return_rate']:.1%} | 转化率:{item['conversion_rate']:.1%}")
    
    # 获取品类汇总
    print("\n2. 品类汇总...")
    summary = service.get_category_summary()
    for cat, data in summary.items():
        print(f"  {cat}: 库存{data['total_stock']}, 在途{data['total_inbound']}, SKU数{data['sku_count']}")
