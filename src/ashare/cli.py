"""ashare CLI - 主入口"""
import click
from . import __version__


@click.group()
@click.version_option(__version__, prog_name="ashare")
def cli():
    """A 股全市场数据平台"""
    pass


@cli.command()
def init():
    """初始化配置"""
    from .config import get_config, CONFIG_SEARCH_PATHS
    cfg = get_config()
    if cfg.loaded_from():
        click.echo(f"配置已存在: {cfg.loaded_from()}")
    else:
        click.echo("未找到配置文件，使用默认配置")
        click.echo(f"  数据库目录: {cfg.db_dir}")
        click.echo(f"  Tushare Token: {'已设置' if cfg.tushare_token else '未设置'}")
        if not cfg.tushare_token:
            click.echo("  提示: 设置 TUSHARE_TOKEN 环境变量或编辑 ~/.ashare/config.yaml")
        click.echo(f"\n运行 `ashare status` 检查数据库状态")


@cli.command()
def status():
    """查看数据库状态概览"""
    from .config import get_config
    from .db.status import show_status
    cfg = get_config()
    show_status()


@cli.command()
@click.argument("ts_code", required=False)
@click.option("--days", "-d", default=None, type=int, help="最近N个交易日")
@click.option("--start", "-s", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", "-e", default=None, help="结束日期 YYYYMMDD")
@click.option("--fields", "-f", default="ts_code,trade_date,close,pct_chg,vol,amount",
              help="查询字段，逗号分隔")
@click.option("--csv", is_flag=True, help="以 CSV 格式输出")
@click.option("--limit", "-l", default=20, type=int, help="行数限制")
def query(ts_code, days, start, end, fields, csv, limit):
    """查询股票数据

    TS_CODE: 股票代码 (例如 600519.SH), 省略则列出所有股票
    """
    from .db.query import run_query
    run_query(ts_code, days, start, end, fields, csv, limit)


@cli.group()
def update():
    """更新数据"""
    pass


@update.command("daily")
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
def update_daily(start, end):
    """更新日线行情"""
    from .db.loader import update_daily
    update_daily(start, end)


@update.command("financial")
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
def update_financial(start, end):
    """更新财务数据"""
    from .db.loader import update_financial
    update_financial(start, end)


@update.command("moneyflow")
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
def update_moneyflow(start, end):
    """更新资金流向"""
    from .db.loader import update_moneyflow
    update_moneyflow(start, end)


@update.command("holders")
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
def update_holders(start, end):
    """更新股东数据"""
    from .db.loader import update_holders
    update_holders(start, end)


@update.command("lhb")
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
def update_lhb(start, end):
    """更新龙虎榜"""
    from .db.loader import update_lhb
    update_lhb(start, end)


@update.command("macro")
def update_macro():
    """更新宏观经济数据"""
    from .db.loader import update_macro
    update_macro()


@update.command("period")
def update_period():
    """聚合周线月线（从日线 SQL 聚合）"""
    from .db.loader import update_period
    update_period()


@update.command("hsgt")
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
def update_hsgt(start, end):
    """更新北向资金（HSGT）数据"""
    from .db.hsgt_backfill import run_update
    run_update(start or "20250101", end or None)

@update.command("all")
@click.option("--start", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", default=None, help="结束日期 YYYYMMDD")
def update_all(start, end):
    """更新全部数据"""
    from .db.loader import update_all
    update_all(start, end)


@cli.command()
@click.argument("ts_code", default=None, required=False)
@click.option("--format", "-f", "fmt", default="csv", type=click.Choice(["csv", "xlsx", "parquet"]))
@click.option("--start", "-s", default=None, help="开始日期 YYYYMMDD")
@click.option("--end", "-e", default=None, help="结束日期 YYYYMMDD")
@click.option("--output", "-o", default=None, help="输出路径")
def export(ts_code, fmt, start, end, output):
    """导出数据

    TS_CODE: 股票代码 (例如 600519.SH), 省略则导出全部
    """
    from .exporters.cli_export import run_export
    run_export(ts_code, fmt, start, end, output)


@cli.command()
def backup():
    """备份所有数据库"""
    from .exporters.backup import run_backup
    run_backup()


@cli.command()
@click.option("--deep", is_flag=True, help="深度校验")
def validate(deep):
    """数据完整性校验"""
    from .db.validate import run_validate
    run_validate(deep)


@cli.command()
@click.option("--port", "-p", default=8501, type=int, help="端口号")
@click.option("--host", default="0.0.0.0", help="监听地址")
def dashboard(port, host):
    """启动 Streamlit 分析平台"""
    from .dashboard.launcher import launch_dashboard
    launch_dashboard(host=host, port=port)


@cli.command()
@click.option("--port", "-p", default=8000, type=int, help="端口号")
@click.option("--host", default="0.0.0.0", help="监听地址")
def serve(port, host):
    """启动 REST API 服务"""
    from .api.server import run_server
    run_server(host=host, port=port)


@cli.command()
@click.argument("ts_code")
@click.option("--output", "-o", default=None, help="输出 PDF 路径")
def report(ts_code, output):
    """生成个股 PDF 分析报告"""
    from .reports.stock_report import generate_report
    generate_report(ts_code, output)


if __name__ == "__main__":
    cli()