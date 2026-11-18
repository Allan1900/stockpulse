#!/usr/bin/env python3
"""P2-④ 产业链图谱引擎

定义产业链上下游关系 + 公司归属查询 + 链式穿透

数据来源: 人工整理的产业链关系（~20条核心产业链）
后续可扩展为从研报/C端API自动抽取
"""

import json, os, sys
import pandas as pd
import psycopg2

PG = {"host": "localhost", "dbname": "ashare", "user": "zrall",
      "options": "-c search_path=ashare,public"}

def _conn():
    return psycopg2.connect(**PG)

# ── SQL 查询 ──────────────────────────────────
def q(sql, params=None):
    """执行 SQL 查询，返回 DataFrame。使用 psycopg2 原生 execute 避免 pandas 参数绑定问题。"""
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [desc[0] for desc in cur.description] if cur.description else []
        data = cur.fetchall()
        cur.close()
        return pd.DataFrame(data, columns=cols)
    finally:
        conn.close()
CHAINS = {
    "锂电池": {
        "name": "锂电产业链",
        "stages": [
            {"name": "上游-锂矿", "industries": ["锂", "有色金属"], "keywords": ["锂矿", "盐湖", "锂"]},
            {"name": "中游-材料", "industries": ["化工原料", "化工"], "keywords": ["正极", "负极", "电解液", "隔膜"]},
            {"name": "中游-电芯", "industries": ["电气设备", "电子"], "keywords": ["电池", "电芯", "pack"]},
            {"name": "下游-整车", "industries": ["汽车", "汽车配件"], "keywords": ["新能源车", "电动车", "整车"]},
        ]
    },
    "光伏": {
        "name": "光伏产业链",
        "stages": [
            {"name": "上游-硅料", "industries": ["化工原料", "有色金属"], "keywords": ["硅料", "多晶硅", "单晶硅"]},
            {"name": "中游-硅片/电池", "industries": ["电气设备", "电子"], "keywords": ["硅片", "电池片", "光伏"]},
            {"name": "中游-组件", "industries": ["电气设备"], "keywords": ["组件", "逆变器", "支架"]},
            {"name": "下游-电站", "industries": ["电力", "公用事业"], "keywords": ["电站", "光伏发电", "运营"]},
        ]
    },
    "半导体": {
        "name": "半导体产业链",
        "stages": [
            {"name": "上游-设计/IP", "industries": ["半导体", "软件"], "keywords": ["芯片设计", "EDA", "IP"]},
            {"name": "中游-制造", "industries": ["半导体"], "keywords": ["晶圆", "代工", "制造"]},
            {"name": "中游-封测", "industries": ["半导体"], "keywords": ["封装", "测试", "封测"]},
            {"name": "下游-应用", "industries": ["元器件", "电子"], "keywords": ["AI芯片", "MCU", "存储"]},
        ]
    },
    "创新药": {
        "name": "创新药产业链",
        "stages": [
            {"name": "上游-研发/CRO", "industries": ["医疗保健", "生物制药"], "keywords": ["CRO", "CDMO", "研发"]},
            {"name": "中游-生产", "industries": ["生物制药", "化学制药"], "keywords": ["原料药", "制剂", "生物药"]},
            {"name": "下游-流通", "industries": ["医药商业", "医疗保健"], "keywords": ["医药流通", "药店", "分销"]},
        ]
    },
    "AI算力": {
        "name": "AI算力产业链",
        "stages": [
            {"name": "上游-芯片", "industries": ["半导体"], "keywords": ["GPU", "AI芯片", "算力"]},
            {"name": "中游-服务器/光模块", "industries": ["通信设备", "元器件"], "keywords": ["服务器", "光模块", "交换机"]},
            {"name": "下游-应用/大模型", "industries": ["软件", "互联网"], "keywords": ["大模型", "AI应用", "云计算"]},
        ]
    },
    "机器人": {
        "name": "机器人产业链",
        "stages": [
            {"name": "上游-核心部件", "industries": ["自动化", "元器件"], "keywords": ["伺服", "减速器", "传感器"]},
            {"name": "中游-本体", "industries": ["自动化", "机械"], "keywords": ["工业机器人", "协作机器人"]},
            {"name": "下游-集成应用", "industries": ["自动化", "汽车"], "keywords": ["系统集成", "自动化产线"]},
        ]
    },
    "特高压": {
        "name": "特高压/电网产业链",
        "stages": [
            {"name": "上游-设备", "industries": ["电气设备"], "keywords": ["变压器", "开关", "电缆"]},
            {"name": "中游-工程", "industries": ["建筑工程", "电力"], "keywords": ["特高压", "输变电", "电网"]},
            {"name": "下游-运营", "industries": ["电力", "公用事业"], "keywords": ["电网运营", "配电"]},
        ]
    },
    "消费电子": {
        "name": "消费电子产业链",
        "stages": [
            {"name": "上游-零部件", "industries": ["元器件", "电子"], "keywords": ["面板", "摄像头", "连接器"]},
            {"name": "中游-组装", "industries": ["电子", "通信设备"], "keywords": ["代工", "整机组装"]},
            {"name": "下游-品牌", "industries": ["消费电子", "家电"], "keywords": ["手机", "可穿戴", "智能家居"]},
        ]
    },
    "军工": {
        "name": "军工产业链",
        "stages": [
            {"name": "上游-材料", "industries": ["航空", "钢铁"], "keywords": ["钛合金", "复合材料", "高温合金"]},
            {"name": "中游-分系统", "industries": ["航空", "国防"], "keywords": ["发动机", "雷达", "导航"]},
            {"name": "下游-总装", "industries": ["航空", "国防"], "keywords": ["飞机", "导弹", "舰船"]},
        ]
    },
}

