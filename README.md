# 🫀 StockPulse · 市场脉搏

**给 AI Agent 一个可以直接调用的 A 股市场。**

A-share data & analytics platform for AI agents — REST API · MCP Server · analysis engines · self-hosted dashboard.

```bash
git clone https://github.com/Allan1900/stockpulse.git && cd stockpulse
pip install -e ".[api,mcp]"
export TUSHARE_TOKEN=your_token
stockpulse-server          # → http://localhost:8000/docs
```

> **v2.0（2026-11）**：从「Agent SDK」升级为「平台」——**70 个标准化端点 + 30 个 MCP 工具 + 5 个分析引擎 + 统一数据血缘**。
> 0.x 的 SDK/CLI 仍保留在 `src/stockpulse/`，v2 的平台能力在 `src/ashare/`。

---

## 它解决什么问题

AI Agent 做 A 股分析，卡在三件事上：**数据散、口径乱、结论不可验证**。

| 问题 | StockPulse 的做法 |
|---|---|
| 数据散在数据源、交易所、财经网站、宏观库 | 统一入库（PostgreSQL 主库 + SQLite 降级），一套 schema、一套查询 |
| 不知道数据是哪天的、全不全 | 每个响应带 `meta`：`data_date` / `data_source` / `completeness`，按表探测真实最新日期 |
| 分析结论不可复现 | 诊股/信号/纪律全部输出**置信度**与**因子归因**，支持回测与证伪 |

---

## 架构

```
┌─ REST API (FastAPI :8000) ──────────────────────────────┐
│  /sp-api/v2/*          70 个标准化端点（统一响应 + 血缘 meta）│
│  /sp-api/v2/agent.json Agent 集成协议（能力自描述）          │
│  /sp-api/system/health 9 库健康监控（PG/SQLite 分库明细）    │
│  /api/v1/*             v1 兼容端点                        │
│  /docs                 OpenAPI 交互文档                    │
├─ MCP Server (stdio / SSE) ──────────────────────────────┤
│  30 Tools — Claude Code / Cursor / Codex / 任意 MCP 客户端  │
├─ 分析引擎 ───────────────────────────────────────────────┤
│  diagnosis 深度诊股 · signal 信号与回测 · regime 大市开关     │
│  discipline 五层交易纪律 · philosophy 证伪/反身性 · portfolio │
├─ 数据层 ─────────────────────────────────────────────────┤
│  PostgreSQL 主库（行情/财务/资金/龙虎榜/股东/指数）           │
│  SQLite 降级（国内宏观 cn_* / 全球宏观 FRED + World Bank）    │
└─────────────────────────────────────────────────────────┘
```

---

## 能力矩阵

| 组 | 端点前缀 | 内容 |
|---|---|---|
| 股票与行情 | `/stocks` `/equity` | 股票列表/搜索、日/周/月线、每日指标、交易日历 |
| 财务 | `/fundamental` | 利润表/资产负债表/现金流量表/财务指标/摘要 |
| 资金流 | `/moneyflow` | 个股资金流、每日排行、全市场汇总 |
| 龙虎榜 | `/lhb` | 每日上榜明细、个股统计、日期列表 |
| 股东 | `/holders` | 十大股东、股东户数 |
| 指数与行业 | `/index` `/industry` | 指数日线/成分、行业日涨跌、行业区间表现 |
| 宏观 | `/macro` `/global_macro` | CPI/PPI/PMI/GDP/M2/LPR、FRED 序列、World Bank 指标 |
| 实时 | `/realtime` | A 股/港股/美股报价、全球指数、外汇、市场快照 |
| 组合 | `/portfolio` | 建仓/持仓/交易、NAV、绩效归因、止损位 |
| 诊股与信号 | `/diagnosis` `/signal` | 四维度深度评分、涨跌概率、量价背离、信号回测 |
| 交易纪律 | `/market/regime` `/discipline` | 大市开关（MA200/MA60）、五层风险计划 |
| 哲学层 | `/philosophy` | Popper 证伪检查、Soros 反身性阶段 |
| 筛选与研报 | `/screen` `/reports` | 多维选股、研报目录/正文/PDF |
| 客户自助 | `/self` | 订阅分层、交付记录 |
| 系统 | `/system/health` `/agent.json` | 健康检查、Agent 协议描述 |

> 以上全部挂在 `/sp-api/v2` 下，完整清单见 `/docs` 或 `GET /sp-api/v2/agent.json`。

**MCP Tools（30 个）**

```
行情   search_stocks · get_daily · get_realtime · get_fundamentals
资金   get_moneyflow · get_moneyflow_rank · get_lhb · get_macro
行业   get_industry_performance · get_industry_daily_performance · screen_stocks
分析   deep_diagnosis · quick_diagnosis · get_signal_analysis · get_probability
       get_divergence · backtest_signal · get_market_regime · get_trading_plan
哲学   get_falsification · get_reflexivity_stage
组合   get_portfolios · get_portfolio_detail · portfolio_performance
研报   get_reports · get_report
客户   get_self_status · get_self_deliveries
告警   check_alerts · get_alert_config
```

---

## 快速开始

### 1. 环境

- Python 3.10+
- PostgreSQL 14+（推荐；没有 PG 时降级到 SQLite，功能有裁剪）

### 2. 安装

```bash
git clone https://github.com/Allan1900/stockpulse.git
cd stockpulse
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[api,mcp]"                          # 面板另加 dashboard
```

