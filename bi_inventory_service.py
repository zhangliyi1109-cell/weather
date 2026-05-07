"""
BI 库存数据服务模块
从观远 BI 系统获取真实的库存、在途、退货率、转化率数据
"""
import sys
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

# 添加 guandata.py 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from guandata import GuanBI, create_bi


class BIInventoryService:
    """BI 库存数据服务类"""
    
    # 关键页面和卡片 ID（根据实际 BI 系统配置）
    INVENTORY_PAGE_ID = "f670828ac13a043fc87114a8"  # 库存消耗进度跟踪页面
    INVENTORY_CARD_ID = "kbcf363fdb24641079e338c0"  # 有款式编码的库存卡片
    
    def __init__(self):
        self.bi = None
        self._inventory_cache = None
        self._cache_time = None
    
    def _ensure_login(self):
        """确保已登录 BI"""
        if self.bi is None:
            self.bi = create_bi()
    
    def fetch_inventory_data(self, use_cache: bool = True, cache_minutes: int = 30) -> List[Dict[str, Any]]:
        """
        从 BI 获取库存数据
        
        Returns:
            商品列表，包含：
            - sku_id: 商品编码
            - name: 商品名称
            - category: 品类
            - stock: 现货库存
            - inbound: 采购在途
            - size_completeness: 尺码齐全度 (0-1)
            - return_rate: 退货率 (0-1)
            - conversion_rate: 转化率 (0-1)
        """
        # 检查缓存
        if use_cache and self._inventory_cache and self._cache_time:
            elapsed = (datetime.now() - self._cache_time).total_seconds() / 60
            if elapsed < cache_minutes:
                print(f"✓ 使用缓存数据（{elapsed:.1f}分钟前更新）")
                return self._inventory_cache
        
        self._ensure_login()
        
        try:
            # 直接获取库存卡片数据
            print("正在从 BI 获取库存数据...")
            parsed_data = self.bi.get_card_data(self.INVENTORY_CARD_ID)
            rows = parsed_data.get('rows', [])
            
            # 解析数据为结构化格式
            inventory_data = self._parse_inventory_rows(rows)
            
            # 更新缓存
            self._inventory_cache = inventory_data
            self._cache_time = datetime.now()
            
            print(f"✓ 成功获取 {len(inventory_data)} 条库存记录")
            return inventory_data
            
        except Exception as e:
            print(f"⚠️ BI 数据获取失败: {e}")
            print("使用模拟数据...")
            return self._get_mock_inventory_data()
    
    def _parse_inventory_rows(self, rows: List[Dict]) -> List[Dict[str, Any]]:
        """解析 BI 返回的行数据为结构化格式"""
        inventory_data = []
        
        for row in rows:
            try:
                # 从 BI 数据中提取字段
                # BI 字段映射：
                # - 款式编码: SKU ID
                # - 小名: 商品名称
                # - 产品分类(到款式): 品类
                # - 指标1-指标N: 各种库存指标
                
                sku_id = self._extract_value(row, ['款式编码'])
                name = self._extract_value(row, ['小名'])
                category = self._extract_value(row, ['产品分类(到款式)'])
                
                # 如果没有基本信息，跳过
                if not sku_id:
                    continue
                
                # 提取库存相关指标
                # 根据 BI 数据结构，指标字段包含各种库存数据
                stock = self._extract_number(row, ['指标1', '现货库存'])
                inbound = self._extract_number(row, ['指标2', '采购在途'])
                
                # 退货率和转化率需要从其他页面获取，这里使用默认值
                # 或者从指标字段中解析（如果有的话）
                return_rate = self._extract_rate(row, ['指标6', '退货率']) or 0.15
                conversion_rate = self._extract_rate(row, ['指标7', '转化率']) or 0.05
                
                # 尺码齐全度（如果有）
                size_completeness = self._extract_rate(row, ['尺码齐全度', '指标8']) or 0.85
                
                item = {
                    'sku_id': str(sku_id),
                    'name': str(name) if name else f"商品-{sku_id}",
                    'category': str(category) if category else "未分类",
                    'stock': stock,
                    'inbound': inbound,
                    'size_completeness': size_completeness,
                    'return_rate': return_rate,
                    'conversion_rate': conversion_rate,
                    'price': 0,  # BI 数据中没有价格
                }
                
                inventory_data.append(item)
                
            except Exception as e:
                print(f"解析行数据失败: {e}")
                continue
        
        return inventory_data
    
    def _extract_value(self, row: Dict, possible_keys: List[str]) -> Optional[str]:
        """从行数据中提取字符串值"""
        for key in possible_keys:
            if key in row:
                val = row[key].get('value')
                if val is not None:
                    return str(val)
        return None
    
    def _extract_number(self, row: Dict, possible_keys: List[str]) -> int:
        """从行数据中提取数值"""
        for key in possible_keys:
            if key in row:
                val = row[key].get('value')
                if val is not None:
                    try:
                        return int(float(val))
                    except:
                        continue
        return 0
    
    def _extract_rate(self, row: Dict, possible_keys: List[str]) -> float:
        """从行数据中提取比率（0-1）"""
        for key in possible_keys:
            if key in row:
                val = row[key].get('value')
                if val is not None:
                    try:
                        rate = float(val)
                        # 如果是百分比格式（>1），转换为小数
                        if rate > 1:
                            rate = rate / 100
                        return max(0, min(1, rate))
                    except:
                        continue
        return 0.0
    
    def _get_mock_inventory_data(self) -> List[Dict[str, Any]]:
        """获取模拟库存数据（BI 获取失败时使用）"""
        print("使用模拟库存数据...")
        
        mock_data = [
            # 夏季T恤
            {"sku_id": "TS001", "name": "轻薄透气棉T恤-白", "category": "夏季T恤", "price": 199, "stock": 1250, "inbound": 500, "size_completeness": 0.95, "return_rate": 0.08, "conversion_rate": 0.12},
            {"sku_id": "TS002", "name": "修身V领T恤-黑", "category": "夏季T恤", "price": 229, "stock": 980, "inbound": 300, "size_completeness": 0.90, "return_rate": 0.10, "conversion_rate": 0.10},
            {"sku_id": "TS003", "name": "印花短袖T恤", "category": "夏季T恤", "price": 259, "stock": 750, "inbound": 200, "size_completeness": 0.85, "return_rate": 0.12, "conversion_rate": 0.08},
            
            # 连衣裙
            {"sku_id": "DR001", "name": "法式碎花连衣裙", "category": "连衣裙", "price": 599, "stock": 680, "inbound": 250, "size_completeness": 0.88, "return_rate": 0.15, "conversion_rate": 0.09},
            {"sku_id": "DR002", "name": "真丝吊带连衣裙", "category": "连衣裙", "price": 899, "stock": 420, "inbound": 150, "size_completeness": 0.82, "return_rate": 0.18, "conversion_rate": 0.07},
            
            # 轻薄针织
            {"sku_id": "KN001", "name": "薄款针织开衫", "category": "轻薄针织", "price": 399, "stock": 850, "inbound": 300, "size_completeness": 0.92, "return_rate": 0.09, "conversion_rate": 0.11},
            {"sku_id": "KN002", "name": "V领针织衫", "category": "轻薄针织", "price": 359, "stock": 720, "inbound": 280, "size_completeness": 0.89, "return_rate": 0.11, "conversion_rate": 0.09},
            
            # 防水外套
            {"sku_id": "JK001", "name": "防风防水冲锋衣", "category": "防水外套", "price": 799, "stock": 560, "inbound": 200, "size_completeness": 0.87, "return_rate": 0.13, "conversion_rate": 0.08},
            {"sku_id": "JK002", "name": "轻薄防晒衣", "category": "防水外套", "price": 299, "stock": 1100, "inbound": 400, "size_completeness": 0.94, "return_rate": 0.07, "conversion_rate": 0.13},
            
            # 牛仔裤
            {"sku_id": "JE001", "name": "高腰直筒牛仔裤", "category": "牛仔裤", "price": 459, "stock": 920, "inbound": 350, "size_completeness": 0.91, "return_rate": 0.14, "conversion_rate": 0.10},
            {"sku_id": "JE002", "name": "阔腿牛仔裤", "category": "牛仔裤", "price": 499, "stock": 680, "inbound": 220, "size_completeness": 0.86, "return_rate": 0.16, "conversion_rate": 0.08},
            
            # 卫衣
            {"sku_id": "SW001", "name": "连帽卫衣", "category": "卫衣", "price": 399, "stock": 780, "inbound": 260, "size_completeness": 0.88, "return_rate": 0.12, "conversion_rate": 0.09},
            {"sku_id": "SW002", "name": "圆领卫衣", "category": "卫衣", "price": 349, "stock": 650, "inbound": 200, "size_completeness": 0.85, "return_rate": 0.13, "conversion_rate": 0.08},
            
            # 毛呢外套
            {"sku_id": "WO001", "name": "羊毛大衣", "category": "毛呢外套", "price": 1299, "stock": 380, "inbound": 120, "size_completeness": 0.80, "return_rate": 0.20, "conversion_rate": 0.06},
            {"sku_id": "WO002", "name": "短款毛呢外套", "category": "毛呢外套", "price": 899, "stock": 450, "inbound": 150, "size_completeness": 0.83, "return_rate": 0.18, "conversion_rate": 0.07},
        ]
        
        return mock_data
    
    def get_category_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        获取品类汇总数据
        
        Returns:
            品类汇总，包含总库存、总在途等
        """
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
_bi_inventory_service = None

def get_bi_inventory_service() -> BIInventoryService:
    """获取 BI 库存服务实例"""
    global _bi_inventory_service
    if _bi_inventory_service is None:
        _bi_inventory_service = BIInventoryService()
    return _bi_inventory_service


if __name__ == "__main__":
    # 测试
    print("=" * 60)
    print("BI 库存数据服务测试")
    print("=" * 60)
    
    service = BIInventoryService()
    
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
