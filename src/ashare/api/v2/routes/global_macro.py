"""StockPulse 全球宏观数据路由 — FRED + World Bank

市场脉搏的"全球节拍"：国际宏观经济数据。
"""
from typing import Optional

from fastapi import APIRouter, Query

from ..data_service import SpDataService
from ..response import sp_success, sp_error, SpError

router = APIRouter(tags=["全球宏观 — 国际节拍"])

FRED_SERIES_INFO = {
    "GDPC1": "Real GDP (Billions Chained 2017 $)",
    "UNRATE": "Unemployment Rate (%)",
    "CPIAUCSL": "CPI All Items (Index 1982-1984=100)",
    "CPILFESL": "CPI Core (less Food & Energy)",
    "FEDFUNDS": "Fed Funds Rate (%)",
    "DFF": "Fed Funds Effective Rate (%)",
    "DGS10": "10-Year Treasury Yield (%)",
    "DGS2": "2-Year Treasury Yield (%)",
    "DGS30": "30-Year Treasury Yield (%)",
    "T10Y2Y": "10Y-2Y Treasury Spread (%)",
    "T5YIE": "5-Year Breakeven Inflation Rate (%)",
    "T10YIE": "10-Year Breakeven Inflation Rate (%)",
    "BAA10Y": "BAA Corp Bond - 10Y Treasury Spread (%)",
    "PAYEMS": "Nonfarm Payrolls (Thousands)",
    "ICSA": "Initial Jobless Claims (Thousands)",
    "HOUST": "Housing Starts (Thousands)",
    "INDPRO": "Industrial Production (Index 2017=100)",
    "TCU": "Capacity Utilization (%)",
    "UMCSENT": "Consumer Sentiment (Index 1966Q1=100)",
    "RSXFS": "Retail & Food Services Sales (Millions $)",
    "M2SL": "M2 Money Supply (Billions $)",
    "PCE": "Personal Consumption Expenditures (Billions $)",
    "PCEPILFE": "Core PCE Price Index (Index 2017=100)",
    "WALCL": "Fed Total Assets (Billions $)",
    "SP500": "S&P 500 Index",
    "DJIA": "Dow Jones Industrial Average",
    "NIKKEI225": "Nikkei 225 (Japan)",
}


@router.get("/fred/list", summary="FRED 可用指标列表")
async def list_fred_series():
    """列出所有可查询的 FRED 指标"""
    return sp_success(data=[
        {"series_id": k, "name": v} for k, v in FRED_SERIES_INFO.items()
    ])


@router.get("/fred/{series_id}", summary="FRED 经济指标查询")
async def get_fred_series(
    series_id: str,
    start_date: Optional[str] = Query(None, description="开始日期 YYYYMMDD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    limit: int = Query(100, ge=1, le=5000),
):
    """查询 FRED 经济指标时间序列"""
    sid = series_id.upper()
    name = FRED_SERIES_INFO.get(sid, sid)

    df = SpDataService.query_raw(
        "fred_series",
        'SELECT * FROM fred_series WHERE series_id=? ORDER BY date DESC LIMIT ?',
        params=[sid, limit],
    )
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"无数据: FRED {sid}")

    # 日期过滤
    if start_date:
        s = start_date.replace("-", "")
        df = df[df["date"].astype(str) >= s]
    if end_date:
        e = end_date.replace("-", "")
        df = df[df["date"].astype(str) <= e]

    return sp_success(data={
        "source": "FRED",
        "series_id": sid,
        "name": name,
        "records": df.to_dict(orient="records") if not df.empty else [],
        "total": len(df),
    }, table="fred_series", date_col="date")


@router.get("/wb/list", summary="World Bank 可用指标列表")
async def list_wb_indicators():
    """列出所有可查询的 World Bank 指标"""
    wb_indicators = {
        "NY.GDP.MKTP.CD": "GDP (current US$)",
        "NY.GDP.MKTP.KD.ZG": "GDP Growth (annual %)",
        "NY.GDP.PCAP.CD": "GDP per Capita (current US$)",
        "NY.GDP.PCAP.PP.CD": "GDP per Capita PPP (current intl $)",
        "FP.CPI.TOTL.ZG": "Inflation Consumer Prices (annual %)",
        "SL.UEM.TOTL.ZS": "Unemployment (% total labor force)",
        "NE.EXP.GNFS.ZS": "Exports of Goods & Services (% GDP)",
        "NE.IMP.GNFS.ZS": "Imports of Goods & Services (% GDP)",
        "BN.CAB.XOKA.GD.ZS": "Current Account Balance (% GDP)",
        "BX.KLT.DINV.WD.GD.ZS": "FDI Net Inflows (% GDP)",
        "NY.GNP.PCAP.CD": "GNI per Capita (current US$)",
        "SP.POP.TOTL": "Population Total",
    }
    return sp_success(data=[
        {"indicator": k, "name": v} for k, v in wb_indicators.items()
    ])


