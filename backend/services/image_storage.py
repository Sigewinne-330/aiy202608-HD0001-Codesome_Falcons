"""
图片存储服务：把 base64 dataUrl 解码落盘到 uploads/ 目录，返回静态 URL 路径。

设计目标：chat_message.extra 只存 URL（如 /uploads/20260803/xxxx.png），
不再存几百 KB 的 base64，避免大字段拖慢查询/排序（MySQL 1038 排序内存溢出）。

- 写入目录：backend/uploads/<YYYYMMDD>/<uuid>.<ext>
- 返回 URL：/uploads/<YYYYMMDD>/<uuid>.<ext>
- 兼容输入：data:image/png;base64,xxxx 或 data:image/jpeg;base64,xxxx 等
"""
import base64
import logging
import os
import re
import uuid
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# uploads 目录：backend/uploads/（与 main.py 静态挂载路径一致）
BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
UPLOAD_DIR = BASE_DIR / "uploads"

# 允许的 MIME → 扩展名映射（与前端 FileReader 产生的 dataUrl 类型对齐）
MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
}

# dataUrl 前缀正则：data:image/xxx;base64,
_DATA_URL_RE = re.compile(r"^data:(image/[\w.+-]+);base64,(.+)$", re.DOTALL)

# 单张图片最大限制：10MB（base64 解码前）
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def data_url_to_file(data_url: str) -> str:
    """把单个 base64 dataUrl 落盘，返回 URL 路径。

    Args:
        data_url: 形如 data:image/png;base64,iVBORw0KGgo...

    Returns:
        形如 /uploads/20260803/xxxx.png 的 URL 路径

    Raises:
        ValueError: 格式非法 / MIME 不支持 / 超过大小限制
    """
    if not data_url:
        raise ValueError("空图片数据")

    m = _DATA_URL_RE.match(data_url.strip())
    if not m:
        # 如果不是 dataUrl（可能已经传了 URL），原样返回，避免重复转换
        if data_url.startswith("/uploads/") or data_url.startswith("http"):
            return data_url
        raise ValueError("图片格式非法：仅支持 data:image/xxx;base64, 格式")

    mime = m.group(1).lower()
    b64_data = m.group(2)

    ext = MIME_EXT.get(mime)
    if not ext:
        raise ValueError(f"不支持的图片类型: {mime}")

    try:
        raw = base64.b64decode(b64_data, validate=False)
    except Exception as e:
        raise ValueError(f"base64 解码失败: {e}")

    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片过大（>{MAX_IMAGE_BYTES // (1024 * 1024)}MB），已拒绝")

    # 目录：uploads/<YYYYMMDD>/
    day_dir = UPLOAD_DIR / date.today().strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = day_dir / filename
    filepath.write_bytes(raw)

    # 返回 URL 路径（相对根路径，由前端 vite 代理 / 后端静态挂载提供）
    url = f"/uploads/{day_dir.name}/{filename}"
    logger.info(f"图片已落盘: {filepath} ({len(raw)} bytes)")
    return url


def save_images(data_urls) -> list:
    """批量保存图片，返回 URL 列表。单个失败不影响其他图片。

    Args:
        data_urls: base64 dataUrl 列表（或可迭代对象）

    Returns:
        URL 路径列表；非法图片会被跳过并在日志告警
    """
    if not data_urls:
        return []

    urls = []
    for img in list(data_urls)[:5]:  # 最多 5 张（与前端一致）
        try:
            urls.append(data_url_to_file(img))
        except ValueError as e:
            logger.warning(f"跳过非法图片: {e}")
    return urls
