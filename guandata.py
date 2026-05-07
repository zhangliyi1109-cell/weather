#!/usr/bin/env python3
"""
观远 BI API 封装脚本 v2.0
用于获取莱瑞时尚 BI 系统的数据和看板信息

配置:
- API地址: https://bi.marius.vip
- 应用Token: d3dc3da5b8356403e882269e
- 登录ID: admin@guandata.com

改进:
- Token 持久化（自动缓存和复用）
- 卡片数据自动解析列名
- 支持筛选、排序、分页
- 更丰富的数据获取方法
"""

import requests
import json
import os
import sys
import time
import re
from typing import Dict, List, Optional, Any, Union, Callable
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 配置（可用环境变量覆盖，便于部署与轮换 token）
BI_BASE = os.getenv("GUANDATA_BASE_URL", "https://bi.marius.vip").rstrip("/")
APP_TOKEN = os.getenv("GUANDATA_APP_TOKEN", "d3dc3da5b8356403e882269e")
LOGIN_ID = os.getenv("GUANDATA_LOGIN_ID", "admin@guandata.com")
TOKEN_CACHE_FILE = os.path.expanduser("~/.openclaw/skills/guandata-bi/scripts/.token_cache")


class GuanBI:
    """观远 BI API 封装 v2.0"""
    
    # 观远 Public API 里页面/卡片 ID 字段在不同版本可能是 id 或 pgId / cdId
    REQUEST_TIMEOUT = int(os.getenv("GUANDATA_REQUEST_TIMEOUT", "120"))

    def __init__(self, token_cache_file: str = TOKEN_CACHE_FILE):
        self.session = requests.Session()
        self.x_auth_token: Optional[str] = None
        self.token_cache_file = token_cache_file
        self._page_cache: Dict[str, Any] = {}
        self._page_detail_cache: Dict[str, Any] = {}
    
    def _load_cached_token(self) -> bool:
        """尝试加载缓存的 token"""
        try:
            if os.path.exists(self.token_cache_file):
                with open(self.token_cache_file, 'r') as f:
                    cache = json.load(f)
                expire_at = cache.get('expire_at', 0)
                # 提前5分钟判断是否过期
                if time.time() < expire_at - 300:
                    self.x_auth_token = cache.get('token')
                    print(f"✓ 使用缓存 Token（剩余 {(expire_at - time.time())/3600:.1f} 小时）")
                    return True
                else:
                    print("○ Token 已过期，重新登录...")
        except Exception:
            pass
        return False
    
    def _save_token_cache(self, expire_at_str: str = None):
        """保存 token 到缓存
        
        Args:
            expire_at_str: 过期时间字符串（ISO格式），可选
        """
        try:
            os.makedirs(os.path.dirname(self.token_cache_file), exist_ok=True)
            # 计算过期时间
            expire_at = time.time() + 24 * 3600  # 默认24小时
            
            if expire_at_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(expire_at_str.replace('Z', '+00:00'))
                    expire_at = dt.timestamp()
                except:
                    pass
            
            cache = {
                'token': self.x_auth_token,
                'expire_at': expire_at
            }
            with open(self.token_cache_file, 'w') as f:
                json.dump(cache, f)
        except Exception as e:
            print(f"Warning: 保存 Token 缓存失败: {e}")
    
    def login(self, force: bool = False) -> bool:
        """登录获取 X-Auth-Token"""
        env_x_token = os.getenv("GUANDATA_X_AUTH_TOKEN", "").strip()
        if env_x_token and not force:
            self.x_auth_token = env_x_token
            print("✓ 使用环境变量 GUANDATA_X_AUTH_TOKEN（跳过 sign-in 接口）")
            return True

        # 尝试加载缓存
        if not force and self._load_cached_token():
            return True
        
        resp = self.session.post(
            f"{BI_BASE}/public-api/user/loginId/sign-in",
            json={"token": APP_TOKEN, "loginId": LOGIN_ID},
            timeout=self.REQUEST_TIMEOUT,
        )
        data = resp.json()
        if data.get("result") == "ok":
            self.x_auth_token = data["response"]["token"]
            expire_at_str = data["response"].get("expireAt", "未知")
            print(f"✓ 登录成功，Token 有效期至: {expire_at_str}")
            self._save_token_cache(expire_at_str)
            return True
        print(f"✗ 登录失败: {data.get('error')}")
        return False
    
    def _headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "X-Auth-Token": self.x_auth_token or ""
        }
    
    def _parse_card_data(self, card_data: Dict) -> Dict[str, Any]:
        """解析卡片数据，自动识别列名"""
        chart = card_data.get('chartMain', {})
        rows = chart.get('data', [])
        
        # 获取维度字段（行字段）
        row_meta = chart.get('row', {}).get('meta', [])
        
        # 构建字段映射
        field_map = {}
        dim_idx = 0
        
        # 维度字段（来自 row.meta）
        for m in row_meta:
            field_map[dim_idx] = {
                'name': m.get('title', m.get('originTitle', f'维度{dim_idx}')),
                'type': 'dim',
                'fdId': m.get('fdId', '')
            }
            dim_idx += 1
        
        # 指标字段数量 = rows[0] 总列数 - dim_idx
        if rows and len(rows[0]) > dim_idx:
            metric_count = len(rows[0]) - dim_idx
            for i in range(metric_count):
                field_map[dim_idx + i] = {
                    'name': f'指标{i+1}',
                    'type': 'metric',
                    'fdId': ''
                }
        
        # 解析行数据
        parsed_rows = []
        for row in rows:
            if not row:
                continue
            parsed_row = {}
            for i, cell in enumerate(row):
                if not cell:
                    continue
                field_info = field_map.get(i, {'name': f'列{i}', 'type': 'unknown'})
                parsed_row[field_info['name']] = {
                    'value': cell.get('v'),
                    'type': field_info['type'],
                    'fdId': field_info.get('fdId', ''),
                    't_idx': cell.get('t_idx', '')
                }
            if parsed_row:
                parsed_rows.append(parsed_row)
        
        return {
            'rows': parsed_rows,
            'field_map': field_map,
            'total': len(parsed_rows)
        }
    
    def get_page_list(self, use_cache: bool = True) -> List[Dict]:
        """获取页面列表"""
        if use_cache and 'page_list' in self._page_cache:
            return self._page_cache['page_list']

        if not self.x_auth_token:
            self.login()

        resp = self.session.post(
            f"{BI_BASE}/public-api/page/list",
            headers=self._headers(),
            json={"token": APP_TOKEN},
            timeout=self.REQUEST_TIMEOUT,
        )
        data = resp.json()
        if data.get("result") == "ok":
            pages = data.get("response", [])
            self._page_cache['page_list'] = pages
            return pages
        raise Exception(f"获取页面列表失败: {data.get('error')}")
    
    def get_page_detail(self, pg_id: str, use_cache: bool = True) -> Dict:
        """获取页面详情（含卡片列表）"""
        if use_cache and pg_id in self._page_detail_cache:
            return self._page_detail_cache[pg_id]

        if not self.x_auth_token:
            self.login()

        header_sets = [
            {
                "Content-Type": "application/json",
                "token": APP_TOKEN,
                "X-Auth-Token": self.x_auth_token or "",
            },
            {"Content-Type": "application/json", "token": APP_TOKEN},
        ]
        last_err = ""
        for hdr in header_sets:
            resp = self.session.get(
                f"{BI_BASE}/public-api/page/{pg_id}",
                headers=hdr,
                timeout=self.REQUEST_TIMEOUT,
            )
            try:
                data = resp.json()
            except Exception:
                last_err = f"非 JSON 响应 HTTP {resp.status_code}"
                continue
            if data.get("result") == "ok":
                detail = data.get("response", {})
                self._page_detail_cache[pg_id] = detail
                return detail
            last_err = str(data.get("error") or data.get("message") or resp.text[:300])
        raise Exception(f"获取页面详情失败: {last_err}")
    
    def get_card_data(self, card_id: str, view: str = "GRAPH", auto_parse: bool = True) -> Union[Dict, Any]:
        """获取卡片数据
        
        Args:
            card_id: 卡片ID
            view: 视图类型，默认 GRAPH
            auto_parse: 是否自动解析列名，默认 True
        
        Returns:
            如果 auto_parse=True，返回解析后的数据（包含 rows 列表）
            否则返回原始数据
        """
        resp = self.session.post(
            f"{BI_BASE}/public-api/card/{card_id}/data",
            headers=self._headers(),
            json={"view": view},
            timeout=self.REQUEST_TIMEOUT,
        )
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"获取卡片数据失败: 响应非 JSON，HTTP {resp.status_code} {resp.text[:400]}")
        if data.get("result") == "ok":
            card_data = data.get("response", {})
            if auto_parse:
                return self._parse_card_data(card_data)
            return card_data
        err = data.get("error") or data.get("message") or resp.text[:400]
        raise Exception(f"获取卡片数据失败: {err} (HTTP {resp.status_code}, card_id={card_id})")
    
    def get_card_raw(self, card_id: str, view: str = "GRAPH") -> Dict:
        """获取卡片原始数据（不解析）"""
        return self.get_card_data(card_id, view, auto_parse=False)
    
    def get_dataset_data(self, ds_id: str, limit: int = 10, offset: int = 0) -> Dict:
        """获取数据集数据"""
        resp = self.session.post(
            f"{BI_BASE}/public-api/data-source/{ds_id}/data",
            headers=self._headers(),
            json={"limit": limit, "offset": offset}
        )
        data = resp.json()
        if data.get("result") == "ok":
            return data.get("response", {})
        raise Exception(f"获取数据集数据失败: {data.get('error')}")
    
    def get_dataset_columns(self, ds_id: str) -> List[Dict]:
        """获取数据集字段信息"""
        resp = self.session.post(
            f"{BI_BASE}/public-api/data-source/{ds_id}/data",
            headers=self._headers(),
            json={"limit": 1}
        )
        data = resp.json()
        if data.get("result") == "ok":
            return data.get("response", {}).get("columns", [])
        raise Exception(f"获取数据集字段失败: {data.get('error')}")
    
    def find_page(self, name_keyword: str) -> Optional[Dict]:
        """根据关键词搜索页面"""
        pages = self.get_page_list()
        for p in pages:
            if name_keyword in p.get('name', ''):
                return p
        return None
    
    def find_card(self, page_id: str, name_keyword: str) -> Optional[Dict]:
        """在页面中搜索卡片"""
        detail = self.get_page_detail(page_id)
        cards = detail.get("cards") or detail.get("cardList") or []
        for c in cards:
            nm = c.get("name", "") or c.get("title", "")
            if name_keyword in nm:
                return c
        return None
    
    @staticmethod
    def _card_id(c: Dict) -> str:
        return str(c.get("cdId") or c.get("id") or "").strip()

    @staticmethod
    def _page_id(p: Dict) -> str:
        return str(p.get("pgId") or p.get("id") or "").strip()

    def get_page_cards_summary(self, pg_id: str) -> List[Dict]:
        """获取页面卡片摘要（名称、ID、类型）"""
        detail = self.get_page_detail(pg_id)
        cards = detail.get("cards") or detail.get("cardList") or []
        out: List[Dict] = []
        for c in cards:
            cid = self._card_id(c)
            if not cid:
                continue
            out.append({
                "cdId": cid,
                "name": c.get("name", "") or c.get("title", ""),
                "type": c.get("cdType") or c.get("type", "") or "",
            })
        return out
    
    def print_card_data(self, card_id: str, max_rows: int = 20, max_fields: int = 10):
        """打印卡片数据（方便调试）"""
        parsed = self.get_card_data(card_id)
        rows = parsed.get('rows', [])
        
        if not rows:
            print("无数据")
            return
        
        # 打印表头
        first_row = rows[0]
        headers = list(first_row.keys())
        print(" | ".join(headers[:max_fields]))
        print("-" * 100)
        
        # 打印数据行
        for i, row in enumerate(rows[:max_rows]):
            values = []
            for h in headers[:max_fields]:
                v = row.get(h, {}).get('value', '')
                if isinstance(v, float):
                    v = f"{v:.2f}"
                values.append(str(v))
            print(" | ".join(values))
        
        if len(rows) > max_rows:
            print(f"... 还有 {len(rows) - max_rows} 行")


