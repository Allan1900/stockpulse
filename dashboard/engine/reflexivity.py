"""
P4-④-B: Soros 反身性引擎 — 七阶段繁荣/衰退识别

核心理念: 价格不是被动反映基本面，价格反作用于基本面。
价格↑→融资成本↓→企业扩产→利润改善→价格再↑→...（自强化循环）
最终发散到不可持续→崩溃。

七阶段: 潜伏期(0)→启动期(1)→加速期(2)→发散期(3)→狂欢期(4)→逆转点(5)→崩溃期(6)
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

PG_URI = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG_URI)

STAGES = [
    {"id": 0, "name": "潜伏期", "icon": "⬜", "signal": "预备"},
    {"id": 1, "name": "启动期", "icon": "🟢", "signal": "BUY"},
    {"id": 2, "name": "加速期", "icon": "🟢🟢", "signal": "BUY"},
    {"id": 3, "name": "发散期", "icon": "🟡", "signal": "减仓"},
    {"id": 4, "name": "狂欢期", "icon": "🔴", "signal": "SELL"},
    {"id": 5, "name": "逆转点", "icon": "🔴🔴", "signal": "SELL"},
    {"id": 6, "name": "崩溃期", "icon": "⛔", "signal": "回避"},
]

def q(sql, params=None):
    return pd.read_sql(sql, engine.raw_connection(), params=params)

def identify_stage(ts_code, date):
    result = {"stage": 0, "name": "数据不足", "icon": "❓", "signal": "--",
              "price_3m": "--", "profit_yoy": "--", "roe": "--",
              "divergence_index": None}
    try:
        start = str(int(date) - 300)
        df = q("SELECT close FROM daily WHERE ts_code=%s AND trade_date>=%s AND trade_date<=%s ORDER BY trade_date", [ts_code, start, date])
        if len(df) < 60: return result
        price_3m = (float(df["close"].iloc[-1]) / float(df["close"].iloc[-60]) - 1) * 100
    except: return result

    try:
        fin = q("SELECT yoy_revenue, yoy_profit, roe FROM fina_indicator WHERE ts_code=%s AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=%s)", [ts_code, ts_code])
        profit_yoy = float(fin.iloc[0]["yoy_profit"]) if not fin.empty and fin.iloc[0]["yoy_profit"] is not None else None
        roe = float(fin.iloc[0]["roe"]) if not fin.empty and fin.iloc[0]["roe"] is not None else None
    except: profit_yoy = roe = None

    result["price_3m"] = f"{price_3m:.1f}%"
    result["profit_yoy"] = f"{profit_yoy:.1f}%" if profit_yoy is not None else "N/A"
    result["roe"] = f"{roe:.1f}%" if roe is not None else "N/A"
    divergence = price_3m - (profit_yoy if profit_yoy is not None else 0)
    result["divergence_index"] = round(divergence, 1)

    price_fast_up = price_3m > 25; price_up = price_3m > 8
    price_stable = -8 <= price_3m <= 8; price_down = price_3m < -8
    price_crash = price_3m < -15; price_explosive = price_3m > 50
    profit_up = profit_yoy is not None and profit_yoy > 10
    profit_down = profit_yoy is not None and profit_yoy < -5
    profit_crash = profit_yoy is not None and profit_yoy < -20

    if price_explosive and profit_down: result.update({"stage": 4, "name": "狂欢期", "icon": "🔴", "signal": "SELL"})
    elif price_fast_up and profit_down: result.update({"stage": 3, "name": "发散期", "icon": "🟡", "signal": "减仓"})
    elif price_fast_up and profit_up: result.update({"stage": 2, "name": "加速期", "icon": "🟢🟢", "signal": "BUY"})
    elif price_up and (profit_up or profit_yoy is None): result.update({"stage": 1, "name": "启动期", "icon": "🟢", "signal": "BUY"})
    elif price_crash and profit_crash: result.update({"stage": 6, "name": "崩溃期", "icon": "⛔", "signal": "回避"})
    elif price_down and profit_down: result.update({"stage": 5, "name": "逆转点", "icon": "🔴🔴", "signal": "SELL"})
    else: result.update({"stage": 0, "name": "潜伏期", "icon": "⬜", "signal": "预备"})

    return result

def add_reflexivity(signals_df, date):
    if signals_df.empty: return signals_df
    df = signals_df.copy()
    stages = [identify_stage(row["ts_code"], date) for _, row in df.iterrows()]
    sdf = pd.DataFrame(stages)
    for c in ["stage", "name", "icon", "signal", "price_3m", "profit_yoy", "divergence_index"]:
        if c in sdf.columns: df[f"reflex_{c}"] = sdf[c].values
    return df

def reflexivity_summary(signals_df):
    if signals_df.empty: return "无信号"
    counts = signals_df["reflex_stage"].value_counts().to_dict()
    lines = ["🔄 Soros 阶段分布:"]
    for s in sorted(STAGES, key=lambda x: x["id"], reverse=True):
        cnt = counts.get(s["id"], 0)
        if cnt > 0: lines.append(f"  {s['icon']} {s['name']}: {cnt}只 → {s['signal']}")
    return "\n".join(lines)

if __name__ == "__main__":
    print("Soros 反身性引擎 v1.0\n")
    for code, name in [("300750.SZ", "宁德时代"), ("600519.SH", "贵州茅台"), ("000858.SZ", "五粮液")]:
        info = identify_stage(code, "20260723")
        print(f"  {name}({code[:6]}): {info['icon']} {info['name']:6s} 信号={info['signal']} 发散={info['divergence_index']} 3m涨幅={info['price_3m']} 利润={info['profit_yoy']}")