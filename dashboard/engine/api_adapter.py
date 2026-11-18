"""
StockPulse API Adapter — Dashboard 数据层转换器

让所有 Streamlit 页面通过 StockPulse REST API 获取数据，
而非直连 SQLite/PG。

函数签名与原有 engine/query.py 兼容，返回 pandas DataFrame。
"""
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd
import requests

# ══════════════════════════════
# 配置
# ══════════════════════════════

API_BASE_URL = "http://localhost:8000/sp-api/v2"
REQUEST_TIMEOUT = 30
CACHE_TTL_SECONDS = 60
_API_AVAILABLE = True
_LAST_ERROR = ""
_cache: dict[str, tuple[float, pd.DataFrame]] = {}

# ══════════════════════════════
# 缓存
# ══════════════════════════════

def _cache_get(key: str) -> Optional[pd.DataFrame]:
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, df = entry
    if time.time() - ts < CACHE_TTL_SECONDS:
        return df
    _cache.pop(key, None)
    return None

def _cache_set(key: str, df: pd.DataFrame):
    _cache[key] = (time.time(), df)

def clear_cache():
    """清空全部缓存（页面切换时调用）"""
    _cache.clear()


# ══════════════════════════════
# 底层 API 调用
# ══════════════════════════════

def _check_api() -> bool:
    global _API_AVAILABLE
    try:
        health_url = API_BASE_URL.replace("/sp-api/v2", "") + "/sp-api/system/health"
        r = requests.get(health_url, timeout=5)
        _API_AVAILABLE = r.status_code == 200 and r.json().get("status") == "ok"
        return _API_AVAILABLE
    except Exception:
        _API_AVAILABLE = False
        return False

def _get(endpoint: str, params: dict = None, use_cache: bool = True) -> dict:
    """调用 StockPulse API GET 端点，返回完整响应 dict"""
    global _LAST_ERROR, _API_AVAILABLE
    if not _API_AVAILABLE:
        _check_api()
        if not _API_AVAILABLE:
            _LAST_ERROR = "StockPulse API 未运行"
            return {"error": _LAST_ERROR}
    cache_key = f"{endpoint}:{str(sorted((params or {}).items()))}" if use_cache else None
    if use_cache:
        cached = _cache_get(cache_key)
        if cached is not None:
            return {"_cached": True, "data": cached.to_dict(orient="records")}
    url = f"{API_BASE_URL}/{endpoint.lstrip('/')}"
    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            _LAST_ERROR = f"API {resp.status_code}"
            return {"error": _LAST_ERROR}
        data = resp.json()
        if data.get("code", -1) != 0:
            _LAST_ERROR = f"API err: {data.get('message', '?')}"
            return {"error": _LAST_ERROR}
        raw = data.get("data")
        if use_cache and raw is not None:
            if isinstance(raw, list):
                df = pd.DataFrame(raw) if raw else pd.DataFrame()
                _cache_set(cache_key, df)
            elif isinstance(raw, dict) and "records" in raw:
                df = pd.DataFrame(raw["records"]) if raw["records"] else pd.DataFrame()
                _cache_set(cache_key, df)
        return data
    except requests.exceptions.ConnectionError:
        _API_AVAILABLE = False
        _LAST_ERROR = f"无法连接 StockPulse API ({url})"
        return {"error": _LAST_ERROR}
    except Exception as e:
        _LAST_ERROR = f"API 异常: {str(e)}"
        return {"error": _LAST_ERROR}

def _records(endpoint: str, params: dict = None, use_cache: bool = True) -> pd.DataFrame:
    """调用 API 并返回 DataFrame（兼容 list 和 {records: [...]} 两种格式）"""
    data = _get(endpoint, params, use_cache=use_cache)
    if "error" in data:
        return pd.DataFrame()
    raw = data.get("data")
    if raw is None:
        # 可能已被缓存为 list
        if data.get("_cached"):
            raw = data.get("data")
    if isinstance(raw, list):
        return pd.DataFrame(raw) if raw else pd.DataFrame()
    if isinstance(raw, dict):
        records = raw.get("records")
        if records:
            return pd.DataFrame(records)
        return pd.DataFrame([raw]) if raw else pd.DataFrame()
    return pd.DataFrame()


