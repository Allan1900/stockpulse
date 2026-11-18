"""
StockPulse 实时行情路由 — A股/美股/港股/外汇/全球指数

市场脉搏的"实时跳动"：此时此刻的市场状态。

注意：实时引擎位于 Streamlit Dashboard 目录下，
当前通过 subprocess 桥接调用，后续将抽取到 ashare 包内。
"""

from fastapi import APIRouter, Query
from typing import Optional

from ..response import sp_success, sp_error, SpError
from ....paths import ENGINE_DIR as _ENGINE_PATH

router = APIRouter(tags=["实时行情 — 实时跳动"])

ENGINE_DIR = str(_ENGINE_PATH)


def _call_engine(func_name: str, arg: str = None, timeout: int = 15) -> tuple:
    """通过 subprocess 调用实时引擎函数"""
    import subprocess, json, sys

    # 引擎函数可能返回 dict 或 DataFrame → 通用序列化转换
    _serialize = (
        "import json; "
        "r = {call}; "
        "r = r.to_dict(orient='records') if hasattr(r, 'to_dict') else r; "
        "print(json.dumps(r))"
    )
    if arg:
        code = (
            f"import sys; sys.path.insert(0, '{ENGINE_DIR}'); "
            f"from realtime import {func_name}; "
            + _serialize.format(call=f"{func_name}('{arg}')")
        )
    else:
        code = (
            f"import sys; sys.path.insert(0, '{ENGINE_DIR}'); "
            f"from realtime import {func_name}; "
            + _serialize.format(call=f"{func_name}()")
        )

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout.strip(), result.stderr[:500]


@router.get("/quote/{ts_code}", summary="A股实时行情")
async def get_realtime_a_share(ts_code: str):
    """A 股实时行情"""
    rc, stdout, stderr = _call_engine("get_realtime_quote", ts_code.upper())
    if rc == 0 and stdout:
        import json
        return sp_success(data=json.loads(stdout))
    return sp_error(SpError.PROVIDER_ERR, f"实时数据获取失败: {stderr}")


@router.get("/market_snapshot", summary="全市场快照")
async def get_market_snapshot():
    """A 股全市场实时快照"""
    rc, stdout, stderr = _call_engine("get_market_snapshot", timeout=30)
    if rc == 0 and stdout:
        import json
        return sp_success(data=json.loads(stdout))
    return sp_error(SpError.PROVIDER_ERR, f"快照获取失败: {stderr[:200]}")


@router.get("/us/{symbol}", summary="美股实时行情")
async def get_realtime_us(symbol: str):
    """美股实时行情"""
    # 尝试用 get_realtime_us 或 get_us_quote
    rc, stdout, stderr = _call_engine("get_us_realtime_quote", symbol.upper())
    if rc == 0 and stdout:
        import json
        return sp_success(data=json.loads(stdout))
    return sp_error(SpError.PROVIDER_ERR, f"美股数据获取失败: {stderr}")


@router.get("/hk/{ts_code}", summary="港股实时行情")
async def get_realtime_hk(ts_code: str):
    """港股实时行情"""
    rc, stdout, stderr = _call_engine("get_hk_realtime_quote", ts_code.upper())
    if rc == 0 and stdout:
        import json
        return sp_success(data=json.loads(stdout))
    return sp_error(SpError.PROVIDER_ERR, f"港股数据获取失败: {stderr}")


@router.get("/forex", summary="外汇实时行情")
async def get_realtime_forex(pair: str = Query("usdcny", description="货币对")):
    """主要外汇对实时行情"""
    rc, stdout, stderr = _call_engine("get_forex_realtime", pair, timeout=15)
    if rc == 0 and stdout:
        import json
        return sp_success(data=json.loads(stdout))
    return sp_error(SpError.PROVIDER_ERR, f"外汇数据获取失败: {stderr[:200]}")


@router.get("/global_indices", summary="全球指数实时行情")
async def get_global_indices():
    """全球主要指数实时行情"""
    rc, stdout, stderr = _call_engine("get_global_index_snapshot", timeout=15)
    if rc == 0 and stdout:
        import json
        return sp_success(data=json.loads(stdout))
    return sp_error(SpError.PROVIDER_ERR, f"全球指数获取失败: {stderr[:200]}")