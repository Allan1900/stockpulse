"""P4-① AI 智能诊股引擎

整合多因子评分 + 财务指标 + 资金流 + 技术分析 + 产业链归属
输出：个股全景诊断报告（对标券商深度研报摘要）
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import datetime as dt
from sqlalchemy import create_engine

PG_URI = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG_URI)

def q(sql, params=None):
    return pd.read_sql(sql, engine, params=list(params) if params else None)

def diagnose_stock(ts_code, date=None):
    """对单只股票生成全景诊断报告"""
    if not date:
        date = q("SELECT MAX(trade_date)::text FROM daily").iloc[0,0]

    # 基本信息
    basic = q("SELECT name, industry, market, list_date FROM stock_basic WHERE ts_code=%s", [ts_code])
    if basic.empty:
        return "查无此股"
    name = basic.iloc[0]["name"]
    industry = basic.iloc[0]["industry"] or "未知"
    market = basic.iloc[0]["market"] or "未知"
    list_date = basic.iloc[0]["list_date"] or "未知"

    # 最新行情
    daily = q("SELECT close, pct_chg, vol, amount, high, low FROM daily WHERE ts_code=%s AND trade_date=%s", [ts_code, date])
    if not daily.empty:
        close = f'{daily.iloc[0]["close"]:.2f}'
        pct = f'{daily.iloc[0]["pct_chg"]:+.2f}%'
        vol_lot = f'{daily.iloc[0]["vol"]/1e4:.0f}万手'
        amount_yi = f'{daily.iloc[0]["amount"]/1e8:.2f}亿'
        hl = f'{daily.iloc[0]["low"]:.2f} ~ {daily.iloc[0]["high"]:.2f}'
    else:
        close = pct = vol_lot = amount_yi = hl = "N/A"

    # 估值
    val = q("SELECT pe_ttm, pb, ps, total_mv, circ_mv FROM daily_basic WHERE ts_code=%s AND trade_date=%s", [ts_code, date])
    if not val.empty:
        pe = f'{val.iloc[0]["pe_ttm"]:.2f}' if val.iloc[0]["pe_ttm"] and val.iloc[0]["pe_ttm"] > 0 else "亏损"
        pb = f'{val.iloc[0]["pb"]:.2f}'
        mv = f'{val.iloc[0]["total_mv"]/1e8:.0f}亿'
    else:
        pe = pb = mv = "N/A"

    # 财务指标
    fin = q("""SELECT roe, gross_margin, net_margin, yoy_revenue, yoy_profit
              FROM fina_indicator WHERE ts_code=%s
              AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=%s)""", [ts_code, ts_code])
    if not fin.empty:
        roe = f'{fin.iloc[0]["roe"]:.1f}%'
        gross_margin = f'{fin.iloc[0]["gross_margin"]:.1f}%'
        rev_yoy = f'{fin.iloc[0]["yoy_revenue"]:+.1f}%'
        profit_yoy = f'{fin.iloc[0]["yoy_profit"]:+.1f}%'
    else:
        roe = gross_margin = rev_yoy = profit_yoy = "N/A"

    # 资金流
    mf = q("SELECT net_mf_amount, buy_elg_amount FROM moneyflow WHERE ts_code=%s AND trade_date=%s", [ts_code, date])
    if not mf.empty:
        net = mf.iloc[0]["net_mf_amount"] or 0
        net_str = f'{net/1e8:.2f}亿'
        net_tag = "🟢净流入" if net > 0 else "🔴净流出" if net < 0 else "⚪持平"
    else:
        net_str = "N/A"; net_tag = ""

    # 技术信号
    tech = q("""SELECT ts_code, trade_date, close,
                      AVG(close) OVER w AS ma5,
                      AVG(close) OVER (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20
               FROM daily WHERE ts_code=%s AND trade_date>=to_char(to_date(%s,'YYYYMMDD')-30,'YYYYMMDD') AND trade_date<=%s
               WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
               ORDER BY trade_date DESC LIMIT 2""", [ts_code, date, date])
    if len(tech) >= 2:
        prev, curr = tech.iloc[1], tech.iloc[0]
        try:
            prev_gap = prev["ma5"] - prev["ma20"]
            curr_gap = curr["ma5"] - curr["ma20"]
            if prev_gap <= 0 and curr_gap > 0:
                tech_signal = "🟢 金叉 (MA5上穿MA20)"
            elif prev_gap >= 0 and curr_gap < 0:
                tech_signal = "🔴 死叉 (MA5下穿MA20)"
            else:
                tech_signal = "⚪ 均线缠绕"
        except:
            tech_signal = "—"
    else:
        tech_signal = "—"

    # 产业链归属
    from engine.industry_chain import get_chain_for_stock
    chains = get_chain_for_stock(ts_code)
    chain_str = ""
    if chains:
        chain_names = [c["chain_name"] + " → " + c["stage"] for c in chains]
        chain_str = "\n".join(f"  🏭 {cn}" for cn in chain_names)

    # 因子评分
    from engine.factors import compute_score
    score_df = compute_score(date)
    if not score_df.empty:
        row = score_df[score_df["ts_code"] == ts_code]
        if not row.empty:
            r = row.iloc[0]
            score_str = (f"  综合: {r['total']:.1f}/100\n"
                         f"  估值: {r['val_score']:.0f} | 质量: {r['qual_score']:.0f}\n"
                         f"  成长: {r['gro_score']:.0f} | 动量: {r['mom_score']:.0f}")
            zonghe = r['total']
        else:
            score_str = "未评分(可能数据不全)"; zonghe = 0
    else:
        score_str = "unavailable"; zonghe = 0

    # ── 构建诊断报告 ──────────────────────────
    lines = []
    # 头部
    lines.append(f"# {name} ({ts_code[:6]}) — AI 智能诊股报告")
    lines.append(f"")
    lines.append(f"行业: {industry} | 板块: {market} | 上市: {list_date[:4]}年 | 诊断日期: {date}")
    lines.append(f"")

    # 概览
    lines.append(f"## 📊 概览")
    lines.append(f"| 指标 | 今日值 | 指标 | 今日值 |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| 收盘价 | {close} | 涨跌幅 | {pct} |")
    lines.append(f"| 成交量 | {vol_lot} | 成交额 | {amount_yi} |")
    lines.append(f"| 日内区间 | {hl} | 市值 | {mv} |")
    lines.append(f"")

    # 估值
    lines.append(f"## 🔍 估值分析")
    lines.append(f"| 指标 | 值 | 行业分位 | 判断 |")
    lines.append(f"|---|---|---|---|")
    if pe != "亏损" and pe != "N/A":
        try:
            pe_val = float(pe)
            pe_tag = "高估" if pe_val > 50 else ("低估" if pe_val < 15 else "合理")
        except: pe_tag = "—"
    else: pe_tag = "—"
    lines.append(f"| PE_TTM | {pe} | — | {pe_tag} |")
    lines.append(f"| PB | {pb} | — | — |")
    lines.append(f"")

    # 财务
    lines.append(f"## 📈 财务状况")
    lines.append(f"| 指标 | 值 | 行业平均 | 评价 |")
    lines.append(f"|---|---|---|---|")
    lines.append(f"| ROE | {roe} | ~8% | {'优秀' if roe!='N/A' and float(roe.rstrip('%'))>15 else '良好' if roe!='N/A' and float(roe.rstrip('%'))>8 else '一般'} |")
    lines.append(f"| 毛利率 | {gross_margin} | — | — |")
    lines.append(f"| 营收增速 | {rev_yoy} | — | {'高增长' if rev_yoy!='N/A' and float(rev_yoy.rstrip('%'))>20 else '稳健' if rev_yoy!='N/A' and float(rev_yoy.rstrip('%'))>0 else '下滑'} |")

    lines.append(f"## ⭐ 多因子评分")
    lines.append(f"{score_str}")
    lines.append(f"")

    # 结论
    lines.append(f"## 💡 综合诊断")
    if zonghe >= 70:
        lines.append(f"**评级: 🟢 推荐** — 四维评分优秀，基本面扎实，估值合理或有安全边际。建议关注。")
    elif zonghe >= 55:
        lines.append(f"**评级: 🟡 关注** — 综合评分中等偏上，部分维度有亮点。可纳入观察池。")
    elif zonghe >= 40:
        lines.append(f"**评级: 🟠 观望** — 评分一般，需进一步确认改善趋势后再做决策。")
    else:
        lines.append(f"**评级: 🔴 谨慎** — 评分偏低，建议等待基本面或估值改善信号。")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"报告由 Hermes Agent P4-① AI智能诊股引擎自动生成 | {dt.now().strftime('%Y-%m-%d %H:%M')}")

    return "\n".join(lines)

def diagnose_batch(stocks, date=None):
    """批量诊断"""
    results = []
    for ts_code in stocks[:10]:
        try:
            report = diagnose_stock(ts_code, date)
            results.append({"ts_code": ts_code, "report": report})
        except Exception as e:
            results.append({"ts_code": ts_code, "report": f"错误: {e}"})
    return results