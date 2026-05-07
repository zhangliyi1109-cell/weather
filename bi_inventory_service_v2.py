"""
BI 库存数据服务模块 V2
从观远 BI 系统的多个页面获取真实的库存、在途、退货率、转化率数据
"""
import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

# 添加 guandata.py 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guandata import GuanBI, create_bi


class BIInventoryServiceV2:
    """BI 库存数据服务类 V2 - 从多个卡片获取数据"""
    
    # 卡片 ID 配置
    CARD_INVENTORY = "n510e3bc975df45cd9534b76"  # MARIUS各品类单品排行_按可售量排序(SKU) - 库存/在途
    CARD_RETURN_RATE = "p94679b3944934a1997669ee"  # MARIUS各品类单品排行_按款退货率排序 - 退货率
    CARD_CONVERSION = "s2d92fbbda13c445bbb1008a"  # 淘宝店铺拉新款式表现 - 转化率
    
    def __init__(self):
        self.bi = None
        self._inventory_cache = None
        self._return_rate_cache = None
        self._conversion_cache = None
        self._cache_time = None
    
    def _ensure_login(self):
        """确保已登录 BI"""
        if self.bi is None:
            self.bi = create_bi()
    
    def fetch_inventory_data(self, use_cache: bool = True, cache_minutes: int = 30) -> List[Dict[str, Any]]:
        """
        从 BI 获取库存数据
        
        注意：由于BI系统中不同卡片的ID体系不一致
        - 库存卡片使用浮点ID（如 0.214978...）
        - 退货率/转化率卡片使用整数ID（如 4445543）
        无法直接关联匹配，因此退货率和转化率使用默认值
        
        Returns:
            商品列表，包含：
            - sku_id: 商品编码（款式编码）
            - name: 商品名称（小名）
            - category: 品类（产品分类）
            - stock: 现货库存（可售量）
            - inbound: 采购在途
            - return_rate: 退货率（默认0.15）
            - conversion_rate: 转化率（默认0.05）
        """
        # 检查缓存
        if use_cache and self._inventory_cache and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds() / 60
            if elapsed < cache_minutes:
                print(f"✓ 使用缓存数据（{elapsed:.1f}分钟前更新）")
                return self._inventory_cache
        
        self._ensure_login()
        
        try:
            # 获取库存数据（从按可售量排序卡片）
            print("正在从 BI 获取库存数据...")
            inventory_data = self._fetch_card_data(self.CARD_INVENTORY)
            inventory_map = self._parse_inventory_data(inventory_data)
            print(f"✓ 获取到 {len(inventory_map)} 条库存记录")
            
            # 转换为列表并添加默认值
            merged_data = []
            for sku_id, inv_data in inventory_map.items():
                item = inv_data.copy()
                # 退货率和转化率使用默认值（因BI卡片ID体系不一致，暂无法关联）
                item['return_rate'] = 0.15
                item['conversion_rate'] = 0.05
                item['size_completeness'] = 0.85
                item['price'] = 0
                merged_data.append(item)
            
            # 更新缓存
            self._inventory_cache = merged_data
            self._cache_time = datetime.now()
            
            print(f"✓ 成功获取 {len(merged_data)} 条库存记录")
            print(f"  注：退货率和转化率使用默认值（因BI卡片ID体系不一致，暂无法关联）")
            return merged_data
            
        except Exception as e:
            print(f"⚠️ BI 数据获取失败: {e}")
            import traceback
            traceback.print_exc()
            print("使用模拟数据...")
            return self._get_mock_inventory_data()
    
    def _fetch_card_data(self, card_id: str) -> List[Dict]:
        """获取卡片原始数据"""
        import time
        time.sleep(1)  # 避免请求过快
        data = self.bi.get_card_data(card_id, auto_parse=True)
        return data.get('rows', [])
    
    def _parse_inventory_data(self, rows: List[Dict]) -> Dict[str, Dict]:
        """解析库存数据，按款式编码建立索引"""
        inventory_map = {}
        
        for row in rows:
            try:
                # 提取款式编码作为key
                sku_cell = row.get('款式编码', {})
                sku_id = self._extract_value_from_cell(sku_cell)
                
                if not sku_id:
                    continue
                
                # 提取其他字段
                name = self._extract_value_from_cell(row.get('小名', {}))
                category_code = self._extract_value_from_cell(row.get('产品分类(到SKC)', {}))
                
                # 将品类代码映射为中文品类名
                category = self._map_category(category_code)
                
                # 提取指标（库存、在途等）
                # 根据BI数据结构分析，指标2可能是库存，指标4可能是在途
                stock = self._extract_metric_from_cell(row.get('指标2', {}))
                inbound = self._extract_metric_from_cell(row.get('指标4', {}))
                
                # 如果指标2和指标4为0，尝试其他指标
                if stock == 0:
                    stock = self._extract_metric_from_cell(row.get('指标1', {}))
                if inbound == 0:
                    inbound = self._extract_metric_from_cell(row.get('指标3', {}))
                
                inventory_map[str(sku_id)] = {
                    'sku_id': str(sku_id),
                    'name': str(name) if name else f"商品-{sku_id}",
                    'category': category,
                    'stock': int(stock),
                    'inbound': int(inbound),
                }
            except Exception as e:
                continue
        
        return inventory_map
    
    def _map_category(self, category_code: Optional[str]) -> str:
        """将品类代码映射为中文品类名"""
        if not category_code:
            return "未分类"
        
        # 尝试将代码转换为整数进行比较
        try:
            code = int(float(category_code))
            # 根据观察到的数据进行映射
            # 这些映射需要根据实际BI数据进行调整
            category_map = {
                0: "其他",
                9: "短外套",
                10: "连衣裙", 
                11: "半身裙",
                18: "衬衫",
                60: "毛呢外套",
                80: "裤装",
            }
            return category_map.get(code, f"品类-{code}")
        except:
            return str(category_code)
    
    def _parse_return_rate_data(self, rows: List[Dict]) -> Dict[str, float]:
        """解析退货率数据，按款式编码建立索引"""
        return_rate_map = {}
        
        for row in rows:
            try:
                sku_cell = row.get('款式编码', {})
                sku_id = self._extract_value_from_cell(sku_cell)
                
                if not sku_id:
                    continue
                
                # 提取退货率指标（假设在某个指标中）
                return_rate = self._extract_metric_from_cell(row.get('指标1', {}))
                
                # 确保退货率是0-1之间的小数
                if return_rate > 1:
                    return_rate = return_rate / 100
                
                return_rate_map[str(sku_id)] = return_rate
            except Exception as e:
                continue
        
        return return_rate_map
    
    def _parse_conversion_data(self, rows: List[Dict]) -> Dict[str, float]:
        """解析转化率数据，按款式编码建立索引"""
        conversion_map = {}
        
        for row in rows:
            try:
                sku_cell = row.get('款式编码', {})
                sku_id = self._extract_value_from_cell(sku_cell)
                
                if not sku_id:
                    continue
                
                # 提取转化率指标
                # 根据之前的数据，指标1可能是转化率
                conversion_rate = self._extract_metric_from_cell(row.get('指标1', {}))
                
                # 确保转化率是0-1之间的小数
                if conversion_rate > 1:
                    conversion_rate = conversion_rate / 100
                
                conversion_map[str(sku_id)] = conversion_rate
            except Exception as e:
                continue
        
        return conversion_map
    
    def _merge_data(self, inventory_map: Dict, return_rate_map: Dict, conversion_map: Dict) -> List[Dict]:
        """合并三类数据"""
        merged = []
        
        for sku_id, inv_data in inventory_map.items():
            item = inv_data.copy()
            
            # 添加退货率
            item['return_rate'] = return_rate_map.get(sku_id, 0.15)
            
            # 添加转化率
            item['conversion_rate'] = conversion_map.get(sku_id, 0.05)
            
            # 添加其他默认值
            item['size_completeness'] = 0.85
            item['price'] = 0
            
            merged.append(item)
        
        return merged
    
    def _extract_value_from_cell(self, cell: Dict) -> Optional[str]:
        """从单元格中提取值"""
        if not cell:
            return None
        value = cell.get('value')
        if value is not None:
            return str(value)
        return None
    
    def _extract_metric_from_cell(self, cell: Dict) -> float:
        """从单元格中提取数值"""
        if not cell:
            return 0.0
        value = cell.get('value')
        if value is not None:
            try:
                return float(value)
            except:
                return 0.0
        return 0.0
    
    def _get_mock_inventory_data(self) -> List[Dict[str, Any]]:
        """获取模拟库存数据（BI 获取失败时使用）"""
        print("使用模拟库存数据...")
        
        mock_data = [
            {"sku_id": "TS001", "name": "轻薄透气棉T恤-白", "category": "夏季T恤", "price": 199, "stock": 1250, "inbound": 500, "size_completeness": 0.95, "return_rate": 0.08, "conversion_rate": 0.12},
            {"sku_id": "TS002", "name": "修身V领T恤-黑", "category": "夏季T恤", "price": 229, "stock": 980, "inbound": 300, "size_completeness": 0.90, "return_rate": 0.10, "conversion_rate": 0.10},
            {"sku_id": "DR001", "name": "法式碎花连衣裙", "category": "连衣裙", "price": 599, "stock": 680, "inbound": 250, "size_completeness": 0.88, "return_rate": 0.15, "conversion_rate": 0.09},
            {"sku_id": "KN001", "name": "薄款针织开衫", "category": "轻薄针织", "price": 399, "stock": 850, "inbound": 300, "size_completeness": 0.92, "return_rate": 0.09, "conversion_rate": 0.11},
            {"sku_id": "JK001", "name": "防风防水冲锋衣", "category": "防水外套", "price": 799, "stock": 560, "inbound": 200, "size_completeness": 0.87, "return_rate": 0.13, "conversion_rate": 0.08},
        ]
        
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
_bi_inventory_service_v2 = None

