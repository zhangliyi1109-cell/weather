# Weather Clothing Framework

## 1) TypeScript 接口定义

```ts
export type TempTrend = "rising" | "falling" | "stable";
export type RiskLevel = "low" | "medium" | "high";

export interface WeatherCondition {
  city?: string;
  date?: string;
  avgTemp: number;              // 均温（°C）
  tempMax?: number;             // 最高温（°C）
  tempMin?: number;             // 最低温（°C）
  rainDays: number;             // 未来N天降雨天数
  precipProb?: number;          // 降雨概率（0-100）
  humidity: number;             // 湿度（0-100）
  windScale: number;            // 风力等级（如 0-12）
  tempTrend: TempTrend;         // 升温/降温/平稳
  season?: "spring" | "summer" | "autumn" | "winter";
}

export interface ClothingRecommendation {
  primaryCategories: string[];  // 主推品类
  secondaryCategories: string[];// 次推品类
  avoidCategories: string[];    // 建议降权/规避品类
  riskLevel: RiskLevel;         // 风险等级
  tags: string[];               // 规则标签，如“高温”“高湿”“雨天”
  notes: string[];              // 业务说明
}

export interface DecisionRule {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;             // 数字越小优先级越高
  condition: (w: WeatherCondition, cfg: RuleConfig) => boolean;
  apply: (w: WeatherCondition, result: ClothingRecommendation, cfg: RuleConfig) => void;
}

export interface RuleConfig {
  temperature: {
    hot: number;                // >= hot
    warmLow: number;            // [warmLow, hot)
    coolLow: number;            // [coolLow, warmLow)
  };
  rain: {
    rainyDaysTrigger: number;   // >= 触发雨天叠加
    heavyPrecipProb: number;    // >= 触发强降雨
  };
  humidity: {
    high: number;               // >= 高湿
    low: number;                // <= 低湿
  };
  wind: {
    strong: number;             // >= 大风
  };
  correction: {
    cityTempOffset: Record<string, number>;   // 城市温度修正
    nationalFocusWeight: Record<string, number>; // 城市权重
  };
}
```

---

## 2) 默认配置参数

```ts
export const defaultRuleConfig: RuleConfig = {
  temperature: {
    hot: 28,
    warmLow: 22,
    coolLow: 15,
  },
  rain: {
    rainyDaysTrigger: 2,
    heavyPrecipProb: 60,
  },
  humidity: {
    high: 75,
    low: 35,
  },
  wind: {
    strong: 5,
  },
  correction: {
    cityTempOffset: {
      "北京": -1.5,
      "上海": 0,
      "江苏": -0.5,
      "浙江": -0.5,
      "广州": 2.0,
    },
    nationalFocusWeight: {
      "北京": 0.30,
      "上海": 0.30,
      "江苏": 0.20,
      "浙江": 0.20,
      "_default": 0.10,
    },
  },
};
```

---

## 3) 核心算法逻辑（函数框架）

```ts
export function calculateClothingRecommendation(
  weather: WeatherCondition,
  config: RuleConfig = defaultRuleConfig
): ClothingRecommendation {
  const result: ClothingRecommendation = {
    primaryCategories: [],
    secondaryCategories: [],
    avoidCategories: [],
    riskLevel: "low",
    tags: [],
    notes: [],
  };

  // 1) 温度主规则
  if (weather.avgTemp >= config.temperature.hot) {
    result.tags.push("高温");
    result.primaryCategories.push("T恤", "背心/吊带", "连衣裙");
    result.secondaryCategories.push("薄针织");
    result.avoidCategories.push("厚针织", "重外套");
  } else if (weather.avgTemp >= config.temperature.warmLow) {
    result.tags.push("温暖");
    result.primaryCategories.push("T恤", "衬衫", "薄外套");
    result.secondaryCategories.push("连衣裙", "休闲裤");
  } else if (weather.avgTemp >= config.temperature.coolLow) {
    result.tags.push("微凉");
    result.primaryCategories.push("针织衫", "衬衫", "休闲裤", "短外套");
    result.secondaryCategories.push("风衣");
  } else {
    result.tags.push("偏冷");
    result.primaryCategories.push("风衣", "大衣", "卫衣", "保暖针织");
    result.secondaryCategories.push("羽绒相关");
  }

  // 2) 降雨叠加
  if (weather.rainDays >= config.rain.rainyDaysTrigger || (weather.precipProb ?? 0) >= config.rain.heavyPrecipProb) {
    result.tags.push("雨天");
    result.primaryCategories.push("风衣", "防泼水外套");
    result.notes.push("雨天叠加：提高防泼水/外套权重");
  }

  // 3) 湿度叠加
  if (weather.humidity >= config.humidity.high) {
    result.tags.push("高湿");
    result.primaryCategories.push("透气衬衫", "轻薄T恤");
    result.avoidCategories.push("厚针织");
    result.notes.push("高湿叠加：降低厚重针织");
  } else if (weather.humidity <= config.humidity.low) {
    result.tags.push("低湿");
    result.secondaryCategories.push("针织层搭");
  }

  // 4) 风力叠加
  if (weather.windScale >= config.wind.strong) {
    result.tags.push("大风");
    result.primaryCategories.push("外套", "风衣");
    result.notes.push("大风叠加：提升外套层次");
  }

  // 5) 危险组合识别（见下方）
  // TODO: 根据危险组合策略调整 riskLevel / primary / avoid / notes

  // 6) 去重、清洗
  result.primaryCategories = Array.from(new Set(result.primaryCategories));
  result.secondaryCategories = Array.from(new Set(result.secondaryCategories))
    .filter((x) => !result.primaryCategories.includes(x));
  result.avoidCategories = Array.from(new Set(result.avoidCategories))
    .filter((x) => !result.primaryCategories.includes(x));

  return result;
}
```

---

## 4) 危险组合标记（必须特殊处理）

```ts
export const dangerousWeatherCombinations = [
  {
    id: "hot_humid_rain",
    name: "高温+高湿+降雨",
    condition: "avgTemp>=28 && humidity>=75 && rainDays>=2",
    action: "主推速干/透气/防泼水；强降针织权重；提升缺货风险等级",
  },
  {
    id: "cool_rain_wind",
    name: "低温+降雨+大风",
    condition: "avgTemp<15 && rainDays>=2 && windScale>=5",
    action: "主推外套/风衣/保暖层；标记高风险，避免轻薄单品",
  },
  {
    id: "temp_drop_fast",
    name: "短期快速降温",
    condition: "tempTrend==='falling' && (tempMax-tempMin)>=8",
    action: "增加过渡保暖品类，减少纯夏装曝光",
  },
  {
    id: "false_summer_signal",
    name: "白天热夜间冷（假夏）",
    condition: "avgTemp>=22 && tempMin<=14",
    action: "建议层搭；上装轻薄但保留外套位；避免单一薄款备货",
  },
];
```

---

## 5) 你可以让 Cursor 直接做的事

- 根据上述接口和默认配置，生成一个可交互的天气选品看板（展示输入天气、命中规则、推荐结果、风险标签）。
- 用 React/Vue 做配置面板，让用户在线调整阈值（温度/降雨/湿度/风力）并实时预览推荐变化。
- 增加“保存配置”与“版本回滚”能力，便于运营团队试错。
- 增加“危险组合命中提醒”模块，单独高亮和告警。
