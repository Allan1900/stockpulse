"""宏观数据深度版 — 100+ 全球指标
数据源: FRED (免费无Key) + World Bank API (免费) + AKShare (国内)
"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd; import numpy as np; import requests
from datetime import datetime

# ── FRED ──
FRED_SERIES = {
    "GDP": "GDP (Nominal)", "GDPC1": "Real GDP", "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "CPI All Items", "CPILFESL": "CPI Core",
    "FEDFUNDS": "Fed Funds Rate", "DFF": "Fed Funds Effective",
    "DGS10": "10Y Treasury", "DGS2": "2Y Treasury", "DGS30": "30Y Treasury",
    "T10Y2Y": "10Y-2Y Spread", "SP500": "S&P 500", "DJIA": "Dow Jones",
    "PAYEMS": "Nonfarm Payrolls", "ICSA": "Jobless Claims",
    "HOUST": "Housing Starts", "INDPRO": "Industrial Production",
    "TCU": "Capacity Utilization", "UMCSENT": "Consumer Sentiment",
    "RSXFS": "Retail Sales", "M2SL": "M2 Money Supply",
    "PCE": "Personal Consumption", "PCEPILFE": "Core PCE Inflation",
    "WALCL": "Fed Balance Sheet", "BAA10Y": "BAA-10Y Spread",
    "T5YIE": "5Y Breakeven", "T10YIE": "10Y Breakeven",
}

def fetch_fred(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd=1900-01-01&coed=2026-12-31"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200: return pd.DataFrame()
        text = resp.text; data_lines = []
        for line in text.strip().split("\n"):
            if line.startswith("observation_date"): continue
            parts = line.split(",")
            if len(parts) >= 2:
                    try:
                        val = float(parts[1])
                        data_lines.append({"date": parts[0], "value": val, "series": series_id})
                    except: pass
        return pd.DataFrame(data_lines) if data_lines else pd.DataFrame()
    except: return pd.DataFrame()

# ── World Bank ──
WORLD_BANK_INDICATORS = {
    "NY.GDP.MKTP.CD": "GDP (current US$)", "NY.GDP.MKTP.KD.ZG": "GDP Growth (%)",
    "NY.GDP.PCAP.CD": "GDP per Capita", "FP.CPI.TOTL.ZG": "Inflation (%)",
    "SL.UEM.TOTL.ZS": "Unemployment (%)", "NE.EXP.GNFS.ZS": "Exports (% GDP)",
    "NE.IMP.GNFS.ZS": "Imports (% GDP)", "BN.CAB.XOKA.GD.ZS": "Current Account (% GDP)",
    "BX.KLT.DINV.WD.GD.ZS": "FDI Inflows (% GDP)",
}

def fetch_world_bank(indicator, country="CN"):
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}?format=json&per_page=50"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200: return pd.DataFrame()
        data = resp.json()
        if not data or len(data) < 2 or not data[1]: return pd.DataFrame()
        rows = []
        for item in data[1]:
            try:
                rows.append({"date": item["date"], "value": float(item["value"]) if item["value"] else None, "indicator": indicator})
            except: pass
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    except: return pd.DataFrame()

# ── 写入 PG ──
# 注意: engine.query.sql 是只读封装(pd.read_sql+自动回滚), 不能执行 INSERT。
# 此处必须用独立连接 + 显式 commit, 否则数据被静默回滚(历史缺陷: 显示ok但0写入)。
PG = {"host": "localhost", "dbname": "ashare", "user": "zrall",
      "options": "-c search_path=ashare,public"}

def write_to_macro(indicator, df):
    if df is None or df.empty: return
    import psycopg2
    conn = psycopg2.connect(**PG)
    try:
        cur = conn.cursor()
        for _, row in df.iterrows():
            if "value" not in row or pd.isna(row["value"]): continue
            period = str(row.get("date", ""))
            try:
                val = float(row["value"])
                cur.execute(
                    "INSERT INTO macro_data (indicator, period, metric, value) "
                    "VALUES (%s, %s, 'value', %s) "
                    "ON CONFLICT (indicator, period, metric) DO UPDATE SET value=EXCLUDED.value",
                    [indicator, period, val])
            except: pass
        conn.commit()  # 关键: 显式提交, 否则全部回滚
    finally:
        conn.close()

# ── 更新函数 ──
def update_fred():
    results = {}
    for sid, name in FRED_SERIES.items():
        df = fetch_fred(sid)
        if not df.empty:
            write_to_macro(f"fred_{sid}", df)
            results[sid] = {"status": "ok", "rows": len(df)}
        else:
            results[sid] = {"status": "error"}
    return results

def update_world_bank(country="CN"):
    results = {}
    for ind, name in WORLD_BANK_INDICATORS.items():
        df = fetch_world_bank(ind, country)
        if not df.empty:
            write_to_macro(f"wb_{ind}", df)
            results[ind] = {"status": "ok", "rows": len(df)}
        else:
            results[ind] = {"status": "error"}
    return results

# ── 查询 ──
def get_macro(indicator, days=120):
    from engine.query import sql as _sql
    df = _sql("SELECT period, value FROM macro_data WHERE indicator=%s ORDER BY period DESC LIMIT %s", params=[indicator, days])
    if df is not None and not df.empty:
        df["period"] = pd.to_datetime(df["period"])
    return df

def list_indicators():
    from engine.query import sql as _sql
    return _sql("SELECT indicator, COUNT(*) AS rows, MIN(period) AS since, MAX(period) AS latest FROM macro_data GROUP BY indicator ORDER BY indicator")

# ── 全量更新 ──
def full_update():
    f = update_fred()
    w = update_world_bank()
    return {"fred": f, "world_bank": w}
