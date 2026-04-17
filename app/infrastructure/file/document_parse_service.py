import logging
import re

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException

logger = logging.getLogger(__name__)

_IMAGE_FILENAME_LINE = re.compile(r"(?m)^image\d+\.(png|jpe?g|gif|bmp|webp)\s*$")
_IMAGE_URL = re.compile(r"https?://\S+?\.(png|jpe?g|gif|bmp|webp)(\?\S*)?", re.IGNORECASE)
_FILE_URL = re.compile(r"file:(//)?\S+", re.IGNORECASE)
_SEPARATOR_LINE = re.compile(r"(?m)^\s*[-_*=]{3,}\s*$")
_CONTROL_CHARS = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]")
_HTML_TAGS = re.compile(r"<[^>]+>")
_MULTI_BLANK_LINES = re.compile(r"\n{3,}")
_LEADING_TRAILING_WS_LINES = re.compile(r"(?m)^[ \t]+|[ \t]+$")


class TextCleaningService:
    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = _IMAGE_FILENAME_LINE.sub("", text)
        text = _IMAGE_URL.sub("", text)
        text = _FILE_URL.sub("", text)
        text = _SEPARATOR_LINE.sub("", text)
        text = _CONTROL_CHARS.sub("", text)
        text = _HTML_TAGS.sub("", text)
        text = _LEADING_TRAILING_WS_LINES.sub("", text)
        text = _MULTI_BLANK_LINES.sub("\n\n", text)
        return text.strip()


text_cleaning_service = TextCleaningService()


class DocumentParseService:
    MAX_TEXT_LENGTH = 5 * 1024 * 1024

    def __init__(self):
        self._cleaner = text_cleaning_service

    async def parse_content(self, file_bytes: bytes, filename: str = "") -> str:
        if not file_bytes:
            return ""
        try:
            content = await self._extract_text(file_bytes, filename)
            cleaned = self._cleaner.clean_text(content)
            if len(cleaned) > self.MAX_TEXT_LENGTH:
                cleaned = cleaned[: self.MAX_TEXT_LENGTH]
            logger.info("文件解析成功: %s, 文本长度: %d", filename, len(cleaned))
            return cleaned
        except BusinessException:
            raise
        except Exception as e:
            logger.error("文件解析失败: %s, error: %s", filename, str(e))
            raise BusinessException(ErrorCode.RESUME_PARSE_FAILED, f"文件解析失败: {e}")

    async def _extract_text(self, file_bytes: bytes, filename: str) -> str:
        lower = filename.lower() if filename else ""

        if lower.endswith(".pdf"):
            return await self._parse_pdf(file_bytes)
        elif lower.endswith(".docx"):
            return await self._parse_docx(file_bytes)
        elif lower.endswith(".doc"):
            return await self._parse_doc(file_bytes)
        elif lower.endswith(".txt") or lower.endswith(".md"):
            return self._parse_text(file_bytes)
        else:
            return await self._parse_by_tika(file_bytes)

    async def _parse_pdf(self, file_bytes: bytes) -> str:
        try:
            import fitz

            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages = [page.get_text() for page in doc]
            doc.close()
            return "\n".join(pages)
        except ImportError:
            return await self._parse_by_tika(file_bytes)

    async def _parse_docx(self, file_bytes: bytes) -> str:
        try:
            import io

            from docx import Document

            doc = Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            return await self._parse_by_tika(file_bytes)

    async def _parse_doc(self, file_bytes: bytes) -> str:
        return await self._parse_by_tika(file_bytes)

    def _parse_text(self, file_bytes: bytes) -> str:
        for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                return file_bytes.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return file_bytes.decode("utf-8", errors="replace")

    async def _parse_by_tika(self, file_bytes: bytes) -> str:
        try:
            import io

            from tika import parser as tika_parser

            parsed = tika_parser.from_buffer(io.BytesIO(file_bytes))
            return parsed.get("content", "") or ""
        except ImportError:
            raise BusinessException(
                ErrorCode.RESUME_PARSE_FAILED,
                "未安装文档解析库，请安装 pymupdf 和 python-docx，或安装 tika",
            )


document_parse_service = DocumentParseService()