# ══════════════════════════════
# 业务函数 — 兼容 engine/query.py
# ══════════════════════════════

def get_stock_list() -> pd.DataFrame:
    """获取全部 A 股列表"""
    return _records("stocks/")

def search_stocks(query: str, limit: int = 20) -> pd.DataFrame:
    """搜索股票"""
    return _records("stocks/search", {"q": query, "limit": limit})

def get_stock_names() -> dict:
    """返回 {ts_code: name} 映射"""
    df = _records("stocks/")
    if df.empty:
        return {}
    return dict(zip(df["ts_code"], df["name"]))

def get_stock_info(ts_code: str) -> dict:
    """获取单只股票详情"""
    data = _get(f"stocks/{ts_code}")
    if "error" in data:
        return {}
    raw = data.get("data")
    if isinstance(raw, list) and raw:
        return raw[0]
    if isinstance(raw, dict):
        return raw
    return {}

def get_daily(ts_code: str, start: str = None, end: str = None,
              limit: int = 250, fields: str = None) -> pd.DataFrame:
    """获取日线行情"""
    params = {"page_size": limit}
    if start: params["start_date"] = start
    if end: params["end_date"] = end
    if fields: params["fields"] = fields
    return _records(f"equity/daily/{ts_code}", params)

def get_daily_basic(ts_code: str, trade_date: str = None) -> pd.DataFrame:
    """获取每日基本面 (PE/PB/市值)"""
    if trade_date:
        return _records("equity/daily_basic", {"ts_code": ts_code, "trade_date": trade_date})
    df = _records("equity/daily_basic", {"ts_code": ts_code, "page_size": 10})
    if not df.empty and "trade_date" in df.columns:
        df = df.sort_values("trade_date", ascending=False).head(1)
    return df

def get_weekly(ts_code: str, limit: int = 100) -> pd.DataFrame:
    return _records(f"equity/weekly/{ts_code}", {"page_size": limit})

def get_monthly(ts_code: str, limit: int = 60) -> pd.DataFrame:
    return _records(f"equity/monthly/{ts_code}", {"page_size": limit})

