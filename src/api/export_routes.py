"""CSV 导出文件下载路由。"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.tools.export_tools import is_export_valid

export_router = APIRouter()


@export_router.get("/exports/{file_id}", summary="下载导出的 CSV 文件")
def download_export(file_id: str):
    """
    下载由 export_to_csv 工具生成的 CSV 文件。

    - 文件有效期 1 小时，过期后返回 404
    - file_id 为 32 位十六进制字符串
    """
    # 只允许合法的 file_id 格式，防止路径遍历攻击
    if not file_id.isalnum() or len(file_id) != 32:
        raise HTTPException(status_code=400, detail="无效的文件 ID")

    filepath = is_export_valid(file_id)
    if not filepath:
        raise HTTPException(status_code=404, detail="文件不存在或已过期，请重新导出")

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件已被清理，请重新导出")

    return FileResponse(
        path=filepath,
        media_type="text/csv; charset=utf-8-sig",
        filename="export.csv",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''export.csv"},
    )
