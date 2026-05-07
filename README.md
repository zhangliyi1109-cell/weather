# 天气驱动的服装选品推荐系统 V2

基于 Open-Meteo 天气 API + 观远 BI 实时库存数据的 Flask 全栈推荐系统，支持**北京、上海、广州**三城。

## 系统架构

```
weather_v2/
├── app.py                        # Flask 主服务（路由/缓存）
├── config.py                     # 配置文件（城市/服务器/BI/飞书）
├── weather_service.py            # Open-Meteo 天气数据服务
├── bi_data_service.py            # ★ 推荐逻辑核心（天气规则 + 品类映射 + 评分算法）
├── bi_inventory_service_v3.py    # ★ Playwright 抓取 BI 库存数据（当前使用版本）
├── bi_inventory_service_v2.py    # v2 版本（备用）
├── bi_inventory_service.py       # v1 版本（备用）
├── guandata.py                   # 观远 BI 数据连接器
├── feishu_service.py             # 飞书多维表同步
├── requirements.txt              # Python 依赖
├── .gitignore                    # Git 忽略规则
├── templates/
│   └── index.html                # 前端仪表板页面
├── README.md                     # 本文件
├── BI集成说明.md                  # BI 数据对接说明
└── 数据更新说明.md               # 数据更新日志
```

## 核心功能

| 模块 | 说明 |
|------|------|
| **天气采集** | Open-Metco API 获取 16 天预报（温度/降水/湿度） |
| **BI 库存抓取** | Playwright 自动登录观远 BI，提取商品库存/在途/退货率/转化率 |
| **智能推荐** | 天气 → 品类映射 → 库存评分 → Top 品类 + Top 单品 |
| **前端展示** | 响应式仪表板：品类卡片 + 单品卡片 + 采购建议 |

## 推荐算法

### 天气 → 品类映射规则

基于 `MARIUS 天气选品数据` 提炼：

| 条件 | 推荐品类 |
|------|----------|
| 均温 ≥25°C | 短袖T恤 → T恤/背心/针织衫；连衣裙 → 连衣裙/半身裙 |
| 15°C ~ 25°C | 长袖T恤 → 针织衫/T恤/衬衫；薄外套 → 西装/短外套/风衣；亚麻款 → 衬衫/西装/马夹 |
| <15°C | 薄毛衣 → 针织衫/卫衣；风衣 → 风衣/大衣 |
| 有降水 | 叠加防泼水外套 → 风衣/短外套/大衣 |

### 评分权重

```
推荐指数 = 可售库存 × 80% + 转化率 × 10% + (1-退货率) × 10%
可售库存 = 总库存(含在途) - 订单占有数
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python app.py

# 3. 访问
open http://localhost:5000
```

## 配置说明

- `app.py` 中 `USE_BI_DATA = True` 使用 BI 真实数据，`= False` 用模拟数据
- BI 抓取地址配置在 `bi_inventory_service_v3.py`
- 飞书同步需在 `config.py` 配置 App ID / Secret / 多维表 Token

## 关键技术点

1. **BI 字段解析**：通过 `[role="gridcell"]` JS 提取，按表头动态确定字段位置，品类用 `known_categories` 列表匹配
2. **订单占有数**：BI 表头当前无此字段，fallback 为 0
3. **前端单品卡片**：显示产品名称(`product_name`) + 小名(`name`) + 款号 + 可售库存 + 推荐指数圆环