# ============== 便捷函数 ==============

def create_bi() -> GuanBI:
    """创建并登录 BI 实例"""
    bi = GuanBI()
    bi.login()
    return bi


def quick_get_card(card_id: str, max_rows: int = 20) -> List[Dict]:
    """快速获取卡片解析后的数据"""
    bi = create_bi()
    parsed = bi.get_card_data(card_id)
    return parsed.get('rows', [])[:max_rows]


def quick_search_card(page_id: str, keyword: str) -> Optional[Dict]:
    """快速搜索卡片"""
    bi = create_bi()
    return bi.find_card(page_id, keyword)


# ============== CLI 命令行支持 ==============

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python guandata.py login              # 登录测试")
        print("  python guandata.py pages             # 获取页面列表")
        print("  python guandata.py cards <pgId>      # 获取页面卡片")
        print("  python guandata.py data <cardId>     # 获取卡片数据")
        print("  python guandata.py find <keyword>    # 搜索页面")
        print("  python guandata.py dump <cardId>     # 打印卡片数据")
        print()
        print("示例:")
        print("  python guandata.py pages")
        print("  python guandata.py cards a1e26ba7dd67542f288ab501")
        print("  python guandata.py data o422e78bca04b4822b18a239")
        print("  python guandata.py find 针织")
        print("  python guandata.py dump o422e78bca04b4822b18a239")
        return
    
    bi = GuanBI()
    command = sys.argv[1]
    
    if command == "login":
        bi.login(force=True)
    
    elif command == "pages":
        bi.login()
        pages = bi.get_page_list()
        print(f"\n共 {len(pages)} 个页面:\n")
        for p in pages[:30]:
            print(f"  {GuanBI._page_id(p)} | {p.get('name')}")
        if len(pages) > 30:
            print(f"  ... 还有 {len(pages) - 30} 个页面")
    
    elif command == "cards":
        if len(sys.argv) < 3:
            print("用法: python guandata.py cards <pgId>")
            return
        bi.login()
        cards = bi.get_page_cards_summary(sys.argv[2])
        print(f"\n共 {len(cards)} 个卡片:\n")
        for c in cards:
            print(f"  {c.get('cdId')} | {c.get('type'):<8} | {c.get('name', '')[:40]}")
    
    elif command == "data":
        if len(sys.argv) < 3:
            print("用法: python guandata.py data <cardId>")
            return
        bi.login()
        parsed = bi.get_card_data(sys.argv[2])
        print(f"\n共 {parsed.get('total', 0)} 行数据")
        bi.print_card_data(sys.argv[2], max_rows=10)
    
    elif command == "find":
        if len(sys.argv) < 3:
            print("用法: python guandata.py find <keyword>")
            return
        bi.login()
        page = bi.find_page(sys.argv[2])
        if page:
            print(f"找到页面: {page.get('pgId')} | {page.get('name')}")
        else:
            print(f"未找到包含 '{sys.argv[2]}' 的页面")
    
    elif command == "dump":
        if len(sys.argv) < 3:
            print("用法: python guandata.py dump <cardId>")
            return
        bi.login()
        bi.print_card_data(sys.argv[2], max_rows=20)
    
    else:
        print(f"未知命令: {command}")


if __name__ == "__main__":
    main()
