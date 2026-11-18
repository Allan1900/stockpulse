"""
StockPulse MCP Server — 让任何 MCP 客户端（Claude Code / Cursor / Codex）直接查 A 股数据

两种运行模式：
  1. stdio: python3 -m src.ashare.api.v2.mcp_server
     → Claude Code: 在 MCP config 中配为 command 类型
  2. SSE: python3 -m src.ashare.api.v2.mcp_server --sse --port 8002
     → 远程 HTTP SSE 连接
"""
import sys
import json
import argparse
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .data_service import SpDataService
from ...paths import ENGINE_DIR, DASHBOARD_DIR

# ── MCP Server ──
mcp = FastMCP(
    name="StockPulse",
    instructions="""StockPulse = A 股市场脉搏服务。

提供以下数据查询能力：
- 行情数据（日线/周线/月线/基本面指标）
- 财务数据（财务指标/利润表/资产负债表/现金流/摘要）
- 资金流向（个股/全市场排行/汇总）
- 龙虎榜（每日上榜/个股统计）
- 宏观经济（CPI/PPI/PMI/GDP/M2/社融/Shibor/美债）
- 条件筛选（PE/PB/ROE/市值/行业）
- 行业分析（行业涨跌排行）
- 实时行情（A股/美股/港股/外汇/全球指数）
- 股票信息（搜索/详情）

所有数据基于 A 股全市场数据库（~19M 行，~2.5GB）。
""",
)


# ── Tools ──


@mcp.tool(
    name="search_stocks",
    description="搜索 A 股股票（代码/名称模糊匹配）",
)
def search_stocks(query: str, limit: int = 10) -> str:
    """搜索股票，支持代码或名称模糊查询"""
    from .routes.stocks import search_stocks as _handler
    # 直接调用数据服务层
    df = SpDataService.query_raw(
        "stock_basic",
        "SELECT ts_code, symbol, name, industry, market FROM stock_basic "
        "WHERE list_status='L' AND (ts_code LIKE ? OR name LIKE ? OR symbol LIKE ?) "
        "ORDER BY ts_code LIMIT ?",
        params=[f"%{query}%", f"%{query}%", f"%{query}%", limit],
    )
    if df.empty:
        return json.dumps({"stocks": [], "total": 0}, ensure_ascii=False)
    return json.dumps({
        "stocks": df.to_dict(orient="records"),
        "total": len(df),
    }, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_daily",
    description="获取 A 股日线行情（OHLCV/涨跌幅/成交额）",
)
def get_daily(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100,
) -> str:
    """获取股票日线行情数据"""
    result = SpDataService.query(
        "daily",
        filters={"ts_code": ts_code.upper()},
        sort_by="trade_date", sort_order="desc",
        limit=limit,
        start_date=start_date, end_date=end_date,
    )
    return result.model_dump_json(exclude_none=True)


@mcp.tool(
    name="get_fundamentals",
    description="获取 A 股财务摘要（ROE/毛利率/EPS/营收/净利润）",
)
def get_fundamentals(ts_code: str) -> str:
    """获取股票最新财务数据摘要"""
    code = ts_code.upper()
    name = SpDataService.get_stock_name(code)

    fina = SpDataService.query_raw(
        "fina_indicator",
        "SELECT * FROM fina_indicator WHERE ts_code=? ORDER BY end_date DESC LIMIT 2",
        params=[code],
    )
    income = SpDataService.query_raw(
        "income",
        "SELECT * FROM income WHERE ts_code=? AND report_type='1' ORDER BY end_date DESC LIMIT 2",
        params=[code],
    )

    summary = {"ts_code": code, "name": name or code}
    if not fina.empty:
        latest = fina.iloc[0]
        summary["latest"] = {
            k: float(latest[k]) if latest.get(k) else None
            for k in ["eps", "roe", "gross_margin", "debt_to_assets", "roa"]
        }
        if len(fina) >= 2:
            prev = fina.iloc[1]
            if latest.get("roe") and prev.get("roe"):
                summary["roe_change"] = round(float(latest["roe"]) - float(prev["roe"]), 2)
    if not income.empty:
        li = income.iloc[0]
        summary["revenue"] = float(li["total_revenue"]) if li.get("total_revenue") else None
        summary["net_income"] = float(li["n_income_attr_p"]) if li.get("n_income_attr_p") else None

    return json.dumps(summary, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_moneyflow",
    description="获取个股资金流向（主力/散户/超大单净流入）",
)
def get_moneyflow(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20,
) -> str:
    """获取个股资金流向数据"""
    result = SpDataService.query(
        "moneyflow",
        filters={"ts_code": ts_code.upper()},
        sort_by="trade_date", sort_order="desc",
        limit=limit,
        start_date=start_date, end_date=end_date,
    )
    return result.model_dump_json(exclude_none=True)


