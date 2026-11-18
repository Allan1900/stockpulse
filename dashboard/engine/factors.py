"""P3-① 多因子选股引擎

对标: Wind 多因子模型 / Bloomberg GSFC
因子体系:
  - 估值因子 (PE/PB/PS 行业分位)
  - 质量因子 (ROE/毛利率/净利率)
  - 成长因子 (营收增速/利润增速)
  - 动量因子 (1月/3月涨幅)
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from sqlalchemy import create_engine

PG_URI = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG_URI)

def q(sql, params=None):
    return pd.read_sql(sql, engine.raw_connection(), params=params)

def get_stock_basic():
    return q("SELECT ts_code, name, industry FROM stock_basic")

def factor_valuation(date):
    """估值因子: PE_ttm/PB 行业分位数 (越低分越高)"""
    df = q("SELECT ts_code, pe_ttm, pb FROM daily_basic WHERE trade_date=%s AND pe_ttm>0 AND pb>0", [date])
    if df.empty: return pd.DataFrame()
    sb = get_stock_basic()
    ind_map = dict(zip(sb["ts_code"], sb["industry"]))
    df["industry"] = df["ts_code"].map(ind_map)
    for col in ["pe_ttm", "pb"]:
        grp = df.groupby("industry")[col]
        df[f"{col}_pct"] = grp.rank(pct=True) * 100
    df["val_score"] = 100 - (df["pe_ttm_pct"] + df["pb_pct"]) / 2
    return df[["ts_code", "industry", "pe_ttm", "pb", "val_score"]]

def factor_quality(date):
    """质量因子: ROE/毛利率/净利率"""
    df = q("""SELECT ts_code, roe, gross_margin, net_margin
              FROM fina_indicator
              WHERE end_date=(SELECT MAX(end_date) FROM fina_indicator)""")
    if df.empty: return pd.DataFrame()
    sb = get_stock_basic()
    ind_map = dict(zip(sb["ts_code"], sb["industry"]))
    df["industry"] = df["ts_code"].map(ind_map)
    for col in ["roe", "gross_margin", "net_margin"]:
        if col not in df.columns: continue
        df[f"{col}_pct"] = df.groupby("industry")[col].rank(pct=True) * 100
    cols = [c for c in df.columns if c.endswith("_pct")]
    df["qual_score"] = df[cols].mean(axis=1) if cols else 50
    return df[["ts_code", "industry", "roe", "gross_margin", "net_margin", "qual_score"]]

def factor_growth(date):
    """成长因子: 营收/利润同比增速"""
    df = q("""SELECT ts_code, yoy_revenue, yoy_profit
              FROM fina_indicator
              WHERE end_date=(SELECT MAX(end_date) FROM fina_indicator)""")
    if df.empty: return pd.DataFrame()
    sb = get_stock_basic()
    ind_map = dict(zip(sb["ts_code"], sb["industry"]))
    df["industry"] = df["ts_code"].map(ind_map)
    for col in ["yoy_revenue", "yoy_profit"]:
        if col not in df.columns: continue
        df[f"{col}_pct"] = df.groupby("industry")[col].rank(pct=True) * 100
    cols = [c for c in df.columns if c.endswith("_pct")]
    df["gro_score"] = df[cols].mean(axis=1) if cols else 50
    return df[["ts_code", "industry", "yoy_revenue", "yoy_profit", "gro_score"]]

def factor_momentum(date):
    """动量因子: 近1月涨幅行业分位"""
    start = str(int(date) - 100)
    mom = q("""SELECT ts_code,
                      (close - lag(close) OVER (PARTITION BY ts_code ORDER BY trade_date))
                      / lag(close) OVER (PARTITION BY ts_code ORDER BY trade_date) * 100 AS mom_1m
               FROM daily WHERE trade_date BETWEEN %s AND %s""", [start, date])
    if mom.empty: return pd.DataFrame()
    last = mom.groupby("ts_code").last().reset_index()
    sb = get_stock_basic()
    ind_map = dict(zip(sb["ts_code"], sb["industry"]))
    last["industry"] = last["ts_code"].map(ind_map)
    last["mom_pct"] = last.groupby("industry")["mom_1m"].rank(pct=True) * 100
    last["mom_score"] = last["mom_pct"]
    return last[["ts_code", "industry", "mom_1m", "mom_score"]]

def compute(date=None):
    """综合打分"""
    if not date:
        date = q("SELECT MAX(trade_date)::text FROM daily").iloc[0,0]
    print(f"\n  P3-① 多因子选股 — {date}")
    print(f"  {'='*45}")
    print("  [1/4] 估值因子...")
    v = factor_valuation(date)
    print(f"    OK: {len(v)} 只")
    print("  [2/4] 质量因子...")
    ql = factor_quality(date)
    print(f"    OK: {len(ql)} 只")
    print("  [3/4] 成长因子...")
    g = factor_growth(date)
    print(f"    OK: {len(g)} 只")
    print("  [4/4] 动量因子...")
    m = factor_momentum(date)
    print(f"    OK: {len(m)} 只")
    print("  合成总分...")
    from functools import reduce
    dfs = [df.set_index("ts_code") for df in [v, ql, g, m] if not df.empty]
    if not dfs:
        print("  错误: 无数据"); return pd.DataFrame()
    score = pd.DataFrame(index=dfs[0].index)
    score["industry"] = dfs[0]["industry"]
    for df in dfs:
        for c in df.columns:
            if c.endswith("_score") and c not in score.columns:
                score[c] = df[c]
    score_cols = [c for c in score.columns if c.endswith("_score")]
    if score_cols:
        score["total"] = score[score_cols].mean(axis=1)
    else:
        score["total"] = 50
    score = score.dropna(subset=["total"]).sort_values("total", ascending=False)
    score["rank"] = range(1, len(score)+1)
    sb = get_stock_basic()
    nm = dict(zip(sb["ts_code"], sb["name"]))
    print(f"  OK: {len(score)} 只完成评分")
    print(f"  TOP 5:")
    for _, r in score.head(5).iterrows():
        nm2 = nm.get(r.name, r.name[:6])
        print(f"    #{r['rank']:.0f} {nm2:12s} 总分:{r['total']:.1f}")
    return score.reset_index()

if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    s = compute(date)
    if not s.empty:
        sb = get_stock_basic()
        nm = dict(zip(sb["ts_code"], sb["name"]))
        print(f"\n前30名:")
        for _, r in s.head(30).iterrows():
            nm2 = nm.get(r["ts_code"], r["ts_code"][:6])
            print(f"  {r['rank']:3.0f}. {nm2:12s}  {r['total']:5.1f}分  "
                  f"估值:{r.get('val_score',0):3.0f}  "
                  f"质量:{r.get('qual_score',0):3.0f}  "
                  f"成长:{r.get('gro_score',0):3.0f}  "
                  f"动量:{r.get('mom_score',0):3.0f}")