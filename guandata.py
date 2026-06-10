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
import tempfile
from typing import Dict, List, Optional, Any, Union, Callable
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 配置（仅从环境变量读取；本地用 .env，生产环境填环境变量）
# 勿在代码中写死应用 Token，避免泄露且防止空字符串变量意外禁用 sign-in。
BI_BASE = os.getenv("GUANDATA_BASE_URL", "https://bi.marius.vip").rstrip("/")
APP_TOKEN = (os.getenv("GUANDATA_APP_TOKEN") or "").strip()
LOGIN_ID = (os.getenv("GUANDATA_LOGIN_ID") or "").strip()
# 与 BI集成说明.md 一致；仅在本机 guancli 已登录且未配置 GUANDATA_APP_TOKEN 时作 sign-in 回退
_DEFAULT_APP_TOKEN = "d3dc3da5b8356403e882269e"

_env_x_warn = (os.getenv("GUANDATA_X_AUTH_TOKEN") or "").strip()
if _env_x_warn and not (APP_TOKEN and LOGIN_ID):
    print(
        "⚠ 观远：已设置 GUANDATA_X_AUTH_TOKEN 但未配置 GUANDATA_APP_TOKEN+GUANDATA_LOGIN_ID；"
        "Token 过期后无法自动续期，请补充 GUANDATA_APP_TOKEN+GUANDATA_LOGIN_ID 并去掉过期 X_AUTH。"
    )


def _default_token_cache_path() -> str:
    """容器/本机默认可写目录；可通过 GUANDATA_TOKEN_CACHE_PATH 覆盖。"""
    explicit = os.getenv("GUANDATA_TOKEN_CACHE_PATH", "").strip()
    if explicit:
        return os.path.expanduser(explicit)
    runtime = os.getenv("GUANDATA_RUNTIME_DIR", "").strip()
    if runtime:
        return os.path.join(os.path.expanduser(runtime), "guandata_token_cache.json")
    return os.path.join(tempfile.gettempdir(), "guandata_token_cache.json")