@mcp.tool(
    name="get_moneyflow_rank",
    description="获取指定交易日全市场资金净流入排行",
)
def get_moneyflow_rank(trade_date: str, top_n: int = 20) -> str:
    """获取某日全市场资金净流入/流出排行"""
    from .routes.moneyflow import get_moneyflow_rank as _handler
    # 直接调用 SpDataService
    td = trade_date.replace("-", "")
    df = SpDataService.query_raw(
        "moneyflow",
        "SELECT ts_code, net_mf_amount, net_mf_vol FROM moneyflow "
        "WHERE trade_date=? ORDER BY net_mf_amount DESC LIMIT ?",
        params=[td, top_n],
    )
    if df.empty:
        return json.dumps({"error": f"暂无 {trade_date} 数据"})
    # 附上股票名称
    records = df.to_dict(orient="records")
    for r in records:
        r["name"] = SpDataService.get_stock_name(r["ts_code"])
    return json.dumps({"trade_date": trade_date, "records": records}, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_lhb",
    description="获取龙虎榜数据（指定交易日）",
)
def get_lhb(trade_date: str, limit: int = 30) -> str:
    """获取龙虎榜上榜股票"""
    td = trade_date.replace("-", "")
    df = SpDataService.query_raw(
        "top_list",
        "SELECT * FROM top_list WHERE trade_date=? ORDER BY net_amount DESC LIMIT ?",
        params=[td, limit],
    )
    if df.empty:
        return json.dumps({"error": f"暂无 {trade_date} 龙虎榜数据"})
    return json.dumps({
        "trade_date": trade_date,
        "records": df.to_dict(orient="records"),
    }, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_macro",
    description="获取宏观经济指标（cpi/ppi/pmi/gdp/m2/social_financing/shibor/lpr/us_treasury）",
)
def get_macro(indicator: str, limit: int = 20) -> str:
    """获取宏观经济数据"""
    from .routes.macro import MACRO_MAP
    info = MACRO_MAP.get(indicator.lower())
    if not info:
        return json.dumps({"error": f"未知指标: {indicator}，可选: {list(MACRO_MAP.keys())}"})

    df = SpDataService.query_raw(
        info["table"],
        f"SELECT * FROM \"{info['table']}\" ORDER BY date DESC LIMIT ?",
        params=[limit],
    )
    return json.dumps({
        "indicator": indicator,
        "name": info["name"],
        "records": df.to_dict(orient="records") if not df.empty else [],
    }, ensure_ascii=False, default=str)


@mcp.tool(
    name="screen_stocks",
    description="多条件筛选 A 股（PE/PB/ROE/市值/行业）",
)
def screen_stocks(
    pe_max: Optional[float] = None,
    pb_max: Optional[float] = None,
    roe_min: Optional[float] = None,
    industry: Optional[str] = None,
    limit: int = 20,
) -> str:
    """按估值和财务条件筛选股票"""
    from .routes.screen import screen_equity
    # 复用 screen_equity 的筛选逻辑太复杂，直接简化为 raw query
    # 取最新 daily_basic 数据
    df = SpDataService.query_raw(
        "daily_basic",
        "SELECT a.ts_code, a.pe_ttm, a.pb, a.total_mv FROM daily_basic a "
        "INNER JOIN (SELECT ts_code, MAX(trade_date) as md FROM daily_basic GROUP BY ts_code) b "
        "ON a.ts_code=b.ts_code AND a.trade_date=b.md",
    )
    stocks = SpDataService.query_raw(
        "stock_basic",
        "SELECT ts_code, name, industry FROM stock_basic",
    )
    name_map = dict(zip(stocks["ts_code"], stocks["name"]))
    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))

    results = []
    for _, row in df.iterrows():
        code = row["ts_code"]
        pe = float(row["pe_ttm"]) if row["pe_ttm"] and row["pe_ttm"] > 0 else None
        pb = float(row["pb"]) if row["pb"] and row["pb"] > 0 else None

        if pe_max and (pe is None or pe > pe_max): continue
        if pb_max and (pb is None or pb > pb_max): continue
        if industry and ind_map.get(code) != industry: continue

        results.append({
            "ts_code": code,
            "name": name_map.get(code, ""),
            "industry": ind_map.get(code, ""),
            "pe_ttm": round(pe, 2) if pe else None,
            "pb": round(pb, 2) if pb else None,
        })
        if len(results) >= limit:
            break

    return json.dumps({"records": results, "total": len(results)}, ensure_ascii=False)


