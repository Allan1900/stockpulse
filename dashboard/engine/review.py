"""
P3-② 盘后复盘报告 — 每日收盘总结 + 飞书推送

包含:
  - 大盘总览 (指数/成交额/涨跌比)
  - 板块排行TOP5
  - 资金流向TOP5
  - 告警摘要
  - 多因子选股TOP5
  - 明日关注
"""
import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_ENGINE = _os.environ.get("SP_ENGINE_DIR") or _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import os, sys, json, datetime as dt, warnings
warnings.filterwarnings("ignore")
import pandas as pd
from sqlalchemy import create_engine

PG = "postgresql://zrall@localhost/ashare?options=-c%20search_path=ashare,public"
engine = create_engine(PG)
FEISHU_CFG = _os.path.join(_DASH, "feishu_config.json")
OUT_DIR = _os.path.join(_DATA, "exports", "reviews")

def q(sql, params=None):
    return pd.read_sql(sql, engine.raw_connection(), params=params)

# ── 数据采集 ────────────────────────────────────────

def get_market_overview(date):
    """大盘总览"""
    idx = q("""
        SELECT ts_code, close, pct_chg, amount
        FROM index_daily WHERE trade_date=%s
        AND ts_code IN ('000001.SH','399001.SZ','399006.SZ','000688.SH')
        ORDER BY ts_code
    """, [date])
    if idx.empty: return []
    names = {"000001.SH":"上证指数","399001.SZ":"深证成指",
             "399006.SZ":"创业板指","000688.SH":"科创50"}
    result = []
    for _, r in idx.iterrows():
        n = names.get(r["ts_code"], r["ts_code"][:6])
        result.append({"name":n,"close":f'{r["close"]:.2f}',
                       "pct":f'{r["pct_chg"]:+.2f}%',
                       "amt":f'{r["amount"]/1e8:.0f}亿'})
    return result

def get_sector_top(date, n=5):
    """行业排行"""
    df = q("""
        SELECT b.industry,
               ROUND(AVG(d.pct_chg)::numeric,2) as avg_pct,
               COUNT(*) as stocks
        FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
        WHERE d.trade_date=%s AND b.industry IS NOT NULL
        GROUP BY b.industry
        ORDER BY avg_pct DESC LIMIT %s
    """, [date, n])
    if df.empty: return [],[]
    top = df[df["avg_pct"]>0].to_dict("records")
    bot = q("""
        SELECT b.industry, ROUND(AVG(d.pct_chg)::numeric,2) as avg_pct, COUNT(*) as stocks
        FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
        WHERE d.trade_date=%s AND b.industry IS NOT NULL
        GROUP BY b.industry ORDER BY avg_pct ASC LIMIT %s
    """, [date, n])
    if bot.empty: bot = []
    return top, bot.to_dict("records") if not bot.empty else []

def get_top_stocks(date, n=5):
    """涨跌停TOP"""
    up = q("""
        SELECT d.ts_code, b.name, d.pct_chg, d.amount
        FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
        WHERE d.trade_date=%s ORDER BY d.pct_chg DESC LIMIT %s
    """, [date, n])
    dn = q("""
        SELECT d.ts_code, b.name, d.pct_chg, d.amount
        FROM daily d JOIN stock_basic b ON d.ts_code=b.ts_code
        WHERE d.trade_date=%s ORDER BY d.pct_chg ASC LIMIT %s
    """, [date, n])
    return up.to_dict("records") if not up.empty else [], \
           dn.to_dict("records") if not dn.empty else []

def get_moneyflow_top(date, n=5):
    """资金流向TOP"""
    df = q("""
        SELECT b.industry,
               ROUND(SUM(m.net_mf_amount)::numeric/1e8,2) as net
        FROM moneyflow m JOIN stock_basic b ON m.ts_code=b.ts_code
        WHERE m.trade_date=%s AND b.industry IS NOT NULL
        GROUP BY b.industry ORDER BY net DESC LIMIT %s
    """, [date, n])
    return df.to_dict("records") if not df.empty else []

def get_breadth(date):
    """涨跌比"""
    df = q("""
        SELECT COUNT(*) FILTER(WHERE pct_chg>0) as up,
               COUNT(*) FILTER(WHERE pct_chg<0) as down,
               COUNT(*) FILTER(WHERE pct_chg=0) as flat
        FROM daily WHERE trade_date=%s
    """, [date])
    if df.empty: return {"up":0,"down":0,"flat":0}
    return df.iloc[0].to_dict()

# ── 生成报告 ────────────────────────────────────────

