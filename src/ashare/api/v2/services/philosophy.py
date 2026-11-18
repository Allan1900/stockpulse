"""
投资哲学引擎服务 — Popper 证伪 + Soros 反身性

2026-11-01 移植：由 dashboard/engine/falsify.py + reflexivity.py 移植（保持规则
完全等价，仅改数据通道：sqlalchemy 直连 → SpDataService.query_raw，去路径依赖），
供 REST /philosophy/* 端点与 MCP 工具复用。

- Popper 证伪：falsify_buy / falsify_sell — 负分=证伪，正分=支持
  F1 PE>行业中位x1.5 / F2 净利同比下滑 / F3 近3月涨幅过高
  S1 破净优质 / S2 超跌 / S3 营收高增长
- Soros 反身：identify_stage — 七阶段 + 发散指数
"""

from ..data_service import SpDataService

# Soros 七阶段定义（与引擎一致）
STAGES = [
    {"id": 0, "name": "潜伏期", "icon": "⬜", "signal": "预备"},
    {"id": 1, "name": "启动期", "icon": "🟢", "signal": "BUY"},
    {"id": 2, "name": "加速期", "icon": "🟢🟢", "signal": "BUY"},
    {"id": 3, "name": "发散期", "icon": "🟡", "signal": "减仓"},
    {"id": 4, "name": "狂欢期", "icon": "🔴", "signal": "SELL"},
    {"id": 5, "name": "逆转点", "icon": "🔴🔴", "signal": "SELL"},
    {"id": 6, "name": "崩溃期", "icon": "⛔", "signal": "回避"},
]


def falsify_buy(ts_code: str, date: str):
    """BUY 证伪 — 问'有什么能否定买入'。返回 (score, reasons[])。"""
    score = 0.0
    reasons = []
    try:
        d = SpDataService.query_raw(
            "daily_basic",
            "SELECT pe_ttm, industry FROM daily_basic "
            "WHERE trade_date=? AND ts_code=? AND pe_ttm>0",
            [date, ts_code])
        if not d.empty:
            pe = float(d.iloc[0]["pe_ttm"])
            ind = d.iloc[0]["industry"]
            if ind:
                m = SpDataService.query_raw(
                    "daily_basic",
                    "SELECT percentile_cont(0.5) WITHIN GROUP(ORDER BY pe_ttm) AS m "
                    "FROM daily_basic WHERE trade_date=? AND industry=? AND pe_ttm>0",
                    [date, ind])
                if not m.empty and m.iloc[0]["m"] and float(m.iloc[0]["m"]) > 0:
                    med = float(m.iloc[0]["m"])
                    if pe > med * 1.5:
                        score -= 0.30
                        reasons.append(f"[F1] PE({pe:.0f}) > 行业中位数x1.5({med:.0f}) [-0.30]")
    except Exception:
        pass
    try:
        d = SpDataService.query_raw(
            "fina_indicator",
            "SELECT yoy_profit FROM fina_indicator WHERE ts_code=? "
            "AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=?)",
            [ts_code, ts_code])
        if not d.empty and d.iloc[0]["yoy_profit"] is not None:
            yoy = float(d.iloc[0]["yoy_profit"])
            if yoy < 0:
                score -= 0.35
                reasons.append(f"[F2] 净利润同比 {yoy:.1f}% (下滑) [-0.35]")
    except Exception:
        pass
    try:
        d = SpDataService.query_raw(
            "daily",
            "SELECT (close/lag(close,60)OVER(ORDER BY trade_date)-1)*100 AS m "
            "FROM daily WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
            [ts_code, date])
        if not d.empty and d.iloc[0]["m"] is not None:
            m = float(d.iloc[0]["m"])
            if m > 50:
                score -= 0.20
                reasons.append(f"[F3] 近3月涨幅 {m:.0f}% (已price in) [-0.20]")
            elif m > 30:
                score -= 0.10
                reasons.append(f"[F3] 近3月涨幅 {m:.0f}% (偏高) [-0.10]")
    except Exception:
        pass
    return score, reasons