def get_trade_dates() -> list[str]:
    data = _get("equity/trade_dates")
    if "error" in data:
        return []
    raw = data.get("data")
    if isinstance(raw, list):
        return [r.get("trade_date", "") for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        records = raw.get("records", [])
        return [r.get("trade_date", "") for r in records]
    return []

def get_financial(ts_code: str, start: str = None, end: str = None,
                  limit: int = 10) -> pd.DataFrame:
    params = {"page_size": limit}
    if start: params["start_date"] = start
    if end: params["end_date"] = end
    return _records(f"fundamental/fina_indicator/{ts_code}", params)

def get_income(ts_code: str, start: str = None, end: str = None,
               limit: int = 10) -> pd.DataFrame:
    params = {"page_size": limit}
    if start: params["start_date"] = start
    if end: params["end_date"] = end
    return _records(f"fundamental/income/{ts_code}", params)

def get_balancesheet(ts_code: str, start: str = None, end: str = None,
                     limit: int = 10) -> pd.DataFrame:
    params = {"page_size": limit}
    if start: params["start_date"] = start
    if end: params["end_date"] = end
    return _records(f"fundamental/balancesheet/{ts_code}", params)

def get_cashflow(ts_code: str, start: str = None, end: str = None,
                 limit: int = 10) -> pd.DataFrame:
    params = {"page_size": limit}
    if start: params["start_date"] = start
    if end: params["end_date"] = end
    return _records(f"fundamental/cashflow/{ts_code}", params)

def get_fundamental_summary(ts_code: str) -> dict:
    data = _get(f"fundamental/summary/{ts_code}")
    if "error" in data:
        return {}
    raw = data.get("data")
    return raw if isinstance(raw, dict) else {}

def get_moneyflow(ts_code: str, limit: int = 20) -> pd.DataFrame:
    return _records(f"moneyflow/{ts_code}", {"page_size": limit})

def get_moneyflow_rank(trade_date: str, top_n: int = 20) -> pd.DataFrame:
    return _records(f"moneyflow/rank/{trade_date}", {"top_n": top_n})

def get_moneyflow_summary(trade_date: str) -> dict:
    data = _get(f"moneyflow/market_summary/{trade_date}")
    if "error" in data:
        return {}
    return data.get("data", {})

def get_lhb(trade_date: str, limit: int = 30) -> pd.DataFrame:
    return _records(f"lhb/{trade_date}", {"page_size": limit})

def get_lhb_dates() -> list[str]:
    data = _get("lhb/dates/list")
    if "error" in data:
        return []
    raw = data.get("data", [])
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("dates", [])
    return []

def get_lhb_stats(ts_code: str) -> pd.DataFrame:
    return _records(f"lhb/stats/{ts_code}")

def get_top10_holders(ts_code: str) -> pd.DataFrame:
    return _records(f"holders/top10/{ts_code}")

def get_holder_number(ts_code: str) -> pd.DataFrame:
    return _records(f"holders/holder_number/{ts_code}")

def get_macro(indicator: str, limit: int = 20) -> pd.DataFrame:
    return _records(f"macro/{indicator}", {"limit": limit})

def get_macro_list() -> list[dict]:
    data = _get("macro/list/all")
    if "error" in data:
        return []
    return data.get("data", {}).get("indicators", [])

def get_industry_performance(start: str = None, end: str = None,
                              top_n: int = 15) -> pd.DataFrame:
    params = {"top_n": top_n}
    if start: params["start_date"] = start
    if end: params["end_date"] = end
    return _records("industry/performance", params)

def get_industry_constituents(industry_name: str) -> pd.DataFrame:
    import urllib.parse
    return _records(f"industry/constituents/{urllib.parse.quote(industry_name)}")

def get_industries() -> list[str]:
    df = get_stock_list()
    if df.empty or "industry" not in df.columns:
        return []
    return sorted(df["industry"].dropna().unique())

def screen_equity(pe_max: float = None, pb_max: float = None,
                   roe_min: float = None, industry: str = None,
                   limit: int = 50) -> pd.DataFrame:
    params = {"limit": limit}
    if pe_max: params["pe_max"] = pe_max
    if pb_max: params["pb_max"] = pb_max
    if roe_min: params["roe_min"] = roe_min
    if industry: params["industry"] = industry
    return _records("screen/equity", params)

def get_realtime_quote(ts_code: str) -> dict:
    data = _get(f"realtime/quote/{ts_code}")
    if "error" in data:
        return {}
    return data.get("data", {})

def get_market_snapshot() -> pd.DataFrame:
    return _records("realtime/market_snapshot")

def get_us_quote(symbol: str) -> dict:
    data = _get(f"realtime/us/{symbol}")
    if "error" in data:
        return {}
    return data.get("data", {})

def get_hk_quote(ts_code: str) -> dict:
    data = _get(f"realtime/hk/{ts_code}")
    if "error" in data:
        return {}
    return data.get("data", {})

def get_forex() -> pd.DataFrame:
    return _records("realtime/forex")

def get_global_indices() -> pd.DataFrame:
    return _records("realtime/global_indices")

def get_index_daily(ts_code: str, limit: int = 250) -> pd.DataFrame:
    return _records(f"index/daily/{ts_code}", {"page_size": limit})

def get_index_constituents(ts_code: str) -> pd.DataFrame:
    return _records(f"index/constituents/{ts_code}")

def get_index_list() -> pd.DataFrame:
    return _records("index/list")

def hybrid_quote(ts_code: str) -> dict:
    """智能混合查询: 交易时段→实时API, 盘后→API日线"""
    realtime = get_realtime_quote(ts_code)
    if realtime:
        return {"source": "realtime", **realtime}
    df = get_daily(ts_code, limit=1)
    if not df.empty:
        row = df.iloc[0].to_dict()
        return {"source": "daily", **row}
    return {"source": "none", "error": "无数据"}

def get_price_data(ts_code: str, days: int = 100) -> pd.DataFrame:
    """获取股价数据（close + pct_chg + vol）"""
    df = get_daily(ts_code, limit=days,
                   fields="ts_code,trade_date,open,high,low,close,pct_chg,vol,amount")
    if not df.empty and "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date")
    return df

