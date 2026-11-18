"""表结构定义 — 所有数据库的建表语句和字段映射"""

# ============================================================
# Master DB (ashare_master.db)
# ============================================================
CREATE_STOCK_BASIC = """
CREATE TABLE IF NOT EXISTS stock_basic (
    ts_code TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    area TEXT,
    industry TEXT,
    fullname TEXT,
    enname TEXT,
    cnspell TEXT,
    market TEXT,
    exchange TEXT,
    curr_type TEXT,
    list_status TEXT,
    list_date TEXT,
    delist_date TEXT,
    is_hs TEXT
)
"""

CREATE_TRADE_CAL = """
CREATE TABLE IF NOT EXISTS trade_cal (
    exchange TEXT,
    cal_date TEXT,
    is_open INTEGER,
    pretrade_date TEXT,
    PRIMARY KEY (exchange, cal_date)
)
"""

CREATE_INDEX_BASIC = """
CREATE TABLE IF NOT EXISTS index_basic (
    ts_code TEXT PRIMARY KEY,
    name TEXT,
    fullname TEXT,
    market TEXT,
    index_type TEXT,
    publisher TEXT,
    index_style TEXT,
    category TEXT,
    base_date TEXT,
    base_point REAL,
    list_date TEXT,
    weight_rule TEXT,
    desc TEXT,
    exp_date TEXT
)
"""

CREATE_INDUSTRY_CLASSIFY = """
CREATE TABLE IF NOT EXISTS industry_classify (
    index_code TEXT,
    index_name TEXT,
    level INTEGER,
    industry_code TEXT,
    industry_name TEXT,
    PRIMARY KEY (index_code, industry_code)
)
"""

CREATE_STOCK_DELISTED = """
CREATE TABLE IF NOT EXISTS stock_delisted (
    ts_code TEXT PRIMARY KEY,
    name TEXT,
    delist_date TEXT
)
"""

# ============================================================
# Daily DB (ashare_daily.db)
# ============================================================
CREATE_DAILY = """
CREATE TABLE IF NOT EXISTS daily (
    ts_code TEXT,
    trade_date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    pre_close REAL,
    change REAL,
    pct_chg REAL,
    vol REAL,
    amount REAL,
    PRIMARY KEY (ts_code, trade_date)
)
"""

CREATE_DAILY_BASIC = """
CREATE TABLE IF NOT EXISTS daily_basic (
    ts_code TEXT,
    trade_date TEXT,
    close REAL,
    turnover_rate REAL,
    turnover_rate_f REAL,
    volume_ratio REAL,
    pe REAL,
    pe_ttm REAL,
    pb REAL,
    total_mv REAL,
    circ_mv REAL,
    total_share REAL,
    circ_share REAL,
    free_share REAL,
    ps REAL,
    ps_ttm REAL,
    dv_ratio REAL,
    dv_ttm REAL,
    float_share REAL,
    PRIMARY KEY (ts_code, trade_date)
)
"""

# ============================================================
# Financial DB (ashare_financial.db)
# ============================================================
CREATE_FINA_INDICATOR = """
CREATE TABLE IF NOT EXISTS fina_indicator (
    ts_code TEXT,
    ann_date TEXT,
    end_date TEXT,
    eps REAL,
    dt_eps REAL,
    total_revenue_ps REAL,
    revenue_ps REAL,
    capital_reserve_ps REAL,
    surplus_reserve_ps REAL,
    undistributed_ps REAL,
    extra_item REAL,
    profit_dedt REAL,
    gross_margin REAL,
    current_ratio REAL,
    quick_ratio REAL,
    cash_ratio REAL,
    ar_turn REAL,
    inv_turn REAL,
    assets_turn REAL,
    current_assets_turn REAL,
    fixed_assets_turn REAL,
    debt_to_assets REAL,
    assets_to_equity REAL,
    equity_to_debt REAL,
    equity_to_interest REAL,
    debt_to_ebitda REAL,
    ebitda_to_interest REAL,
    roe REAL,
    roe_waa REAL,
    roe_dt REAL,
    roa REAL,
    roa_dp REAL,
    profit_to_gr REAL,
    opprofit_to_gr REAL,
    op_to_ebt REAL,
    roic REAL,
    np_to_gr REAL,
    PRIMARY KEY (ts_code, end_date)
)
"""