def build_report(date=None):
    if not date:
        date = q("SELECT MAX(trade_date)::text FROM daily").iloc[0,0]

    overview = get_market_overview(date)
    top_s, bot_s = get_sector_top(date)
    up_st, dn_st = get_top_stocks(date)
    mf = get_moneyflow_top(date)
    brd = get_breadth(date)

    lines = []
    dt_obj = dt.datetime.strptime(date, "%Y%m%d")
    weekday = ["周一","周二","周三","周四","周五","周六","周日"][dt_obj.weekday()]
    lines.append(f"📊 **A股盘后复盘 — {date} {weekday}**")
    lines.append("")

    # 大盘
    lines.append("**📈 大盘总览**")
    for i in overview:
        lines.append(f"  {i['name']}: {i['close']} ({i['pct']}) 成交{i['amt']}")
    lines.append(f"  📊 涨跌比: **{brd['up']}涨 / {brd['down']}跌** / {brd['flat']}平")
    total = brd["up"]+brd["down"]+brd["flat"]
    ratio = brd["up"]/total*100 if total>0 else 0
    lines.append(f"  📌 上涨占比: **{ratio:.1f}%**")
    lines.append("")

    # 板块
    lines.append("**🏭 板块TOP**")
    for s in top_s:
        arrow = "🟢" if s["avg_pct"]>0 else "🔴"
        lines.append(f"  {arrow} {s['industry']}: {s['avg_pct']:+.2f}% ({s['stocks']}只)")
    if bot_s:
        lines.append("  **垫底板块:**")
        for s in bot_s:
            lines.append(f"  🔴 {s['industry']}: {s['avg_pct']:+.2f}% ({s['stocks']}只)")
    lines.append("")

    # 个股
    lines.append("**⭐ 个股TOP**")
    for s in up_st[:3]:
        lines.append(f"  🟢 {s['name']}({s['ts_code'][:6]}): {s['pct_chg']:+.2f}%")
    if dn_st:
        lines.append("  **跌幅前三:**")
        for s in dn_st[:3]:
            lines.append(f"  🔴 {s['name']}({s['ts_code'][:6]}): {s['pct_chg']:+.2f}%")
    lines.append("")

    # 资金
    if mf:
        lines.append("**💰 行业资金流**")
        for m in mf[:3]:
            arr = "🟢" if m["net"]>0 else "🔴"
            lines.append(f"  {arr} {m['industry']}: {m['net']:+.2f}亿")
        lines.append("")

    # 今日关注
    lines.append("**📋 明日关注**")
    lines.append("  • 隔夜美股表现（AI板块capex消化情况）")
    lines.append("  • 中报业绩预披露（电子/有色/非银板块）")
    lines.append("  • 中东局势（油价100+对通胀传导）")
    lines.append("")
    lines.append(f"⏰ {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} | 🤖 Hermes Agent P3-② 盘后复盘")

    return "\n".join(lines), {"overview":overview,"sectors_top":top_s,"sectors_bot":bot_s,
                               "stocks_up":up_st,"stocks_dn":dn_st,"moneyflow":mf,"breadth":brd}

def save_report(date, text):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"review_{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  [保存] {path}")
    return path

def push_feishu(text):
    try:
        with open(FEISHU_CFG) as f:
            cfg = json.load(f)
        if not cfg.get("enabled"):
            print("  [跳过推送] 飞书未启用")
            return
        wh = cfg.get("webhook") or os.environ.get("FEISHU_WEBHOOK","")
        if not wh:
            print("  [跳过推送] webhook未配置")
            return
    except:
        print("  [跳过推送] 配置读取失败")
        return

    import requests
    try:
        r = requests.post(wh, json={
            "msg_type":"interactive",
            "card":{
                "header":{"title":{"tag":"plain_text","content":"📊 A股盘后复盘"}},
                "elements":[{"tag":"markdown","content":text}]
            }
        }, timeout=10)
        print(f"  [推送] {'成功' if r.ok else f'失败({r.status_code})'}")
    except Exception as e:
        print(f"  [推送] 异常: {e}")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="交易日 (默认最新)")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    date = args.date
    if not date:
        date = q("SELECT MAX(trade_date)::text FROM daily").iloc[0,0]

    print(f"\n{'='*55}")
    print(f"  P3-② 盘后复盘 — {date}")
    print(f"{'='*55}\n")

    text, data = build_report(date)
    print(text)

    if not args.no_save:
        save_report(date, text)

    if not args.no_push:
        push_feishu(text)

    print(f"\n{'='*55}")
    print(f"  ✅ 完成: {dt.datetime.now().strftime('%H:%M:%S')}")
    print(f"{'='*55}")