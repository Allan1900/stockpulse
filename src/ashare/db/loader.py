#!/usr/bin/env python3
"""一键数据更新 — 从 Tushare API 增量拉取所有数据类别

所有函数支持断点续跑，自动跳过已有数据。
"""
import os, sys, time, sqlite3, json
from datetime import datetime, timedelta

import pandas as pd

from ..config import get_config, db_path
from .schema import ALL_SCHEMAS, CREATE_META


def _init_db(db_key):
    """确保数据库文件存在且表结构正确"""
    path = db_path(db_key)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # 创建表
    tables = ALL_SCHEMAS.get(db_key, [])
    for tname, sql in tables:
        conn.execute(sql)
    conn.execute(CREATE_META)
    conn.commit()
    return conn


def _write_meta(conn, stage, status, detail):
    """记录更新元信息"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value, updated_at) VALUES (?, ?, ?)",
        (f"{stage}_{status}", detail, now)
    )
    conn.commit()


def _get_token():
    """获取 Tushare Token"""
    cfg = get_config()
    token = cfg.tushare_token
    if token:
        return token
    # 尝试从环境变量
    token = os.environ.get("TUSHARE_TOKEN")
    if token:
        return token
    raise ValueError("TUSHARE_TOKEN 未设置")


def _tushare_pro():
    """初始化 Tushare Pro API"""
    import tushare as ts
    token = _get_token()
    pro = ts.pro_api(token)
    # 冒烟测试
    df = pro.trade_cal(exchange="SSE", start_date="20250101", end_date="20250101",
                       fields="cal_date,is_open")
    if df.empty:
        raise RuntimeError("Tushare API 连接失败或 token 无效")
    return pro


def _requests_fetch(api_name, params, fields=None):
    """使用 requests 直调 Tushare REST API (绕过 to_sql 静默失败问题)"""
    import requests
    token = _get_token()
    payload = {"api_name": api_name, "token": token, "params": params}
    if fields:
        payload["fields"] = fields
    r = requests.post("http://api.tushare.pro", json=payload, timeout=30)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"Tushare API error ({api_name}): {data.get('msg', 'unknown')}")
    return data["data"]["fields"], data["data"]["items"]


def _bulk_insert(conn, table_name, fields_list, rows):
    """批量 INSERT OR IGNORE — 自动按 DB 列过滤 API 字段"""
    if not rows:
        return 0
    # 获取 DB 实际列名
    db_cols = set(r[1] for r in conn.execute(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall())
    # 筛选只存在于 DB 的字段
    keep_indices = [i for i, f in enumerate(fields_list) if f in db_cols]
    filtered_fields = [fields_list[i] for i in keep_indices]
    filtered_rows = [[row[i] for i in keep_indices] for row in rows]
    if not filtered_fields:
        return 0
    cols = ",".join(f'"{f}"' for f in filtered_fields)
    ph = ",".join(["?"] * len(filtered_fields))
    sql = f"INSERT OR IGNORE INTO [{table_name}] ({cols}) VALUES ({ph})"
    conn.executemany(sql, filtered_rows)
    conn.commit()
    return len(filtered_rows)


# ============================================================
# 交易日历
# ============================================================
def _get_trading_days(start_date, end_date):
    """获取交易日列表"""
    import tushare as ts
    pro = ts.pro_api(_get_token())
    df = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date,
                       fields="cal_date,is_open")
    if df.empty:
        return []
    return sorted(df[df["is_open"] == 1]["cal_date"].tolist())


# ============================================================
# 各数据类别更新函数
# ============================================================

def update_daily(start_date=None, end_date=None):
    """更新日线行情 + 每日基本面指标"""
    cfg = get_config()
    if not start_date:
        start_date = cfg.default_start
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'=' * 60}")
    print(f"更新日线数据: {start_date} ~ {end_date}")
    print(f"{'=' * 60}")

    conn = _init_db("daily")

    # 获取已有交易日
    existing = set(r[0] for r in conn.execute(
        "SELECT DISTINCT trade_date FROM daily"
    ).fetchall())

    # 待拉取的交易日
    all_days = _get_trading_days(start_date, end_date)
    pending = [d for d in all_days if d not in existing]
    print(f"交易日: {len(all_days)} 天, 已有: {len(existing)} 天, 还需: {len(pending)} 天")

    if not pending:
        print("  ✓ 日线数据已完整")
        _write_meta(conn, "daily", "ok", f"complete up to {end_date}")
        conn.close()
        return

    pro = _tushare_pro()
    d_total, b_total = 0, 0
    start_time = datetime.now()
    api_delay = cfg.api_delay

    for i, day in enumerate(pending):
        try:
            # 日线
            df_d = pro.daily(trade_date=day)
            if not df_d.empty:
                df_d.to_sql("daily", conn, if_exists="append", index=False, method="multi")
                d_total += len(df_d)

            # 基本面指标
            df_b = pro.daily_basic(trade_date=day)
            if not df_b.empty:
                df_b.to_sql("daily_basic", conn, if_exists="append", index=False, method="multi")
                b_total += len(df_b)

            if (i + 1) % 50 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                print(f"  进度: {i+1}/{len(pending)} 天 ({rate:.0f} 天/分)")
                conn.commit()

            time.sleep(api_delay)

        except Exception as e:
            print(f"  ⚠ {day} 失败: {e}")
            continue

    elapsed = (datetime.now() - start_time).total_seconds()
    conn.commit()
    _write_meta(conn, "daily", "ok", f"rows_d={d_total}, rows_b={b_total}, days={len(pending)}, elapsed={elapsed:.0f}s")
    conn.close()

    rate = len(pending) / elapsed * 60 if elapsed > 0 else 0
    print(f"\n完成! 日线: {d_total:,} 行, 基础指标: {b_total:,} 行")
    print(f"用时: {elapsed:.0f} 秒 ({rate:.0f} 天/分)")


def update_moneyflow(start_date=None, end_date=None):
    """更新资金流向数据 — 使用 requests 直调 REST API"""

    cfg = get_config()
    if not start_date:
        start_date = cfg.default_start
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'=' * 60}")
    print(f"更新资金流数据: {start_date} ~ {end_date}")
    print(f"{'=' * 60}")

    conn = _init_db("moneyflow")

    # 校验 moneyflow 表字段
    cols = conn.execute('PRAGMA table_info("moneyflow")').fetchall()
    col_names = [c[1] for c in cols]
    print(f"  表字段: {col_names}")

    # 已有日期
    existing = set()
    if conn.execute("SELECT COUNT(*) FROM moneyflow").fetchone()[0] > 0:
        existing = set(r[0] for r in conn.execute(
            "SELECT DISTINCT trade_date FROM moneyflow"
        ).fetchall())

    all_days = _get_trading_days(start_date, end_date)
    pending = [d for d in all_days if d not in existing]
    print(f"交易日: {len(all_days)} 天, 已有: {len(existing)} 天, 还需: {len(pending)} 天")

    if not pending:
        print("  ✓ 资金流数据已完整")
        _write_meta(conn, "moneyflow", "ok", f"complete up to {end_date}")
        conn.close()
        return

    # moneyflow 仅保留 12 个字段
    moneyflow_cols = ["ts_code", "trade_date", "buy_sm_vol", "sell_sm_vol",
                      "buy_md_vol", "sell_md_vol", "buy_lg_vol", "sell_lg_vol",
                      "buy_elg_vol", "sell_elg_vol", "net_mf_vol", "net_mf_amount"]

    total_rows = 0
    start_time = datetime.now()
    api_delay = cfg.api_delay

    for i, day in enumerate(pending):
        try:
            fields, items = _requests_fetch("moneyflow", {"trade_date": day})
            # 筛选仅 12 字段
            field_indices = [fields.index(c) for c in moneyflow_cols]
            rows = [[item[idx] for idx in field_indices] for item in items]

            if rows:
                _bulk_insert(conn, "moneyflow", moneyflow_cols, rows)
                total_rows += len(rows)

            if (i + 1) % 50 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                print(f"  进度: {i+1}/{len(pending)} 天 ({rate:.0f} 天/分, {total_rows:,} 行)")

            time.sleep(api_delay)

        except Exception as e:
            print(f"  ⚠ {day} 失败: {e}")
            continue

    elapsed = (datetime.now() - start_time).total_seconds()
    conn.commit()
    _write_meta(conn, "moneyflow", "ok", f"rows={total_rows}, days={len(pending)}, elapsed={elapsed:.0f}s")
    conn.close()

    rate = len(pending) / elapsed * 60 if elapsed > 0 else 0
    print(f"\n完成! 资金流: {total_rows:,} 行")
    print(f"用时: {elapsed:.0f} 秒 ({rate:.0f} 天/分)")


def update_holders(start_date=None, end_date=None):
    """更新股东数据 (前十大股东 + 股东人数)"""
    cfg = get_config()
    if not start_date:
        start_date = cfg.default_start.replace("2025", "2020")  # 从2020开始
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'=' * 60}")
    print(f"更新股东数据: {start_date} ~ {end_date}")
    print(f"{'=' * 60}")

    conn = _init_db("holders")

    # 获取股票列表
    master_conn = sqlite3.connect(db_path("master"))
    codes = [r[0] for r in master_conn.execute(
        "SELECT ts_code FROM stock_basic"
    ).fetchall()]
    master_conn.close()
    print(f"股票数: {len(codes)} 只")

    pro = _tushare_pro()
    api_delay = cfg.api_delay
    start_time = datetime.now()
    hd_total = hn_total = 0

    for i, code in enumerate(codes):
        try:
            # 前十大股东
            existing_cnt = conn.execute(
                "SELECT COUNT(*) FROM top10_holders WHERE ts_code=?", (code,)
            ).fetchone()[0]
            if existing_cnt == 0:
                df = pro.top10_holders(ts_code=code, start_date=start_date, end_date=end_date)
                if not df.empty:
                    df.to_sql("top10_holders", conn, if_exists="append", index=False, method="multi")
                    hd_total += len(df)

            # 股东人数
            existing_cnt2 = conn.execute(
                "SELECT COUNT(*) FROM stk_holdernumber WHERE ts_code=?", (code,)
            ).fetchone()[0]
            if existing_cnt2 == 0:
                df = pro.stk_holdernumber(ts_code=code, start_date=start_date, end_date=end_date)
                if not df.empty:
                    df.to_sql("stk_holdernumber", conn, if_exists="append", index=False, method="multi")
                    hn_total += len(df)

            if (i + 1) % 500 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                print(f"  进度: {i+1}/{len(codes)} 只 ({rate:.0f} 只/分)")
                conn.commit()

            time.sleep(api_delay)

        except Exception as e:
            if (i + 1) % 500 == 0:
                print(f"  ⚠ {code} 失败: {e}")
            continue

    elapsed = (datetime.now() - start_time).total_seconds()
    conn.commit()
    _write_meta(conn, "holders", "ok", f"top10={hd_total}, holdernumber={hn_total}, stocks={len(codes)}, elapsed={elapsed:.0f}s")
    conn.close()

    rate = len(codes) / elapsed * 60 if elapsed > 0 else 0
    print(f"\n完成! 股东: {hd_total:,} 行, 股东人数: {hn_total:,} 行")


def update_financial(start_date=None, end_date=None):
    """更新财务数据 (fina_indicator + income + balancesheet + cashflow)"""
    cfg = get_config()
    if not start_date:
        start_date = "20200101"
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'=' * 60}")
    print(f"更新财务数据: {start_date} ~ {end_date}")
    print(f"{'=' * 60}")

    conn = _init_db("financial")

    master_conn = sqlite3.connect(db_path("master"))
    codes = [r[0] for r in master_conn.execute(
        "SELECT ts_code FROM stock_basic"
    ).fetchall()]
    master_conn.close()
    print(f"股票数: {len(codes)} 只")

    api_delay = cfg.api_delay
    start_time = datetime.now()
    totals = {"fina_indicator": 0, "income": 0, "balancesheet": 0, "cashflow": 0}

    for i, code in enumerate(codes):
        try:
            for table_name, api_name in [
                ("fina_indicator", "fina_indicator"),
                ("income", "income"),
                ("balancesheet", "balancesheet"),
                ("cashflow", "cashflow"),
            ]:
                existing_cnt = conn.execute(
                    f'SELECT COUNT(*) FROM "{table_name}" WHERE ts_code=?', (code,)
                ).fetchone()[0]
                if existing_cnt == 0:
                    fields, items = _requests_fetch(api_name, {
                        "ts_code": code,
                        "start_date": start_date,
                        "end_date": end_date,
                    })
                    if items:
                        _bulk_insert(conn, table_name, fields, items)
                        totals[table_name] += len(items)

            if (i + 1) % 500 == 0:
                elapsed = (datetime.now() - start_time).total_seconds()
                rate = (i + 1) / elapsed * 60 if elapsed > 0 else 0
                print(f"  进度: {i+1}/{len(codes)} 只 ({rate:.0f} 只/分)")

            time.sleep(api_delay / 2)

        except Exception as e:
            if (i + 1) % 500 == 0:
                print(f"  ⚠ {code} 失败: {e}")
            continue

    elapsed = (datetime.now() - start_time).total_seconds()
    conn.commit()
    detail = ", ".join(f"{k}={v}" for k, v in totals.items())
    _write_meta(conn, "financial", "ok", f"{detail}, elapsed={elapsed:.0f}s")
    conn.close()

    rate = len(codes) / elapsed * 60 if elapsed > 0 else 0
    print(f"\n完成! {', '.join(f'{k}: {v:,}' for k, v in totals.items())}")


def update_lhb(start_date=None, end_date=None):
    """更新龙虎榜数据"""
    cfg = get_config()
    if not start_date:
        start_date = cfg.default_start
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'=' * 60}")
    print(f"更新龙虎榜: {start_date} ~ {end_date}")
    print(f"{'=' * 60}")

    conn = _init_db("lhb")

    existing = set(r[0] for r in conn.execute(
        "SELECT DISTINCT trade_date FROM top_list"
    ).fetchall())

    all_days = _get_trading_days(start_date, end_date)
    pending = [d for d in all_days if d not in existing]
    print(f"交易日: {len(all_days)} 天, 已有: {len(existing)} 天, 还需: {len(pending)} 天")

    if not pending:
        print("  ✓ 龙虎榜数据已完整")
        conn.close()
        return

    pro = _tushare_pro()
    total_rows = 0
    start_time = datetime.now()

    for i, day in enumerate(pending):
        try:
            df = pro.top_list(trade_date=day)
            if not df.empty:
                df.to_sql("top_list", conn, if_exists="append", index=False, method="multi")
                total_rows += len(df)
            time.sleep(0.3)
        except Exception as e:
            continue

    elapsed = (datetime.now() - start_time).total_seconds()
    conn.commit()
    _write_meta(conn, "lhb", "ok", f"rows={total_rows}, days={len(pending)}, elapsed={elapsed:.0f}s")
    conn.close()
    print(f"\n完成! 龙虎榜: {total_rows:,} 行")


def update_macro():
    """更新宏观经济数据"""
    cfg = get_config()

    print(f"\n{'=' * 60}")
    print(f"更新宏观经济数据")
    print(f"{'=' * 60}")

    conn = _init_db("macro")

    macro_apis = [
        ("cn_cpi", None),
        ("cn_ppi", None),
        ("cn_pmi", None),
        ("cn_gdp", None),
        ("cn_m", None),
        ("sf_month", None),
        ("shibor", None),
        ("us_tycr", None),
    ]

    total_rows = 0
    pro = _tushare_pro()

    for api_name, _ in macro_apis:
        try:
            df = getattr(pro, api_name)()
            if not df.empty:
                table_name = api_name.replace("-", "_")
                df.to_sql(table_name, conn, if_exists="replace", index=False)
                total_rows += len(df)
                print(f"  ✓ {api_name}: {len(df)} 行")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠ {api_name}: {e}")

    # shibor_lpr 单独处理（有 5次/天 限频）
    try:
        df = pro.shibor_lpr()
        if not df.empty:
            df.to_sql("shibor_lpr", conn, if_exists="replace", index=False)
            total_rows += len(df)
            print(f"  ✓ shibor_lpr: {len(df)} 行")
    except Exception as e:
        print(f"  ⚠ shibor_lpr (限频): {e}")

    conn.commit()
    _write_meta(conn, "macro", "ok", f"total_rows={total_rows}")
    conn.close()
    print(f"\n完成! 宏观经济: {total_rows:,} 行")


def update_index(start_date=None, end_date=None):
    """更新指数行情"""
    # 主要指数列表
    INDEX_CODES = [
        "000001.SH", "000016.SH", "000300.SH", "000905.SH", "000688.SH",
        "399001.SZ", "399006.SZ", "399005.SZ", "399016.SZ",
        "000852.SH", "000015.SH", "H10355.CSI",
    ]

    cfg = get_config()
    if not start_date:
        start_date = cfg.default_start
    if not end_date:
        end_date = datetime.now().strftime("%Y%m%d")

    print(f"\n{'=' * 60}")
    print(f"更新指数行情: {start_date} ~ {end_date}")
    print(f"{'=' * 60}")

    conn = _init_db("index")
    pro = _tushare_pro()
    total_rows = 0

    for code in INDEX_CODES:
        try:
            existing_cnt = conn.execute(
                "SELECT COUNT(*) FROM index_daily WHERE ts_code=?", (code,)
            ).fetchone()[0]
            if existing_cnt == 0:
                df = pro.index_daily(ts_code=code, start_date=start_date, end_date=end_date)
                if not df.empty:
                    df.to_sql("index_daily", conn, if_exists="append", index=False, method="multi")
                    total_rows += len(df)
                    print(f"  ✓ {code}: {len(df)} 行")
                time.sleep(0.3)
            else:
                print(f"  — {code}: 已有 {existing_cnt} 行")
        except Exception as e:
            print(f"  ⚠ {code}: {e}")

    conn.commit()
    _write_meta(conn, "index", "ok", f"rows={total_rows}, elapsed=done")
    conn.close()
    print(f"\n完成! 指数: {total_rows:,} 行")


def update_period():
    """从日线聚合周线月线"""
    print(f"\n{'=' * 60}")
    print("聚合周线月线（从日线 SQL 聚合）")
    print(f"{'=' * 60}")

    conn = _init_db("period")

    # 从日线读取数据
    daily_conn = sqlite3.connect(db_path("daily"))
    df = pd.read_sql("SELECT ts_code, trade_date, open, high, low, close, vol, amount FROM daily ORDER BY ts_code, trade_date",
                      daily_conn)
    daily_conn.close()

    if df.empty:
        print("  ⚠ 日线数据为空，无法聚合")
        conn.close()
        return

    print(f"日线数据: {len(df):,} 行")

    # 转换日期
    dates = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    iso = dates.dt.isocalendar()
    df["week"] = iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    df["month"] = dates.dt.strftime("%Y-%m")

    # 聚合周线
    weekly = df.groupby(["ts_code", "week"], as_index=False, sort=False).agg(
        trade_date=("trade_date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        vol=("vol", "sum"),
        amount=("amount", "sum"),
    )
    weekly.to_sql("weekly", conn, if_exists="replace", index=False)
    print(f"  ✓ 周线: {len(weekly):,} 行")

    # 聚合月线
    monthly = df.groupby(["ts_code", "month"], as_index=False, sort=False).agg(
        trade_date=("trade_date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        vol=("vol", "sum"),
        amount=("amount", "sum"),
    )
    monthly.to_sql("monthly", conn, if_exists="replace", index=False)
    print(f"  ✓ 月线: {len(monthly):,} 行")

    conn.commit()
    conn.close()
    print("完成!")


# ============================================================
# 一键更新全部
# ============================================================

def update_all(start_date=None, end_date=None):
    """更新全部数据类别"""
    cfg = get_config()
    total_start = datetime.now()

    print("=" * 60)
    print("A 股数据全量更新")
    print(f"开始: {total_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 日线 (最快，5分)
    update_daily(start_date, end_date)

    # 2. 周线月线聚合 (秒级)
    update_period()

    # 3. 指数 (10秒)
    update_index(start_date, end_date)

    # 4. 资金流 (2分)
    update_moneyflow(start_date, end_date)

    # 5. 龙虎榜 (1分)
    update_lhb(start_date, end_date)

    # 6. 宏观 (10秒)
    update_macro()

    # 7. 财务 (最慢，可后台)
    update_financial(start_date, end_date)

    # 8. 股东
    update_holders(start_date, end_date)

    total_elapsed = (datetime.now() - total_start).total_seconds()
    print(f"\n{'=' * 60}")
    print(f"全部更新完成! 总用时: {total_elapsed:.0f} 秒 ({total_elapsed/60:.1f} 分钟)")
    print(f"{'=' * 60}")