#!/usr/bin/env python3
"""每日增量更新: Tushare → PostgreSQL
定时: 交易日 15:30 CST（收盘后）

覆盖数据:
  1. daily — A股日线行情
  2. daily_basic — 每日基本面（PE/PB/市值等）
  3. moneyflow — 个股资金流向
  4. index_daily — 指数日线（~8000指数/天，单次API全量）
  5. top_list — 龙虎榜（单次API全量）
  6. hsgt_moneyflow + hsgt_top10 — 北向资金（按月批量，自动调用）

策略:
  1. 从 PG 查出各表最新交易日
  2. 交易日历算出缺失日期列表
  3. 按天切片全市场拉取（daily/daily_basic/moneyflow/index_daily/top_list）
  4. 批量 INSERT ON CONFLICT DO NOTHING
  5. HSGT 增量更新（按月批量，调用 hsgt_backfill.run_update）
  6. REFRESH MATERIALIZED VIEW weekly + monthly
"""
import os, sys, time, json, requests
from datetime import datetime, timedelta

import psycopg2
import pandas as pd
import numpy as np

# ── 配置 ────────────────────────────────────────────
PG = {"host": "localhost", "dbname": "ashare", "user": "zrall",
      "options": "-c search_path=ashare,public"}

TUSHARE_API = "http://api.tushare.pro"
TOKEN = os.environ.get("TUSHARE_TOKEN")
if not TOKEN:
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("TUSHARE_TOKEN="):
                TOKEN = line.strip().split("=", 1)[1]
                break
if not TOKEN:
    print("[FATAL] TUSHARE_TOKEN 未设置"); sys.exit(1)

API_DELAY = 0.35  # 两次 API 调用间隔（秒）

LOG_PREFIX = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}]"


def log(msg):
    print(f"{LOG_PREFIX} {msg}")


def ts_api(api_name, params, fields=""):
    """调用 Tushare REST API"""
    payload = {
        "api_name": api_name, "token": TOKEN,
        "params": params, "fields": fields,
    }
    for attempt in range(3):
        try:
            r = requests.post(TUSHARE_API, json=payload, timeout=30)
            data = r.json()
            if data.get("code") != 0:
                log(f"  ⚠ {api_name} → {data.get('msg', '未知错误')}")
                if "频率超限" in str(data.get("msg", "")):
                    time.sleep(5)
                    continue
                return None
            items = data.get("data", {}).get("items", [])
            flds = data.get("data", {}).get("fields", [])
            if not items:
                return None
            return pd.DataFrame(items, columns=flds)
        except Exception as e:
            log(f"  ⚠ {api_name} 请求失败 (尝试{attempt+1}/3): {e}")
            time.sleep(2)
    return None


def get_pg_latest_dates():
    """查询 PG 中各表最新交易日"""
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM daily")
    d_daily = cur.fetchone()[0]
    cur.execute("SELECT MAX(trade_date) FROM daily_basic")
    d_basic = cur.fetchone()[0]
    cur.execute("SELECT MAX(trade_date) FROM moneyflow")
    d_mf = cur.fetchone()[0]
    cur.execute("SELECT MAX(trade_date) FROM index_daily")
    d_idx = cur.fetchone()[0]
    cur.execute("SELECT MAX(trade_date) FROM top_list")
    d_tl = cur.fetchone()[0]
    cur.execute("SELECT MAX(cal_date) FROM trade_cal WHERE is_open=1")
    d_cal = cur.fetchone()[0]
    conn.close()
    return {
        "daily": d_daily or "20150105",
        "daily_basic": d_basic or "20150105",
        "moneyflow": d_mf or "20150105",
        "index_daily": d_idx or "20150105",
        "top_list": d_tl or "20150105",
        "last_trade_day": d_cal or datetime.now().strftime("%Y%m%d"),
    }


def get_trading_days(start, end):
    """从 PG 交易日历获取交易日列表"""
    conn = psycopg2.connect(**PG)
    df = pd.read_sql(
        "SELECT cal_date FROM trade_cal WHERE is_open=1 "
        "AND cal_date>=%s AND cal_date<=%s ORDER BY cal_date",
        conn, params=[start, end]
    )
    conn.close()
    return df["cal_date"].tolist()


def batch_insert(conn, table, df, pk_cols=["ts_code", "trade_date"]):
    """批量 UPSERT — 用 execute_values + ON CONFLICT DO NOTHING"""
    if df.empty:
        return 0
    from psycopg2.extras import execute_values
    cols = list(df.columns)
    col_list = ", ".join(f'"{c}"' for c in cols)
    tuples = [tuple(None if pd.isna(v) else v for v in row) for row in df.to_numpy()]
    sql = f"INSERT INTO {table} ({col_list}) VALUES %s ON CONFLICT DO NOTHING"
    cur = conn.cursor()
    execute_values(cur, sql, tuples, template=f"({', '.join(['%s']*len(cols))})")
    conn.commit()
    cur.close()
    return len(tuples)


