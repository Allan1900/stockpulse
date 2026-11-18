#!/usr/bin/env python3
"""P4-④ 自动交易信号引擎 — 五位一体
融合: factors(factors) + alerts(告警) + sentinel(盯盘)
     + falsify(🔬Popper证伪) + reflexivity(🔄Soros反身性)
"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_ENGINE = _os.environ.get("SP_ENGINE_DIR") or _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import os, sys, warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from sqlalchemy import create_engine
from datetime import datetime
from falsify import apply_falsification, falsification_summary
from reflexivity import add_reflexivity, reflexivity_summary

PG_URI = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG_URI)

def q(sql, params=None):
    return pd.read_sql(sql, engine.raw_connection(), params=params)

# ── 因子信号 ──────────────────────────────────────
def signal_from_factor(date):
    try:
        from factors import compute
        sc = compute(date)
    except: return pd.DataFrame()
    if sc.empty: return pd.DataFrame()

    stocks = q("SELECT ts_code, name FROM stock_basic")
    nm = dict(zip(stocks["ts_code"], stocks["name"]))
    sc["name"] = sc["ts_code"].map(nm)
    p80 = sc["total"].quantile(0.8)
    p20 = sc["total"].quantile(0.2)
    rows = []
    for _, r in sc.iterrows():
        if r["total"] >= p80:
            rows.append({"ts_code":r["ts_code"],"name":r["name"],
                         "signal":"BUY","confidence":"HIGH",
                         "source":"factor","score":round(r["total"],1),
                         "detail":f"综合评分{r['total']:.1f}(行业TOP80%)"})
        elif r["total"] <= p20:
            rows.append({"ts_code":r["ts_code"],"name":r["name"],
                         "signal":"SELL","confidence":"HIGH",
                         "source":"factor","score":round(r["total"],1),
                         "detail":f"综合评分{r['total']:.1f}(行业BOTTOM20%)"})
    return pd.DataFrame(rows)

# ── 告警信号 ──────────────────────────────────────
def signal_from_alerts(date):
    from falsify import falsify_buy, falsify_sell
    rows = []
    try:
        from alerts import check_valuation, check_moneyflow, check_technical, check_volume
        for a in check_valuation(date):
            t = a.get("type","")
            if "低估" in t: rows.append({"ts_code":a["ts_code"],"signal":"BUY","confidence":"MEDIUM","source":"alerts_val","score":70,"detail":a.get("message","")})
            elif "高估" in t: rows.append({"ts_code":a["ts_code"],"signal":"SELL","confidence":"MEDIUM","source":"alerts_val","score":30,"detail":a.get("message","")})
        for a in check_technical(date):
            t = a.get("type","")
            if "金叉" in t: rows.append({"ts_code":a["ts_code"],"signal":"BUY","confidence":"HIGH","source":"alerts_tech","score":80,"detail":a.get("message","")})
            elif "死叉" in t: rows.append({"ts_code":a["ts_code"],"signal":"SELL","confidence":"HIGH","source":"alerts_tech","score":20,"detail":a.get("message","")})
        for a in check_moneyflow(date):
            t = a.get("type","")
            if "大幅流入" in t: rows.append({"ts_code":a["ts_code"],"signal":"BUY","confidence":"MEDIUM","source":"alerts_mf","score":60,"detail":a.get("message","")})
            elif "大幅流出" in t: rows.append({"ts_code":a["ts_code"],"signal":"SELL","confidence":"MEDIUM","source":"alerts_mf","score":40,"detail":a.get("message","")})
    except: pass
    if rows:
        stocks = q("SELECT ts_code,name FROM stock_basic")
        nm = dict(zip(stocks["ts_code"],stocks["name"]))
        for r in rows: r["name"] = nm.get(r["ts_code"],r["ts_code"][:6])
    return pd.DataFrame(rows)

# ── 五位一体核心逻辑 ────────────────────────────────
def consolidate(date=None):
    if not date: date = q("SELECT MAX(trade_date)::text FROM daily").iloc[0,0]

    print(f"\n  📊 P4-④ 五位一体交易信号 — {date}")
    print(f"  {'='*55}")

    print("  [1/5] 📊 因子评分...")
    fs = signal_from_factor(date)
    print(f"    BUY={len(fs[fs['signal']=='BUY'])} SELL={len(fs[fs['signal']=='SELL'])}")

    print("  [2/5] 🚨 告警信号...")
    als = signal_from_alerts(date)
    print(f"    BUY={len(als[als['signal']=='BUY'])} SELL={len(als[als['signal']=='SELL'])}")

    # 合并
    all_sig = pd.concat([fs, als], ignore_index=True)
    if all_sig.empty:
        print("  [SKIP] 无信号(默认HOLD)")
        return pd.DataFrame()

    stocks = q("SELECT ts_code,name FROM stock_basic")
    nm = dict(zip(stocks["ts_code"],stocks["name"]))

    rows = []
    for code, grp in all_sig.groupby("ts_code"):
        name = nm.get(code, code[:6])
        buy_c = (grp["signal"]=="BUY").sum()
        sell_c = (grp["signal"]=="SELL").sum()
        srcs = grp["source"].tolist()

        if buy_c >= 2:
            s,c = "BUY", "HIGH" if buy_c>=3 else "MEDIUM"
        elif sell_c >= 2:
            s,c = "SELL", "HIGH" if sell_c>=3 else "MEDIUM"
        elif buy_c == 1:
            s,c = "WATCH", "LOW"
        elif sell_c == 1:
            s,c = "WATCH", "LOW"
        else:
            continue

        avg = grp["score"].mean()
        det = "; ".join(grp["detail"].dropna().tolist()[:3])
        rows.append({"ts_code":code,"name":name,"signal":s,"confidence":c,
                     "source":"/".join(srcs),"score":round(avg,1),"detail":det})

    result = pd.DataFrame(rows)
    if result.empty: return result

    conf_order = {"HIGH":0,"MEDIUM":1,"LOW":2}
    result["_ord"] = result["confidence"].map(conf_order)
    result = result.sort_values(["_ord","score"],ascending=[True,False])
    result = result.drop(columns=["_ord"]).reset_index(drop=True)

    # ── [3/5] 🔬 Popper 证伪 ────────────────────────
    print("  [3/5] 🔬 Popper 证伪审查...")
    from falsify import falsify_buy, falsify_sell
    fscores = []
    fdetails = []
    new_sigs = []
    new_confs = []

    for _, row in result.iterrows():
        if row["signal"] == "BUY":
            sc, rs = falsify_buy(row["ts_code"], date)
        elif row["signal"] == "SELL":
            sc, rs = falsify_sell(row["ts_code"], date)
        else:
            sc, rs = 0.0, []

        fscores.append(round(sc,2))
        fdetails.append("; ".join(rs) if rs else "无证伪触发")

        if sc < -0.5:
            new_sigs.append("WATCH")
            new_confs.append("LOW(证伪)")
        elif sc < -0.3:
            new_sigs.append(row["signal"])
            downgrade = {"HIGH":"MEDIUM","MEDIUM":"LOW","LOW":"LOW"}
            new_confs.append(downgrade.get(row["confidence"],"LOW")+"(质疑)")
        elif sc > 0.5:
            new_sigs.append(row["signal"])
            upgrade = {"LOW":"MEDIUM","MEDIUM":"HIGH","HIGH":"HIGH"}
            new_confs.append(upgrade.get(row["confidence"],"HIGH")+"(确认)")
        elif sc > 0.3:
            new_sigs.append(row["signal"])
            upgrade = {"LOW":"MEDIUM","MEDIUM":"HIGH","HIGH":"HIGH"}
            new_confs.append(upgrade.get(row["confidence"],"HIGH")+"(支持)")
        else:
            new_sigs.append(row["signal"])
            new_confs.append(row["confidence"])

    result["signal"] = new_sigs
    result["confidence"] = new_confs
    result["falsify_score"] = fscores
    result["falsify_detail"] = fdetails
    print(f"    通过 {sum(1 for x in fscores if x>-0.3)}/{len(fscores)} 条")

    # ── [4/5] 🔄 Soros 反身性 ───────────────────────
    print("  [4/5] 🔄 Soros 反身性阶段识别...")
    from reflexivity import identify_stage

    stages = []
    for _, row in result.iterrows():
        info = identify_stage(row["ts_code"], date)
        stages.append(info)

    stage_df = pd.DataFrame(stages)
    for col in ["stage","name","icon","signal","price_3m","profit_yoy","divergence_index","detail"]:
        if col in stage_df.columns:
            result[f"reflex_{col}"] = stage_df[col].values

    print(f"    阶段分布: {result['reflex_stage'].value_counts().to_dict()}")

    print(f"\n  {'='*55}")
    print(f"  结果: BUY={int((result['signal']=='BUY').sum())} "
          f"SELL={int((result['signal']=='SELL').sum())} "
          f"WATCH={int((result['signal']=='WATCH').sum())}")
    print(f"  {'='*55}")

    # ── P4-④ Popper 证伪审查 ──────────────────────────
    result = apply_falsification(result, date)
    # ── P4-④ Soros 反身性阶段 ─────────────────────────
    result = add_reflexivity(result, date)

    return result

# ── 消息构建 ──────────────────────────────────────
def build_msg(date, sig_df):
    lines = [f"📊 五位一体交易信号 — {date}", ""]
    if sig_df.empty:
        lines.append("今日无信号（谨慎原则：默认HOLD）")
        lines.append("全部引擎运行正常，未检测到多源交叉验证的强烈方向信号。")
        lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return "\n".join(lines)

    for sig_type, icon in [("BUY","🟢"),("SELL","🔴"),("WATCH","🟡")]:
        sub = sig_df[sig_df["signal"]==sig_type]
        if sub.empty: continue
        lines.append(f"**{icon} {sig_type} ({len(sub)} 只)**")
        for _, r in sub.head(5).iterrows():
            falsify_tag = f"证伪{r['falsify_score']:+.2f}" if r.get("falsify_score",0) != 0 else ""
            reflex_tag = f"阶段{r.get('reflex_name','--')}" if r.get("reflex_name") else ""
            tags = " | ".join(t for t in [falsify_tag,reflex_tag] if t)
            lines.append(f"  {r['name']}({r['ts_code'][:6]}) [{r['source']}]")
            if tags: lines.append(f"    {tags}")
            if r.get("detail"): lines.append(f"    {r['detail']}")
        if len(sub) > 5:
            lines.append(f"    ... +{len(sub)-5} 只")
        lines.append("")

    lines.append("---")
    lines.append("五位一体:因子(📊)+告警(🚨)+证伪(🔬)+反身(🔄)+合成(🎯)")
    lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("🤖 P4-④ signals.py v2.0 (Popper+Soros)")
    return "\n".join(lines)

def save(date, sig_df):
    out_dir = os.path.join(os.path.dirname(__file__), "..", "exports", "signals")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    msg = build_msg(date, sig_df)
    md_path = os.path.join(out_dir, f"{date}.md")
    with open(md_path, "w", encoding="utf-8") as f: f.write(msg)
    print(f"  [SAVE] {md_path}")
    if not sig_df.empty:
        csv_path = os.path.join(out_dir, f"{date}.csv")
        sig_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"  [SAVE] {csv_path}")
    return md_path

def push(date, sig_df):
    cfg_path = _os.path.join(_DASH, "feishu_config.json")
    try:
        import json
        with open(cfg_path) as f: cfg = json.load(f)
        if not cfg.get("enabled"): print("  [SKIP] 飞书推送未启用"); return
        wh = cfg.get("webhook") or os.environ.get("FEISHU_WEBHOOK","")
        if not wh: print("  [SKIP] webhook未配置"); return
    except: print("  [SKIP] 飞书配置读取失败"); return

    import requests
    msg = build_msg(date, sig_df)
    try:
        r = requests.post(wh, json={
            "msg_type":"interactive",
            "card":{
                "header":{"title":{"tag":"plain_text","content":"📊 P4-④ 交易信号"}},
                "elements":[{"tag":"markdown","content":msg}]
            }
        }, timeout=10)
        print(f"  [PUSH] {'成功' if r.ok else f'失败({r.status_code})'}")
    except Exception as e:
        print(f"  [PUSH] 异常: {e}")

if __name__ == "__main__":
    import sys
    date = None; no_save = False; no_push = False
    for a in sys.argv[1:]:
        if a == "--no-push": no_push = True
        elif a == "--no-save": no_save = True
        else: date = a

    if not date:
        date = q("SELECT MAX(trade_date)::text FROM daily").iloc[0,0]

    sig = consolidate(date)
    if sig.empty:
        msg = build_msg(date, sig)
        print(f"\n{msg}\n")
        if not no_save: save(date, sig)
        if not no_push: push(date, sig)
        sys.exit(0)

    if not no_save: save(date, sig)
    if not no_push: push(date, sig)

    # 表格输出
    print(f"\n  {'='*55}")
    print(f"  综合评分:")
    for _, r in sig.head(10).iterrows():
        print(f"    {r['signal']:6s} {r['name']:12s} "
              f"置信={r['confidence']:15s} "
              f"证伪={r.get('falsify_score',0):+.2f} "
              f"阶段={r.get('reflex_name','--')}")
    print(f"\n  共 {len(sig)} 只", file=sys.stderr)