CREATE_INCOME = """
CREATE TABLE IF NOT EXISTS income (
    ts_code TEXT,
    ann_date TEXT,
    end_date TEXT,
    report_type TEXT,
    comp_type TEXT,
    basic_eps REAL,
    diluted_eps REAL,
    total_revenue REAL,
    operate_profit REAL,
    n_income REAL,
    n_income_attr_p REAL,
    PRIMARY KEY (ts_code, end_date, report_type)
)
"""

CREATE_BALANCESHEET = """
CREATE TABLE IF NOT EXISTS balancesheet (
    ts_code TEXT,
    ann_date TEXT,
    end_date TEXT,
    report_type TEXT,
    comp_type TEXT,
    total_assets REAL,
    total_liab REAL,
    total_equity REAL,
    minority_interest REAL,
    equity_attr_p REAL,
    accounts_receiv REAL,
    accounts_pay REAL,
    inventory REAL,
    fixed_assets REAL,
    intan_assets REAL,
    cash_equivalents REAL,
    current_assets REAL,
    current_liab REAL,
    non_current_assets REAL,
    non_current_liab REAL,
    PRIMARY KEY (ts_code, end_date, report_type)
)
"""

CREATE_CASHFLOW = """
CREATE TABLE IF NOT EXISTS cashflow (
    ts_code TEXT,
    ann_date TEXT,
    end_date TEXT,
    report_type TEXT,
    comp_type TEXT,
    n_income REAL,
    cash_receipts_sg REAL,
    cash_paid_for_purchases REAL,
    cash_paid_for_employee REAL,
    net_cashflow_operate REAL,
    net_cashflow_invest REAL,
    net_cashflow_finance REAL,
    free_cashflow REAL,
    net_incr_cash_equiv REAL,
    PRIMARY KEY (ts_code, end_date, report_type)
)
"""

# ============================================================
# Period DB (ashare_period.db) — aggregated from daily
# ============================================================
CREATE_WEEKLY = """
CREATE TABLE IF NOT EXISTS weekly (
    ts_code TEXT,
    trade_date TEXT,
    week TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    vol REAL,
    amount REAL,
    PRIMARY KEY (ts_code, week)
)
"""

CREATE_MONTHLY = """
CREATE TABLE IF NOT EXISTS monthly (
    ts_code TEXT,
    trade_date TEXT,
    month TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    vol REAL,
    amount REAL,
    PRIMARY KEY (ts_code, month)
)
"""

# ============================================================
# Moneyflow DB (ashare_moneyflow.db) — 12字段版本
# ============================================================
CREATE_MONEYFLOW = """
CREATE TABLE IF NOT EXISTS moneyflow (
    ts_code TEXT,
    trade_date TEXT,
    buy_sm_vol REAL,
    sell_sm_vol REAL,
    buy_md_vol REAL,
    sell_md_vol REAL,
    buy_lg_vol REAL,
    sell_lg_vol REAL,
    buy_elg_vol REAL,
    sell_elg_vol REAL,
    net_mf_vol REAL,
    net_mf_amount REAL,
    PRIMARY KEY (ts_code, trade_date)
)
"""

# ============================================================
# Holders DB (ashare_holders.db)
# ============================================================
CREATE_TOP10_HOLDERS = """
CREATE TABLE IF NOT EXISTS top10_holders (
    ts_code TEXT,
    ann_date TEXT,
    end_date TEXT,
    holder_name TEXT,
    hold_amount REAL,
    hold_ratio REAL,
    PRIMARY KEY (ts_code, end_date, holder_name)
)
"""

CREATE_STK_HOLDERNUMBER = """
CREATE TABLE IF NOT EXISTS stk_holdernumber (
    ts_code TEXT,
    ann_date TEXT,
    end_date TEXT,
    holder_num INTEGER,
    PRIMARY KEY (ts_code, end_date)
)
"""

# ============================================================
# LHB DB (ashare_lhb.db) — 龙虎榜
# ============================================================
CREATE_TOP_LIST = """
CREATE TABLE IF NOT EXISTS top_list (
    trade_date TEXT,
    ts_code TEXT,
    name TEXT,
    close REAL,
    pct_chg REAL,
    turnover_rate REAL,
    amount REAL,
    l_sell REAL,
    l_buy REAL,
    l_amount REAL,
    net_amount REAL,
    net_rate REAL,
    amount_rate REAL,
    float_values REAL,
    reason TEXT,
    PRIMARY KEY (trade_date, ts_code)
)
"""

