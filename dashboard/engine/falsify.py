"""
P4-④-A: Popper 证伪引擎

核心理念: 每个信号必须先通过证伪测试。
不是问"有什么证据支持"，而是问"有什么证据能否定它"。
只有未被证伪的假设才是暂时可接受的。
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

PG_URI = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG_URI)

def q(sql, params=None):
    return pd.read_sql(sql, engine.raw_connection(), params=params)

# ── BUY 证伪 ────────────────────────────────────
def falsify_buy(ts_code, date):
    score = 0.0; reasons = []
    try:
        d = q("SELECT b.pe_ttm, b.industry FROM daily_basic b WHERE b.trade_date=%s AND b.ts_code=%s AND b.pe_ttm>0", [date, ts_code])
        if not d.empty:
            pe = float(d.iloc[0]["pe_ttm"]); ind = d.iloc[0]["industry"]
            if ind:
                m = q("SELECT percentile_cont(0.5) WITHIN GROUP(ORDER BY pe_ttm) AS m FROM daily_basic WHERE trade_date=%s AND industry=%s AND pe_ttm>0", [date, ind])
                if not m.empty and m.iloc[0]["m"] and float(m.iloc[0]["m"]) > 0:
                    med = float(m.iloc[0]["m"])
                    if pe > med * 1.5: score -= 0.30; reasons.append(f"[F1] PE({pe:.0f}) > 行业中位数x1.5({med:.0f}) [-0.30]")
    except: pass
    try:
        d = q("SELECT yoy_profit FROM fina_indicator WHERE ts_code=%s AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=%s)", [ts_code, ts_code])
        if not d.empty and d.iloc[0]["yoy_profit"] is not None:
            yoy = float(d.iloc[0]["yoy_profit"])
            if yoy < 0: score -= 0.35; reasons.append(f"[F2] 净利润同比 {yoy:.1f}% (下滑) [-0.35]")
    except: pass
    try:
        d = q("SELECT (close/lag(close,60)OVER(ORDER BY trade_date)-1)*100 AS m FROM daily WHERE ts_code=%s AND trade_date<=%s ORDER BY trade_date DESC LIMIT 1", [ts_code, date])
        if not d.empty and d.iloc[0]["m"] is not None:
            m = float(d.iloc[0]["m"])
            if m > 50: score -= 0.20; reasons.append(f"[F3] 近3月涨幅 {m:.0f}% (已price in) [-0.20]")
            elif m > 30: score -= 0.10; reasons.append(f"[F3] 近3月涨幅 {m:.0f}% (偏高) [-0.10]")
    except: pass
    return score, reasons

def falsify_sell(ts_code, date):
    score = 0.0; reasons = []
    try:
        d = q("SELECT b.pb, f.roe FROM daily_basic b LEFT JOIN fina_indicator f ON b.ts_code=f.ts_code AND f.end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=b.ts_code) WHERE b.trade_date=%s AND b.ts_code=%s AND b.pb>0", [date, ts_code])
        if not d.empty:
            pb = float(d.iloc[0]["pb"]); roe = float(d.iloc[0]["roe"]) if d.iloc[0]["roe"] is not None else 0
            if pb < 1 and roe > 10: score += 0.30; reasons.append(f"[S1] PB({pb:.2f})<1&ROE({roe:.1f}%)>10% (破净优质) [+0.30]")
    except: pass
    try:
        d = q("SELECT (close/lag(close,20)OVER(ORDER BY trade_date)-1)*100 AS m FROM daily WHERE ts_code=%s AND trade_date<=%s ORDER BY trade_date DESC LIMIT 1", [ts_code, date])
        if not d.empty and d.iloc[0]["m"] is not None:
            m = float(d.iloc[0]["m"])
            if m < -20: score += 0.25; reasons.append(f"[S2] 近1月跌幅 {abs(m):.0f}% (超跌) [+0.25]")
    except: pass
    try:
        d = q("SELECT yoy_revenue FROM fina_indicator WHERE ts_code=%s AND end_date=(SELECT MAX(end_date) FROM fina_indicator WHERE ts_code=%s)", [ts_code, ts_code])
        if not d.empty and d.iloc[0]["yoy_revenue"] is not None:
            rev = float(d.iloc[0]["yoy_revenue"])
            if rev > 20: score += 0.30; reasons.append(f"[S3] 营收同比 {rev:.1f}% (高增长) [+0.30]")
    except: pass
    return score, reasons

def apply_falsification(signals_df, date):
    if signals_df.empty: return signals_df
    df = signals_df.copy()
    fscores, fdetails, nsigs, nconfs = [], [], [], []
    for _, row in df.iterrows():
        sig = row.get("signal",""); conf = row.get("confidence","MEDIUM")
        if sig == "BUY": sc, rs = falsify_buy(row["ts_code"], date)
        elif sig == "SELL": sc, rs = falsify_sell(row["ts_code"], date)
        else: sc, rs = 0.0, []
        fscores.append(round(sc,2)); fdetails.append("; ".join(rs) if rs else "无证伪触发")
        if sc < -0.5: nsigs.append("WATCH"); nconfs.append("LOW(FALSIFIED)")
        elif sc < -0.3: nsigs.append(sig); nconfs.append({"HIGH":"MEDIUM","MEDIUM":"LOW","LOW":"LOW"}.get(conf,"LOW")+"(DISPUTED)")
        elif sc > 0.5: nsigs.append(sig); nconfs.append({"LOW":"MEDIUM","MEDIUM":"HIGH","HIGH":"HIGH"}.get(conf,"HIGH")+"(CONFIRMED)")
        elif sc > 0.3: nsigs.append(sig); nconfs.append({"LOW":"MEDIUM","MEDIUM":"HIGH","HIGH":"HIGH"}.get(conf,"HIGH")+"(CORROBORATED)")
        else: nsigs.append(sig); nconfs.append(conf)
    df["falsify_score"] = fscores; df["falsify_detail"] = fdetails
    df["signal"] = nsigs; df["confidence"] = nconfs
    return df

def falsification_summary(signals_df):
    if signals_df.empty: return "无信号"
    t = len(signals_df)
    fal = sum(1 for x in signals_df["falsify_score"] if x < -0.5)
    dis = sum(1 for x in signals_df["falsify_score"] if -0.5 <= x < -0.3)
    con = sum(1 for x in signals_df["falsify_score"] if x > 0.5)
    cor = sum(1 for x in signals_df["falsify_score"] if 0.3 < x <= 0.5)
    neu = t - fal - dis - con - cor
    return f"证伪统计: 共{t}条 | ❌证伪{fal} | ⚠️质疑{dis} | ✅确认{con} | 📎支持{cor} | ⏸️中立{neu}"

if __name__ == "__main__":
    date = "20260723"
    print("Popper 证伪引擎 v1.0\n")
    for code, name in [("300750.SZ","宁德时代"),("600519.SH","贵州茅台"),("000858.SZ","五粮液")]:
        sc, rs = falsify_buy(code, date)
        print(f"  BUY证伪 {name}: score={sc:.2f}")
        for r in rs: print(f"    {r}")
        sc, rs = falsify_sell(code, date)
        print(f"  SELL证伪 {name}: score={sc:.2f}")
        for r in rs: print(f"    {r}")
        print()