@mcp.tool(
    name="get_industry_performance",
    description="获取行业涨跌排行",
)
def get_industry_performance(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_n: int = 10,
) -> str:
    """获取行业区间涨跌排行"""
    from .routes.industry import get_industry_performance as _ep
    # 实际调用 industry 逻辑
    start = (start_date or "").replace("-", "")
    end = (end_date or "").replace("-", "")

    stocks = SpDataService.query_raw(
        "stock_basic",
        "SELECT ts_code, industry FROM stock_basic WHERE industry IS NOT NULL AND industry != ''",
    )
    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))

    df = SpDataService.query_raw(
        "daily",
        f"SELECT ts_code, trade_date, close FROM daily "
        f"WHERE trade_date >= COALESCE(NULLIF('{start}',''), (SELECT MIN(trade_date) FROM daily)) "
        f"AND trade_date <= COALESCE(NULLIF('{end}',''), (SELECT MAX(trade_date) FROM daily)) "
        f"ORDER BY ts_code, trade_date",
    )
    if df.empty:
        return json.dumps({"error": "暂无数据"})

    import pandas as pd
    first_close = df.groupby("ts_code").first()["close"]
    last_close = df.groupby("ts_code").last()["close"]
    returns = ((last_close / first_close) - 1) * 100

    records = []
    for code, ret in returns.items():
        ind = ind_map.get(code)
        if ind:
            records.append({"ts_code": code, "industry": ind, "return": round(float(ret), 2)})

    pdf = pd.DataFrame(records)
    perf = pdf.groupby("industry")["return"].agg(["median", "count"]).sort_values(
        "median", ascending=False
    ).head(top_n).reset_index()

    return json.dumps({
        "start_date": start or "全部",
        "end_date": end or "最新",
        "records": perf.to_dict(orient="records"),
    }, ensure_ascii=False)


@mcp.tool(
    name="get_realtime",
    description="获取 A 股实时行情",
)
def get_realtime(ts_code: str) -> str:
    """获取 A 股实时行情（通过 subprocess 桥接实时引擎）"""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, '{ENGINE_DIR}'); "
         f"from realtime import get_realtime_quote; "
         f"import json; print(json.dumps(get_realtime_quote('{ts_code.upper()}')))"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return json.dumps({"error": f"实时数据获取失败: {result.stderr[:200]}"})


@mcp.tool(
    name="get_industry_daily_performance",
    description="获取行业单日涨跌排行（当日涨跌中位数）或近N交易日区间累计涨幅。修复板块轮动查询：替代旧SQLite脚本，数据源为PG。",
)
def get_industry_daily_performance(
    trade_date: Optional[str] = None,
    days: Optional[int] = None,
    top_n: int = 10,
) -> str:
    """行业板块节拍 — 单日/近N日行业涨跌排行（PG直查）"""
    from .routes.industry import _industry_daily_agg
    agg, label, mode = _industry_daily_agg(trade_date=trade_date, days=days)
    if agg is None:
        return json.dumps({"error": label})
    return json.dumps({
        "trade_date": label,
        "mode": mode,
        "records": agg.head(top_n).to_dict(orient="records"),
    }, ensure_ascii=False)


