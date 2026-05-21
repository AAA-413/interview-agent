import logging
import re

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException

logger = logging.getLogger(__name__)


class FileValidationService:
    def validate_file(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str | None,
        max_size: int,
        allowed_types: list[str],
        file_type_name: str = "文件",
    ) -> str:
        if not file_bytes:
            raise BusinessException(ErrorCode.BAD_REQUEST, f"请选择要上传的{file_type_name}")

        if len(file_bytes) > max_size:
            raise BusinessException(ErrorCode.BAD_REQUEST, "文件大小超过限制")

        if content_type and not self._is_allowed_type(content_type, allowed_types):
            raise BusinessException(ErrorCode.BAD_REQUEST, f"不支持的文件类型: {content_type}")

        safe_name = self.sanitize_filename(filename)
        if content_type and "pdf" in content_type.lower() and not self._check_pdf_magic(file_bytes):
            raise BusinessException(ErrorCode.BAD_REQUEST, "PDF 文件格式无效")
        return safe_name

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """清理文件名，去除路径遍历字符和危险字符。"""
        name = filename.replace("\\", "/").split("/")[-1]
        name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
        name = name.strip(". ")
        return name or "unnamed"

    @staticmethod
    def _check_pdf_magic(file_bytes: bytes) -> bool:
        """检查 PDF 文件魔术字节（%PDF）。"""
        return len(file_bytes) >= 4 and file_bytes[:4] == b"%PDF"

    @staticmethod
    def _is_allowed_type(content_type: str, allowed_types: list[str]) -> bool:
        if not content_type:
            return False
        lower = content_type.lower().split(";")[0].strip()  # 去除 charset 等参数
        for allowed in allowed_types:
            if lower == allowed.lower():
                return True
        return False


file_validation_service = FileValidationService()
