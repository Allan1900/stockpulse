"""
StockPulse 行业分析路由 — 行业涨跌排行/成分股

市场脉搏的"板块节拍"：行业轮动、板块强弱。
"""

from fastapi import APIRouter, Query
from typing import Optional
import time

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["行业分析 — 板块节拍"])

# 行业表现 TTL 缓存：全历史累计聚合开销大（840万行），结果日级变化 → 600s 缓存
_PERF_CACHE: dict = {"key": None, "ts": 0.0, "data": None}
_PERF_TTL = 600


@router.get("/performance", summary="行业涨跌排行")
async def get_industry_performance(
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    top_n: int = Query(15, ge=5, le=50, description="返回行业数"),
):
    """行业区间涨跌排行（全历史累计聚合 + 600s TTL 缓存）"""
    start = (start_date or "").replace("-", "")
    end = (end_date or "").replace("-", "")
    cache_key = f"{start}|{end}"

    now = time.time()
    if _PERF_CACHE["key"] == cache_key and now - _PERF_CACHE["ts"] < _PERF_TTL:
        ind_perf = _PERF_CACHE["data"]
        return sp_success(data={
            "start_date": start or "全部",
            "end_date": end or "最新",
            "top_n": top_n,
            "cached": True,
            "records": ind_perf.head(top_n).to_dict(orient="records"),
        })

    # 从 stock_basic 获取行业列表
    stocks = SpDataService.query_raw(
        "stock_basic",
        "SELECT ts_code, name, industry FROM stock_basic WHERE industry IS NOT NULL AND industry != ''",
    )
    if stocks.empty:
        return sp_success(data=[])

    # 获取所有股票的区间首末收盘价
    df = SpDataService.query_raw(
        "daily",
        f"SELECT ts_code, trade_date, close FROM daily "
        f"WHERE trade_date >= COALESCE(NULLIF('{start}', ''), (SELECT MIN(trade_date) FROM daily)) "
        f"AND trade_date <= COALESCE(NULLIF('{end}', ''), (SELECT MAX(trade_date) FROM daily)) "
        f"ORDER BY ts_code, trade_date",
    )

    if df.empty:
        return sp_error(SpError.NOT_FOUND, "无数据")

    # 计算每只股票的区间涨跌幅
    first_close = df.groupby("ts_code").first()["close"]
    last_close = df.groupby("ts_code").last()["close"]
    returns = ((last_close / first_close) - 1) * 100

    ind_map = dict(zip(stocks["ts_code"], stocks["industry"]))
    name_map = dict(zip(stocks["ts_code"], stocks["name"]))

    results = []
    for code, ret in returns.items():
        ind = ind_map.get(code)
        if ind:
            results.append({
                "ts_code": code,
                "name": name_map.get(code, ""),
                "industry": ind,
                "return": round(float(ret), 2),
            })

    # 按行业聚合
    import pandas as pd
    result_df = pd.DataFrame(results)
    ind_perf = result_df.groupby("industry")["return"].agg(
        ["median", "mean", "count"]
    ).sort_values("median", ascending=False).reset_index()

    # 写入缓存（默认区间缓存 600s：结果日级变化）
    if not start and not end:
        _PERF_CACHE["key"] = cache_key
        _PERF_CACHE["ts"] = now
        _PERF_CACHE["data"] = ind_perf

    return sp_success(data={
        "start_date": start or "全部",
        "end_date": end or "最新",
        "top_n": top_n,
        "records": ind_perf.head(top_n).to_dict(orient="records"),
    })


# 行业单日聚合缓存：当日数据日级变化，结果开盘后稳定 → 60s 缓存
_DAILY_CACHE: dict = {"key": None, "ts": 0.0, "data": None}
_DAILY_TTL = 60


