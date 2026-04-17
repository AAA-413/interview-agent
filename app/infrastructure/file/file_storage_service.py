import logging
import uuid
from datetime import datetime

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException
from app.config import settings

logger = logging.getLogger(__name__)


class FileStorageService:
    def __init__(self):
        self._s3_client = None

    def _get_s3_client(self):
        if self._s3_client is None:
            try:
                import boto3

                self._s3_client = boto3.client(
                    "s3",
                    endpoint_url=settings.storage.endpoint,
                    aws_access_key_id=settings.storage.access_key,
                    aws_secret_access_key=settings.storage.secret_key,
                    region_name=settings.storage.region,
                )
            except ImportError:
                raise BusinessException(ErrorCode.INTERNAL_ERROR, "未安装 boto3 库")
        return self._s3_client

    async def upload_resume(self, file_bytes: bytes, filename: str, content_type: str | None = None) -> tuple[str, str]:
        return await self._upload_file(file_bytes, filename, content_type, "resumes")

    async def upload_knowledge_base(
        self, file_bytes: bytes, filename: str, content_type: str | None = None
    ) -> tuple[str, str]:
        return await self._upload_file(file_bytes, filename, content_type, "knowledgebases")

    async def _upload_file(
        self, file_bytes: bytes, filename: str, content_type: str | None, prefix: str
    ) -> tuple[str, str]:
        try:
            ext = ""
            if "." in filename:
                ext = filename[filename.rfind("."):]
            date_prefix = datetime.now().strftime("%Y/%m/%d")
            unique_name = f"{uuid.uuid4().hex}{ext}"
            key = f"{prefix}/{date_prefix}/{unique_name}"

            s3 = self._get_s3_client()
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type

            s3.put_object(
                Bucket=settings.storage.bucket,
                Key=key,
                Body=file_bytes,
                **extra_args,
            )

            url = f"{settings.storage.endpoint}/{settings.storage.bucket}/{key}"
            return key, url
        except BusinessException:
            raise
        except Exception as e:
            logger.error("文件上传失败: %s", str(e))
            raise BusinessException(ErrorCode.INTERNAL_ERROR, f"文件上传失败: {e}")

    async def download_file(self, storage_key: str) -> bytes:
        try:
            s3 = self._get_s3_client()
            resp = s3.get_object(Bucket=settings.storage.bucket, Key=storage_key)
            return resp["Body"].read()
        except Exception as e:
            logger.error("文件下载失败: key=%s, error=%s", storage_key, str(e))
            raise BusinessException(ErrorCode.INTERNAL_ERROR, f"文件下载失败: {e}")

    async def delete_file(self, storage_key: str) -> None:
        try:
            s3 = self._get_s3_client()
            s3.delete_object(Bucket=settings.storage.bucket, Key=storage_key)
        except Exception as e:
            logger.warning("删除存储文件失败: key=%s, error=%s", storage_key, str(e))


file_storage_service = FileStorageService()