@router.get("/wb/countries", summary="World Bank 支持的国家列表")
async def list_wb_countries():
    """列出数据库中已有数据的国家"""
    df = SpDataService.query_raw(
        "wb_data",
        "SELECT DISTINCT country FROM wb_data ORDER BY country",
    )
    countries = df["country"].tolist() if not df.empty else []
    country_names = {
        "CN": "China", "US": "United States", "JP": "Japan", "DE": "Germany",
        "GB": "United Kingdom", "FR": "France", "IN": "India", "KR": "South Korea",
        "AU": "Australia", "CA": "Canada", "BR": "Brazil", "RU": "Russia",
        "ZA": "South Africa", "CH": "Switzerland", "SG": "Singapore", "HK": "Hong Kong",
    }
    return sp_success(data=[
        {"code": c, "name": country_names.get(c, c)} for c in countries
    ])


@router.get("/wb/{indicator}", summary="World Bank 指标查询")
async def get_wb_data(
    indicator: str,
    country: Optional[str] = Query(None, description="国家代码 CN/US/JP/DE 等"),
    start_date: Optional[str] = Query(None, description="开始日期 YYYY"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY"),
    limit: int = Query(20, ge=1, le=200),
):
    """查询 World Bank 跨国经济指标"""
    ind = indicator.upper()
    df = SpDataService.query_raw(
        "wb_data",
        'SELECT * FROM wb_data WHERE indicator=? ORDER BY date DESC LIMIT ?',
        params=[ind, limit * 50],
    )
    if df.empty:
        return sp_error(SpError.NOT_FOUND, f"无数据: WB {ind}")

    if country:
        df = df[df["country"] == country.upper()]
    if start_date:
        s = start_date.replace("-", "")
        df = df[df["date"].astype(str) >= s]
    if end_date:
        e = end_date.replace("-", "")
        df = df[df["date"].astype(str) <= e]

    df = df.head(limit)
    name = df.iloc[0]["name"] if not df.empty else ""

    return sp_success(data={
        "source": "World Bank",
        "indicator": ind,
        "name": name,
        "country": country or "ALL",
        "records": df.to_dict(orient="records") if not df.empty else [],
        "total": len(df),
    }, table="wb_data", date_col="date")


@router.get("/status", summary="全球宏观数据状态")
async def get_global_macro_status():
    """查询全球宏观数据源状态"""
    fred_count = SpDataService.query_raw(
        "fred_series", "SELECT COUNT(*) AS cnt FROM fred_series"
    )
    fred_series_count = SpDataService.query_raw(
        "fred_series", "SELECT COUNT(DISTINCT series_id) AS cnt FROM fred_series"
    )
    fred_latest = SpDataService.query_raw(
        "fred_series", "SELECT MAX(date) AS latest FROM fred_series"
    )
    wb_count = SpDataService.query_raw(
        "wb_data", "SELECT COUNT(*) AS cnt FROM wb_data"
    )
    wb_indicators = SpDataService.query_raw(
        "wb_data", "SELECT COUNT(DISTINCT indicator) AS cnt FROM wb_data"
    )
    wb_countries = SpDataService.query_raw(
        "wb_data", "SELECT COUNT(DISTINCT country) AS cnt FROM wb_data"
    )
    wb_latest = SpDataService.query_raw(
        "wb_data", "SELECT MAX(date) AS latest FROM wb_data"
    )

    return sp_success(data={
        "fred": {
            "series": int(fred_series_count.iloc[0]["cnt"]) if not fred_series_count.empty else 0,
            "rows": int(fred_count.iloc[0]["cnt"]) if not fred_count.empty else 0,
            "latest": str(fred_latest.iloc[0]["latest"]) if not fred_latest.empty else None,
        },
        "world_bank": {
            "indicators": int(wb_indicators.iloc[0]["cnt"]) if not wb_indicators.empty else 0,
            "countries": int(wb_countries.iloc[0]["cnt"]) if not wb_countries.empty else 0,
            "rows": int(wb_count.iloc[0]["cnt"]) if not wb_count.empty else 0,
            "latest": str(wb_latest.iloc[0]["latest"]) if not wb_latest.empty else None,
        },
    })