# Agent 示例

把「一句话需求」映射到工具组合。以下均可直接用 MCP 客户端执行。

## 1. 个股体检

> 「牧原股份现在什么状态？把财务、资金、技术、宏观都过一遍」

```
deep_diagnosis("002714.SZ")
→ 四维评分 + 综合分 + 置信度 + 证伪条件 + 反身性阶段
```

## 2. 择时纪律

> 「我想买 100 万牧原，按纪律给我计划」

```
get_market_regime("000001.SH")        # 先看大市开关
get_trading_plan("002714.SZ", total_capital=1000000)
→ L1 环境 / L2 标的 / L3 风险预算（单笔≤2%、单票≤20%）/ L4 退出 / 结论
```

大市空头时严格模式直接给 `grade=回避`——「大市不好不买」。

## 3. 信号与概率

```
get_signal_analysis("002714.SZ")   # 均线/MACD/RSI/KDJ/BOLL 信号与量价背离
get_probability("002714.SZ")       # 涨跌概率 + 因子归因
backtest_signal("002714.SZ", signal="MACD金叉", horizon=10)   # 历史胜率
```

## 4. 行业与资金

```
get_industry_daily_performance()   # 当日行业涨跌
get_moneyflow_rank("20261117")     # 资金流排行
get_lhb("20261117")                # 龙虎榜
```

## 5. 选股

```
screen_stocks(pe_max=15, roe_min=20, industry="银行")
```

## 组合技：写一份收盘复盘

1. `get_market_regime` → 今天能不能做
2. `get_industry_daily_performance` → 哪个板块在动
3. `get_moneyflow_rank` + `get_lhb` → 钱去哪了
4. 对 3-5 只候选 `quick_diagnosis` → 有没有值得跟的
5. `get_reports` → 引用自己此前的判断，做一次复盘（证实/证伪）

## 写提示词的一条建议

不要让它「预测涨跌」，让它**给条件**：什么价位、什么信号出现才成立，什么情况下判断被证伪。StockPulse 的接口本身就是按这个思路设计的（置信度 + 证伪条件 + 回测）。
