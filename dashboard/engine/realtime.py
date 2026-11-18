"""实时行情引擎 — 混合架构"""
import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import datetime, time
import requests as _req
import re

TRADING_START = time(9, 30)
TRADING_END = time(15, 0)
def is_trading_time(dt=None):
    dt = dt or datetime.now()
    if dt.weekday() >= 5: return False
    t = dt.time()
    return TRADING_START <= t < TRADING_END

SINA_HEADERS = {"Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def _tscode_to_sina(ts_code):
    code = ts_code.upper(); base = code.replace(".SZ","").replace(".SH","").strip()
    if code.endswith(".SZ"): return "sz" + base.lower()
    if code.endswith(".SH"): return "sh" + base.lower()
    return ("sh" if base.startswith(("6","9")) else "sz") + base.lower()

def _parse_sina(text, min_fields=8):
    m = re.search(r'"([^"]+)"', text)
    if not m: return {"error": "无法解析"}
    fields = m.group(1).split(",")
    if len(fields) < min_fields: return {"error": f"字段不足({len(fields)})"}
    return fields

def _fld(fields, i, d=0.0):
    try: return float(fields[i]) if fields[i].strip() else d
    except: return d

# ── A股实时 ──
def get_realtime_quote(ts_code):
    symbol = _tscode_to_sina(ts_code)
    try:
        resp = _req.get(f"https://hq.sinajs.cn/list={symbol}", headers=SINA_HEADERS, timeout=8)
        resp.encoding = "gbk"; text = resp.text.strip()
    except Exception as e:
        return {"error": f"网络失败: {e}", "source": "sina"}
    f = _parse_sina(text, 8)
    if "error" in f: return {**f, "source": "sina"}
    price = _fld(f,3); yest = _fld(f,2)
    pct = ((price-yest)/yest*100) if yest else 0
    return {"ts_code":ts_code, "name":f[0], "open":round(_fld(f,1),2),
        "yest_close":round(yest,2), "price":round(price,2),
        "high":round(_fld(f,4),2), "low":round(_fld(f,5),2),
        "volume":int(_fld(f,8,0)), "amount":round(_fld(f,9,0),2),
        "pct_chg":round(pct,2), "change":round(price-yest,2),
        "datetime":f"{f[30] if len(f)>30 else ''} {f[31] if len(f)>31 else ''}".strip(),
        "source":"sina_realtime"}

# ── A股全市场快照 ──
def get_market_snapshot():
    import akshare as ak
    try:
        df = ak.stock_zh_a_spot_tx()
        if df is not None and not df.empty:
            df["ts_code"] = df["code"].apply(lambda x: x[2:]+".SH" if x.startswith("sh") else x[2:]+".SZ")
        return df
    except:
        try: return ak.stock_zh_a_spot()
        except: return pd.DataFrame({"error":["快照失败"]})

# ── A股分时 ──
def get_intraday_minutes(ts_code, period="1"):
    import akshare as ak
    s = ts_code.replace(".SZ","sz").replace(".SH","sh").lower()
    try: return ak.stock_zh_a_minute(symbol=s, period=period, adjust="")
    except Exception as e: return pd.DataFrame({"error":[f"分时失败:{e}"]})

# ── 港股实时 ──
def get_hk_realtime_quote(ts_code):
    base = ts_code.upper().replace(".HK","").strip(); symbol = "hk"+base
    try:
        resp = _req.get(f"https://hq.sinajs.cn/list={symbol}", headers=SINA_HEADERS, timeout=8)
        resp.encoding = "gbk"; text = resp.text.strip()
    except Exception as e:
        return {"error": f"港股网络失败:{e}", "source": "hk"}
    f = _parse_sina(text, 6)
    if "error" in f: return {**f, "source": "hk"}
    return {"ts_code":ts_code, "name":f[1], "open":round(_fld(f,2),2),
        "yest_close":round(_fld(f,3),2), "price":round(_fld(f,6),2),
        "high":round(_fld(f,4),2), "low":round(_fld(f,5),2),
        "volume":int(_fld(f,9,0)), "amount":round(_fld(f,11,0),2),
        "pct_chg":round(_fld(f,8),2), "change":round(_fld(f,7),2),
        "datetime":f"{f[17] if len(f)>17 else ''} {f[18] if len(f)>18 else ''}".strip(),
        "source":"hk_realtime"}

# ── 港股全市场 ──
def get_hk_market_snapshot():
    import akshare as ak
    try:
        df = ak.stock_hk_spot()
        if df is not None and not df.empty:
            df["ts_code"] = df["代码"].apply(lambda x: str(x).zfill(5)+".HK")
        return df
    except Exception as e:
        return pd.DataFrame({"error":[f"港股快照失败:{e}"]})

# ── 美股实时 ──
def get_us_realtime_quote(symbol):
    try:
        resp = _req.get(f"https://hq.sinajs.cn/list=gb_{symbol.lower()}", headers=SINA_HEADERS, timeout=8)
        resp.encoding = "gbk"; text = resp.text.strip()
    except Exception as e:
        return {"error": f"美股网络失败:{e}", "source": "us"}
    f = _parse_sina(text, 20)
    if "error" in f: return {**f, "source": "us"}
    return {"symbol":symbol, "name":f[0], "price":_fld(f,1),
        "pct_chg":_fld(f,2), "change":_fld(f,4), "open":_fld(f,5),
        "high":_fld(f,6), "low":_fld(f,7),
        "pre_close":_fld(f,21), "yest_close":_fld(f,26),
        "volume":int(_fld(f,12,0)),
        "datetime":f[3] if len(f)>3 else "",
        "source":"us_realtime"}

# ── 美股日线 ──
def get_us_daily(symbol, days=100):
    import akshare as ak
    try:
        df = ak.stock_us_daily(symbol=symbol, adjust="")
        if df is not None and not df.empty:
            df = df.sort_values("date", ascending=False).head(days)
            df["symbol"] = symbol
        return df
    except Exception as e:
        return pd.DataFrame({"error":[f"美股日线失败:{e}"]})

# ── 港股日线 ──
def get_hk_daily(ts_code, days=200, adjust="qfq"):
    import akshare as ak
    sym = ts_code.upper().replace(".HK","").strip()
    try:
        df = ak.stock_hk_daily(symbol=sym, adjust=adjust)
        if df is not None and not df.empty:
            df = df.sort_values("date", ascending=False).head(days)
        return df
    except Exception as e:
        return pd.DataFrame({"error":[f"港股日线失败:{e}"]})

# ── 外汇实时 ──
def get_forex_realtime(pair="usdcny"):
    try:
        resp = _req.get(f"https://hq.sinajs.cn/list=fx_s{pair.lower()}", headers=SINA_HEADERS, timeout=8)
        resp.encoding = "gbk"; text = resp.text.strip()
    except Exception as e:
        return {"error": f"汇率失败:{e}"}
    f = _parse_sina(text, 5)
    if "error" in f: return f
    return {"pair":pair.upper(), "price":_fld(f,1),
        "high":_fld(f,3), "low":_fld(f,7),
        "time":f[0] if len(f)>0 else "",
        "source":"forex"}

# ── 全球指数 ──
def get_global_index_snapshot():
    import akshare as ak
    try:
        df = ak.stock_hk_index_spot_sina()
        if df is not None and not df.empty:
            df.columns = [c.replace(" ","") for c in df.columns]
        return df
    except Exception as e:
        return pd.DataFrame({"error":[f"全球指数失败:{e}"]})

# ── PG盘后 ──
def get_pg_quote(ts_code):
    from engine.query import sql_one
    row = sql_one(None,
        "SELECT trade_date, close, pct_chg, high, low, vol, amount, open, pre_close "
        "FROM daily WHERE ts_code=%s ORDER BY trade_date DESC LIMIT 1", [ts_code])
    if not row: return {"error": f"PG无数据:{ts_code}", "source":"pg"}
    nr = sql_one(None, "SELECT name FROM stock_basic WHERE ts_code=%s", [ts_code])
    return {"ts_code":ts_code, "name":nr["name"] if nr else "", "trade_date":row["trade_date"],
        "price":float(row["close"]), "pct_chg":float(row["pct_chg"]),
        "high":float(row["high"]), "low":float(row["low"]),
        "volume":int(row["vol"]) if row["vol"] else 0,
        "amount":float(row["amount"]) if row["amount"] else 0,
        "open":float(row["open"]) if row["open"] else 0,
        "yest_close":float(row["pre_close"]) if row["pre_close"] else 0, "source":"pg"}

# ── 混合路由 ──
def hybrid_quote(ts_code, force_pg=False):
    if not force_pg and is_trading_time():
        result = get_realtime_quote(ts_code)
        if "error" not in result: return result
        fb = get_pg_quote(ts_code)
        fb["fallback_reason"] = result.get("error"); return fb
    return get_pg_quote(ts_code)