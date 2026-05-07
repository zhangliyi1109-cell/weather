"""
飞书多维表服务模块
负责与飞书开放API交互
"""
import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from config import FEISHU_CONFIG, FEISHU_BITABLE


class FeishuService:
    """飞书服务类"""
    
    BASE_URL = "https://open.feishu.cn/open-apis"
    
    def __init__(self, app_id: str = None, app_secret: str = None):
        self.app_id = app_id or FEISHU_CONFIG.get("app_id")
        self.app_secret = app_secret or FEISHU_CONFIG.get("app_secret")
        self.access_token = None
        self.token_expire_time = None
    
    def _get_tenant_access_token(self) -> Optional[str]:
        """获取租户访问令牌"""
        if self.access_token and self.token_expire_time and datetime.now() < self.token_expire_time:
            return self.access_token
        
        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json"}
        data = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            
            if result.get("code") == 0:
                self.access_token = result.get("tenant_access_token")
                expire = result.get("expire", 7200)
                self.token_expire_time = datetime.now() + timedelta(seconds=expire - 300)
                return self.access_token
            else:
                print(f"获取token失败: {result}")
                return None
                
        except Exception as e:
            print(f"请求失败: {e}")
            return None
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        token = self._get_tenant_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def create_bitable(self, name: str = "天气预报数据") -> Optional[str]:
        """
        创建多维表
        
        Returns:
            app_token: 多维表的唯一标识
        """
        url = f"{self.BASE_URL}/bitable/v1/apps"
        headers = self._get_headers()
        data = {
            "name": name,
            "description": "自动同步的天气预报数据",
            "is_advanced": False
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            
            if result.get("code") == 0:
                app_token = result.get("data", {}).get("app", {}).get("app_token")
                print(f"多维表创建成功: {app_token}")
                return app_token
            else:
                print(f"创建多维表失败: {result}")
                return None
                
        except Exception as e:
            print(f"请求失败: {e}")
            return None
    
    def create_table(self, app_token: str, name: str = "天气数据") -> Optional[str]:
        """
        在多维表中创建数据表
        
        Args:
            app_token: 多维表token
            name: 表名
            
        Returns:
            table_id: 表的ID
        """
        url = f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables"
        headers = self._get_headers()
        
        # 定义表字段
        fields = [
            {"field_name": "城市", "field_type": 1},  # 文本
            {"field_name": "日期", "field_type": 5},  # 日期
            {"field_name": "星期", "field_type": 1},
            {"field_name": "天气白天", "field_type": 1},
            {"field_name": "天气夜间", "field_type": 1},
            {"field_name": "最高温度", "field_type": 2},  # 数字
            {"field_name": "最低温度", "field_type": 2},
            {"field_name": "降水概率", "field_type": 2},
            {"field_name": "湿度", "field_type": 2},
            {"field_name": "风向", "field_type": 1},
            {"field_name": "风力", "field_type": 1},
            {"field_name": "紫外线", "field_type": 1},
            {"field_name": "能见度", "field_type": 1},
            {"field_name": "日出", "field_type": 1},
            {"field_name": "日落", "field_type": 1},
            {"field_name": "更新时间", "field_type": 5}
        ]
        
        data = {
            "table": {
                "name": name,
                "fields": fields
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            result = response.json()
            
            if result.get("code") == 0:
                table_id = result.get("data", {}).get("table_id")
                print(f"数据表创建成功: {table_id}")
                return table_id
            else:
                print(f"创建数据表失败: {result}")
                return None
                
        except Exception as e:
            print(f"请求失败: {e}")
            return None
    
    def add_records(self, app_token: str, table_id: str, records: List[Dict]) -> bool:
        """
        批量添加记录
        
        Args:
            app_token: 多维表token
            table_id: 表ID
            records: 记录列表
            
        Returns:
            bool: 是否成功
        """
        url = f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
        headers = self._get_headers()
        
        # 批量处理，每批最多500条
        batch_size = 500
        total = len(records)
        success_count = 0
        
        for i in range(0, total, batch_size):
            batch = records[i:i+batch_size]
            
            # 转换记录格式
            formatted_records = []
            for record in batch:
                fields = {}
                for key, value in record.items():
                    if key == "日期":
                        # 日期字段转换为毫秒时间戳
                        from datetime import datetime
                        try:
                            dt = datetime.strptime(str(value), "%Y-%m-%d")
                            timestamp = int(dt.timestamp() * 1000)
                            fields[key] = timestamp
                        except:
                            fields[key] = str(value)
                    elif key in ["最高温度", "最低温度", "降水概率", "湿度"]:
                        # 数字字段
                        try:
                            fields[key] = int(value)
                        except:
                            fields[key] = 0
                    else:
                        # 文本字段
                        fields[key] = str(value)
                
                formatted_records.append({"fields": fields})
            
            data = {"records": formatted_records}
            
            try:
                response = requests.post(url, headers=headers, json=data, timeout=30)
                result = response.json()
                
                if result.get("code") == 0:
                    success_count += len(batch)
                    print(f"已添加 {success_count}/{total} 条记录")
                else:
                    print(f"添加记录失败: {result}")
                    return False
                    
            except Exception as e:
                print(f"请求失败: {e}")
                return False
        
        print(f"成功添加 {success_count} 条记录")
        return True
    
    def delete_all_records(self, app_token: str, table_id: str) -> bool:
        """
        删除所有记录（用于全量更新）
        
        Args:
            app_token: 多维表token
            table_id: 表ID
            
        Returns:
            bool: 是否成功
        """
        # 先获取所有记录ID
        url = f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        headers = self._get_headers()
        
        record_ids = []
        page_token = None
        
        while True:
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=10)
                result = response.json()
                
                if result.get("code") == 0:
                    items = result.get("data", {}).get("items", [])
                    record_ids.extend([item.get("record_id") for item in items])
                    
                    has_more = result.get("data", {}).get("has_more", False)
                    if not has_more:
                        break
                    page_token = result.get("data", {}).get("page_token")
                else:
                    break
                    
            except Exception as e:
                print(f"获取记录失败: {e}")
                break
        
        if not record_ids:
            return True
        
        # 批量删除
        delete_url = f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
        
        # 分批删除，每批100条
        for i in range(0, len(record_ids), 100):
            batch = record_ids[i:i+100]
            data = {"records": batch}
            
            try:
                response = requests.post(delete_url, headers=headers, json=data, timeout=10)
                result = response.json()
                
                if result.get("code") != 0:
                    print(f"删除记录失败: {result}")
                    return False
                    
            except Exception as e:
                print(f"删除请求失败: {e}")
                return False
        
        print(f"已删除 {len(record_ids)} 条旧记录")
        return True
    
    def sync_weather_data(self, records: List[Dict], app_token: str = None, table_id: str = None) -> bool:
        """
        同步天气数据到飞书（全量更新）
        
        Args:
            records: 天气记录列表
            app_token: 多维表token（可选，默认使用配置）
            table_id: 表ID（可选，默认使用配置）
            
        Returns:
            bool: 是否成功
        """
        app_token = app_token or FEISHU_BITABLE.get("app_token")
        table_id = table_id or FEISHU_BITABLE.get("table_id")
        
        if not app_token or not table_id:
            print("错误: 未配置飞书多维表信息")
            return False
        
        print(f"开始同步 {len(records)} 条记录到飞书...")
        
        # 1. 删除旧数据
        if not self.delete_all_records(app_token, table_id):
            print("删除旧数据失败")
            return False
        
        # 2. 添加新数据
        if not self.add_records(app_token, table_id, records):
            print("添加新数据失败")
            return False
        
        print("同步完成！")
        return True


# 单例模式
_feishu_service = None

def get_feishu_service() -> FeishuService:
    """获取飞书服务实例"""
    global _feishu_service
    if _feishu_service is None:
        _feishu_service = FeishuService()
    return _feishu_service


if __name__ == "__main__":
    # 测试
    service = FeishuService()
    
    print("=" * 60)
    print("飞书服务测试")
    print("=" * 60)
    
    # 测试获取token
    token = service._get_tenant_access_token()
    if token:
        print(f"\n✅ Token获取成功: {token[:20]}...")
    else:
        print("\n❌ Token获取失败")