### 3. 配置

```bash
cp configs/config.yaml.example config.yaml
```

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `TUSHARE_TOKEN` | Tushare Pro Token（拉取行情/财务） | 空 |
| `SP_DATA_DIR` | 数据目录（SQLite 库、导出文件） | `~/ashare_data` |
| `SP_DASHBOARD_DIR` | 面板目录 | 仓库内 `dashboard/` |
| `SP_ENGINE_DIR` | 分析引擎目录 | `<dashboard>/engine` |
| `PGHOST` `PGDATABASE` `PGUSER` | PostgreSQL 连接 | `localhost` / `ashare` / 当前用户 |

PostgreSQL 首次建库：

```bash
createdb ashare
psql -d ashare -c "CREATE SCHEMA IF NOT EXISTS ashare;"
```

### 4. 拉数据

```bash
ashare update all --start 20150101     # 全量（Tushare，初次较慢）
ashare status                          # 各库行数与最新日期
```

> 仓库**不含任何行情数据**。数据需用你自己的 Tushare Pro 账号拉取，或把已有数据按 `ashare.db.schema` 建表导入。

### 5. 起服务

```bash
stockpulse-server                      # REST API :8000 → /docs
stockpulse-mcp                         # MCP stdio
stockpulse-mcp --sse --port 8002       # MCP over SSE
ashare dashboard                       # Streamlit 面板 :8501（需 [dashboard]）
```

---

## API 示例

```bash
# 个股日线（带血缘 meta：data_date / data_source / completeness）
curl "http://localhost:8000/sp-api/v2/equity/daily?ts_code=002714.SZ&limit=3"

# 深度诊股：四维度评分 + 置信度 + 证伪/反身性
curl "http://localhost:8000/sp-api/v2/diagnosis/deep/002714.SZ"

# 大市开关（MA200 / MA60）
curl "http://localhost:8000/sp-api/v2/market/regime?ts_code=000001.SH"

# 交易纪律：五层风险计划（环境/标的/风险预算/退出/结论）
curl "http://localhost:8000/sp-api/v2/discipline/plan/002714.SZ?total_capital=1000000"
```

响应统一为：

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "meta": {
    "total": 1, "page": 1, "page_size": 20,
    "data_date": "20261117", "data_source": "postgresql", "completeness": 1.0
  }
}
```

---

## MCP 接入

Claude Code / Cursor / Codex 的 MCP 配置：

```json
{
  "mcpServers": {
    "stockpulse": {
      "command": "python",
      "args": ["-m", "ashare.api.v2.mcp_server"],
      "env": { "TUSHARE_TOKEN": "your_token", "PGDATABASE": "ashare" },
      "timeout": 120
    }
  }
}
```

接入后可以直接说：

- 「查一下宁德时代最近 20 个交易日，算一下 MACD 和量价背离」
- 「今天龙虎榜有哪些席位异动」
- 「牧原现在能不能买——按陈江挺的五层纪律给我一份计划」
- 「筛选 PE<15 且 ROE>20 的股票，按行业分组」

---

## 分析引擎

| 引擎 | 端点 | 输出 |
|---|---|---|
| 深度诊股 | `/diagnosis/deep/{code}` | 财务/资金/技术/宏观四维评分 + 综合分 + 置信度 + 证伪否决 + 反身性阶段 |
| 信号 | `/signal/analysis` `/probability` `/divergence` `/backtest` | 均线/MACD/RSI/KDJ/BOLL 信号、涨跌概率（因子归因）、量价背离、历史胜率回测 |
| 大市开关 | `/market/regime` | 指数 MA200/MA60 → 可操作 / 观望 / 震荡 |
| 交易纪律 | `/discipline/plan/{code}` | 五层检查：环境 → 标的 → 风险预算（单笔≤2%、单票≤20%）→ 退出 → 结论 |
| 哲学层 | `/philosophy/*` | Popper 证伪清单、Soros 反身性阶段 |

所有引擎输出**判断**而非投资建议；每条带置信度，数据覆盖不足时置信度自动降级。

---

## 项目结构

```
src/ashare/
  api/        FastAPI v1 + v2（20 个路由模块）、静态 PWA、MCP Server
  db/         schema / loader / query / status（数据入库与查询）
  dashboard/  Streamlit 启动器
  config.py   配置（YAML + 环境变量）
  paths.py    路径解析（SP_DATA_DIR / SP_DASHBOARD_DIR）
dashboard/    Streamlit 面板（18 页）+ engine/ 分析引擎（指标/回测/因子/宏观/告警/研报/每日更新）
src/stockpulse/  0.x 时代的 SDK/CLI（保留兼容）
docs/         文档
```

---

## 💖 支持项目

如果 StockPulse 对你有帮助，欢迎支持：

[![爱发电](https://img.shields.io/badge/爱发电-赞助项目-blue?style=flat-square)](https://afdian.com/a/Allan1900)

---

## ⚖️ 数据说明 & 合规声明

- 数据来自**公开接口**（Tushare Pro 等），不含任何个人隐私数据或非公开信息；使用时需遵守数据源的服务条款。
- 本项目是**分析工具**，不构成投资建议。所有评分、概率、计划均为模型输出，请自行判断并承担风险。
- 不做投资顾问资质相关的任何声称；如需对外提供服务，请自行确认当地监管要求。

## 📜 许可证

MIT