def _industry_daily_agg(trade_date: Optional[str] = None, days: Optional[int] = None):
    """行业单日/区间聚合核心（sync，供 REST 路由与 MCP 工具复用）。

    修复 2026-10-31 SQLite 归档后旧 daily_sector_performance.py 断链问题：
    数据源直接走 PG（daily JOIN stock_basic），支持：
      - trade_date=20261030 → 单日涨跌中位数/均值/最高/最低
      - days=5              → 近 5 交易日首末收盘累计涨幅
    返回 (agg, label, mode)；无数据时 agg=None。
    """
    cache_key = f"{trade_date}|{days}"
    now = time.time()
    if _DAILY_CACHE["key"] == cache_key and now - _DAILY_CACHE["ts"] < _DAILY_TTL:
        return _DAILY_CACHE["data"], cache_key, "daily" if days is None else "range"

    if days is not None:
        # ── 区间模式：近 N 交易日首末收盘涨幅（按行业聚合） ──
        dates = SpDataService.query_raw(
            "daily",
            "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT ?",
            params=[days + 1],
        )
        if dates.empty or len(dates) < 2:
            return None, "可用交易日不足", "range"
        dates_l = dates["trade_date"].astype(str).tolist()
        start_d, end_d = dates_l[-1], dates_l[0]
        df = SpDataService.query_raw(
            "daily",
            "SELECT sb.industry, (b.close - a.close) / a.close * 100 AS ret "
            "FROM daily a JOIN daily b ON a.ts_code = b.ts_code "
            "JOIN stock_basic sb ON a.ts_code = sb.ts_code "
            "WHERE a.trade_date = ? AND b.trade_date = ? AND a.close > 0 "
            "AND b.close IS NOT NULL AND b.close > 0 "
            "AND sb.industry IS NOT NULL AND sb.industry != ''",
            params=[start_d, end_d],
        )
        label = f"{start_d} → {end_d}（近{days}个交易日）"
        mode = "range"
    else:
        # ── 单日模式：当日 pct_chg 按行业聚合 ──
        if not trade_date:
            dates = SpDataService.query_raw(
                "daily",
                "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT 1",
            )
            if dates.empty:
                return None, "无交易日数据", "daily"
            d0 = str(dates.iloc[0]["trade_date"])
            trade_date = d0.replace("-", "") if "-" in d0 else d0
        df = SpDataService.query_raw(
            "daily",
            "SELECT sb.industry, d.pct_chg "
            "FROM daily d JOIN stock_basic sb ON d.ts_code = sb.ts_code "
            "WHERE d.trade_date = ? AND d.pct_chg IS NOT NULL "
            "AND sb.industry IS NOT NULL AND sb.industry != ''",
            params=[trade_date],
        )
        label = trade_date
        mode = "daily"

    if df.empty:
        return None, f"{label} 无数据（非交易日或数据未更新）", mode

    import pandas as pd
    pct_col = "pct_chg" if mode == "daily" else "ret"
    agg = df.groupby("industry")[pct_col].agg(
        median=lambda s: round(float(s.median()), 2),
        mean=lambda s: round(float(s.mean()), 2),
        count="count",
        max=lambda s: round(float(s.max()), 2),
        min=lambda s: round(float(s.min()), 2),
    ).sort_values("median", ascending=False).reset_index()

    if mode == "daily":
        _DAILY_CACHE["key"] = cache_key
        _DAILY_CACHE["ts"] = now
        _DAILY_CACHE["data"] = agg

    return agg, label, mode


@router.get("/daily", summary="行业单日/近N日涨跌排行（PG直查，替代旧SQLite脚本）")
async def get_industry_daily(
    trade_date: Optional[str] = Query(None, description="交易日 YYYYMMDD（默认最新交易日）"),
    days: Optional[int] = Query(None, ge=2, le=250, description="近 N 个交易日区间累计涨跌幅（与 trade_date 互斥）"),
    top_n: int = Query(15, ge=5, le=50, description="返回行业数"),
):
    """行业当日涨跌 或 近 N 交易日累计涨跌（按中位数排行）"""
    agg, label, mode = _industry_daily_agg(trade_date, days)
    if agg is None:
        return sp_error(SpError.NOT_FOUND, label)
    return sp_success(data={
        "trade_date": label,
        "mode": mode,
        "top_n": top_n,
        "records": agg.head(top_n).to_dict(orient="records"),
    })


@router.get("/constituents/{industry_name}", summary="行业成分股")
async def get_industry_constituents(
    industry_name: str,
    sort_by: str = Query("ts_code", description="排序字段"),
):
    """获取某行业的全部成分股"""
    df = SpDataService.query_raw(
        "stock_basic",
        f"SELECT ts_code, symbol, name, market, list_date "
        f"FROM stock_basic WHERE industry=? ORDER BY {sort_by}",
        params=[industry_name],
    )
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"未找到行业: {industry_name}")

    return sp_success(data={
        "industry": industry_name,
        "stocks": df.to_dict(orient="records"),
        "total": len(df),
    })