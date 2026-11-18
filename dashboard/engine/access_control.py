"""StockPulse 权限管控引擎 — 用户分级 + 功能矩阵检查"""
import os
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".hermes"
EMAIL_USERS_PATH = CONFIG_DIR / "email-users.yaml"

FEATURE_MATRIX = {
    "A": {"name": "行情数据", "features": {
        "A1": "A股指数行情", "A2": "个股行情+技术分析",
        "A3": "国际市场行情", "A4": "技术指标"}},
    "B": {"name": "基本面", "features": {
        "B1": "财务数据", "B2": "深度财报",
        "B3": "估值分析", "B4": "股东数据"}},
    "C": {"name": "资金流向", "features": {
        "C1": "北向资金", "C2": "主力资金", "C3": "龙虎榜"}},
    "D": {"name": "智能分析", "features": {
        "D1": "AI诊股", "D2": "多因子选股",
        "D3": "交易信号", "D4": "条件盯盘", "D5": "智能告警"}},
    "E": {"name": "板块/组合", "features": {
        "E1": "行业轮动", "E2": "产业链",
        "E3": "组合回测", "E4": "筛选引擎"}},
    "F": {"name": "宏观/全球", "features": {
        "F1": "中国宏观", "F2": "美债",
        "F3": "外汇商品", "F4": "地缘POWER-8"}},
    "G": {"name": "报告", "features": {
        "G1": "周报", "G2": "日报", "G3": "AI链跟踪",
        "G4": "健康报告(内管)", "G5": "PDF报告(内管)"}},
    "H": {"name": "数据工具(内管)", "features": {
        "H1": "数据导出", "H2": "数据浏览器", "H3": "批量导出"}},
}

TIER_FEATURES = {
    "admin": "all",
    "vip": ["A1","A2","A3","A4","B1","B2","B3","B4",
            "C1","C2","C3","D1","D2","D3","D4","D5",
            "E1","E2","E3","E4","F1","F2","F3","F4",
            "G1","G2","G3"],
    # trial = 测试用户,权限对齐 VIP 全部对外功能,默认 7 天有效期
    "trial": ["A1","A2","A3","A4","B1","B2","B3","B4",
              "C1","C2","C3","D1","D2","D3","D4","D5",
              "E1","E2","E3","E4","F1","F2","F3","F4",
              "G1","G2","G3"],
    "annual_pass_base": ["A1","A3","G1","G2","G3","E1","F1"],
}

def _load_users():
    if not EMAIL_USERS_PATH.exists(): return {}
    try:
        import yaml
        with open(EMAIL_USERS_PATH) as f:
            data = yaml.safe_load(f)
        if not data or "users" not in data: return {}
        return {u["email"].lower(): u for u in data["users"] if "email" in u}
    except: return {}

def get_user_info(email):
    users = _load_users(); info = users.get(email.lower())
    if not info: return {"email":email,"tier":None,"features":[],"exists":False}
    return {"email":email,"name":info.get("name",email),"tier":info["tier"],
        "features":info.get("features",[]),"since":info.get("since",""),
        "expires":info.get("expires",""),"exists":True}

def require_feature(email, feature_code):
    info = get_user_info(email)
    if not info["exists"]:
        return {"allowed":False,"message":f"{email} 未注册,请先订阅","user_info":info}
    tier = info["tier"]
    if info.get("expires"):
        try:
            exp = datetime.strptime(info["expires"],"%Y-%m-%d")
            if exp < datetime.now():
                msg = f"订阅已于{info['expires']}过期,请续费"
                if tier == "trial":
                    msg = f"测试期已于{info['expires']}结束,可升级正式订阅(年卡¥799/年,VIP¥3,999/年),回复本邮件即可办理"
                return {"allowed":False,"message":msg,"user_info":info}
        except: pass
    if tier == "admin": return {"allowed":True,"message":"ok","user_info":info}
    if tier == "vip":
        if feature_code in TIER_FEATURES["vip"]:
            return {"allowed":True,"message":"ok","user_info":info}
        return {"allowed":False,"message":"该功能仅限管理员","user_info":info}
    if tier == "trial":
        if feature_code in TIER_FEATURES["trial"]:
            return {"allowed":True,"message":"ok","user_info":info}
        return {"allowed":False,"message":"该功能仅限管理员","user_info":info}
    if tier == "annual_pass":
        allowed = set(TIER_FEATURES["annual_pass_base"] + info.get("features",[]))
        if feature_code in allowed:
            return {"allowed":True,"message":"ok","user_info":info}
        return {"allowed":False,"message":"该功能需升级VIP","user_info":info}
    return {"allowed":False,"message":"未注册","user_info":info}

def get_feature_matrix():
    matrix = {}
    for ck, cv in FEATURE_MATRIX.items():
        for fc, fn in cv["features"].items():
            matrix[fc] = {"name":fn,"category":cv["name"],"tier":"VIP"}
            if fc in ["G4","G5","H1","H2","H3"]: matrix[fc]["tier"] = "admin"
            if fc in TIER_FEATURES["annual_pass_base"]: matrix[fc]["tier"] = "年卡"
    return matrix

def list_all_users():
    return [{"email":u["email"],"name":u.get("name",""),"tier":u.get("tier",""),
        "since":u.get("since",""),"expires":u.get("expires",""),
        "features":u.get("features",[])} for u in _load_users().values()]

def add_user(email, tier, name="", features=None, expires=""):
    import yaml
    users = list(_load_users().values())
    users.append({"email":email.lower(),"name":name or email,"tier":tier,
        "since":datetime.now().strftime("%Y-%m-%d"),"expires":expires,
        **(features and {"features":features} or {})})
    try:
        with open(EMAIL_USERS_PATH,"w") as f:
            yaml.dump({"users":users},f,default_flow_style=False,allow_unicode=True)
        return {"status":"ok","message":f"用户 {email} 已添加"}
    except Exception as e:
        return {"status":"error","message":f"写入失败: {e}"}
