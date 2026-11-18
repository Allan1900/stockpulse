# 快速开始

## 1. 环境

- Python 3.10+
- PostgreSQL 14+（推荐）。没有 PG 时自动降级到 SQLite，宏观以外的部分能力会裁剪。

## 2. 安装（从源码）

```bash
git clone https://github.com/Allan1900/stockpulse.git
cd stockpulse
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[api,mcp]"                         # 面板另加 dashboard
```

> 没有发布到 PyPI，请勿使用 `pip install stockpulse`。

## 3. 配置

```bash
cp configs/config.yaml.example config.yaml
```

| 变量 | 说明 | 默认 |
|---|---|---|
| `TUSHARE_TOKEN` | Tushare Pro Token | 空 |
| `SP_DATA_DIR` | 数据目录（SQLite、导出） | `~/ashare_data` |
| `SP_DASHBOARD_DIR` | 面板目录 | 仓库 `dashboard/` |
| `SP_ENGINE_DIR` | 引擎目录 | `<dashboard>/engine` |
| `PGHOST`/`PGDATABASE`/`PGUSER` | PG 连接 | `localhost`/`ashare`/当前用户 |

```bash
createdb ashare
psql -d ashare -c "CREATE SCHEMA IF NOT EXISTS ashare;"
```

## 4. 拉数据

```bash
ashare update all --start 20150101
ashare status
```

初次全量较慢（取决于 Tushare 积分与限频）；之后增量：

```bash
ashare update daily          # 日线
ashare update financial      # 财务
ashare update moneyflow      # 资金流
```

## 5. 起服务

```bash
stockpulse-server                 # API :8000
stockpulse-server --port 8080     # 换端口（等价于 run_server(port=)）
stockpulse-mcp                    # MCP stdio
stockpulse-mcp --sse --port 8002  # MCP SSE
ashare dashboard                  # 面板 :8501
```

## 6. 自检

```bash
curl http://localhost:8000/sp-api/system/health
curl "http://localhost:8000/sp-api/v2/equity/daily?ts_code=002714.SZ&limit=1"
curl "http://localhost:8000/sp-api/v2/market/regime?ts_code=000001.SH"
```

三条都能返回 `"code": 0` 且 `meta.data_date` 是最新交易日，说明链路通了。

## 常见问题

- **`/health` 404**：健康端点只有 `/sp-api/system/health`。
- **PG 连接不上**：确认 `createdb ashare` 已执行、`PGUSER` 有权限；程序不会自动建库。
- **数据全是空**：`ashare status` 看行数；行情数据必须自己拉，仓库不带。
- **面板起不来**：`pip install -e ".[dashboard]"`，并且 `SP_DASHBOARD_DIR` 指向仓库 `dashboard/`。