def get_stocks_by_industry(industries):
    """根据行业列表查询股票"""
    if not industries:
        return pd.DataFrame()
    return q("""
        SELECT ts_code, name, industry, market, list_date
        FROM stock_basic
        WHERE industry = ANY(%s)
        ORDER BY market, ts_code
    """, [industries])

def get_stocks_by_keywords(keywords):
    """根据关键词模糊匹配股票名称"""
    if not keywords:
        return pd.DataFrame()
    cond = " OR ".join(f"b.name LIKE '%{kw}%'" for kw in keywords)
    return q(f"""
        SELECT b.ts_code, b.name, b.industry, b.market
        FROM stock_basic b
        WHERE {cond}
        ORDER BY b.market, b.ts_code
    """)

# ── 核心穿透函数 ──────────────────────────────

def get_chain(chain_id):
    """获取产业链完整结构"""
    if chain_id not in CHAINS:
        return None
    chain = CHAINS[chain_id]
    result = {"id": chain_id, "name": chain["name"], "stages": []}
    for stage in chain["stages"]:
        # 按行业匹配
        df_ind = get_stocks_by_industry(stage["industries"])
        # 按关键词匹配
        df_kw = get_stocks_by_keywords(stage["keywords"])
        # 合并去重
        combined = pd.concat([df_ind, df_kw]).drop_duplicates(subset=["ts_code"])
        result["stages"].append({
            "name": stage["name"],
            "stocks": combined.to_dict("records") if not combined.empty else []
        })
    return result

def get_all_chains():
    """所有产业链列表"""
    return [{"id": k, "name": v["name"], "stages": len(v["stages"])}
            for k, v in CHAINS.items()]

def get_chain_for_stock(ts_code):
    """查询股票所属产业链"""
    stock = q("SELECT name, industry FROM stock_basic WHERE ts_code=%s", [ts_code])
    if stock.empty:
        return []
    name = stock.iloc[0]["name"]
    industry = stock.iloc[0]["industry"]
    result = []
    for cid, chain in CHAINS.items():
        for stage in chain["stages"]:
            # 行业匹配
            if industry in stage["industries"]:
                result.append({"chain": cid, "chain_name": chain["name"],
                               "stage": stage["name"]})
                break
            # 关键词匹配
            for kw in stage["keywords"]:
                if kw in name or kw in industry:
                    result.append({"chain": cid, "chain_name": chain["name"],
                                   "stage": stage["name"]})
                    break
            else:
                continue
            break
    return result


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "list"
    if action == "list":
        chains = get_all_chains()
        print(f"\n{'='*55}")
        print(f"  产业链图谱 — {len(chains)} 条产业链")
        print(f"{'='*55}\n")
        for c in chains:
            print(f"  {c['id']:8s}  {c['name']:16s}  ({c['stages']} 个环节)")
        print()
    elif action == "show" and len(sys.argv) > 2:
        chain = get_chain(sys.argv[2])
        if not chain:
            print(f"未找到产业链: {sys.argv[2]}")
            sys.exit(1)
        print(f"\n{'='*55}")
        print(f"  {chain['name']}")
        print(f"{'='*55}\n")
        for s in chain["stages"]:
            stocks = s["stocks"]
            print(f"  [{s['name']}]  {len(stocks)} 只股票")
            for st in stocks[:8]:
                print(f"    {st['ts_code']}  {st['name']:12s}  {st.get('industry',''):10s}  {st.get('market','')}")
            if len(stocks) > 8:
                print(f"    ... +{len(stocks)-8} 只")
            print()
    elif action == "stock" and len(sys.argv) > 2:
        chains = get_chain_for_stock(sys.argv[2])
        if not chains:
            print(f"未找到 {sys.argv[2]} 所属产业链")
            sys.exit(1)
        stock = q("SELECT name, industry FROM stock_basic WHERE ts_code=%s", [sys.argv[2]])
        sname = stock.iloc[0]["name"] if not stock.empty else sys.argv[2]
        print(f"\n  {sname} ({sys.argv[2]}) 所属产业链:\n")
        for c in chains:
            print(f"    {c['chain_name']:16s} → {c['stage']}")
        print()