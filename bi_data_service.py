"""
BI数据服务模块
从观远BI系统获取真实的库存、采购、销售数据
"""
import json
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Set, Iterable

# 导入BI库存服务（使用V3版本 - 从拉新款式表现卡片获取所有数据）
from bi_inventory_service_v3 import BIInventoryServiceV3


class BIDataService:
    """BI数据服务类"""

    # ============================================================
    # 天气选品推荐规范（基于 MARIUS 天气选品数据 Excel 提炼）
    # 
    # 规则来源：按均温+天气现象两个维度判断
    #
    # 【超薄】均温 ≥ 25°C，晴/多云
    #   原始品类：短袖T恤、连衣裙、亚麻款、冰丝款
    #   → BI映射：U领针织背心、半高领针织打底衫、印花松紧腰半身裙、
    #             印花松紧腰短裙、豹纹印花中短裙、亚麻马甲
    #
    # 【薄】均温 15~25°C，晴/多云/阴/轻微降水
    #   原始品类：长袖T恤、薄外套、薄款长裤、亚麻款、连衣裙、短袖T恤
    #   → BI映射：半高领针织打底衫、U领针织背心、亚麻宽松小领西装、
    #             花苞裤、亚麻马甲、印花松紧腰半身裙、印花松紧腰短裙
    #
    # 【中等/雨天】均温 < 15°C，或有雨/雾
    #   原始品类：长袖T恤、风衣、防泼水外套、薄外套、薄毛衣
    #   → BI映射：半高领针织打底衫、亚麻宽松小领西装、U领针织背心
    #
    # 【雨天叠加规则】有降水时，优先推防泼水/风衣类
    #   → BI映射：亚麻宽松小领西装（最接近风衣/防泼水外套）
    # ============================================================

    # ============================================================
    # Excel品类 → BI产品分类 映射表
    # 
    # BI 产品分类字段包含：POLO衫、T恤、休闲裤、半身裙、卫衣、大衣、
    # 小香风、牛仔裤、皮草、皮衣、短外套、组合套、羽绒服、背心/吊带、
    # 衬衫、西装、连衣裙、配饰、针织衫、风衣、马夹/马夹裙
    # ============================================================
    EXCEL_TO_BI_CATEGORY = {
        # 超薄档（均温≥25°C）
        "短袖T恤":   ["T恤", "背心/吊带", "针织衫"],
        "冰丝款":    ["针织衫", "T恤"],
        "连衣裙":    ["连衣裙", "半身裙"],
        "亚麻款":    ["衬衫", "西装", "马夹/马夹裙"],
        
        # 薄档（均温15~25°C）
        "长袖T恤":   ["针织衫", "T恤", "衬衫"],
        "薄外套":    ["西装", "短外套", "风衣", "衬衫"],
        "薄款长裤":  ["休闲裤", "牛仔裤"],
        
        # 中等档（均温<15°C）
        "风衣":      ["风衣", "大衣"],
        "防泼水外套":["风衣", "短外套", "大衣"],
        "薄毛衣":    ["针织衫", "卫衣"],
        "羽绒服":    ["羽绒服"],
    }

    # 城市温度校准系数（用于体现体感差异）
    CITY_TEMP_OFFSET = {
        "北京": -1.5,
        "上海": 0.0,
        "广州": 2.0,
        "杭州": -0.5,
        "江苏": -0.5
    }

    HIGH_HUMIDITY_THRESHOLD = 75
    HIGH_WIND_THRESHOLD = 5
    # 体感低于该值才将全国多雨/高湿/大风映射品类并入推荐；≥ 该值时仅以温度主规则为准（与内置「温暖档」下限 22°C 对齐）
    SUPPLEMENTAL_OVERLAY_MERGE_BELOW_ADJ_TEMP = 22.0
    # 体感 ≥ 该值则从推荐中剔除大衣/短外套/风衣（内置「薄外套」仍会映射出短外套/风衣；仅靠 22°C 时北京等 -1.5℃ 体感常落在 15~22 档导致剔除不生效）
    OUTERWEAR_STRIP_MIN_ADJ_TEMP = 20.0
    HOT_DAY_STRIPPED_OUTERWEAR = frozenset({"大衣", "短外套", "风衣"})
    MAJOR_RAIN_CITIES = {"北京", "上海", "广州", "杭州", "江苏"}

    BRAND_ALIASES = {
        "all": "all",
        "全部": "all",
        "marius": "marius",
        "zihaoselect": "zihaoselect",
        "zihao select": "zihaoselect",
        "zihao_select": "zihaoselect",
        "子豪": "zihaoselect",
        "子豪select": "zihaoselect",
    }
    
    def __init__(self, use_bi_data: bool = True):
        self.use_bi_data = use_bi_data
        self._bi_service = None
        self._products_cache = None
        self._rules_config = self._load_rules_config()
        # 款式 -> { unit_cost, retail_price? }，来自 sku_unit_cost.json（利润款）
        self._sku_economics_map: Optional[Dict[str, Dict[str, Any]]] = None

    def _load_rules_config(self) -> Dict[str, Any]:
        """加载推荐规则与品牌映射配置"""
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "recommendation_rules.json"
        )
        default_config = {
            "brand_mapping": {
                "default_brand": "marius",
                "brands": {
                    "marius": {"sku_prefixes": []},
                    "zihaoselect": {"sku_prefixes": ["z", "zs", "zh"]}
                }
            },
            "weather_recommendation_framework": {}
        }
        try:
            if not os.path.exists(config_path):
                return default_config
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            if not isinstance(user_config, dict):
                return default_config
            merged = default_config.copy()
            merged.update(user_config)
            return merged
        except Exception as e:
            print(f"⚠️ 规则配置加载失败，使用默认配置: {e}")
            return default_config

    def _sku_economics_file_path(self) -> str:
        raw = (os.getenv("SKU_UNIT_COST_FILE") or "sku_unit_cost.json").strip() or "sku_unit_cost.json"
        base = os.path.dirname(os.path.abspath(__file__))
        return raw if os.path.isabs(raw) else os.path.join(base, raw)

    def reload_sku_economics(self) -> None:
        """热更新单品成本/售价映射（下次读取文件）。"""
        self._sku_economics_map = None

    def _load_sku_economics_map(self) -> Dict[str, Dict[str, Any]]:
        if self._sku_economics_map is not None:
            return self._sku_economics_map
        path = self._sku_economics_file_path()
        out: Dict[str, Dict[str, Any]] = {}
        if not os.path.isfile(path):
            self._sku_economics_map = out
            return out
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            print(f"⚠️ 单品成本文件读取失败 ({path}): {e}")
            self._sku_economics_map = out
            return out
        if not isinstance(raw, dict):
            self._sku_economics_map = out
            return out
        for k, v in raw.items():
            ks = str(k).strip()
            if not ks or ks.startswith("_"):
                continue
            if isinstance(v, (int, float)):
                out[ks] = {"unit_cost": float(v), "retail_price": None}
            elif isinstance(v, dict):
                c = v.get("unit_cost", v.get("cost"))
                if c is None:
                    continue
                rp = v.get("retail_price", v.get("price"))
                out[ks] = {
                    "unit_cost": float(c),
                    "retail_price": float(rp) if rp is not None else None,
                }
        self._sku_economics_map = out
        return out

    def _get_unit_cost(self, product: Dict[str, Any]) -> Optional[float]:
        sku = str(product.get("sku_id", "")).strip()
        row = self._load_sku_economics_map().get(sku)
        if not row:
            return None
        return float(row["unit_cost"])

    def _get_effective_retail_price(self, product: Dict[str, Any]) -> float:
        """售价：优先成本文件中的 retail_price，否则 BI 商品 price。"""
        sku = str(product.get("sku_id", "")).strip()
        row = self._load_sku_economics_map().get(sku)
        if row and row.get("retail_price") is not None:
            return float(row["retail_price"])
        return float(product.get("price") or 0)

    def clear_cache(self):
        """清除缓存"""
        self._products_cache = None
        # 确保BI服务实例已创建，然后清除其缓存
        bi_service = self._get_bi_service()
        bi_service.clear_cache()
        print("✓ BIDataService 缓存已清除")
    
    def _get_bi_service(self):
        """获取BI服务实例"""
        if self._bi_service is None:
            self._bi_service = BIInventoryServiceV3()
        return self._bi_service

    def _normalize_brand(self, brand: str) -> str:
        if not brand:
            return "all"
        key = str(brand).strip().lower()
        return self.BRAND_ALIASES.get(key, "all")

    def _infer_brand(self, item: Dict[str, Any]) -> str:
        """
        品牌识别规则（可配置）：
        - 款号以 z 开头 => zihaoselect
        - 其余默认归为 marius
        """
        sku_id = str(item.get("sku_id", "")).strip().lower()
        brand_mapping = self._rules_config.get("brand_mapping", {})
        brands = brand_mapping.get("brands", {})
        default_brand = brand_mapping.get("default_brand", "marius")

        for brand_name, rule in brands.items():
            sku_prefixes = [str(k).strip().lower() for k in rule.get("sku_prefixes", [])]
            if sku_prefixes and any(prefix and sku_id.startswith(prefix) for prefix in sku_prefixes):
                return brand_name
        return default_brand

    def get_recommendation_framework(self) -> Dict[str, Any]:
        """返回可讨论/可配置的天气推荐框架"""
        return self._rules_config.get("weather_recommendation_framework", {})

    def _get_product_role_thresholds(self) -> Dict[str, Any]:
        """
        单品角色门槛：引流款 / 利润款 / 库存款。
        配置见 recommendation_rules.json → product_role_thresholds（配置页可改）。
        """
        base: Dict[str, Any] = {
            "profit_retail_to_cost_ratio_min": 2.8,
            "traffic_min_net_sales_qty": 1000,
            "traffic_min_main_warehouse_stock": 200,
            "traffic_min_conversion_rate": 0.05,
            "traffic_price_positions": ["低"],
            "inventory_min_main_warehouse_stock": 200,
            "inventory_require_zero_procurement_inbound": True,
            "roles_min_available_stock": 0,
        }
        raw = self._rules_config.get("product_role_thresholds")
        if not isinstance(raw, dict):
            out = dict(base)
            out["traffic_price_positions"] = list(base["traffic_price_positions"])
            return self._finalize_product_role_thresholds(out)
        out = dict(base)
        out["traffic_price_positions"] = list(base["traffic_price_positions"])
        for key, default in base.items():
            if key not in raw:
                continue
            v = raw[key]
            if key == "inventory_require_zero_procurement_inbound":
                if isinstance(v, bool):
                    out[key] = v
                else:
                    out[key] = str(v).strip().lower() in ("1", "true", "yes", "on")
                continue
            if key == "traffic_price_positions":
                if isinstance(v, list):
                    out[key] = [str(x).strip() for x in v if str(x).strip()]
                elif isinstance(v, str):
                    out[key] = [
                        x.strip()
                        for x in v.replace("，", ",").split(",")
                        if x.strip()
                    ]
                continue
            if isinstance(default, bool):
                continue
            if isinstance(default, int):
                try:
                    out[key] = int(float(v))
                except (TypeError, ValueError):
                    pass
                continue
            if isinstance(default, float):
                try:
                    out[key] = float(v)
                except (TypeError, ValueError):
                    pass
        return self._finalize_product_role_thresholds(out)

    def _finalize_product_role_thresholds(self, out: Dict[str, Any]) -> Dict[str, Any]:
        """转化率阈值存 0~1；若配置写成百分数字如 5 则视为 5%。"""
        tc = float(out.get("traffic_min_conversion_rate", 0.05) or 0.0)
        if tc > 1.0:
            tc = tc / 100.0
        out["traffic_min_conversion_rate"] = float(min(max(tc, 0.0), 1.0))
        pos = out.get("traffic_price_positions")
        if not isinstance(pos, list):
            out["traffic_price_positions"] = []
        return out

    def _traffic_matches_price_position(
        self, product: Dict[str, Any], allowed: List[str]
    ) -> bool:
        """引流款价格定位：allowed 为空则不限制；否则 BI 字段需包含任一配置片段（如「低」）。"""
        if not allowed:
            return True
        pp = str(product.get("price_position") or "").strip()
        if not pp:
            return False
        for token in allowed:
            t = str(token).strip()
            if not t:
                continue
            if t in pp or pp in t:
                return True
        return False

    def get_rules_config(self) -> Dict[str, Any]:
        """返回完整规则配置"""
        return self._rules_config

    def update_rules_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        更新规则配置并持久化
        返回最新配置
        """
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "recommendation_rules.json"
        )
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(new_config, f, ensure_ascii=False, indent=2)
        self._rules_config = self._load_rules_config()
        return self._rules_config
    
    def _generate_mock_products(self) -> List[Dict[str, Any]]:
        """生成模拟商品数据
        
        品类与BI产品分类字段保持一致：
        POLO衫、T恤、休闲裤、半身裙、卫衣、大衣、小香风、牛仔裤、
        皮草、皮衣、短外套、组合套、羽绒服、背心/吊带、衬衫、
        西装、连衣裙、配饰、针织衫、风衣、马夹/马夹裙
        """
        products = []
        
        # 商品基础数据（使用BI产品分类）
        categories_data = {
            # 超薄档（均温≥25°C）
            "T恤": {
                "items": [
                    {"sku_id": "TS001", "name": "纯棉基础款T恤", "base_price": 99},
                    {"sku_id": "TS002", "name": "印花休闲T恤", "base_price": 129},
                    {"sku_id": "TS003", "name": "速干运动T恤", "base_price": 159},
                    {"sku_id": "TS004", "name": "丝光棉T恤", "base_price": 199},
                ]
            },
            "针织衫": {
                "items": [
                    {"sku_id": "ZZ001", "name": "V领针织衫", "base_price": 189},
                    {"sku_id": "ZZ002", "name": "圆领薄毛衣", "base_price": 219},
                    {"sku_id": "ZZ003", "name": "针织开衫", "base_price": 269},
                    {"sku_id": "ZZ004", "name": "半高领针织打底衫", "base_price": 199},
                    {"sku_id": "ZZ005", "name": "U领针织背心", "base_price": 149},
                ]
            },
            "半身裙": {
                "items": [
                    {"sku_id": "BQ001", "name": "印花松紧腰半身裙", "base_price": 299},
                    {"sku_id": "BQ002", "name": "印花松紧腰短裙", "base_price": 259},
                    {"sku_id": "BQ003", "name": "豹纹印花中短裙", "base_price": 329},
                    {"sku_id": "BQ004", "name": "碎花半身裙", "base_price": 279},
                ]
            },
            "背心/吊带": {
                "items": [
                    {"sku_id": "BX001", "name": "基础款背心", "base_price": 79},
                    {"sku_id": "BX002", "name": "蕾丝吊带", "base_price": 129},
                ]
            },
            "连衣裙": {
                "items": [
                    {"sku_id": "DQ001", "name": "碎花连衣裙", "base_price": 299},
                    {"sku_id": "DQ002", "name": "法式茶歇裙", "base_price": 359},
                    {"sku_id": "DQ003", "name": "吊带连衣裙", "base_price": 259},
                ]
            },
            
            # 薄档（均温15~25°C）
            "衬衫": {
                "items": [
                    {"sku_id": "CS001", "name": "亚麻衬衫", "base_price": 229},
                    {"sku_id": "CS002", "name": "雪纺衬衫", "base_price": 199},
                    {"sku_id": "CS003", "name": "纯棉牛津纺衬衫", "base_price": 259},
                    {"sku_id": "CS004", "name": "亚麻宽松小领西装", "base_price": 599},
                ]
            },
            "西装": {
                "items": [
                    {"sku_id": "XZ001", "name": "廓形西装", "base_price": 699},
                    {"sku_id": "XZ002", "name": "修身西装", "base_price": 599},
                    {"sku_id": "XZ003", "name": "亚麻西装", "base_price": 799},
                ]
            },
            "休闲裤": {
                "items": [
                    {"sku_id": "XK001", "name": "花苞裤", "base_price": 299},
                    {"sku_id": "XK002", "name": "直筒休闲裤", "base_price": 259},
                    {"sku_id": "XK003", "name": "阔腿休闲裤", "base_price": 329},
                ]
            },
            "牛仔裤": {
                "items": [
                    {"sku_id": "NZ001", "name": "修身牛仔裤", "base_price": 299},
                    {"sku_id": "NZ002", "name": "阔腿牛仔裤", "base_price": 329},
                    {"sku_id": "NZ003", "name": "直筒牛仔裤", "base_price": 279},
                ]
            },
            "马夹/马夹裙": {
                "items": [
                    {"sku_id": "MJ001", "name": "亚麻马甲", "base_price": 399},
                    {"sku_id": "MJ002", "name": "西装马甲", "base_price": 359},
                ]
            },
            "短外套": {
                "items": [
                    {"sku_id": "DW001", "name": "牛仔外套", "base_price": 399},
                    {"sku_id": "DW002", "name": "夹克外套", "base_price": 459},
                ]
            },
            
            # 中等档（均温<15°C）
            "卫衣": {
                "items": [
                    {"sku_id": "WY001", "name": "连帽卫衣", "base_price": 239},
                    {"sku_id": "WY002", "name": "圆领卫衣", "base_price": 199},
                    {"sku_id": "WY003", "name": "加绒卫衣", "base_price": 279},
                ]
            },
            "风衣": {
                "items": [
                    {"sku_id": "FY001", "name": "经典风衣", "base_price": 699},
                    {"sku_id": "FY002", "name": "中长款风衣", "base_price": 799},
                ]
            },
            "大衣": {
                "items": [
                    {"sku_id": "DY001", "name": "羊毛大衣", "base_price": 899},
                    {"sku_id": "DY002", "name": "短款大衣", "base_price": 699},
                    {"sku_id": "DY003", "name": "双面呢大衣", "base_price": 1299},
                ]
            },
            "羽绒服": {
                "items": [
                    {"sku_id": "YR001", "name": "轻薄羽绒服", "base_price": 499},
                    {"sku_id": "YR002", "name": "长款羽绒服", "base_price": 899},
                    {"sku_id": "YR003", "name": "羽绒马甲", "base_price": 359},
                ]
            },
            
            # 其他品类
            "POLO衫": {
                "items": [
                    {"sku_id": "PL001", "name": "经典POLO衫", "base_price": 199},
                    {"sku_id": "PL002", "name": "休闲POLO衫", "base_price": 229},
                ]
            },
            "小香风": {
                "items": [
                    {"sku_id": "XX001", "name": "小香风外套", "base_price": 599},
                ]
            },
            "皮草": {
                "items": [
                    {"sku_id": "PC001", "name": "仿皮草外套", "base_price": 799},
                ]
            },
            "皮衣": {
                "items": [
                    {"sku_id": "PY001", "name": "机车皮衣", "base_price": 899},
                ]
            },
        }
        
        for category, data in categories_data.items():
            for item in data["items"]:
                # 生成随机业务数据
                stock = random.randint(220, 2600)  # 现货库存（便于满足引流主仓门槛演示）
                inbound = random.randint(0, 800)  # 采购在途
                order_occupied = random.randint(0, min(150, stock))
                size_completeness = round(random.uniform(0.6, 1.0), 2)  # 尺码齐全度
                return_rate = round(random.uniform(0.05, 0.25), 2)  # 退货率 5%-25%
                conversion_rate = round(random.uniform(0.05, 0.18), 3)  # 支付转化率（与引流下限对齐）
                sales_qty = random.randint(1200, 4500)
                net_sales_qty = max(
                    1001,
                    int(round(sales_qty * (1 - min(return_rate, 0.95)))),
                )
                price_position = random.choice(["低", "中", "高"])
                avail = max(0, stock + inbound - order_occupied)
                
                products.append({
                    "sku_id": item["sku_id"],
                    "category": category,
                    "name": item["name"],
                    "product_name": item["name"],
                    "price": item["base_price"],
                    "stock": stock,
                    "inbound": inbound,
                    "sales_return_stock": 0,
                    "sales_return_inbound": 0,
                    "virtual_cloud_stock": 0,
                    "order_occupied": order_occupied,
                    "available_stock": avail,
                    "sales_qty": sales_qty,
                    "net_sales_qty": net_sales_qty,
                    "size_completeness": size_completeness,
                    "return_rate": return_rate,
                    "conversion_rate": conversion_rate,
                    "price_position": price_position,
                    "update_time": datetime.now().isoformat()
                })
        
        return products
    
    def fetch_bi_inventory_data(self) -> List[Dict[str, Any]]:
        """
        获取BI库存数据
        优先从观远BI系统获取真实数据；真实模式失败时返回空，避免模拟数据污染
        """
        if self.use_bi_data:
            try:
                bi_service = self._get_bi_service()
                # 防止 BI 请求长时间阻塞接口
                executor = ThreadPoolExecutor(max_workers=1)
                try:
                    future = executor.submit(bi_service.fetch_inventory_data)
                    bi_data = future.result(timeout=150)
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
                if bi_data and len(bi_data) > 0:
                    # 将BI数据格式转换为推荐系统格式
                    converted_data = []
                    valid_categories = set()
                    for item in bi_data:
                        # 直接使用BI返回的品类和名称
                        sku_id = item.get('sku_id', '')
                        short_name = item.get('name', '')
                        product_name = item.get('product_name', '')
                        category = item.get('category', '其他')

                        # 名称优先级：小名 -> 产品名称 -> sku_id
                        display_name = short_name
                        if (
                            display_name in ['', 'None', None]
                            or '.' in str(display_name)
                            or (str(display_name).isdigit() and len(str(display_name)) >= 8)
                        ):
                            display_name = product_name or f"款式-{sku_id}"
                        
                        # 检查品类是否有效
                        if category and category != '其他':
                            valid_categories.add(category)
                        
                        converted_data.append({
                            "sku_id": sku_id,
                            "category": category,
                            "name": display_name,
                            "product_name": product_name,
                            "style_tag": item.get('style_tag', ''),
                            "brand": self._infer_brand(item),
                            "price_position": str(item.get("price_position", "") or "").strip(),
                            "image_url": item.get('image_url', ''),
                            "price": item.get('price', 299),
                            "stock": item.get('stock', 0),
                            "sales_return_stock": item.get('sales_return_stock', 0),
                            "inbound": item.get('inbound', 0),
                            "sales_return_inbound": item.get('sales_return_inbound', 0),
                            "virtual_cloud_stock": item.get('virtual_cloud_stock', 0),
                            "order_occupied": item.get('order_occupied', 0),
                            "available_stock": item.get('available_stock', item.get('stock', 0)),
                            "sales_qty": int(item.get("sales_qty", 0) or 0),
                            "net_sales_qty": int(item.get("net_sales_qty", 0) or 0),
                            "size_completeness": item.get('size_completeness', 0.85),
                            "return_rate": item.get('return_rate', 0.15),
                            "conversion_rate": item.get('conversion_rate', 0.05),
                            "update_time": datetime.now().isoformat()
                        })
                    
                    print(f"[DEBUG] BI数据转换完成: {len(converted_data)} 条记录")
                    print(f"[DEBUG] 有效品类: {valid_categories}")
                    
                    # 品类过少通常表示抓取异常，返回空等待重试
                    if len(valid_categories) < 3:
                        print(f"⚠️ BI数据品类异常（只有 {len(valid_categories)} 个有效品类），返回空数据")
                        return []
                    
                    return converted_data
            except FuturesTimeoutError:
                print("从BI获取数据超时，返回空数据")
            except Exception as e:
                print(f"从BI获取数据失败: {e}，返回空数据")
            return []

        # 仅在明确配置 use_bi_data=False 时才使用模拟数据
        return self._generate_mock_products()
    
    def _infer_category(self, name: str) -> str:
        """根据商品名称推断品类"""
        name = name.lower()
        # 简单的关键词匹配
        if any(kw in name for kw in ['t恤', 't-shirt', '短袖']):
            return "夏季T恤"
        elif any(kw in name for kw in ['连衣裙', '裙子']):
            return "连衣裙"
        elif any(kw in name for kw in ['针织', '开衫']):
            return "轻薄针织"
        elif any(kw in name for kw in ['外套', '夹克']):
            return "防水外套"
        elif any(kw in name for kw in ['牛仔裤', '牛仔']):
            return "牛仔裤"
        elif any(kw in name for kw in ['卫衣']):
            return "卫衣"
        elif any(kw in name for kw in ['大衣', '毛呢']):
            return "毛呢外套"
        else:
            return "其他"
    
    def _canonical_temp_band(self, adjusted_temp: float) -> str:
        """
        与 recommendation_rules.json 中 temp_range 对应的体感温度档（互斥区间，单位 °C）。
        15°C 以下细分为：10~15、5~10、0~5、-5~0、-15~-5；体感 <-15°C 与 -15~-5 共用同一档配置。
        """
        if adjusted_temp >= 28:
            return ">=28"
        if adjusted_temp >= 22:
            return "22-28"
        if adjusted_temp >= 15:
            return "15-22"
        if adjusted_temp >= 10:
            return "10-15"
        if adjusted_temp >= 5:
            return "5-10"
        if adjusted_temp >= 0:
            return "0-5"
        if adjusted_temp >= -5:
            return "-5~0"
        return "-15~-5"

    def _normalize_temp_range_key(self, temp_range: str) -> str:
        """将配置里的 temp_range 归一到与 _canonical_temp_band 一致的键。"""
        raw = str(temp_range or "").strip()
        s = (
            raw.replace(" ", "")
            .replace("℃", "")
            .replace("°C", "")
            .replace("～", "~")
            .replace("—", "-")
        )
        sl = s.lower()

        if s in (">=28", ">=28c") or sl == ">=28" or "高温档" in raw or raw.strip() == "高温":
            return ">=28"
        if s in ("22-28", "22~28", "22—28") or "温暖档" in raw:
            return "22-28"
        if s in ("15-22", "15~22") or "微凉档" in raw:
            return "15-22"

        # 15°C 以下细分档（含零下）
        if s in ("10-15", "10~15") or "初冬过渡" in raw:
            return "10-15"
        if s in ("5-10", "5~10") or ("深秋" in raw and "寒凉" in raw) or raw.strip() == "深秋寒凉档":
            return "5-10"
        if s in ("0-5", "0~5") or "入冬保暖" in raw or (raw.strip() == "入冬防寒档"):
            return "0-5"
        if s in ("-5~0", "-5-0", "n5~0", "neg5~0") or "零下轻冻" in raw or "轻冻档" in raw:
            return "-5~0"
        s_dash = s.replace("−", "-")
        if s_dash in ("-15~-5", "-15--5") or "严寒冰冻" in raw:
            return "-15~-5"
        # 旧版单独「<-15」行：与 -15~-5 共用同一套品类
        if s_dash.replace(" ", "") in ("<-15",) or sl.replace("−", "-") == "<-15" or "极寒" in raw:
            return "-15~-5"

        # 旧版整段「<15°C」兼容：归一为 <15，供配置回退匹配
        if s in ("<15",) or sl == "<15" or "偏冷档" in raw:
            return "<15"
        return ""

    def _bi_categories_from_config_temperature(
        self, adjusted_temp: float
    ) -> Optional[Tuple[Dict[str, Any], Set[str], List[str]]]:
        """
        若 recommendation_rules.json 中配置了 temperature_rules（BI 品类直选），
        返回 (temp_rule_dict, bi_categories_set, categories_display_order)；否则返回 None。
        """
        rules = self._rules_config.get("temperature_rules")
        if not isinstance(rules, list) or not rules:
            return None
        band = self._canonical_temp_band(adjusted_temp)
        chosen: List[str] = []
        for row in rules:
            if not isinstance(row, dict):
                continue
            key = self._normalize_temp_range_key(str(row.get("temp_range", "")))
            if key != band:
                continue
            cats = row.get("categories")
            if isinstance(cats, list):
                chosen = [str(c).strip() for c in cats if str(c).strip()]
                break
        # 未命中细分档时，回退旧配置「整段 <15°C」行（体感仍低于 15°C 时）
        if not chosen and adjusted_temp < 15:
            for row in rules:
                if not isinstance(row, dict):
                    continue
                if self._normalize_temp_range_key(str(row.get("temp_range", ""))) != "<15":
                    continue
                cats = row.get("categories")
                if isinstance(cats, list):
                    chosen = [str(c).strip() for c in cats if str(c).strip()]
                    break
        if not chosen:
            return None
        bi_set = set(chosen)
        label_map = {
            ">=28": ("高温档", "高温晴热", "体感>=28°C，按配置推荐 BI 品类"),
            "22-28": ("温暖档", "温暖舒适", "体感22~28°C，按配置推荐 BI 品类"),
            "15-22": ("微凉档", "微凉过渡", "体感15~22°C，按配置推荐 BI 品类"),
            "10-15": ("初冬过渡档", "初冬偏凉", "体感10~15°C，轻薄外套与叠穿过渡"),
            "5-10": ("深秋寒凉档", "深秋寒凉", "体感5~10°C，大衣/羽绒需求上升"),
            "0-5": ("入冬防寒档", "入冬防寒", "体感0~5°C，羽绒与厚外套为主"),
            "-5~0": ("零下轻冻档", "零下轻冻", "体感-5~0°C，防寒保暖与配饰"),
            "-15~-5": ("严寒冰冻档", "严寒冰冻", "体感低于-5°C（含<-15°C），极厚保暖与防风"),
            "<15": ("偏冷档", "偏冷保暖", "体感<15°C（整段兼容），按配置推荐 BI 品类"),
        }
        name, label, desc = label_map.get(band, ("温度档", "温度规则", "按配置推荐 BI 品类"))
        return (
            {
                "name": name,
                "label": label,
                "description": desc,
                "excel_categories": [],
                "bi_categories_direct": list(bi_set),
            },
            bi_set,
            chosen,
        )

    def _get_temp_rule(self, adjusted_temp: float) -> Dict[str, Any]:
        """温度规则：>=28、22~28、15~22，及 15°C 以下多档（含零下）。"""
        if adjusted_temp >= 28:
            return {
                "name": "高温档",
                "label": "高温晴热",
                "description": "体感温度>=28°C，优先超薄与透气单品",
                "excel_categories": ["短袖T恤", "连衣裙", "亚麻款", "冰丝款"]
            }
        if adjusted_temp >= 22:
            return {
                "name": "温暖档",
                "label": "温暖舒适",
                "description": "体感温度22~28°C，优先轻薄叠穿",
                "excel_categories": ["短袖T恤", "长袖T恤", "薄外套", "连衣裙", "亚麻款"]
            }
        if adjusted_temp >= 15:
            return {
                "name": "微凉档",
                "label": "微凉过渡",
                "description": "体感温度15~22°C，优先长袖/薄外套/长裤",
                "excel_categories": ["长袖T恤", "薄外套", "薄款长裤", "亚麻款", "薄毛衣"]
            }
        if adjusted_temp >= 10:
            return {
                "name": "初冬过渡档",
                "label": "初冬偏凉",
                "description": "体感10~15°C，风衣/针织叠穿与薄外套过渡",
                "excel_categories": ["风衣", "薄毛衣", "长袖T恤", "防泼水外套"]
            }
        if adjusted_temp >= 5:
            return {
                "name": "深秋寒凉档",
                "label": "深秋寒凉",
                "description": "体感5~10°C，大衣与保暖外套需求明显上升",
                "excel_categories": ["风衣", "防泼水外套", "薄毛衣", "长袖T恤", "薄外套"]
            }
        if adjusted_temp >= 0:
            return {
                "name": "入冬防寒档",
                "label": "入冬防寒",
                "description": "体感0~5°C，羽绒、大衣、皮草等厚保暖为主",
                "excel_categories": ["防泼水外套", "薄毛衣", "羽绒服", "风衣", "长袖T恤"]
            }
        if adjusted_temp >= -5:
            return {
                "name": "零下轻冻档",
                "label": "零下轻冻",
                "description": "体感-5~0°C，厚羽绒/皮草/配饰防冻",
                "excel_categories": ["羽绒服", "风衣", "防泼水外套", "薄毛衣"]
            }
        return {
            "name": "严寒冰冻档",
            "label": "严寒冰冻",
            "description": "体感低于-5°C（含<-15°C），极厚保暖、防风与户外防寒",
            "excel_categories": ["羽绒服", "防泼水外套", "风衣", "薄毛衣"]
        }

    @staticmethod
    def _finalize_category_order(preferred: List[str], final_set: Set[str]) -> List[str]:
        """保留 preferred 中仍存在于 final_set 的顺序，其余按字母补齐。"""
        out: List[str] = []
        seen: Set[str] = set()
        for c in preferred:
            if c in final_set and c not in seen:
                out.append(c)
                seen.add(c)
        for c in sorted(final_set):
            if c not in seen:
                out.append(c)
                seen.add(c)
        return out

    def _get_bi_categories_for_weather(
        self,
        avg_temp: float,
        city: str = "北京",
        avg_humidity: float = 60,
        avg_wind_scale: float = 3,
        season: str = "spring",
        national_rainy_city_count: int = 0
    ) -> Tuple[List[Dict[str, Any]], List[str], float, float, Set[str]]:
        """
        根据温度/湿度/风力/季节/全国雨情返回推荐规则。

        返回最后一项 temp_primary_bi_categories：仅「温度主规则」映射出的 BI 品类集合。

        当体感温度 ≥ SUPPLEMENTAL_OVERLAY_MERGE_BELOW_ADJ_TEMP（默认 22°C）时，bi_categories 仅含温度主规则，
        不并入全国多雨/高湿/大风（温度优先）。低于该阈值时才叠加这些规则。
        """
        city_offset = self.CITY_TEMP_OFFSET.get(city, 0.0)
        adjusted_temp = avg_temp + city_offset

        matched_rules = []
        bi_categories: Set[str] = set()
        temp_primary_bi_categories: Set[str] = set()
        order_hint: List[str] = []

        # 1) 温度主规则（优先使用配置中的 temperature_rules，BI 品类直配）
        cfg_temp = self._bi_categories_from_config_temperature(adjusted_temp)
        if cfg_temp:
            temp_rule, direct_cats, chosen_order = cfg_temp
            matched_rules.append(temp_rule)
            bi_categories.update(direct_cats)
            temp_primary_bi_categories.update(direct_cats)
            order_hint = list(chosen_order)
        else:
            temp_rule = self._get_temp_rule(adjusted_temp)
            matched_rules.append(temp_rule)
            for excel_cat in temp_rule["excel_categories"]:
                for c in self.EXCEL_TO_BI_CATEGORY.get(excel_cat, []):
                    if c not in order_hint:
                        order_hint.append(c)
            bi_categories.update(order_hint)
            temp_primary_bi_categories.update(order_hint)

        merge_supplemental = adjusted_temp < self.SUPPLEMENTAL_OVERLAY_MERGE_BELOW_ADJ_TEMP

        def _append_categories_to_order(mapped: Iterable[str]) -> None:
            for c in mapped:
                if c not in order_hint:
                    order_hint.append(c)

        # 2)～4) 仅在偏凉体感下叠加；高温天不因多雨/高湿/大风把大衣、短外套等并入推荐品类
        if merge_supplemental:
            # 2) 全国大部分城市雨天规则（未来7天雨天城市数 >= 2）
            if national_rainy_city_count >= 2:
                overlay = self._rules_config.get("rain_overlay_categories")
                if isinstance(overlay, list) and any(isinstance(x, str) and x.strip() for x in overlay):
                    rain_cats = {str(x).strip() for x in overlay if isinstance(x, str) and str(x).strip()}
                    rain_rule = {
                        "name": "全国多雨",
                        "label": "全国多城市降雨",
                        "description": "未来7天多数重点城市有雨，叠加配置中的雨天品类",
                        "excel_categories": [],
                        "bi_categories_direct": list(rain_cats),
                    }
                    matched_rules.append(rain_rule)
                    bi_categories.update(rain_cats)
                    _append_categories_to_order(sorted(rain_cats))
                else:
                    rain_rule = {
                        "name": "全国多雨",
                        "label": "全国多城市降雨",
                        "description": "未来7天多数重点城市有雨，叠加防泼水/外套需求",
                        "excel_categories": ["风衣", "防泼水外套", "薄外套"]
                    }
                    matched_rules.append(rain_rule)
                    for excel_cat in rain_rule["excel_categories"]:
                        mapped = self.EXCEL_TO_BI_CATEGORY.get(excel_cat, [])
                        bi_categories.update(mapped)
                        _append_categories_to_order(mapped)

            # 3) 高湿度规则（下调针织，提升轻薄快干候选）
            if avg_humidity >= self.HIGH_HUMIDITY_THRESHOLD:
                humid_rule = {
                    "name": "高湿",
                    "label": "高湿闷热",
                    "description": "湿度高于75%，减少针织优先级，提升轻薄透气类",
                    "excel_categories": ["短袖T恤", "亚麻款", "连衣裙"]
                }
                matched_rules.append(humid_rule)
                for excel_cat in humid_rule["excel_categories"]:
                    mapped = self.EXCEL_TO_BI_CATEGORY.get(excel_cat, [])
                    bi_categories.update(mapped)
                    _append_categories_to_order(mapped)

            # 4) 大风规则（按季节）
            if avg_wind_scale >= self.HIGH_WIND_THRESHOLD:
                if season == "winter":
                    wind_rule = {
                        "name": "冬季大风",
                        "label": "冬季大风",
                        "description": "冬季大风，提升冲锋衣/羽绒服权重（无冲锋衣字段时由风衣/短外套替代）",
                        "excel_categories": ["防泼水外套", "风衣", "薄毛衣"]
                    }
                    bi_categories.update({"羽绒服"})
                    _append_categories_to_order(["羽绒服"])
                else:
                    wind_rule = {
                        "name": "春秋大风",
                        "label": "春秋大风",
                        "description": "春秋大风，提升外套/风衣权重",
                        "excel_categories": ["薄外套", "风衣", "防泼水外套"]
                    }
                matched_rules.append(wind_rule)
                for excel_cat in wind_rule["excel_categories"]:
                    mapped = self.EXCEL_TO_BI_CATEGORY.get(excel_cat, [])
                    bi_categories.update(mapped)
                    _append_categories_to_order(mapped)

        # 暖热体感：去掉大衣/短外套/风衣（与叠加规则无关；来自 Excel「薄外套」等对 BI 的固定映射）
        if adjusted_temp >= self.OUTERWEAR_STRIP_MIN_ADJ_TEMP:
            stripped_bio = set(bi_categories) - self.HOT_DAY_STRIPPED_OUTERWEAR
            stripped_tp = set(temp_primary_bi_categories) - self.HOT_DAY_STRIPPED_OUTERWEAR
            if stripped_bio:
                bi_categories = stripped_bio
            if stripped_tp:
                temp_primary_bi_categories = stripped_tp

        order_hint = [c for c in order_hint if c in bi_categories]
        bi_categories_ordered = self._finalize_category_order(order_hint, bi_categories)

        return matched_rules, bi_categories_ordered, adjusted_temp, city_offset, set(temp_primary_bi_categories)

    def get_category_summary(self, bi_categories: List[str]) -> Dict[str, Any]:
        """
        按BI品类聚合库存数据
        一个BI品类 = 多个单品的汇总（stock/inbound求和，return_rate/conversion_rate求均值）
        """
        summary = {}
        products = self.fetch_bi_inventory_data()
        
        # 调试输出
        print(f"[DEBUG] 请求的BI品类: {bi_categories}")
        print(f"[DEBUG] 产品总数: {len(products)}")
        if products:
            print(f"[DEBUG] 产品品类分布: {list(set(p['category'] for p in products))}")

        for category in bi_categories:
            category_products = [p for p in products if p["category"] == category]
            print(f"[DEBUG] 品类 '{category}' 匹配到 {len(category_products)} 个产品")
            if category_products:
                total_stock = sum(p["stock"] for p in category_products)
                total_inbound = sum(p["inbound"] for p in category_products)
                sku_count = len(category_products)
                avg_return_rate = round(
                    sum(p["return_rate"] for p in category_products) / sku_count, 2
                )
                avg_conversion_rate = round(
                    sum(p["conversion_rate"] for p in category_products) / sku_count, 3
                )
                summary[category] = {
                    "total_stock": total_stock,
                    "total_inbound": total_inbound,
                    "sku_count": sku_count,
                    "avg_return_rate": avg_return_rate,
                    "avg_conversion_rate": avg_conversion_rate,
                    "skus": [p["sku_id"] for p in category_products],
                }

        return summary
    
    def calculate_recommendation_score(self, product: Dict[str, Any]) -> float:
        """
        库存款推荐指数：主仓库存 + 转化（清库存导向；不含在途）。
        """
        warehouse_stock = product.get("stock", 0)

        import math
        stock_normalized = min(math.log10(warehouse_stock + 10) / math.log10(5010), 1.0)
        stock_score = stock_normalized * 80

        cvr_score = min(product["conversion_rate"] / 0.15, 1.0) * 20

        return round(stock_score + cvr_score, 2)

    def calculate_traffic_score(self, product: Dict[str, Any]) -> float:
        """引流款：高净销量/销量 + 高转化，退货率惩罚。"""
        import math

        net_sales = int(product.get("net_sales_qty", 0) or 0)
        sales_qty = int(product.get("sales_qty", 0) or 0)
        cvr = float(product.get("conversion_rate", 0) or 0)
        ret = float(product.get("return_rate", 0) or 0)
        safe_ret = min(max(ret, 0.0), 0.95)
        implied_net = int(round(sales_qty * (1 - safe_ret))) if sales_qty else 0
        vol = max(net_sales, implied_net)
        vol_norm = min(math.log10(vol + 10) / math.log10(10010), 1.0) * 45
        cvr_norm = min(cvr / 0.12, 1.0) * 45
        sales_signal = min(math.log10(sales_qty + 10) / math.log10(50010), 1.0) * 10
        penalty = min(ret, 0.9) * 15
        return round(max(0.0, min(100.0, vol_norm + cvr_norm + sales_signal - penalty)), 2)

    def calculate_profit_score(self, product: Dict[str, Any]) -> float:
        """利润款：毛利率为主，辅以净销量与转化（需成本文件 + 有效售价）。"""
        import math

        cost = self._get_unit_cost(product)
        price = self._get_effective_retail_price(product)
        if cost is None or price <= 0 or price <= cost:
            return 0.0
        margin = (price - cost) / price
        net_sales = int(product.get("net_sales_qty", 0) or 0)
        cvr = float(product.get("conversion_rate", 0) or 0)
        margin_pts = margin * 55
        vol_pts = min(math.log10(net_sales + 10) / math.log10(50010), 1.0) * 30
        cvr_pts = min(cvr / 0.12, 1.0) * 15
        return round(max(0.0, min(100.0, margin_pts + vol_pts + cvr_pts)), 2)

    def _is_quick_dry_candidate(self, product: Dict[str, Any]) -> bool:
        """
        系统暂无速干字段时的替代识别：
        1) 商品名称关键词
        2) 高温高湿优先品类
        """
        name = (product.get("name", "") or "") + " " + (product.get("product_name", "") or "")
        name = name.lower()
        if any(kw in name for kw in ["速干", "冰丝", "凉感", "吸湿", "透气", "dry", "cool"]):
            return True
        return product.get("category") in {"T恤", "背心/吊带", "衬衫", "连衣裙"}

    def _is_eligible_stock_product(self, product: Dict[str, Any]) -> bool:
        """库存款：无采购在途（可配置）且主仓在库 > 阈值（默认 200）。"""
        th = self._get_product_role_thresholds()
        stock = int(product.get("stock", 0) or 0)
        inv_min = int(th.get("inventory_min_main_warehouse_stock", 200) or 0)
        if stock <= inv_min:
            return False
        if th.get("inventory_require_zero_procurement_inbound", True):
            if int(product.get("inbound", 0) or 0) != 0:
                return False
        return True

    def _estimate_daily_sales(self, product: Dict[str, Any]) -> int:
        """
        单品预估日净销量（用于品类款均）：销售量 × (1 - 退货率)。
        """
        raw_sales = int(product.get("sales_qty", 0) or 0)
        return_rate = float(product.get("return_rate", 0) or 0)
        if raw_sales > 0:
            safe_return_rate = min(max(return_rate, 0.0), 0.95)
            estimated_net_sales = int(round(raw_sales * (1 - safe_return_rate)))
            return max(1, estimated_net_sales)
        # 无 BI 销售数量时不臆造，返回 0 并由上层标记缺失
        return 0

    def _build_category_sales_aggregates(self, products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        按品类：对有销售数量的款式求预估日净销量之和，再除以款式数得到「平均日净销量（款均）」。
        单品口径：销售量 × (1 - 退货率)
        """
        category_sum: Dict[str, int] = {}
        category_missing_flags: Dict[str, bool] = {}
        category_product_count: Dict[str, int] = {}
        category_real_sales_count: Dict[str, int] = {}
        for p in products:
            cat = p.get("category")
            if not cat:
                continue
            category_product_count[cat] = category_product_count.get(cat, 0) + 1
            raw_sales = int(p.get("sales_qty", 0) or 0)
            est = self._estimate_daily_sales(p)
            if raw_sales > 0:
                category_real_sales_count[cat] = category_real_sales_count.get(cat, 0) + 1
                category_sum[cat] = category_sum.get(cat, 0) + est

        category_avg_daily: Dict[str, int] = {}
        for cat in category_product_count:
            real_count = category_real_sales_count.get(cat, 0)
            total_est = category_sum.get(cat, 0)
            if real_count > 0 and total_est > 0:
                category_avg_daily[cat] = int(round(total_est / real_count))
            else:
                category_avg_daily[cat] = 0

        for cat in category_product_count:
            real_count = category_real_sales_count.get(cat, 0)
            category_missing_flags[cat] = (
                real_count == 0 or category_avg_daily.get(cat, 0) <= 0
            )

        return {
            "avg_daily": category_avg_daily,
            "sum_daily": category_sum,
            "missing": category_missing_flags,
            "skus_with_sales": category_real_sales_count,
        }

    def _urgency_by_sellable_days(self, sellable_days: int) -> str:
        if sellable_days <= 14:
            return "urgent"
        if sellable_days <= 30:
            return "warning"
        if sellable_days <= 90:
            return "normal"
        return "overstock"

    def _promote_urgency(self, urgency: str) -> str:
        order = ["overstock", "normal", "warning", "urgent"]
        idx = order.index(urgency)
        return order[min(len(order) - 1, idx + 1)]

    def _extract_wave_months(self, text: str) -> List[int]:
        """
        从波段文本中提取月份（如 7A-12B、3B、10A）
        只关心月份，A/B代表上/下旬，不影响季节判断。
        """
        if not text:
            return []
        months = [int(m) for m in re.findall(r"(?<!\d)(1[0-2]|[1-9])[AB](?!\d)", text.upper())]
        return [m for m in months if 1 <= m <= 12]

    def _detect_product_launch_season(self, product: Dict[str, Any]) -> str:
        """
        识别商品季节：spring_summer / autumn_winter / unknown
        规则：
        1) 商品名称出现“春夏/秋冬”直接判定
        2) 波段月份 7A-12B 判定秋冬，1A-6B 判定春夏
        """
        texts = [
            str(product.get("name", "") or ""),
            str(product.get("product_name", "") or ""),
            str(product.get("style_tag", "") or "")
        ]
        combined = " ".join(texts).upper()
        if "秋冬" in combined:
            return "autumn_winter"
        if "春夏" in combined:
            return "spring_summer"

        months = self._extract_wave_months(combined)
        if months:
            if all(7 <= m <= 12 for m in months):
                return "autumn_winter"
            if all(1 <= m <= 6 for m in months):
                return "spring_summer"
        return "unknown"

    def _is_product_season_match(self, product: Dict[str, Any], season: str) -> bool:
        """
        季节过滤：
        - 春夏季（spring/summer）：过滤秋冬上新
        - 秋冬季（autumn/winter）：过滤春夏上新
        """
        launch_season = self._detect_product_launch_season(product)
        if launch_season == "unknown":
            return True
        if season in {"spring", "summer"}:
            return launch_season != "autumn_winter"
        return launch_season != "spring_summer"
    
    def get_weather_recommendations(
        self,
        avg_temp: float,
        rain_days: int = 0,
        temp_trend: str = "stable",
        precip: float = 0,
        city: str = "北京",
        avg_humidity: float = 60,
        avg_wind_scale: float = 3,
        season: str = "spring",
        national_rainy_city_count: int = 0,
        brand: str = "all"
    ) -> Dict[str, Any]:
        """
        基于天气推荐品类，并按品类聚合库存
        
        Args:
            avg_temp: 均温（°C）
            rain_days: 未来N天降雨天数
            temp_trend: 温度趋势 (rising/falling/stable)
            city: 城市名称
            avg_humidity: 平均湿度
            avg_wind_scale: 平均风力等级
            season: 季节（spring/summer/autumn/winter）
            national_rainy_city_count: 未来7天有雨的重点城市数
        """
        # 匹配推荐规则 + 对应BI品类
        matched_rules, bi_categories, adjusted_temp, city_offset, temp_primary_for_purchase_advice = (
            self._get_bi_categories_for_weather(
                avg_temp=avg_temp,
                city=city,
                avg_humidity=avg_humidity,
                avg_wind_scale=avg_wind_scale,
                season=season,
                national_rainy_city_count=national_rainy_city_count,
            )
        )

        # 获取所有产品数据
        all_products = self.fetch_bi_inventory_data()
        normalized_brand = self._normalize_brand(brand)
        if normalized_brand != "all":
            all_products = [p for p in all_products if p.get("brand", "marius") == normalized_brand]
        # 品类结构分析必须覆盖所有商品，不做在库门槛过滤
        category_scope_products = all_products
        category_sales_pack = self._build_category_sales_aggregates(category_scope_products)
        category_avg_daily_net_sales = category_sales_pack.get("avg_daily", {})
        category_sales_missing = category_sales_pack.get("missing", {})
        category_skus_with_sales = category_sales_pack.get("skus_with_sales", {})

        def _sku_in_transit_qty(p: Dict[str, Any]) -> int:
            return int(p.get("inbound", 0) or 0) + int(p.get("sales_return_inbound", 0) or 0)

        all_skus_sum_procurement_in_transit = sum(int(p.get("inbound", 0) or 0) for p in all_products)
        all_skus_sum_sales_return_in_transit = sum(
            int(p.get("sales_return_inbound", 0) or 0) for p in all_products
        )
        all_skus_total_in_transit = all_skus_sum_procurement_in_transit + all_skus_sum_sales_return_in_transit
        all_skus_row_count = len(all_products)
        # 如果没有匹配到任何BI品类，回退到全部品类（字母序，便于稳定展示）
        if not bi_categories:
            bi_categories = sorted(
                {p["category"] for p in category_scope_products if p.get("category")}
            )

        # 按品类聚合库存
        category_summary = {}
        for category in bi_categories:
            category_products = [p for p in category_scope_products if p["category"] == category]
            if category_products:
                sku_count = len(category_products)
                total_current_stock = sum(
                    (p.get("stock", 0) or 0) + (p.get("sales_return_stock", 0) or 0)
                    for p in category_products
                )
                total_in_transit_stock = sum(
                    (p.get("inbound", 0) or 0) + (p.get("sales_return_inbound", 0) or 0)
                    for p in category_products
                )
                avg_daily = int(category_avg_daily_net_sales.get(category, 0))
                category_summary[category] = {
                    # 兼容字段：total_stock/total_inbound 统一改为新的业务口径
                    "total_stock": total_current_stock,
                    "total_sales_return_stock": sum(p.get("sales_return_stock", 0) for p in category_products),
                    "total_inbound": total_in_transit_stock,
                    "total_sales_return_inbound": sum(p.get("sales_return_inbound", 0) for p in category_products),
                    "total_current_stock": total_current_stock,
                    "total_in_transit_stock": total_in_transit_stock,
                    "sku_count": sku_count,
                    "avg_return_rate": round(sum(p["return_rate"] for p in category_products) / sku_count, 2),
                    "avg_conversion_rate": round(sum(p["conversion_rate"] for p in category_products) / sku_count, 3),
                    "estimated_net_sales": avg_daily,
                    "daily_sales": avg_daily,
                    "avg_daily_net_sales_per_sku": avg_daily,
                    "skus_with_sales_for_avg": int(category_skus_with_sales.get(category, 0)),
                    "sales_data_missing": bool(category_sales_missing.get(category, True)),
                    "sellable_days": None if category_sales_missing.get(category, True) else int(
                        round(total_current_stock / max(avg_daily, 1))
                    ),
                    "skus": [p["sku_id"] for p in category_products],
                }

        # 规则命中的品类即使 BI 无 SKU 也占位，保证与 T 恤等并列单独展示
        for category in bi_categories:
            if category not in category_summary:
                category_summary[category] = {
                    "total_stock": 0,
                    "total_sales_return_stock": 0,
                    "total_inbound": 0,
                    "total_sales_return_inbound": 0,
                    "total_current_stock": 0,
                    "total_in_transit_stock": 0,
                    "sku_count": 0,
                    "avg_return_rate": 0.0,
                    "avg_conversion_rate": 0.0,
                    "estimated_net_sales": 0,
                    "daily_sales": 0,
                    "avg_daily_net_sales_per_sku": 0,
                    "skus_with_sales_for_avg": 0,
                    "sales_data_missing": True,
                    "sellable_days": None,
                    "skus": [],
                    "no_skus": True,
                }

        # 推荐品类顺序与 temperature_rules / 温度映射一致（不因库存合并或重排）
        sorted_categories = [c for c in bi_categories if c in category_summary]

        # 生成采购建议
        purchase_advice = self._generate_purchase_advice(
            sorted_categories=sorted_categories,
            temp_trend=temp_trend,
            rain_days=rain_days,
            avg_humidity=avg_humidity,
            category_summary=category_summary,
            category_scope_products=category_scope_products,
            category_avg_daily_net_sales=category_avg_daily_net_sales,
            category_sales_missing=category_sales_missing,
            purchase_advice_allowlist=temp_primary_for_purchase_advice,
        )

        # 推荐单品：引流款 / 利润款 / 库存款（宽池含在途可卖；库存款仍主仓>200）
        wide_for_skus = [
            p
            for p in all_products
            if p.get("category") in set(sorted_categories)
            and self._is_product_season_match(p, season)
            and float(p.get("return_rate", 0) or 0) <= 0.8
        ]
        if avg_humidity >= self.HIGH_HUMIDITY_THRESHOLD:
            wide_for_skus = [
                p
                for p in wide_for_skus
                if p.get("category") != "针织衫" or self._is_quick_dry_candidate(p)
            ]
        reco_pack = self._get_recommended_products(
            sorted_categories,
            category_summary,
            wide_for_skus,
            season=season,
        )
        recommended_products = reco_pack["merged"]
        recommended_products_by_tag = reco_pack["by_tag"]

        # 拼装规则说明
        rule_labels = [r["label"] for r in matched_rules]
        rule_desc = " + ".join(r["description"] for r in matched_rules)

        return {
            "weather_labels": rule_labels,
            "weather_desc": rule_desc,
            "recommended_categories": sorted_categories,
            "category_summary": category_summary,
            "recommended_products": recommended_products,  # 引流+利润+库存合并列表（带 recommend_tag）
            "recommended_products_by_tag": recommended_products_by_tag,
            "purchase_advice": purchase_advice,
            "total_stock": sum(s["total_stock"] for s in category_summary.values()),
            "total_inbound": sum(s["total_inbound"] for s in category_summary.values()),
            "total_current_stock": sum(s.get("total_current_stock", 0) for s in category_summary.values()),
            "total_in_transit_stock": sum(s.get("total_in_transit_stock", 0) for s in category_summary.values()),
            "all_skus_total_in_transit": int(all_skus_total_in_transit),
            "all_skus_sum_procurement_in_transit": int(all_skus_sum_procurement_in_transit),
            "all_skus_sum_sales_return_in_transit": int(all_skus_sum_sales_return_in_transit),
            "all_skus_row_count": int(all_skus_row_count),
            "recommended_in_transit_by_category": [
                {
                    "category": c,
                    "in_transit_pieces": int(category_summary[c].get("total_in_transit_stock", 0)),
                }
                for c in sorted_categories
                if c in category_summary
            ],
            "in_transit_scope_note": (
                "大数字=推荐品类在途合计；全款式总在途=接口明细表按行求和（每行：款采购在途+款销退在途），"
                "并给出采购/销退分项与行数便于与观远页面对账。"
            ),
            "brand": normalized_brand,
            "rule_context": {
                "city": city,
                "city_temp_offset": city_offset,
                "adjusted_avg_temp": round(adjusted_temp, 1),
                "avg_humidity": avg_humidity,
                "avg_wind_scale": avg_wind_scale,
                "season": season,
                "national_rainy_city_count": national_rainy_city_count,
                "brand": normalized_brand,
                "category_scope": "all products in recommended categories",
                "single_product_roles": (
                    "引流款：款净销量与主仓在库满足 product_role_thresholds；"
                    "利润款：有效售价/成本 > 配置倍率且需 sku_unit_cost.json 或 BI 标价；"
                    "库存款：无采购在途且主仓在库 > 阈值。"
                ),
                "single_product_stock_filter": (
                    "阈值来自 recommendation_rules.json → product_role_thresholds（配置页可编辑）"
                ),
                "product_role_thresholds": self._get_product_role_thresholds(),
                "recommendation_category_scope": (
                    f"体感≥{self.OUTERWEAR_STRIP_MIN_ADJ_TEMP}°C 时不推荐大衣/短外套/风衣；"
                    f"体感≥{self.SUPPLEMENTAL_OVERLAY_MERGE_BELOW_ADJ_TEMP}°C 时不并入全国多雨/高湿/大风。"
                ),
                "purchase_advice_scope": (
                    "智能采购建议仅列温度主规则命中品类（与高温天推荐品类一致；低温叠加时也不把叠加入池写进采购建议）。"
                ),
            }
        }
    
    def _format_recommended_product_row(
        self,
        product: Dict[str, Any],
        *,
        recommend_tag: str,
        recommend_tag_key: str,
        role_score: float,
    ) -> Dict[str, Any]:
        net_sales = int(product.get("net_sales_qty", 0) or 0)
        cost = self._get_unit_cost(product)
        price = self._get_effective_retail_price(product)
        margin = None
        if cost is not None and price > 0 and price > cost:
            margin = round((price - cost) / price, 4)
        return {
            "sku_id": product.get("sku_id", ""),
            "name": product.get("name", ""),
            "product_name": product.get("product_name", ""),
            "category": product.get("category", ""),
            "brand": product.get("brand", "marius"),
            "stock": product.get("stock", 0),
            "sales_return_stock": product.get("sales_return_stock", 0),
            "inbound": product.get("inbound", 0),
            "sales_return_inbound": product.get("sales_return_inbound", 0),
            "virtual_cloud_stock": product.get("virtual_cloud_stock", 0),
            "order_occupied": product.get("order_occupied", 0),
            "available_stock": product.get("available_stock", product.get("stock", 0)),
            "sales_qty": int(product.get("sales_qty", 0) or 0),
            "image_url": product.get("image_url", ""),
            "return_rate": product.get("return_rate", 0),
            "conversion_rate": product.get("conversion_rate", 0),
            "price_position": product.get("price_position", ""),
            "recommendation_score": role_score,
            "recommend_tag": recommend_tag,
            "recommend_tag_key": recommend_tag_key,
            "estimated_total_net_sales": net_sales,
            "estimated_total_net_sales_note": "口径：观远「款净销量」字段（历史/统计周期以 BI 卡片为准）",
            "retail_price": price if price > 0 else None,
            "gross_margin_rate": margin,
            "size_completeness": product.get("size_completeness", 0.85),
            "uses_procurement_inbound": recommend_tag in ("引流款", "利润款"),
        }

    def _get_recommended_products(
        self,
        categories: List[str],
        category_summary: Dict[str, Any],
        wide_products: List[Dict[str, Any]],
        season: str = "spring",
        max_per_tag: int = 36,
        per_category_limit: int = 4,
    ) -> Dict[str, Any]:
        """
        三类推荐：
        - 引流款：高销量/转化（可售含在途）
        - 利润款：高毛利（需 sku_unit_cost.json；可售含在途）
        - 库存款：主仓充足清库存（沿用原库存指数）
        同一 sku 优先归入引流 > 利润 > 库存。
        """
        th = self._get_product_role_thresholds()
        min_avail = int(th.get("roles_min_available_stock", 0) or 0)
        traffic_net_min = int(th.get("traffic_min_net_sales_qty", 1000) or 0)
        traffic_stock_min = int(th.get("traffic_min_main_warehouse_stock", 200) or 0)
        traffic_cvr_min = float(th.get("traffic_min_conversion_rate", 0.05) or 0.0)
        allowed_pp = th.get("traffic_price_positions") or []
        if not isinstance(allowed_pp, list):
            allowed_pp = []
        profit_ratio_min = float(th.get("profit_retail_to_cost_ratio_min", 2.8) or 2.8)

        traffic_rows: List[Dict[str, Any]] = []
        profit_rows: List[Dict[str, Any]] = []
        inventory_rows: List[Dict[str, Any]] = []
        used: Set[str] = set()

        for cat in categories:
            cat_ps = [p for p in wide_products if p.get("category") == cat]
            if not cat_ps:
                continue

            def _traffic_eligible(p: Dict[str, Any]) -> bool:
                if min_avail > 0:
                    a = int(p.get("available_stock", p.get("stock", 0)) or 0)
                    if a < min_avail:
                        return False
                cvr = float(p.get("conversion_rate", 0) or 0)
                if cvr < traffic_cvr_min:
                    return False
                if not self._traffic_matches_price_position(p, allowed_pp):
                    return False
                net = int(p.get("net_sales_qty", 0) or 0)
                stock = int(p.get("stock", 0) or 0)
                return net > traffic_net_min and stock > traffic_stock_min

            def _profit_eligible(p: Dict[str, Any]) -> bool:
                if min_avail > 0:
                    a = int(p.get("available_stock", p.get("stock", 0)) or 0)
                    if a < min_avail:
                        return False
                cost = self._get_unit_cost(p)
                price = self._get_effective_retail_price(p)
                if cost is None or float(cost) <= 0 or price <= 0 or price <= float(cost):
                    return False
                return (price / float(cost)) > profit_ratio_min

            t_pool = [p for p in cat_ps if _traffic_eligible(p)]
            t_pool.sort(key=lambda x: self.calculate_traffic_score(x), reverse=True)
            for p in t_pool:
                sku = str(p.get("sku_id", "")).strip()
                if not sku or sku in used:
                    continue
                if len([x for x in traffic_rows if x["category"] == cat]) >= per_category_limit:
                    break
                if len(traffic_rows) >= max_per_tag:
                    break
                used.add(sku)
                sc = self.calculate_traffic_score(p)
                traffic_rows.append(
                    self._format_recommended_product_row(
                        p, recommend_tag="引流款", recommend_tag_key="traffic", role_score=sc
                    )
                )

            p_pool = [p for p in cat_ps if str(p.get("sku_id", "")).strip() not in used and _profit_eligible(p)]
            p_pool.sort(key=lambda x: self.calculate_profit_score(x), reverse=True)
            for p in p_pool:
                sku = str(p.get("sku_id", "")).strip()
                if not sku or sku in used:
                    continue
                if len([x for x in profit_rows if x["category"] == cat]) >= per_category_limit:
                    break
                if len(profit_rows) >= max_per_tag:
                    break
                used.add(sku)
                sc = self.calculate_profit_score(p)
                profit_rows.append(
                    self._format_recommended_product_row(
                        p, recommend_tag="利润款", recommend_tag_key="profit", role_score=sc
                    )
                )

            i_pool = [
                p
                for p in cat_ps
                if str(p.get("sku_id", "")).strip() not in used and self._is_eligible_stock_product(p)
            ]
            i_pool.sort(key=lambda x: self.calculate_recommendation_score(x), reverse=True)
            for p in i_pool:
                sku = str(p.get("sku_id", "")).strip()
                if not sku or sku in used:
                    continue
                if len([x for x in inventory_rows if x["category"] == cat]) >= per_category_limit:
                    break
                if len(inventory_rows) >= max_per_tag:
                    break
                used.add(sku)
                sc = self.calculate_recommendation_score(p)
                inventory_rows.append(
                    self._format_recommended_product_row(
                        p, recommend_tag="库存款", recommend_tag_key="inventory", role_score=sc
                    )
                )

        merged = traffic_rows + profit_rows + inventory_rows
        return {
            "by_tag": {
                "traffic": traffic_rows,
                "profit": profit_rows,
                "inventory": inventory_rows,
            },
            "merged": merged,
        }

    def _generate_purchase_advice(
        self,
        sorted_categories: List[str],
        temp_trend: str,
        rain_days: int,
        avg_humidity: float,
        category_summary: Dict[str, Any],
        category_scope_products: List[Dict[str, Any]],
        category_avg_daily_net_sales: Dict[str, int],
        category_sales_missing: Dict[str, bool],
        purchase_advice_allowlist: Set[str],
    ) -> List[Dict[str, Any]]:
        """生成采购建议（时间维度 + 天气联动 + 动作建议 + 品类联动）"""
        advice = []
        cool_categories = {"针织衫", "卫衣", "风衣", "大衣", "羽绒服"}

        # 只展示「温度主规则」下的品类，避免全国多雨/大风等把大衣、短外套叠进高温天的采购建议
        if purchase_advice_allowlist:
            advice_categories = [c for c in sorted_categories if c in purchase_advice_allowlist]
        else:
            advice_categories = list(sorted_categories[:6])
        if not advice_categories:
            advice_categories = list(sorted_categories[:6])

        for category in advice_categories[:6]:
            if category not in category_summary:
                continue

            cat_summary = category_summary[category]
            products = [p for p in category_scope_products if p.get("category") == category]
            daily_sales = int(category_avg_daily_net_sales.get(category, 0))
            sales_missing = bool(category_sales_missing.get(category, True))
            total_current_stock = int(cat_summary.get("total_current_stock", cat_summary.get("total_stock", 0)) or 0)
            total_in_transit_stock = int(cat_summary.get("total_in_transit_stock", cat_summary.get("total_inbound", 0)) or 0)
            sellable_days = None if sales_missing else int(round(total_current_stock / max(daily_sales, 1)))
            inbound_ratio = (total_in_transit_stock / total_current_stock) if total_current_stock > 0 else 0.0

            urgency = "warning" if sales_missing else self._urgency_by_sellable_days(sellable_days)
            weather_hits = []
            if temp_trend == "falling" and category in cool_categories:
                urgency = self._promote_urgency(urgency)
                weather_hits.append("未来7天偏降温，保暖层需求上升")
            if rain_days >= 3 and category in {"风衣", "短外套"}:
                urgency = self._promote_urgency(urgency)
                weather_hits.append(f"未来有{rain_days}天降雨，防雨外套需求增强")
            if rain_days >= 3 and avg_humidity >= 85 and category in {"T恤", "衬衫"}:
                urgency = self._promote_urgency(urgency)
                weather_hits.append("连续降雨+高湿，速干轻薄品类需求上升")

            action = "维持常规补货节奏，按周复盘即可"
            transfer_to = []
            if sales_missing:
                action = "BI 销售数量缺失，暂无法计算平均日净销量与可售天数，请先补齐卡片销售字段"
            elif urgency == "urgent":
                action = "未来2周缺货风险高，建议加急补货并锁定到货时间"
            elif urgency == "warning":
                action = "未来1个月库存偏低，建议提前下单并分批到货"
            elif urgency == "overstock":
                action = "库存周期过长，建议暂停采购并配合促销清仓"
                transfer_to = ["轻薄衬衫", "短袖T恤", "防水外套"]
            if inbound_ratio >= 0.35:
                action += "；在途量偏高，请确认在途到货节奏避免重叠到货"
            if temp_trend == "rising" and category in cool_categories:
                action += "；叠加升温趋势，存在双重积压风险"
                if not transfer_to:
                    transfer_to = ["轻薄衬衫", "短袖T恤"]

            urgency_text = {
                "urgent": "🔴 紧急",
                "warning": "🟡 预警",
                "normal": "🟢 普通",
                "overstock": "🔵 过剩"
            }[urgency]
            advice.append({
                "category": category,
                "urgency": urgency,
                "urgency_text": urgency_text,
                "current_stock": total_current_stock,
                "inbound_quantity": total_in_transit_stock,
                "estimated_net_sales": daily_sales,
                "daily_sales": daily_sales,
                "sales_data_missing": sales_missing,
                "sellable_days": sellable_days,
                "inbound_ratio": round(inbound_ratio, 2),
                "weather_note": " + ".join(weather_hits) if weather_hits else "天气影响中性",
                "action": action,
                "transfer_to": transfer_to
            })

        return advice