# ============================================================
# Index DB (ashare_index.db)
# ============================================================
CREATE_INDEX_DAILY = """
CREATE TABLE IF NOT EXISTS index_daily (
    ts_code TEXT,
    trade_date TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    pre_close REAL,
    change REAL,
    pct_chg REAL,
    vol REAL,
    amount REAL,
    PRIMARY KEY (ts_code, trade_date)
)
"""

# ============================================================
# Global Macro DB (ashare_global_macro.db) — FRED + World Bank
# ============================================================
CREATE_FRED_SERIES = """
CREATE TABLE IF NOT EXISTS fred_series (
    series_id TEXT,
    date TEXT,
    value REAL,
    name TEXT,
    units TEXT,
    PRIMARY KEY (series_id, date)
)
"""

CREATE_WB_DATA = """
CREATE TABLE IF NOT EXISTS wb_data (
    indicator TEXT,
    country TEXT,
    date TEXT,
    value REAL,
    name TEXT,
    PRIMARY KEY (indicator, country, date)
)
"""

# ============================================================
# Meta table (all DBs)
# ============================================================
CREATE_META = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
)
"""

# ============================================================
# 映射：db_key -> [table_name, create_sql]
# ============================================================
ALL_SCHEMAS = {
    "master": [
        ("stock_basic", CREATE_STOCK_BASIC),
        ("trade_cal", CREATE_TRADE_CAL),
        ("index_basic", CREATE_INDEX_BASIC),
        ("industry_classify", CREATE_INDUSTRY_CLASSIFY),
        ("stock_delisted", CREATE_STOCK_DELISTED),
    ],
    "daily": [
        ("daily", CREATE_DAILY),
        ("daily_basic", CREATE_DAILY_BASIC),
    ],
    "financial": [
        ("fina_indicator", CREATE_FINA_INDICATOR),
        ("income", CREATE_INCOME),
        ("balancesheet", CREATE_BALANCESHEET),
        ("cashflow", CREATE_CASHFLOW),
    ],
    "period": [
        ("weekly", CREATE_WEEKLY),
        ("monthly", CREATE_MONTHLY),
    ],
    "moneyflow": [
        ("moneyflow", CREATE_MONEYFLOW),
    ],
    "holders": [
        ("top10_holders", CREATE_TOP10_HOLDERS),
        ("stk_holdernumber", CREATE_STK_HOLDERNUMBER),
    ],
    "lhb": [
        ("top_list", CREATE_TOP_LIST),
    ],
    "index": [
        ("index_daily", CREATE_INDEX_DAILY),
    ],
    "global_macro": [
        ("fred_series", CREATE_FRED_SERIES),
        ("wb_data", CREATE_WB_DATA),
    ],
}


def get_schema(db_key: str, table_name: str) -> str:
    """获取指定表的建表 SQL"""
    tables = ALL_SCHEMAS.get(db_key, [])
    for tname, sql in tables:
        if tname == table_name:
            return sql
    raise ValueError(f"Unknown table: {db_key}.{table_name}")


FIELD_ALIAS = {
    "close":      ("daily", "daily", "close"),
    "open":       ("daily", "daily", "open"),
    "high":       ("daily", "daily", "high"),
    "low":        ("daily", "daily", "low"),
    "vol":        ("daily", "daily", "vol"),
    "amount":     ("daily", "daily", "amount"),
    "pct_chg":    ("daily", "daily", "pct_chg"),
    "pe":         ("daily", "daily_basic", "pe"),
    "pe_ttm":     ("daily", "daily_basic", "pe_ttm"),
    "pb":         ("daily", "daily_basic", "pb"),
    "turnover":   ("daily", "daily_basic", "turnover_rate"),
    "total_mv":   ("daily", "daily_basic", "total_mv"),
    "circ_mv":    ("daily", "daily_basic", "circ_mv"),
    "roe":        ("financial", "fina_indicator", "roe"),
    "roe_waa":    ("financial", "fina_indicator", "roe_waa"),
    "gross_margin": ("financial", "fina_indicator", "gross_margin"),
    "eps":        ("financial", "fina_indicator", "eps"),
    "revenue":    ("financial", "income", "total_revenue"),
    "n_income":   ("financial", "income", "n_income"),
    "net_mf":     ("moneyflow", "moneyflow", "net_mf_amount"),
    "net_mf_vol": ("moneyflow", "moneyflow", "net_mf_vol"),
    "name":       ("master", "stock_basic", "name"),
    "industry":   ("master", "stock_basic", "industry"),
}