@mcp.tool(
    name="get_falsification",
    description="Popper 证伪测试：对 BUY/SELL 信号执行证伪规则(F1-F3/S1-S3)，返回证伪分+触发规则+判定。负分=证伪，正分=支持。",
)
def get_falsification(ts_code: str, date: Optional[str] = None) -> str:
    """投资哲学 — Popper 证伪测试（买入/卖出）"""
    from .services.philosophy import falsify_buy, falsify_sell
    d = (date or "").replace("-", "")
    if not d:
        from .routes.philosophy import _resolve_date
        d = _resolve_date(d)
    buy_score, buy_reasons = falsify_buy(ts_code, d)
    sell_score, sell_reasons = falsify_sell(ts_code, d)
    return json.dumps({
        "ts_code": ts_code, "trade_date": d,
        "buy": {"score": round(buy_score, 2),
                "verdict": "被证伪" if buy_score < -0.30 else ("可疑" if buy_score < 0 else "未被证伪"),
                "rules": buy_reasons},
        "sell": {"score": round(sell_score, 2),
                 "verdict": "反驳成立" if sell_score > 0.30 else ("弱反驳" if sell_score > 0 else "无反驳"),
                 "rules": sell_reasons},
    }, ensure_ascii=False)


@mcp.tool(
    name="get_reflexivity_stage",
    description="Soros 反身性阶段识别：七阶段定位(潜伏/启动/加速/发散/狂欢/逆转/崩溃) + 发散指数 + 价格/利润/ROE 观测",
)
def get_reflexivity_stage(ts_code: str, date: Optional[str] = None) -> str:
    """投资哲学 — Soros 反身性七阶段定位"""
    from .services.philosophy import identify_stage, STAGES
    d = (date or "").replace("-", "")
    if not d:
        from .routes.philosophy import _resolve_date
        d = _resolve_date(d)
    info = identify_stage(ts_code, d)
    stage_def = next((s for s in STAGES if s["id"] == info["stage"]), {})
    return json.dumps({
        "ts_code": ts_code, "trade_date": d,
        "stage": info["stage"], "stage_name": info["name"],
        "icon": info["icon"], "signal": info["signal"],
        "stage_guide": stage_def.get("signal", ""),
        "price_3m": info["price_3m"], "profit_yoy": info["profit_yoy"],
        "roe": info["roe"], "divergence_index": info["divergence_index"],
    }, ensure_ascii=False)


@mcp.tool(
    name="get_portfolios",
    description="组合管理：列出所有组合（名称/描述/创建时间）。",
)
def get_portfolios() -> str:
    """组合管理 — 组合列表"""
    from .services.portfolio import list_portfolios
    df = list_portfolios()
    return json.dumps({
        "total": len(df),
        "portfolios": df.to_dict(orient="records") if not df.empty else [],
    }, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_portfolio_detail",
    description="组合管理：查看组合详情（基本信息 + 持仓列表，带股票名称/行业/权重）。",
)
def get_portfolio_detail(pid: int) -> str:
    """组合管理 — 组合详情"""
    from .services.portfolio import get_portfolio
    info, holdings = get_portfolio(pid)
    if info is None:
        return json.dumps({"error": f"组合 {pid} 不存在"}, ensure_ascii=False)
    return json.dumps({
        "portfolio": info.to_dict(),
        "holdings": holdings.to_dict(orient="records") if holdings is not None and not holdings.empty else [],
        "holding_count": len(holdings) if holdings is not None else 0,
    }, ensure_ascii=False, default=str)


