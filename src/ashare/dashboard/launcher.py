"""启动 Streamlit Dashboard — 包内版"""
import sys, os, subprocess
from pathlib import Path


def launch_dashboard(host="0.0.0.0", port=8501):
    """启动 Streamlit 分析平台（包内版）"""
    # 面板目录：优先 SP_DASHBOARD_DIR，其次仓库内 dashboard/
    from ..paths import DASHBOARD_DIR
    dashboard_dir = Path(DASHBOARD_DIR).resolve()
    app_path = dashboard_dir / "app.py"

    print(f"启动 Dashboard: http://{host}:{port}")
    print(f"目录: {dashboard_dir}")
    print("Dashboard 需要 streamlit+plotly 支持 (pip install ashare[dashboard])")
    print("按 Ctrl+C 停止")

    env = os.environ.copy()
    env["STREAMLIT_EMAIL"] = ""
    env["STREAMLIT_SERVER_HEADLESS"] = "true"

    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.address", host,
        "--server.port", str(port),
        "--server.headless", "true",
    ]
    subprocess.run(cmd, env=env, cwd=str(dashboard_dir))