def falsify_sell(ts_code: str, date: str):
    """SELL 证伪 — 问'有什么能否定卖出'。返回 (score, reasons[])。"""
    score = 0.0
    reasons = []
    try:
        d = SpDataService.query_raw(
            "daily_basic",
            "SELECT b.pb, f.roe FROM daily_basic b "
            "LEFT JOIN fina_indicator f ON b.ts_code=f.ts_code "
            "AND f.end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=b.ts_code) "
            "WHERE b.trade_date=? AND b.ts_code=? AND b.pb>0",
            [date, ts_code])
        if not d.empty:
            pb = float(d.iloc[0]["pb"])
            roe = float(d.iloc[0]["roe"]) if d.iloc[0]["roe"] is not None else 0
            if pb < 1 and roe > 10:
                score += 0.30
                reasons.append(f"[S1] PB({pb:.2f})<1&ROE({roe:.1f}%)>10% (破净优质) [+0.30]")
    except Exception:
        pass
    try:
        d = SpDataService.query_raw(
            "daily",
            "SELECT (close/lag(close,20)OVER(ORDER BY trade_date)-1)*100 AS m "
            "FROM daily WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
            [ts_code, date])
        if not d.empty and d.iloc[0]["m"] is not None:
            m = float(d.iloc[0]["m"])
            if m < -20:
                score += 0.25
                reasons.append(f"[S2] 近1月跌幅 {abs(m):.0f}% (超跌) [+0.25]")
    except Exception:
        pass
    try:
        d = SpDataService.query_raw(
            "fina_indicator",
            "SELECT yoy_revenue FROM fina_indicator WHERE ts_code=? "
            "AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=?)",
            [ts_code, ts_code])
        if not d.empty and d.iloc[0]["yoy_revenue"] is not None:
            rev = float(d.iloc[0]["yoy_revenue"])
            if rev > 20:
                score += 0.30
                reasons.append(f"[S3] 营收同比 {rev:.1f}% (高增长) [+0.30]")
    except Exception:
        pass
    return score, reasons


def identify_stage(ts_code: str, date: str):
    """Soros 反身阶段识别 — 七阶段定位 + 发散指数。返回 dict。"""
    result = {"stage": 0, "name": "数据不足", "icon": "❓", "signal": "--",
              "price_3m": "--", "profit_yoy": "--", "roe": "--",
              "divergence_index": None}
    try:
        start = str(int(date) - 300)
        df = SpDataService.query_raw(
            "daily",
            "SELECT close FROM daily WHERE ts_code=? AND trade_date>=? "
            "AND trade_date<=? ORDER BY trade_date",
            [ts_code, start, date])
        if len(df) < 60:
            return result
        price_3m = (float(df["close"].iloc[-1]) / float(df["close"].iloc[-60]) - 1) * 100
    except Exception:
        return result

    try:
        fin = SpDataService.query_raw(
            "fina_indicator",
            "SELECT yoy_revenue, yoy_profit, roe FROM fina_indicator WHERE ts_code=? "
            "AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=?)",
            [ts_code, ts_code])
        profit_yoy = float(fin.iloc[0]["yoy_profit"]) if not fin.empty and fin.iloc[0]["yoy_profit"] is not None else None
        roe = float(fin.iloc[0]["roe"]) if not fin.empty and fin.iloc[0]["roe"] is not None else None
    except Exception:
        profit_yoy = roe = None

    result["price_3m"] = f"{price_3m:.1f}%"
    result["profit_yoy"] = f"{profit_yoy:.1f}%" if profit_yoy is not None else "N/A"
    result["roe"] = f"{roe:.1f}%" if roe is not None else "N/A"
    divergence = price_3m - (profit_yoy if profit_yoy is not None else 0)
    result["divergence_index"] = round(divergence, 1)

    price_fast_up = price_3m > 25
    price_up = price_3m > 8
    price_stable = -8 <= price_3m <= 8
    price_down = price_3m < -8
    price_crash = price_3m < -15
    price_explosive = price_3m > 50
    profit_up = profit_yoy is not None and profit_yoy > 10
    profit_down = profit_yoy is not None and profit_yoy < -5
    profit_crash = profit_yoy is not None and profit_yoy < -20

    if price_explosive and profit_down:
        result.update({"stage": 4, "name": "狂欢期", "icon": "🔴", "signal": "SELL"})
    elif price_fast_up and profit_down:
        result.update({"stage": 3, "name": "发散期", "icon": "🟡", "signal": "减仓"})
    elif price_fast_up and profit_up:
        result.update({"stage": 2, "name": "加速期", "icon": "🟢🟢", "signal": "BUY"})
    elif price_up and (profit_up or profit_yoy is None):
        result.update({"stage": 1, "name": "启动期", "icon": "🟢", "signal": "BUY"})
    elif price_crash and profit_crash:
        result.update({"stage": 6, "name": "崩溃期", "icon": "⛔", "signal": "回避"})
    elif price_down and profit_down:
        result.update({"stage": 5, "name": "逆转点", "icon": "🔴🔴", "signal": "SELL"})
    else:
        result.update({"stage": 0, "name": "潜伏期", "icon": "⬜", "signal": "预备"})

    return result