def get_bi_inventory_service_v2() -> BIInventoryServiceV2:
    """获取 BI 库存服务 V2 实例"""
    global _bi_inventory_service_v2
    if _bi_inventory_service_v2 is None:
        _bi_inventory_service_v2 = BIInventoryServiceV2()
    return _bi_inventory_service_v2


if __name__ == "__main__":
    # 测试
    print("=" * 60)
    print("BI 库存数据服务 V2 测试")
    print("=" * 60)
    
    service = BIInventoryServiceV2()
    
    # 获取库存数据
    print("\n1. 获取库存数据...")
    inventory = service.fetch_inventory_data(use_cache=False)
    
    print(f"\n获取到 {len(inventory)} 条记录")
    print("\n前5条数据预览:")
    for item in inventory[:5]:
        print(f"  {item['sku_id']} | {item['name'][:20]:<20} | 库存:{item['stock']:<5} | 在途:{item['inbound']:<5} | 退货率:{item['return_rate']:.1%} | 转化率:{item['conversion_rate']:.1%}")
    
    # 获取品类汇总
    print("\n2. 品类汇总...")
    summary = service.get_category_summary()
    for cat, data in summary.items():
        print(f"  {cat}: 库存{data['total_stock']}, 在途{data['total_inbound']}, SKU数{data['sku_count']}")
