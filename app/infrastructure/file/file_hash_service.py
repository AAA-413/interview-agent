import hashlib

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException


class FileHashService:
    @staticmethod
    def calculate_hash(data: bytes) -> str:
        try:
            digest = hashlib.sha256(data).hexdigest()
            return digest
        except Exception as e:
            raise BusinessException(ErrorCode.INTERNAL_ERROR, f"计算文件哈希失败: {e}")


file_hash_service = FileHashService()
