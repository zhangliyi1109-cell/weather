"""
款号（款式编码）识别规则（与业务脚本对齐）

合法款号：
- ^(ME|MD)\\w{7,}$：ME/MD 开头，其后至少 7 个「字类」字符（按 ASCII 字母数字下划线实现，避免 \\w 匹配到中文）
- ^9[A-Z0-9]\\w{5,}[A-Z].*$：9 开头第二位为字母数字，其后至少 5 个 \\w，再出现一个大写字母段（整体不区分大小写匹配）
- ^[A-Za-z0-9]{8,}$ 且非纯数字：兜底

不识别为款号：含中文、纯数字、长度 < 8
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

_RE_ME_MD = re.compile(r"^(?:ME|MD)[A-Za-z0-9_]{7,}$")
# 用户给定模式的不区分大小写版；末尾「含字母」用最后一字符为字母满足常见款号
_RE_9_LEAD = re.compile(r"^9[A-Za-z0-9][A-Za-z0-9_]{5,}[A-Za-z].*$")
_RE_ALNUM_FALLBACK = re.compile(r"^[A-Za-z0-9]{8,}$")


def contains_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", s))


def is_valid_style_code(s: Optional[str]) -> bool:
    if not s:
        return False
    t = str(s).strip()
    if len(t) < 8:
        return False
    if contains_cjk(t):
        return False
    if t.isdigit():
        return False
    if _RE_ME_MD.match(t):
        return True
    if _RE_9_LEAD.match(t):
        return True
    if _RE_ALNUM_FALLBACK.match(t) and not t.isdigit():
        return True
    return False


def pick_style_code(candidates: Iterable[str]) -> str:
    """
    按顺序取第一个合法款号；若无，则取第一个非空字符串（兼容历史数据）。
    """
    seen: List[str] = []
    for raw in candidates:
        if raw is None:
            continue
        x = str(raw).strip()
        if not x or x in seen:
            continue
        seen.append(x)
        if is_valid_style_code(x):
            return x
    return seen[0] if seen else ""


def pick_style_code_from_dim_titles(dim_cells: List[dict], prefer_indices: Optional[List[int]] = None) -> str:
    """
    从观远行维度 title 中提取款号。默认优先 dims[2]（款式编码列），再扫其它列。
    dim_cells: chartMain.row.values 的每一行，元素为 {title: ...}
    """
    if not dim_cells:
        return ""
    order = prefer_indices if prefer_indices is not None else [2, 1, 0, 3, 4, 5, 6, 7, 8, 9]
    candidates: List[str] = []
    for i in order:
        if 0 <= i < len(dim_cells):
            t = dim_cells[i].get("title")
            if t is not None and str(t).strip():
                candidates.append(str(t).strip())
    for i, cell in enumerate(dim_cells):
        if i in order:
            continue
        t = cell.get("title")
        if t is not None and str(t).strip():
            candidates.append(str(t).strip())
    return pick_style_code(candidates)
