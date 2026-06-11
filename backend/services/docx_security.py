from __future__ import annotations

import io
import zipfile


CFBF_SIGNATURE = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])


def check_docx_security(content: bytes) -> dict:
    if content.startswith(CFBF_SIGNATURE):
        return {"encrypted": True, "readable": False, "message": "该 Word 文档已加密，请先解除密码后再试。"}
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            archive.getinfo("word/document.xml")
    except Exception:
        return {"encrypted": False, "readable": False, "message": "无法读取该 Word 文档内容，文件可能损坏或不是标准 .docx 文件。"}
    return {"encrypted": False, "readable": True, "message": None}