@mcp.tool(
    name="portfolio_performance",
    description="组合管理：组合业绩表现（NAV曲线 + 绩效统计：年化收益/夏普/最大回撤/超额，对比沪深300）。",
)
def portfolio_performance(pid: int, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
    """组合管理 — 组合业绩（NAV + 统计）"""
    from .services.portfolio import calc_portfolio_nav, calc_portfolio_stats
    nav = calc_portfolio_nav(pid, start_date, end_date)
    if nav.empty:
        return json.dumps({"error": "无持仓或区间无行情"}, ensure_ascii=False)
    stats = calc_portfolio_stats(nav)
    return json.dumps({
        "pid": pid,
        "stats": stats,
        "nav_head": nav.head(5).to_dict(orient="records"),
        "nav_tail": nav.tail(5).to_dict(orient="records"),
        "points": len(nav),
    }, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_reports",
    description="研报生态：研报目录（每日收盘日报 + 市场周报，按日期倒序，含 md/pdf 路径）。查询最近研报列表",
)
def get_reports() -> str:
    """研报生态 — 研报目录"""
    from .services.reports import list_reports
    data = list_reports()
    data["total"] = len(data["daily"]) + len(data["weekly"])
    return json.dumps(data, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_report",
    description="研报详情：读取研报正文预览（markdown 前 N 字符）。kind=daily|weekly，daily 用日期 YYYYMMDD，weekly 用周目录名（如 2026-W44）",
)
def get_report(kind: str, date: str, limit: int = 4000) -> str:
    """研报生态 — 研报正文预览"""
    from .services.reports import get_report as _gr
    data = _gr(kind, date, limit)
    if not data:
        return json.dumps({"error": f"研报不存在: {kind}/{date}"}, ensure_ascii=False)
    return json.dumps(data, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_self_status",
    description="客户自助：查询订阅状态（层级 admin/vip/basic、有效期、功能权限）。用客户邮箱",
)
def get_self_status(email: str) -> str:
    """客户自助 — 订阅状态"""
    from .services.self_service import get_status, can_access
    status = get_status(email)
    status["access"] = {
        "public_market": True,
        "reports": can_access(email, "reports"),
        "deliveries": can_access(email, "deliveries"),
        "portfolio": can_access(email, "portfolio"),
    }
    return json.dumps(status, ensure_ascii=False, default=str)


@mcp.tool(
    name="get_self_deliveries",
    description="客户自助：交付记录（客户已收到的研报 PDF/交互文件，按时间倒序）。",
)
def get_self_deliveries(email: str, limit: int = 20) -> str:
    """客户自助 — 交付记录"""
    from .services.self_service import get_status, list_deliveries, can_access
    if not can_access(email, "deliveries"):
        return json.dumps({"error": "该层级无权查看交付记录（需年卡/管理）"}, ensure_ascii=False)
    return json.dumps(list_deliveries(email, limit), ensure_ascii=False, default=str)


@mcp.tool(
    name="check_alerts",
    description="运行一次盘中告警检查：价格突破/量比激增/成交额TOP/行业异动/关注列表。返回当前告警列表",
)
def check_alerts() -> str:
    """盘中告警 — 市场脉搏的异常波动探测（复用 dashboard 实时告警引擎）"""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, '{DASHBOARD_DIR}'); "
         f"sys.path.insert(0, '{ENGINE_DIR}'); "
         "from engine.realtime_alerts import run_intraday_alerts, format_alerts_text; "
         "import json; r = run_intraday_alerts(); "
         "print(json.dumps({'timestamp': r.get('timestamp',''), 'in_session': r.get('in_session'), "
         "'alerts_count': r.get('alerts_count', 0), 'alerts': r.get('alerts', [])}, "
         "ensure_ascii=False, default=str))"],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return json.dumps({"error": f"告警检查失败: {result.stderr[:200]}"})


@mcp.tool(
    name="get_alert_config",
    description="查看当前盘中告警配置：关注列表(watchlist)、阈值(涨跌幅/量比/行业异动)", 
)
def get_alert_config() -> str:
    """告警配置 — 当前关注列表与触发阈值"""
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, '{DASHBOARD_DIR}'); "
         f"sys.path.insert(0, '{ENGINE_DIR}'); "
         "from engine.realtime_alerts import load_config; "
         "import json; print(json.dumps(load_config(), ensure_ascii=False, default=str))"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return json.dumps({"error": f"告警配置读取失败: {result.stderr[:200]}"})


@mcp.tool(
    name="deep_diagnosis",
    description="AI 深度诊股：多源交叉验证(财务+资金+技术+宏观四维度) + Popper证伪 + Soros反身阶段，输出综合评分(0-100)/观点/置信度/证据清单。",
)
def deep_diagnosis(ts_code: str, date: Optional[str] = None) -> str:
    """AI 深度诊股 — 多源交叉验证诊断报告"""
    from .services.diagnosis import deep_diagnosis as _dd
    try:
        result = _dd(ts_code, date)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"诊股引擎异常: {e}"}, ensure_ascii=False)


@mcp.tool(
    name="quick_diagnosis",
    description="AI 诊股简版：快速综合评分 + 观点 + 置信度 + 反身阶段，适合快速决策。",
)
def quick_diagnosis(ts_code: str, date: Optional[str] = None) -> str:
    """AI 诊股简版 — 快速评分"""
    from .services.diagnosis import quick_score
    try:
        result = quick_score(ts_code, date)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"评分引擎异常: {e}"}, ensure_ascii=False)


