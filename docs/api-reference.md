# API 参考

Base URL：`http://localhost:8000`，全部 v2 端点在 `/sp-api/v2` 下，交互文档见 `/docs`，能力自描述见 `/sp-api/v2/agent.json`。

## 统一响应

```json
{
  "code": 0,
  "message": "ok",
  "data": [],
  "meta": {
    "total": 120, "page": 1, "page_size": 20,
    "data_date": "20261117",
    "data_source": "postgresql",
    "completeness": 1.0
  }
}
```

- `code=0` 成功；非 0 见错误码表。
- `meta.data_date` 是按**该端点实际使用的表**探测的最新日期，不是全库最新交易日。
- `meta.completeness` 表示该表相对预期覆盖度的估计值（1.0 = 完整）。
- `data_source`：`postgresql` / `sqlite`。

## 分页

`page`（默认 1）、`page_size`（默认 20，**上限 1000**）。返回 `meta.total` 为总数。

## 错误码

| code | 含义 |
|---|---|
| 0 | 成功 |
| 1001 | 参数错误 |
| 1004 | 无权限 / 未注册（`/self` 分层校验） |
| 2001 | 数据不存在 |
| 2002 | 上游数据源超时 |
| 5000 | 服务内部错误 |

## 端点分组

| 前缀 | 说明 | 代表端点 |
|---|---|---|
| `/stocks` | 股票列表与搜索 | `/stocks/{ts_code}`、`/stocks/search` |
| `/equity` | 日/周/月线、每日指标、交易日历 | `/equity/daily`、`/equity/daily_basic`、`/equity/trade_dates` |
| `/fundamental` | 三大报表 + 财务指标 | `/fundamental/fina_indicator/{ts_code}` |
| `/moneyflow` | 资金流 | `/moneyflow/{ts_code}`、`/moneyflow/rank/{date}` |
| `/lhb` | 龙虎榜 | `/lhb/{trade_date}`、`/lhb/stats/{ts_code}` |
| `/holders` | 股东 | `/holders/top10/{ts_code}`、`/holders/holder_number/{ts_code}` |
| `/index` | 指数 | `/index/daily/{ts_code}`、`/index/constituents/{ts_code}` |
| `/industry` | 行业 | `/industry/daily`、`/industry/performance` |
| `/macro` | 国内宏观（cn_*） | `/macro/cpi`、`/macro/list/all` |
| `/global_macro` | FRED + World Bank | `/global_macro/fred/{series_id}`、`/global_macro/wb/{indicator}` |
| `/realtime` | 实时行情 | `/realtime/quote/{ts_code}`、`/realtime/global_indices` |
| `/portfolio` | 组合 CRUD + NAV + 归因 | `/portfolio/{pid}/nav`、`/portfolio/{pid}/stats` |
| `/diagnosis` | 诊股 | `/diagnosis/{ts_code}`、`/diagnosis/deep/{ts_code}` |
| `/signal` | 信号与回测 | `/signal/analysis/{ts_code}`、`/signal/probability/{ts_code}`、`/signal/backtest` |
| `/market/regime` | 大市开关 | `?ts_code=000001.SH` |
| `/discipline` | 交易纪律 | `/discipline/plan/{ts_code}`、`/discipline/plan/portfolio/{pid}` |
| `/philosophy` | 证伪 / 反身性 | `/philosophy/falsification/{ts_code}` |
| `/screen` | 选股 | `/screen/equity` |
| `/reports` | 研报目录与正文 | `/reports`、`/reports/{kind}/{date}/pdf` |
| `/self` | 客户自助 | `/self/status`、`/self/deliveries` |
| `/system/health` | 健康检查 | 9 库状态、版本 |

## 示例

```bash
# 日线（最近 3 条）
curl "localhost:8000/sp-api/v2/equity/daily?ts_code=002714.SZ&limit=3"

# 资金流排行
curl "localhost:8000/sp-api/v2/moneyflow/rank/20261117?limit=10"

# 涨跌概率（因子归因）
curl "localhost:8000/sp-api/v2/signal/probability/002714.SZ"

# 信号回测（中文信号名需 URL 编码）
curl "localhost:8000/sp-api/v2/signal/backtest?ts_code=002714.SZ&signal=MACD%E9%87%91%E5%8F%89&horizon=10"
```
