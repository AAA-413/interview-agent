import logging

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.config import settings

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
    ) -> None:
        if not file_bytes:
            raise BusinessException(ErrorCode.BAD_REQUEST, f"请选择要上传的{file_type_name}")

        if len(file_bytes) > max_size:
            raise BusinessException(ErrorCode.BAD_REQUEST, "文件大小超过限制")

        if content_type and not self._is_allowed_type(content_type, allowed_types):
            raise BusinessException(ErrorCode.BAD_REQUEST, f"不支持的文件类型: {content_type}")

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
