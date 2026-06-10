# BI 系统集成说明

## ✅ 集成完成

已成功将观远 BI 系统集成到天气数据分析与智能产品推荐系统中！

## 📊 数据来源

### BI 系统信息

- **BI 平台**: 观远数据 (GuanData)
- **BI 地址**: [https://bi.marius.vip](https://bi.marius.vip)
- **数据来源页面**: 库存消耗进度跟踪 (pageId: f670828ac13a043fc87114a8)
- **数据卡片**: MARIUS25秋冬产品库存消耗进度跟踪 (cardId: kbcf363fdb24641079e338c0)

### 获取的数据字段


| 字段                | 说明        | 来源      |
| ----------------- | --------- | ------- |
| sku_id            | 款式编码      | BI      |
| name              | 小名（商品名称）  | BI      |
| category          | 产品分类      | BI      |
| stock             | 现货库存（指标1） | BI      |
| inbound           | 采购在途（指标2） | BI      |
| size_completeness | 尺码齐全度     | 默认 0.85 |
| return_rate       | 退货率       | 默认 0.15 |
| conversion_rate   | 转化率       | 默认 0.05 |


## 📁 新增文件


| 文件                        | 说明                         |
| ------------------------- | -------------------------- |
| `guandata.py`             | 观远 BI API 封装脚本（从 skill 复制） |
| `bi_inventory_service.py` | BI 库存数据服务模块                |
| `BI集成说明.md`               | 本文档                        |


## 🔧 修改的文件


| 文件                   | 修改内容           |
| -------------------- | -------------- |
| `bi_data_service.py` | 集成真实 BI 数据获取逻辑 |


## 🚀 使用方法

### 1. 直接使用 BI 数据

```python
from bi_data_service import BIDataService

# 创建服务（自动使用 BI 数据）
service = BIDataService(use_bi_data=True)

# 获取库存数据
products = service.fetch_bi_inventory_data()
print(f"获取到 {len(products)} 条商品记录")

# 获取推荐
recommendations = service.get_recommendations_by_weather(
    avg_temp=25,
    rain_days=3,
    temp_trend="rising"
)
```

### 2. 单独使用 BI 库存服务

```python
from bi_inventory_service import get_bi_inventory_service

# 获取服务实例
bi_service = get_bi_inventory_service()

# 获取库存数据
inventory = bi_service.fetch_inventory_data()

# 获取品类汇总
summary = bi_service.get_category_summary()
```

### 3. 命令行查看 BI 数据

```bash
# 查看 BI 页面列表
python guandata.py pages

# 查看库存页面卡片
python guandata.py cards f670828ac13a043fc87114a8

# 查看库存数据
python guandata.py dump kbcf363fdb24641079e338c0
```

## 📈 数据规模

- **SKU 数量**: 1,777 款
- **数据更新**: 实时从 BI 获取（支持缓存）
- **数据时效**: Token 缓存 24 小时，数据缓存 30 分钟

## 🔐 认证信息

BI 系统使用 Token 认证，已配置：

- App Token: d3dc3da5b8356403e882269e
- 登录账号: [admin@guandata.com](mailto:admin@guandata.com)

Token 会自动缓存到 `~/.openclaw/skills/guandata-bi/scripts/.token_cache`

## ⚠️ 注意事项

1. **品类推断**: 目前根据商品名称关键词推断品类，可能不够准确
2. **退货率/转化率**: BI 数据中暂时没有这些字段，使用默认值
3. **数据权限**: 确保 BI 账号有权限访问库存页面

## 📝 后续优化建议

1. **完善品类映射**: 建立 SKU 到标准品类的映射表
2. **获取退货率/转化率**: 从 BI 的其他页面获取这些指标
3. **数据同步**: 设置定时任务，定期同步 BI 数据到本地缓存
4. **异常处理**: 增加 BI 服务不可用时自动降级到模拟数据

---

**集成时间**: 2026-04-09  
**数据来源**: 观远 BI 系统  
**数据量**: 1,777 SKU