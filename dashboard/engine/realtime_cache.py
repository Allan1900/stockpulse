"""
实时行情缓存层 — 避免盘中高频刷新重复请求外部API

缓存策略:
  - 全市场快照: 缓存 30 秒 (腾讯 ~6s 获取, 避免每秒刷新)
  - 个股实时: 缓存 10 秒 (新浪毫秒级, 非瓶颈, 但防极端循环)
  - 个股分时: 缓存 120 秒 (日内分时数据不变)
  - 港股实时: 缓存 15 秒

用法:
    from engine.realtime_cache import cached_snapshot, cached_quote, cached_minutes
    snap = cached_snapshot()           # 30s 内复用
    q    = cached_quote("300750.SZ")   # 10s 内复用
"""
import os
import json
import time
from datetime import datetime, timedelta
import pandas as pd
import threading

# ── 缓存目录 ────────────────────────────────────────
CACHE_DIR = "/tmp/stockpulse_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

# ── 内存锁 (多线程安全) ─────────────────────────────
_lock = threading.Lock()

# ── 缓存写入/读取 ───────────────────────────────────

def _cache_path(key: str) -> str:
    """缓存文件路径, key 如 'snapshot', 'quote_300750.SZ'"""
    safe = key.replace(".", "_").replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe}.json")


def _read_cache(key: str, max_age: int) -> dict | None:
    """
    读取缓存, max_age 秒内有效
    返回: dict (含 data 字段) 或 None
    """
    path = _cache_path(key)
    try:
        with _lock:
            if not os.path.exists(path):
                return None
            mtime = os.path.getmtime(path)
            age = time.time() - mtime
            if age > max_age:
                return None
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        return None


def _write_cache(key: str, data):
    """写入缓存 (JSON 序列化)"""
    path = _cache_path(key)
    try:
        with _lock:
            with open(path, "w") as f:
                json.dump({
                    "data": data,
                    "cached_at": datetime.now().strftime("%H:%M:%S"),
                    "expires_in": "see max_age",
                }, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _df_to_json(df: pd.DataFrame) -> list:
    """DataFrame → JSON 可序列化 list of dict"""
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")


def _json_to_df(records: list) -> pd.DataFrame:
    """JSON list → DataFrame"""
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)


# ── 公开缓存接口 ────────────────────────────────────

def cached_snapshot(max_age: int = 30):
    """
    全市场快照缓存 (默认 30s)
    首次调用或过期 → 真实获取 → 自动缓存
    """
    key = "market_snapshot"

    cached = _read_cache(key, max_age)
    if cached is not None:
        df = _json_to_df(cached.get("records", []))
        if not df.empty:
            return df

    # 缓存过期 → 真实获取
    from engine.realtime import get_market_snapshot
    df = get_market_snapshot()

    if df is not None and not df.empty and "error" not in df.columns:
        records = _df_to_json(df)
        _write_cache(key, {"records": records, "count": len(df)})

    return df


def cached_quote(ts_code: str, max_age: int = 10):
    """
    个股实时行情缓存 (默认 10s)
    首次调用或过期 → 新浪直连 → 自动缓存
    """
    key = f"quote_{ts_code}"

    cached = _read_cache(key, max_age)
    if cached is not None:
        data = cached.get("quote")
        if data and "error" not in data:
            data["source"] = data.get("source", "cache")
            data["_cached"] = True
            return data

    # 缓存过期 → 新浪直连
    from engine.realtime import get_realtime_quote
    result = get_realtime_quote(ts_code)

    if "error" not in result:
        _write_cache(key, {"quote": result})

    return result


def cached_minutes(ts_code: str, period: str = "1", max_age: int = 120):
    """
    个股分时数据缓存 (默认 120s — 日内分时不变)
    """
    key = f"minutes_{ts_code}_{period}"

    cached = _read_cache(key, max_age)
    if cached is not None:
        df = _json_to_df(cached.get("records", []))
        if not df.empty:
            return df

    # 缓存过期 → 腾讯接口
    from engine.realtime import get_intraday_minutes
    df = get_intraday_minutes(ts_code, period)

    if df is not None and not df.empty and "error" not in df.columns:
        records = _df_to_json(df)
        _write_cache(key, {"records": records, "count": len(df)})

    return df


def cached_hk_quote(ts_code: str, max_age: int = 15):
    """
    港股实时行情缓存 (默认 15s)
    """
    key = f"hk_quote_{ts_code}"

    cached = _read_cache(key, max_age)
    if cached is not None:
        data = cached.get("quote")
        if data and "error" not in data:
            data["source"] = "cache"
            return data

    from engine.realtime import get_hk_realtime_quote
    result = get_hk_realtime_quote(ts_code)

    if "error" not in result:
        _write_cache(key, {"quote": result})

    return result


def cached_hk_snapshot(max_age: int = 30):
    """港股全市场快照缓存 (30s)"""
    key = "hk_snapshot"

    cached = _read_cache(key, max_age)
    if cached is not None:
        df = _json_to_df(cached.get("records", []))
        if not df.empty:
            return df

    from engine.realtime import get_hk_market_snapshot
    df = get_hk_market_snapshot()

    if df is not None and not df.empty and "error" not in df.columns:
        records = _df_to_json(df)
        _write_cache(key, {"records": records, "count": len(df)})

    return df


def clear_cache(key_prefix: str = None):
    """
    清除缓存
    key_prefix=None → 全部清空
    key_prefix='quote_' → 清空行情缓存
    """
    import glob
    with _lock:
        if key_prefix:
            pattern = os.path.join(CACHE_DIR, f"{key_prefix}*.json")
        else:
            pattern = os.path.join(CACHE_DIR, "*.json")
        for f in glob.glob(pattern):
            os.remove(f)


def cache_stats() -> dict:
    """缓存统计"""
    import glob
    files = glob.glob(os.path.join(CACHE_DIR, "*.json"))
    total_size = sum(os.path.getsize(f) for f in files)
    ages = []
    for f in files:
        age = time.time() - os.path.getmtime(f)
        ages.append(age)
    avg_age = sum(ages) / len(ages) if ages else 0
    return {
        "files": len(files),
        "total_size_kb": round(total_size / 1024, 1),
        "avg_age_sec": round(avg_age, 1),
        "oldest_sec": round(max(ages), 1) if ages else 0,
    }