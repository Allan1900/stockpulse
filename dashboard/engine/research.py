"""
StockPulse 研报引擎 — 上传/存储/搜索/查看/删除

存储结构:
  $SP_DATA_DIR/research/
    ├── metadata.json   ← 全部元数据
    └── files/          ← 原文件副本
          └── <id>_<filename>

字段说明:
  id         — UUID 唯一标识
  title      — 研报标题
  author     — 作者/机构
  date       — 上传日期 YYYY-MM-DD
  tags       — 标签列表
  stocks     — 关联股票代码列表
  filename   — 原始文件名
  content    — 纯文本内容 (TXT/MD 全文, PDF 预览)
  preview    — 内容预览 (前 300 字符)
"""

import os as _os
_DASH = _os.environ.get("SP_DASHBOARD_DIR") or _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_ENGINE = _os.environ.get("SP_ENGINE_DIR") or _os.path.dirname(_os.path.abspath(__file__))
_DATA = _os.environ.get("SP_DATA_DIR") or _os.path.join(_os.path.expanduser("~"), "ashare_data")
import json, os, shutil, uuid
from datetime import date
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────
BASE = Path(_os.path.join(_DATA, "research"))
FILES_DIR = BASE / "files"
META_PATH = BASE / "metadata.json"

# 确保目录存在
BASE.mkdir(parents=True, exist_ok=True)
FILES_DIR.mkdir(parents=True, exist_ok=True)

# ── 元数据读写 ────────────────────────────────────

def _load_metadata() -> list[dict]:
    """从 JSON 加载全部元数据"""
    if not META_PATH.exists():
        return []
    with open(META_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_metadata(records: list[dict]) -> None:
    """持久化元数据"""
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

def _extract_text(file_path: Path) -> str:
    """抽取文件纯文本内容"""
    ext = file_path.suffix.lower()
    try:
        if ext == ".txt" or ext == ".md":
            return file_path.read_text(encoding="utf-8", errors="replace")
        elif ext == ".pdf":
            # PDF: 尝试 pypdf2/PDFMiner, 兜底返回文件名
            try:
                import pypdf
                text = ""
                reader = pypdf.PdfReader(file_path)
                for page in reader.pages:
                    text += page.extract_text() or ""
                return text or f"[PDF 文件: {file_path.name} — 需安装 pypdf 查看全文]"
            except ImportError:
                try:
                    import pdfminer.high_level
                    text = pdfminer.high_level.extract_text(str(file_path))
                    return text or f"[PDF 文件: {file_path.name}]"
                except ImportError:
                    pass
            return f"[PDF 文件: {file_path.name} — 安装 pypdf 或 pdfminer.six 查看全文]"
        else:
            return f"[不支持直接预览的文件类型: {ext}]"
    except Exception as e:
        return f"[读取文件失败: {e}]"

# ── 公开 API ──────────────────────────────────────

def research_list(sort_by: str = "date", reverse: bool = True) -> list[dict]:
    """列出所有研报

    Args:
        sort_by: 排序字段 — "date" / "title" / "author"
        reverse: True=降序(最新在前)

    Returns:
        元数据列表，每条包含 id/title/author/date/tags/stocks/filename/preview
    """
    records = _load_metadata()
    if sort_by == "date":
        records.sort(key=lambda r: r.get("date", ""), reverse=reverse)
    elif sort_by == "title":
        records.sort(key=lambda r: r.get("title", "").lower(), reverse=reverse)
    elif sort_by == "author":
        records.sort(key=lambda r: r.get("author", "").lower(), reverse=reverse)
    return records


def research_search(query: str) -> list[dict]:
    """搜索研报 — 匹配文件名/标题/标签/关联股票/内容

    Args:
        query: 搜索关键词（大小写不敏感）

    Returns:
        匹配的元数据列表
    """
    if not query or not query.strip():
        return research_list()
    q = query.strip().lower()
    records = _load_metadata()
    results = []
    for r in records:
        # 标题
        if q in r.get("title", "").lower():
            results.append(r)
            continue
        # 文件名
        if q in r.get("filename", "").lower():
            results.append(r)
            continue
        # 标签
        tags = r.get("tags", [])
        if any(q in t.lower() for t in tags):
            results.append(r)
            continue
        # 关联股票
        stocks = r.get("stocks", [])
        if any(q in s.lower() for s in stocks):
            results.append(r)
            continue
        # 内容预览
        if q in r.get("preview", "").lower():
            results.append(r)
            continue
    return results


def research_upload(
    file_path: str,
    title: str = "",
    author: str = "",
    tags: list[str] | None = None,
    stocks: list[str] | None = None,
) -> dict:
    """上传研报 — 复制文件到存储目录并记录元数据

    Args:
        file_path: 源文件路径
        title: 研报标题（空则取文件名）
        author: 作者/机构
        tags: 标签列表
        stocks: 关联股票代码列表

    Returns:
        新记录的元数据 dict

    Raises:
        FileNotFoundError: 源文件不存在
    """
    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    tags = tags or []
    stocks = stocks or []
    research_id = uuid.uuid4().hex[:12]
    title = title or src.stem
    today = date.today().isoformat()

    # 复制文件
    dest_name = f"{research_id}_{src.name}"
    dest_path = FILES_DIR / dest_name
    shutil.copy2(str(src), str(dest_path))

    # 抽取内容
    content = _extract_text(dest_path)
    preview = content[:300].replace("\n", " ") if content else ""

    record = {
        "id": research_id,
        "title": title,
        "author": author,
        "date": today,
        "tags": tags,
        "stocks": stocks,
        "filename": src.name,
        "saved_as": dest_name,
        "preview": preview,
    }

    records = _load_metadata()
    records.insert(0, record)  # 最新在前
    _save_metadata(records)
    return record


def research_get(research_id: str) -> dict | None:
    """获取单篇研报详情（含完整内容）

    Args:
        research_id: 研报 UUID (id 字段)

    Returns:
        元数据 + content 字段，或 None
    """
    records = _load_metadata()
    for r in records:
        if r["id"] == research_id:
            # 读取完整内容
            saved_as = r.get("saved_as", "")
            file_path = FILES_DIR / saved_as
            if file_path.exists():
                r["content"] = _extract_text(file_path)
            else:
                r["content"] = f"[文件缺失: {saved_as}]"
            return r
    return None


def research_delete(research_id: str) -> bool:
    """删除研报

    Args:
        research_id: 研报 UUID

    Returns:
        True=成功, False=未找到
    """
    records = _load_metadata()
    for i, r in enumerate(records):
        if r["id"] == research_id:
            # 删除文件
            saved_as = r.get("saved_as", "")
            if saved_as:
                file_path = FILES_DIR / saved_as
                if file_path.exists():
                    file_path.unlink()
            # 删除元数据
            records.pop(i)
            _save_metadata(records)
            return True
    return False