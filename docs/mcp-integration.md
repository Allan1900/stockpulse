# MCP 接入

StockPulse 提供标准 MCP Server（FastMCP），30 个工具，支持 **stdio** 与 **SSE** 两种传输。

## 安装

```bash
pip install -e ".[api,mcp]"
```

## Claude Code / Cursor / Codex 配置

```json
{
  "mcpServers": {
    "stockpulse": {
      "command": "python",
      "args": ["-m", "ashare.api.v2.mcp_server"],
      "env": {
        "TUSHARE_TOKEN": "your_token",
        "PGDATABASE": "ashare",
        "SP_DATA_DIR": "/path/to/data"
      },
      "timeout": 120
    }
  }
}
```

远程模式（SSE）：

```bash
stockpulse-mcp --sse --port 8002
# 客户端连 http://host:8002/sse
```

## 工具清单（30）

| 组 | 工具 |
|---|---|
| 行情 | `search_stocks` `get_daily` `get_realtime` `get_fundamentals` |
| 资金 | `get_moneyflow` `get_moneyflow_rank` `get_lhb` `get_macro` |
| 行业 | `get_industry_performance` `get_industry_daily_performance` `screen_stocks` |
| 诊股与信号 | `deep_diagnosis` `quick_diagnosis` `get_signal_analysis` `get_probability` `get_divergence` `backtest_signal` |
| 市场与纪律 | `get_market_regime` `get_trading_plan` |
| 哲学层 | `get_falsification` `get_reflexivity_stage` |
| 组合 | `get_portfolios` `get_portfolio_detail` `portfolio_performance` |
| 研报 | `get_reports` `get_report` |
| 客户 | `get_self_status` `get_self_deliveries` |
| 告警 | `check_alerts` `get_alert_config` |

## 典型返回

`get_daily("002714.SZ", limit=3)`：

```json
{"records": [{"ts_code":"002714.SZ","trade_date":"20261117","close":45.82,"pct_chg":-1.0367}],
 "meta": {"data_date":"20261117","data_source":"postgresql"}}
```

失败时返回 `{"error": "..."}` 而不是抛异常，方便 Agent 继续推理。

## 提示

- 行情类工具走 PG，宏观/全球宏观走 SQLite——`meta.data_source` 会告诉你是哪一个。
- `get_trading_plan` 支持 `strict=true|false`：严格模式下大市空头直接否决（`grade=回避`），宽松模式只提示。
- 需要补充语义搜索/新闻时，MCP 不负责联网抓取，交给宿主 Agent 的检索工具。