# ══════════════════════════════
# 状态查询
# ══════════════════════════════

def get_api_status() -> dict:
    global _API_AVAILABLE, _LAST_ERROR
    _check_api()
    return {
        "available": _API_AVAILABLE,
        "base_url": API_BASE_URL,
        "last_error": _LAST_ERROR,
        "cache_size": len(_cache),
        "cache_ttl": CACHE_TTL_SECONDS,
    }

def get_db_status() -> dict:
    health_url = API_BASE_URL.replace("/sp-api/v2", "") + "/sp-api/system/health"
    data = _get(health_url)
    if "error" in data:
        return {"error": _LAST_ERROR}
    return data.get("databases", {})

# ══════════════════════════════
# 快速检测
# ══════════════════════════════

def self_check() -> list[str]:
    msgs = []
    ok = _check_api()
    msgs.append(f"[API] {'OK' if ok else 'FAIL'} StockPulse API")
    if not ok:
        msgs.append(f"      -> {_LAST_ERROR}")
        return msgs
    df = get_stock_list()
    msgs.append(f"[股票] {len(df)} stocks")
    df = get_daily("600519.SH", limit=2)
    msgs.append(f"[日线] {len(df)} rows (茅台)")
    summary = get_fundamental_summary("600519.SH")
    msgs.append(f"[财务] ROE={summary.get('latest',{}).get('roe','?')}%")
    df = get_industry_performance(top_n=5)
    msgs.append(f"[行业] {len(df)} industries")
    return msgs

if __name__ == "__main__":
    print("=" * 50)
    print("  StockPulse API Adapter")
    print("=" * 50)
    for line in self_check():
        print(f"  {line}")
    print("=" * 50)

# ══════════════════════════════════════════════════════
# 兼容别名 — 与 engine/query.py 同名函数桥接
# ══════════════════════════════════════════════════════

def query_single_stock(ts_code, fields="*", start=None, end=None):
    """兼容 query.py 的 query_single_stock（API page_size上限1000）"""
    if fields and fields != "*":
        return get_daily(ts_code, start=start, end=end, limit=1000, fields=fields)
    return get_daily(ts_code, start=start, end=end, limit=1000)

# get_single_stock is NOT the same as query_single_stock
# get_single_stock fetches ALL data (pagination)
def get_single_stock(ts_code, fields="*", start=None, end=None):
    """获取单只股票全部日线数据（自动分页）"""
    MAX_PER_PAGE = 1000
    if fields and fields != "*":
        df = get_daily(ts_code, start=start, end=end, limit=MAX_PER_PAGE, fields=fields)
    else:
        df = get_daily(ts_code, start=start, end=end, limit=MAX_PER_PAGE)
    return df

# get_stk_holdernumber(ts_code) -> pd.DataFrame
# 映射到 get_holder_number
def get_stk_holdernumber(ts_code: str):
    return get_holder_number(ts_code)

# get_stk_holdernumber(ts_code) -> pd.DataFrame
def get_stk_holdernumber(ts_code: str) -> pd.DataFrame:
    """兼容 query.py 的 get_stk_holdernumber（映射到 get_holder_number）"""
    return get_holder_number(ts_code)

def get_moneyflow_dates():
    """获取有资金流向数据的交易日列表"""
    # Fallback to trade dates since moneyflow might not have a distinct dates endpoint
    return get_trade_dates()

# get_moneyflow_by_date(trade_date) -> pd.DataFrame
def get_moneyflow_by_date(trade_date: str) -> pd.DataFrame:
    """获取指定交易日资金流向数据"""
    return get_moneyflow_rank(trade_date, top_n=1000)

# get_backend() -> str
def get_backend() -> str:
    """返回数据后端类型"""
    s = get_api_status()
    return "stockpulse-api" if s["available"] else "unavailable"

# get_backend_label() -> str
def get_backend_label() -> str:
    """返回后端显示标签"""
    s = get_api_status()
    return "✅ StockPulse API" if s["available"] else "❌ API Unavailable"

# get_pg_stats() -> dict
def get_pg_stats() -> dict:
    """返回数据库统计"""
    return get_db_status()