TOKEN_CACHE_FILE = _default_token_cache_path()


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

    @staticmethod
    def _is_auth_error(resp: requests.Response, data: Any) -> bool:
        """判断是否因 Token 失效或未授权（用于触发 sign-in 刷新）。"""
        if resp is not None and resp.status_code in (401, 403):
            return True
        if not isinstance(data, dict):
            return False
        if data.get("result") == "ok":
            return False
        # 观远卡片接口常见：HTTP 401 + {"status":1018,"message":"Not Login or token expired",...}
        st = data.get("status")
        if st == 1018 or st == "1018":
            return True
        err = str(data.get("error") or data.get("message") or "")
        detail = data.get("detail")
        if isinstance(detail, dict):
            err += " " + json.dumps(detail, ensure_ascii=False)
        elif detail is not None:
            err += " " + str(detail)
        err_l = err.lower()
        hints = (
            "unauthorized",
            "forbidden",
            "token",
            "auth",
            "login",
            "sign-in",
            "not login",
            "登录",
            "认证",
            "权限",
            "过期",
            "失效",
            "expire",
            "invalid",
        )
        if any(h in err_l for h in hints):
            return True
        try:
            blob = json.dumps(data, ensure_ascii=False).lower()
            if "token expired" in blob or "not login" in blob:
                return True
        except (TypeError, ValueError):
            pass
        return False

    def _invalidate_token_and_page_caches(self) -> None:
        self.x_auth_token = None
        self._page_cache.clear()
        self._page_detail_cache.clear()

    def _load_guancli_profile(self) -> Optional[Dict[str, Any]]:
        """读取 guancli 默认 profile（login_id / base_url 等）。"""
        candidates = [
            os.path.expanduser("~/Library/Application Support/guancli/config.json"),
            os.path.expanduser("~/.config/guancli/config.json"),
        ]
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                profiles = cfg.get("profiles") or {}
                prof = None
                for p in profiles.values():
                    if isinstance(p, dict) and p.get("is_default"):
                        prof = p
                        break
                if prof is None and profiles:
                    prof = next(iter(profiles.values()))
                if isinstance(prof, dict):
                    return prof
            except Exception:
                continue
        return None

    def _resolve_signin_credentials(self) -> tuple:
        """合并 .env 与 guancli profile，得到 Public API sign-in 用的 (app_token, login_id)。"""
        app_token = (os.getenv("GUANDATA_APP_TOKEN") or "").strip()
        login_id = (os.getenv("GUANDATA_LOGIN_ID") or "").strip()
        prof = self._load_guancli_profile()
        if prof:
            if not login_id:
                login_id = str(prof.get("login_id") or "").strip()
            if not app_token:
                app_token = str(prof.get("app_token") or _DEFAULT_APP_TOKEN).strip()
        return app_token, login_id

    def _signin_with_credentials(self, app_token: str, login_id: str) -> bool:
        """调用 Public API loginId/sign-in 换取 X-Auth-Token。"""
        if not app_token or not login_id:
            return False
        resp = self.session.post(
            f"{BI_BASE}/public-api/user/loginId/sign-in",
            json={"token": app_token, "loginId": login_id},
            timeout=self.REQUEST_TIMEOUT,
        )
        try:
            data = resp.json()
        except Exception:
            print(f"✗ 登录失败: 响应非 JSON HTTP {resp.status_code}")
            return False
        if data.get("result") == "ok":
            self.x_auth_token = data["response"]["token"]
            expire_at_str = data["response"].get("expireAt", "未知")
            print(f"✓ 登录成功，Token 有效期至: {expire_at_str}")
            self._save_token_cache(expire_at_str)
            self._page_cache.clear()
            self._page_detail_cache.clear()
            return True
        print(f"✗ 登录失败: {data.get('error') or data.get('message')}")
        return False

    def _try_guancli_signin(self) -> bool:
        """
        开发机回退：guancli 的 JWT/uIdToken 不能用于 Public API；
        改用 guancli profile 的 login_id + 应用 Token 走 sign-in。
        """
        app_token, login_id = self._resolve_signin_credentials()
        if not login_id:
            return False
        if self._signin_with_credentials(app_token, login_id):
            print("✓ 使用 guancli profile + Public API sign-in（本地开发）")
            return True
        return False

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
            parent = os.path.dirname(self.token_cache_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
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
        """
        获取 X-Auth-Token。

        生产推荐：配置 GUANDATA_APP_TOKEN + GUANDATA_LOGIN_ID，通过 sign-in 自动换票并写入缓存；
        GUANDATA_X_AUTH_TOKEN 有时效，仅靠环境变量无法续期。

        若必须只用粘贴的 X-Auth-Token：设 GUANDATA_ONLY_ENV_X_AUTH_TOKEN=true。
        """
        only_env = os.getenv("GUANDATA_ONLY_ENV_X_AUTH_TOKEN", "").lower() in (
            "1",
            "true",
            "yes",
        )
        env_x_token = os.getenv("GUANDATA_X_AUTH_TOKEN", "").strip()
        signin_app, signin_login = self._resolve_signin_credentials()
        has_signin = bool(signin_app and signin_login)

        if only_env and env_x_token:
            self.x_auth_token = env_x_token
            print(
                "✓ 使用 GUANDATA_X_AUTH_TOKEN（GUANDATA_ONLY_ENV_X_AUTH_TOKEN=true，不会自动 sign-in）"
            )
            return True

        if has_signin:
            if not force and self._load_cached_token():
                return True
            if force:
                self._invalidate_token_and_page_caches()
            return self._signin_with_credentials(signin_app, signin_login)

        if env_x_token and not has_signin:
            self.x_auth_token = env_x_token
            if not force:
                print(
                    "⚠ 使用 GUANDATA_X_AUTH_TOKEN（未配置 GUANDATA_APP_TOKEN+GUANDATA_LOGIN_ID，"
                    "过期后无法自动换票；请配置 GUANDATA_APP_TOKEN+GUANDATA_LOGIN_ID 并删除过期的 X_AUTH）"
                )
            return True

        if not force and self._load_cached_token():
            return True

        if self._try_guancli_signin():
            return True

        print(
            "✗ 观远未配置：请设置 GUANDATA_APP_TOKEN + GUANDATA_LOGIN_ID，"
            "或临时设置 GUANDATA_X_AUTH_TOKEN，或在本机执行 guancli auth login"
        )
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

        last_err = ""
        for attempt in range(2):
            if not self.x_auth_token:
                self.login()
            resp = self.session.post(
                f"{BI_BASE}/public-api/page/list",
                headers=self._headers(),
                json={"token": APP_TOKEN},
                timeout=self.REQUEST_TIMEOUT,
            )
            try:
                data = resp.json()
            except Exception:
                last_err = f"非 JSON 响应 HTTP {resp.status_code}"
                if attempt == 0 and resp.status_code in (401, 403):
                    self.login(force=True)
                    continue
                raise Exception(f"获取页面列表失败: {last_err}")
            if data.get("result") == "ok":
                pages = data.get("response", [])
                self._page_cache['page_list'] = pages
                return pages
            last_err = str(data.get("error") or data.get("message") or resp.text[:300])
            if attempt == 0 and self._is_auth_error(resp, data):
                self.login(force=True)
                continue
            break
        raise Exception(f"获取页面列表失败: {last_err}")
    
    def get_page_detail(self, pg_id: str, use_cache: bool = True) -> Dict:
        """获取页面详情（含卡片列表）"""
        if use_cache and pg_id in self._page_detail_cache:
            return self._page_detail_cache[pg_id]

        last_err = ""

        for attempt in range(2):
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
            saw_auth_error = False

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
                    if resp.status_code in (401, 403):
                        saw_auth_error = True
                    continue
                if data.get("result") == "ok":
                    detail = data.get("response", {})
                    self._page_detail_cache[pg_id] = detail
                    return detail
                last_err = str(data.get("error") or data.get("message") or resp.text[:300])
                if self._is_auth_error(resp, data):
                    saw_auth_error = True

            if attempt == 0 and saw_auth_error:
                self.login(force=True)
                continue
            break

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
        last_err = ""
        for attempt in range(2):
            if not self.x_auth_token:
                self.login()
            resp = self.session.post(
                f"{BI_BASE}/public-api/card/{card_id}/data",
                headers=self._headers(),
                json={"view": view},
                timeout=self.REQUEST_TIMEOUT,
            )
            try:
                data = resp.json()
            except Exception:
                raise Exception(
                    f"获取卡片数据失败: 响应非 JSON，HTTP {resp.status_code} {resp.text[:400]}"
                )
            if data.get("result") == "ok":
                card_data = data.get("response", {})
                if auto_parse:
                    return self._parse_card_data(card_data)
                return card_data
            last_err = str(data.get("error") or data.get("message") or resp.text[:400])
            if attempt == 0 and self._is_auth_error(resp, data):
                self.login(force=True)
                if not self.x_auth_token:
                    raise Exception(
                        "观远鉴权失败：无法取得 X-Auth-Token；请配置 "
                        "GUANDATA_APP_TOKEN + GUANDATA_LOGIN_ID。"
                    )
                continue
            break
        hint = ""
        err_low = last_err.lower()
        if "1018" in last_err or "token expired" in err_low or "not login" in err_low:
            hint = (
                " 【处理】填写 GUANDATA_APP_TOKEN、GUANDATA_LOGIN_ID，"
                "删除已过期的 GUANDATA_X_AUTH_TOKEN，重启服务。"
            )
        raise Exception(
            f"获取卡片数据失败: {last_err} (HTTP {resp.status_code}, card_id={card_id}){hint}"
        )
    
    def get_card_raw(self, card_id: str, view: str = "GRAPH") -> Dict:
        """获取卡片原始数据（不解析）"""
        return self.get_card_data(card_id, view, auto_parse=False)
    
    def get_dataset_data(self, ds_id: str, limit: int = 10, offset: int = 0) -> Dict:
        """获取数据集数据"""
        last_err = ""
        for attempt in range(2):
            if not self.x_auth_token:
                self.login()
            resp = self.session.post(
                f"{BI_BASE}/public-api/data-source/{ds_id}/data",
                headers=self._headers(),
                json={"limit": limit, "offset": offset},
                timeout=self.REQUEST_TIMEOUT,
            )
            data = resp.json()
            if data.get("result") == "ok":
                return data.get("response", {})
            last_err = str(data.get("error") or "")
            if attempt == 0 and self._is_auth_error(resp, data):
                self.login(force=True)
                continue
            break
        raise Exception(f"获取数据集数据失败: {last_err}")

    def fetch_dataset_rows(
        self,
        ds_id: str,
        *,
        page_size: int = 5000,
        max_rows: Optional[int] = None,
        column_names: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        分页拉取数据集全量/部分行，返回 {列名: 值} 字典列表。
        column_names 若指定则只保留这些列（按数据集 fd 顺序解析后再过滤）。
        """
        page_size = max(1, min(int(page_size or 5000), 20000))
        offset = 0
        all_rows: List[Dict[str, Any]] = []
        col_names: List[str] = column_names[:] if column_names else []

        while True:
            chunk = self.get_dataset_data(ds_id, limit=page_size, offset=offset)
            columns = chunk.get("columns") or []
            if not col_names:
                col_names = [str(c.get("name", "")) for c in columns if c.get("name")]
            preview = chunk.get("preview") or chunk.get("data") or []
            if not preview:
                break
            for raw in preview:
                if not isinstance(raw, (list, tuple)):
                    continue
                row: Dict[str, Any] = {}
                for i, name in enumerate(col_names):
                    if i < len(raw):
                        row[name] = raw[i]
                all_rows.append(row)
            offset += len(preview)
            total = chunk.get("rowCount") or chunk.get("total")
            if len(preview) < page_size:
                break
            if max_rows is not None and len(all_rows) >= max_rows:
                all_rows = all_rows[:max_rows]
                break
            if isinstance(total, int) and offset >= total:
                break
        return all_rows
    
    def get_dataset_columns(self, ds_id: str) -> List[Dict]:
        """获取数据集字段信息"""
        last_err = ""
        for attempt in range(2):
            if not self.x_auth_token:
                self.login()
            resp = self.session.post(
                f"{BI_BASE}/public-api/data-source/{ds_id}/data",
                headers=self._headers(),
                json={"limit": 1},
                timeout=self.REQUEST_TIMEOUT,
            )
            data = resp.json()
            if data.get("result") == "ok":
                return data.get("response", {}).get("columns", [])
            last_err = str(data.get("error") or "")
            if attempt == 0 and self._is_auth_error(resp, data):
                self.login(force=True)
                continue
            break
        raise Exception(f"获取数据集字段失败: {last_err}")
    
    def find_page(self, name_keyword: str) -> Optional[Dict]:
        """根据关键词搜索页面"""
        pages = self.get_page_list()
        for p in pages:
            if name_keyword in p.get('name', ''):
                return p
        return None
    
    def find_card(self, page_id: str, name_keyword: str) -> Optional[Dict]:
        """在页面中搜索卡片（支持逗号分隔多个关键字，命中任一即匹配）"""
        detail = self.get_page_detail(page_id)
        cards = self._collect_page_cards(detail)
        kws = [k.strip() for k in (name_keyword or "").split(",") if k.strip()]
        if not kws:
            return None
        for c in cards:
            label = self._card_label(c)
            if any(k in label for k in kws):
                return c
        return None

    @staticmethod
    def _card_id(c: Dict) -> str:
        return str(c.get("cdId") or c.get("id") or "").strip()

    @staticmethod
    def _card_label(c: Dict) -> str:
        """合并观远页面详情里可能出现的多字段标题，便于按 GUANDATA_CARD_NAME_KEYWORD 匹配。"""
        parts: List[str] = []
        for k in (
            "name",
            "title",
            "cardName",
            "cdName",
            "caption",
            "chartName",
            "originName",
        ):
            v = c.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        for sub in (c.get("setting"), c.get("domSetting"), c.get("config")):
            if isinstance(sub, dict):
                for k in ("name", "title", "cardTitle", "chartTitle"):
                    v = sub.get(k)
                    if isinstance(v, str) and v.strip():
                        parts.append(v.strip())
        return " ".join(parts)

    @staticmethod
    def _collect_page_cards(detail: Dict) -> List[Dict]:
        """
        页面详情中的卡片可能在顶层 cards，也可能在 tabs/sheet 或 dom 布局内；
        仅扫顶层首张会导致 GUANDATA_CARD_NAME_KEYWORD 永远匹配不到其它 Tab 上的明细表。
        """
        seen: set = set()
        acc: List[Dict] = []

        def add_card_dict(node: Dict) -> None:
            cid = GuanBI._card_id(node)
            if not cid or cid in seen:
                return
            seen.add(cid)
            acc.append(node)

        def from_sequence(seq) -> None:
            if not isinstance(seq, list):
                return
            for item in seq:
                if not isinstance(item, dict):
                    continue
                if GuanBI._card_id(item):
                    add_card_dict(item)
                    continue
                for key in ("card", "chart", "widget", "content"):
                    nested = item.get(key)
                    if isinstance(nested, dict) and GuanBI._card_id(nested):
                        add_card_dict(nested)
                        break

        from_sequence(detail.get("cards") or detail.get("cardList") or [])
        from_sequence(detail.get("doms") or [])

        for key in ("tabs", "pageTabs", "tabList", "sheetList"):
            for tab in detail.get(key) or []:
                if not isinstance(tab, dict):
                    continue
                from_sequence(tab.get("cards") or tab.get("cardList") or [])
                from_sequence(tab.get("doms") or [])

        return acc

    @staticmethod
    def _page_id(p: Dict) -> str:
        return str(p.get("pgId") or p.get("id") or "").strip()

    def get_page_cards_summary(self, pg_id: str) -> List[Dict]:
        """获取页面卡片摘要（名称、ID、类型）"""
        detail = self.get_page_detail(pg_id)
        cards = self._collect_page_cards(detail)
        out: List[Dict] = []
        for c in cards:
            cid = self._card_id(c)
            if not cid:
                continue
            out.append({
                "cdId": cid,
                "name": self._card_label(c),
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
