# StockPulse · 市场脉搏

给 AI Agent 一个可以直接调用的 A 股市场：**REST API + MCP Server + 分析引擎 + 自托管面板**。

- [快速开始](getting-started.md) — 从源码安装、配库、拉数据、起服务
- [API 参考](api-reference.md) — 70 个 v2 端点、统一响应、血缘 meta
- [MCP 接入](mcp-integration.md) — Claude Code / Cursor / Codex 配置与 30 个工具
- [Agent 示例](agent-examples.md) — 自然语言 → 工具调用 → 结构化回答

## 30 秒了解

```bash
git clone https://github.com/Allan1900/stockpulse.git && cd stockpulse
pip install -e ".[api,mcp]"
export TUSHARE_TOKEN=your_token && ashare update all --start 20150101
stockpulse-server     # http://localhost:8000/docs
stockpulse-mcp        # MCP stdio，给 Claude Code 用
```

## 三个设计原则

1. **每个数字都能溯源**：响应 `meta` 带 `data_date` / `data_source` / `completeness`，按表探测而不是拿全库最新日期糊弄。
2. **判断带置信度**：诊股、概率、交易计划都输出置信度与因子归因，数据缺失时自动降级，不假装确定。
3. **可证伪**：`/philosophy/falsification` 给出证伪条件，`/signal/backtest` 让规则可样本外检验。

## 版本

- **v2.0**（2026-11）：平台化——70 端点 / 30 MCP 工具 / 五大引擎 / PG+SQLite 双后端
- v1.0（2026-07）：Agent SDK/CLI 形态，保留在 `src/stockpulse/`

> 数据来自公开接口，需自备 Tushare Pro Token；仓库不含行情数据。本项目是分析工具，不构成投资建议。