def main():
    t0 = time.time()
    log("🚀 开始每日增量更新")

    # 1. 当前状态
    state = get_pg_latest_dates()
    log(f"📊 PG 状态:")
    log(f"   daily:       {state['daily']}")
    log(f"   daily_basic: {state['daily_basic']}")
    log(f"   moneyflow:   {state['moneyflow']}")
    log(f"   index_daily: {state['index_daily']}")
    log(f"   top_list:    {state['top_list']}")
    log(f"   最新交易日:  {state['last_trade_day']}")

    # 需要回填的截止日（取今天或最新交易日，取小值）
    today = datetime.now().strftime("%Y%m%d")
    end_day = min(state["last_trade_day"], today)

    for table_key, table_name, api_name, api_fields in [
        ("daily",       "daily",       "daily",
         "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"),
        ("daily_basic", "daily_basic", "daily_basic",
         "ts_code,trade_date,close,turnover_rate,turnover_rate_f,volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,total_share,float_share,free_share,total_mv,circ_mv"),
        ("moneyflow",   "moneyflow",   "moneyflow",
         "ts_code,trade_date,buy_sm_vol,sell_sm_vol,buy_md_vol,sell_md_vol,"
         "buy_lg_vol,sell_lg_vol,buy_elg_vol,sell_elg_vol,net_mf_vol,net_mf_amount,"
         "buy_sm_amount,sell_sm_amount,buy_md_amount,sell_md_amount,"
         "buy_lg_amount,sell_lg_amount,buy_elg_amount,sell_elg_amount"),
        ("index_daily", "index_daily", "index_daily",
         "ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount"),
        ("top_list",    "top_list",    "top_list",
         "trade_date,ts_code,name,close,pct_change,turnover_rate,amount,"
         "l_sell,l_buy,l_amount,net_amount,net_rate,amount_rate,float_values,reason"),
    ]:
        latest = state[table_key]
        days = get_trading_days(latest, end_day)
        # 去掉 latest 本身（已存在）
        pending = [d for d in days if d > latest]

        if not pending:
            log(f"✅ {table_name} 已是最新 ({latest})")
            continue

        log(f"🔄 {table_name}: 缺失 {len(pending)} 天 ({pending[0]} ~ {pending[-1]})")

        conn = psycopg2.connect(**PG)
        inserted_total = 0
        for i, day in enumerate(pending):
            df = ts_api(api_name, {"trade_date": day}, api_fields)
            if df is not None and not df.empty:
                n = batch_insert(conn, table_name, df)
                inserted_total += n
                sys.stdout.write(
                    f"\r  [{i+1}/{len(pending)}] {day} → {n:>5,} 行 "
                    f"(累计 {inserted_total:>8,})     "
                )
                sys.stdout.flush()
            else:
                sys.stdout.write(f"\r  [{i+1}/{len(pending)}] {day} → 无数据      ")
                sys.stdout.flush()
            time.sleep(API_DELAY)
        conn.close()
        print()
        log(f"  ✅ {table_name}: 完成 {inserted_total:,} 行")

    # 5. HSGT 增量更新（北向资金，按月批量）
    log("🔄 更新 HSGT 北向资金数据 ...")
    try:
        from ashare.db.hsgt_backfill import run_update
        # 自动从最近30天开始，确保覆盖全
        last_idx = max(state["index_daily"], state["daily"])
        start_m = (datetime.strptime(last_idx, "%Y%m%d") - timedelta(days=30)).strftime("%Y%m01")
        end_m = datetime.now().strftime("%Y%m%d")
        run_update(start_m, end_m)
        log("  ✅ HSGT 更新完成")
    except Exception as e:
        log(f"  ⚠ HSGT 更新异常: {e}")

    # 6. 刷新物化视图
    log("🔄 刷新物化视图 weekly / monthly ...")
    conn = psycopg2.connect(**PG)
    cur = conn.cursor()
    t1 = time.time()
    cur.execute("REFRESH MATERIALIZED VIEW weekly")
    cur.execute("REFRESH MATERIALIZED VIEW monthly")
    conn.commit()
    conn.close()
    log(f"  ✅ 物化视图刷新完成 ({time.time()-t1:.1f}s)")

    elapsed = time.time() - t0
    log(f"🎉 每日更新完成! 总耗时 {elapsed:.0f}s ({elapsed/60:.1f}分)")


if __name__ == "__main__":
    main()