#!/usr/bin/env python3
"""北向资金数据回填 — HSGT (moneyflow_hsgt + hsgt_top10)"""
import os
from pathlib import Path, sys, time, json
from datetime import datetime
import requests, psycopg2, pandas as pd

PG = {"dbname": "ashare", "user": "zrall"}
TOK = os.environ.get("TUSHARE_TOKEN", "")
API = "http://api.tushare.pro"

LOG = str(Path.home() / "backfill_hsgt.log")
def log(m):
    ts = datetime.now().strftime("%H:%M:%S")
    l = f"[{ts}] {m}"; print(l, flush=True)
    with open(LOG, "a") as f: f.write(l + "\n")

def ts(api, p=None):
    if p is None: p = {}
    r = requests.post(API, json={"api_name": api, "token": TOK, "params": p}, timeout=30)
    d = r.json()
    if d.get("code") != 0: raise Exception(f"{api}: {d.get('msg','?')}")
    return pd.DataFrame(d["data"]["items"], columns=d["data"]["fields"])

def backfill_moneyflow(start, end):
    conn = psycopg2.connect(**PG); conn.set_session(autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT trade_date FROM ashare.hsgt_moneyflow")
    done = set(r[0] for r in cur.fetchall())
    log(f"HSGT moneyflow 已有 {len(done)} 天")
    total = 0
    for y in range(int(start[:4]), int(end[:4])+1):
        for m in range(1,13):
            ym = f"{y}{m:02d}"
            if ym > end[:6]: break
            try:
                df = ts("moneyflow_hsgt", {"start_date": f"{ym}01", "end_date": f"{ym}31"})
                if df is None or df.empty: continue
                cnt = 0
                for _, r in df.iterrows():
                    if r["trade_date"] in done: continue
                    cur.execute("""INSERT INTO ashare.hsgt_moneyflow
                        (trade_date,ggt_ss,ggt_sz,hgt,sgt,north_money,south_money)
                        VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (r["trade_date"],r.get("ggt_ss"),r.get("ggt_sz"),r.get("hgt"),
                         r.get("sgt"),r.get("north_money"),r.get("south_money")))
                    cnt += 1
                total += cnt; done.update(df["trade_date"])
                if cnt: log(f"  {ym}: {cnt}天 (累计{total})")
            except Exception as e:
                log(f"  {ym}: {str(e)[:60]}")
    cur.close(); conn.close()
    log(f"HSGT moneyflow 完成! {total} 天")

def backfill_top10(start, end):
    conn = psycopg2.connect(**PG); conn.set_session(autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT trade_date FROM ashare.hsgt_top10")
    done = set(r[0] for r in cur.fetchall())
    log(f"HSGT top10 已有 {len(done)} 天")
    total = 0
    for y in range(int(start[:4]), int(end[:4])+1):
        for m in range(1,13):
            ym = f"{y}{m:02d}"
            if ym > end[:6]: break
            try:
                df = ts("hsgt_top10", {"start_date": f"{ym}01", "end_date": f"{ym}31"})
                if df is None or df.empty: continue
                cnt = 0
                for _, r in df.iterrows():
                    if r["trade_date"] in done: continue
                    cur.execute("""INSERT INTO ashare.hsgt_top10
                        (trade_date,ts_code,name,close,pct_change,rank,market_type,amount,net_amount,buy,sell)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (r["trade_date"],r["ts_code"],r.get("name"),r.get("close"),
                         r.get("pct_change"),r.get("rank"),r.get("market_type"),r.get("amount"),
                         r.get("net_amount"),r.get("buy"),r.get("sell")))
                    cnt += 1
                total += cnt; done.update(df["trade_date"])
                if cnt: log(f"  {ym}: {cnt}条 (累计{total})")
            except Exception as e:
                log(f"  {ym}: {str(e)[:60]}")
    cur.close(); conn.close()
    log(f"HSGT top10 完成! {total} 条")

if __name__ == "__main__":
    start, end = "20250101", datetime.now().strftime("%Y%m%d")
    log(f"=== HSGT 北向资金回填 {start} ~ {end} ===")
    backfill_moneyflow(start, end)
    backfill_top10(start, end)
    log("=== 全部完成 ===")

def run_update(start="20250101", end=None):
    """CLI 入口：增量更新 HSGT 数据"""
    if end is None:
        end = datetime.now().strftime("%Y%m%d")
    log(f"=== HSGT 增量更新 {start} ~ {end} ===")
    backfill_moneyflow(start, end)
    backfill_top10(start, end)
    log("=== 增量更新完成 ===")
