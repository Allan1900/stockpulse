"""个股 PDF 分析报告生成"""
import os
from datetime import datetime
from pathlib import Path


def generate_report(ts_code, output=None):
    """生成个股分析报告"""
    from ..config import get_config
    from ..db.query import query_single_stock, get_stock_names, get_daily_basic, get_financial
    from ..db.query import get_balancesheet, get_cashflow, get_moneyflow

    cfg = get_config()

    # 获取数据
    name_map = get_stock_names()
    name = name_map.get(ts_code, ts_code)

    start = cfg.default_start
    end = datetime.now().strftime("%Y%m%d")

    df = query_single_stock(ts_code, "*", start, end)
    if df.empty:
        print(f"无数据: {ts_code}")
        return

    # 基础统计
    latest = df.iloc[-1]
    first = df.iloc[0]
    period_return = (latest["close"] / first["close"] - 1) * 100
    period_high = df["high"].max()
    period_low = df["low"].min()
    avg_vol = df["vol"].mean()
    avg_amount = df["amount"].mean()

    # 生成 Markdown 报告
    md = f"""# {name} ({ts_code}) — 分析报告

**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**数据范围:** {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}
**交易日数:** {len(df)}

## 行情概览

| 指标 | 值 |
|------|-----|
| 最新收盘价 | {latest['close']:.2f} |
| 区间涨跌幅 | {period_return:+.2f}% |
| 区间最高 | {period_high:.2f} |
| 区间最低 | {period_low:.2f} |
| 日均成交量 | {avg_vol/10000:.0f} 万股 |
| 日均成交额 | {avg_amount/1e8:.2f} 亿元 |
| 最新振幅 | {latest['high'] - latest['low']:.2f} |

## 近期表现

| 日期 | 开盘 | 收盘 | 涨跌幅 | 成交量 |
|------|------|------|--------|--------|
"""
    # 最近 10 个交易日
    for _, r in df.tail(10).iterrows():
        md += f"| {r['trade_date']} | {r['open']:.2f} | {r['close']:.2f} | {r['pct_chg']:+.2f}% | {r['vol']/10000:.0f}万 |\n"

    md += f"""
## 估值指标

"""
    try:
        df_basic = get_daily_basic(ts_code, start, end)
        if not df_basic.empty:
            latest_b = df_basic.iloc[-1]
            md += f"""| 指标 | 值 |
|------|------|
| PE (TTM) | {latest_b.get('pe_ttm', 'N/A')} |
| PB | {latest_b.get('pb', 'N/A')} |
| 换手率 | {latest_b.get('turnover_rate', 'N/A')}% |
| 总市值 | {latest_b.get('total_mv', 0)/1e8:.2f} 亿元 |
| 流通市值 | {latest_b.get('circ_mv', 0)/1e8:.2f} 亿元 |
"""
    except Exception:
        md += "估值数据不可用\n"

    md += """
## 财务指标

"""
    try:
        df_fi = get_financial(ts_code, start, end)
        if not df_fi.empty:
            latest_f = df_fi.iloc[-1]
            md += f"""| 指标 | 值 |
|------|------|
| ROE | {latest_f.get('roe', 'N/A')}% |
| 毛利率 | {latest_f.get('gross_margin', 'N/A')}% |
| 每股收益 | {latest_f.get('eps', 'N/A')} |
| 资产负债率 | {latest_f.get('debt_to_assets', 0)*100:.1f}% |
"""
    except Exception:
        md += "财务数据不可用\n"

    # 写入文件
    if not output:
        output = f"{ts_code}_{name}_report.md"

    Path(output).write_text(md, encoding="utf-8")
    print(f"报告已生成: {output}")

    # 尝试转 PDF
    try:
        import markdown
        from weasyprint import HTML

        html = markdown.markdown(md, extensions=["tables", "fenced_code"])
        html = f"""<html><head><meta charset="utf-8"><style>
body {{ font-family: sans-serif; padding: 2em; }}
h1 {{ color: #1a56db; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f0f4f8; }}
</style></head><body>{html}</body></html>"""

        pdf_path = output.replace(".md", ".pdf")
        HTML(string=html).write_pdf(pdf_path)
        print(f"PDF 已生成: {pdf_path}")
    except ImportError:
        print("提示: 安装 weasyprint 可生成 PDF: pip install weasyprint")
    except Exception as e:
        print(f"PDF 生成失败: {e}")