# 单例模式
_bi_service = None

def get_bi_service(use_bi_data: bool = True) -> BIDataService:
    """获取BI数据服务实例
    
    Args:
        use_bi_data: 是否使用BI数据，False则使用模拟数据
    """
    global _bi_service
    if _bi_service is None:
        _bi_service = BIDataService(use_bi_data=use_bi_data)
    return _bi_service


def reset_bi_service(use_bi_data: bool = True):
    """重置BI数据服务实例（用于切换数据源）"""
    global _bi_service
    _bi_service = BIDataService(use_bi_data=use_bi_data)
    print(f"✓ BI服务已重置，use_bi_data={use_bi_data}")
    return _bi_service


if __name__ == "__main__":
    # 测试
    service = BIDataService()
    
    print("=" * 60)
    print("BI数据服务测试")
    print("=" * 60)
    
    # 测试获取所有商品
    products = service.fetch_bi_inventory_data()
    print(f"\n总商品数: {len(products)}")
    
    # 测试天气推荐 (高温)
    print("\n" + "=" * 60)
    print("高温天气推荐 (32°C)")
    print("=" * 60)
    
    result = service.get_weather_recommendations(avg_temp=32, rain_days=1, temp_trend="rising")
    
    print(f"\n推荐品类: {result['recommended_categories']}")
    print(f"\n品类汇总:")
    for cat, data in result['category_summary'].items():
        print(f"  {cat}: 现货{data['total_stock']}件 | 在途{data['total_inbound']}件")
    
    print(f"\nTop 推荐商品（合并列表）:")
    for i, product in enumerate(result.get("recommended_products", [])[:5], 1):
        print(f"\n{i}. [{product.get('recommend_tag', '')}] {product.get('name')} ({product.get('category')})")
        print(f"   角色分: {product.get('recommendation_score')} | 预计总净销量: {product.get('estimated_total_net_sales')}")
        print(f"   库存: {product.get('stock')} | 退货率: {product.get('return_rate', 0)*100:.1f}% | 转化: {product.get('conversion_rate', 0)*100:.1f}%")
    
    print(f"\n采购建议:")
    for advice in result['purchase_advice']:
        print(f"  {advice['category']}: 建议补货 {advice['suggested_restock']} 件")