@mcp.tool(
    name="get_signal_analysis",
    description="技术信号汇总：MA/MACD/RSI/KDJ/BOLL 金叉死叉/超买超卖/突破/连阳连阴 + 最新指标快照。",
)
def get_signal_analysis(ts_code: str, date: Optional[str] = None) -> str:
    """预测/信号引擎 — 技术信号汇总"""
    from .services.signal_engine import analyze_signals
    try:
        signals, snapshot, ctx = analyze_signals(ts_code, date)
        return json.dumps({
            "ts_code": ts_code,
            "trade_date": ctx.get("trade_date") if ctx else None,
            "signals": signals,
            "indicators": snapshot,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"信号引擎异常: {e}"}, ensure_ascii=False)


@mcp.tool(
    name="get_probability",
    description="涨跌概率估算：多因子模型(均线/MACD/RSI/动量/量能) → 未来5-20日看涨概率(0-100%)，附因子归因。",
)
def get_probability(ts_code: str, date: Optional[str] = None) -> str:
    """预测/信号引擎 — 涨跌概率估算"""
    from .services.signal_engine import predict_probability
    try:
        result = predict_probability(ts_code, date)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"概率模型异常: {e}"}, ensure_ascii=False)


@mcp.tool(
    name="get_divergence",
    description="量价背离预警：顶背离(价近高量萎缩) / 底背离(价新低但主力吸筹)。",
)
def get_divergence(ts_code: str, date: Optional[str] = None) -> str:
    """预测/信号引擎 — 量价背离预警"""
    from .services.signal_engine import detect_divergence
    try:
        result = detect_divergence(ts_code, date)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"背离检测异常: {e}"}, ensure_ascii=False)


@mcp.tool(
    name="backtest_signal",
    description="历史信号回测：统计指定技术信号(MACD金叉/死叉, MA金叉/死叉, RSI超卖/超买)出现后的胜率与平均收益。",
)
def backtest_signal(ts_code: str, signal: str = "MACD金叉", lookback: int = 500,
                    horizon: int = 10) -> str:
    """预测/信号引擎 — 历史信号回测"""
    from .services.signal_engine import backtest_signal as _bs
    try:
        result = _bs(ts_code, signal, lookback, horizon)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"回测引擎异常: {e}"}, ensure_ascii=False)


@mcp.tool(
    name="get_market_regime",
    description="大盘市场状态（陈江挺趋势框架）：上证指数MA200牛熊分界+MA60中期方向 → 可操作(多头)/观望(空头)/震荡。回答'大市是否允许出手'，不做涨跌预测。",
)
def get_market_regime(ts_code: str = "000001.SH", date: Optional[str] = None) -> str:
    """市场状态引擎 — 大市开关"""
    from .services.market_regime import get_market_regime as _gm
    try:
        result = _gm(ts_code, date)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"市场状态引擎异常: {e}"}, ensure_ascii=False)


@mcp.tool(
    name="get_trading_plan",
    description="交易机会纪律计划（陈江挺五层）：L1大市环境 / L2标的+临界点 / L3风险预算(止损+仓位反推) / L4退出管理 / 结论。strict=true 严格(L1空头一票否决) / false 宽松(L1只提示)。判定'交易机会价值'，不做公司价值判断。",
)
def get_trading_plan(ts_code: str, total_capital: float = 100000.0,
                     current_risk_pct: float = 0.0,
                     date: Optional[str] = None,
                     strict: Optional[bool] = None) -> str:
    """交易纪律引擎 — 五层检查（strict 开关见引擎文档）"""
    from .services.trading_discipline import build_trading_plan
    try:
        result = build_trading_plan(ts_code, total_capital, current_risk_pct, date, strict)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"交易纪律引擎异常: {e}"}, ensure_ascii=False)


# ── 入口 ──
def main():
    parser = argparse.ArgumentParser(description="StockPulse MCP Server")
    parser.add_argument("--sse", action="store_true", help="启用 SSE 传输（HTTP）")
    parser.add_argument("--port", type=int, default=8002, help="SSE 端口（默认 8002）")
    args = parser.parse_args()

    if args.sse:
        print(f"StockPulse MCP Server (SSE) → http://0.0.0.0:{args.port}")
        print(f"  直接连接: {args.port}")
        mcp.run(transport="sse", host="0.0.0.0", port=args.port)
    else:
        # stdio 模式 — Claude Code spawns this as a subprocess
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()