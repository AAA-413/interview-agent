from app.common.model import AsyncTaskStatus
from app.modules.resume.models import ResumeEntity
from app.modules.resume.upload_service import ResumeUploadService


class FakeDB:
    def __init__(self):
        self.flush_count = 0
        self.commit_count = 0

    async def flush(self):
        self.flush_count += 1

    async def commit(self):
        self.commit_count += 1


class FakeFileHashService:
    def calculate_hash(self, file_bytes: bytes) -> str:
        return "same-file-hash"


class FakeFileValidationService:
    def validate_file(self, **kwargs) -> str:
        return kwargs["filename"]


class FakeFileStorageService:
    async def upload_resume(self, file_bytes: bytes, safe_filename: str, content_type: str | None):
        return "resume/key.pdf", "https://storage.local/resume/key.pdf"


class FakeDocumentParseService:
    async def parse_content(self, file_bytes: bytes, filename: str) -> str:
        return "parsed resume text"


class FakeResumePersistenceService:
    def __init__(self, existing_by_user: dict[int, ResumeEntity] | None = None):
        self.existing_by_user = existing_by_user or {}
        self.find_calls: list[tuple[str, int | None]] = []
        self.saved: ResumeEntity | None = None

    async def find_by_file_hash(self, db, file_hash: str, user_id: int | None = None):
        self.find_calls.append((file_hash, user_id))
        return self.existing_by_user.get(user_id)

    async def save_resume(self, db, entity: ResumeEntity) -> ResumeEntity:
        entity.id = 100
        self.saved = entity
        return entity

    async def update_analyze_status(self, db, resume_id: int, status: AsyncTaskStatus, error: str | None = None):
        return None


def _patch_upload_dependencies(monkeypatch, persistence: FakeResumePersistenceService) -> None:
    monkeypatch.setattr("app.modules.resume.upload_service.file_hash_service", FakeFileHashService())
    monkeypatch.setattr("app.modules.resume.upload_service.file_validation_service", FakeFileValidationService())
    monkeypatch.setattr("app.modules.resume.upload_service.file_storage_service", FakeFileStorageService())
    monkeypatch.setattr("app.modules.resume.upload_service.document_parse_service", FakeDocumentParseService())
    monkeypatch.setattr("app.modules.resume.upload_service.resume_persistence_service", persistence)


async def test_upload_deduplicates_only_within_current_user(monkeypatch):
    persistence = FakeResumePersistenceService(
        existing_by_user={
            1: ResumeEntity(
                id=1,
                user_id=1,
                file_hash="same-file-hash",
                original_filename="resume.pdf",
                access_count=0,
                analyze_status=AsyncTaskStatus.COMPLETED,
            )
        }
    )
    _patch_upload_dependencies(monkeypatch, persistence)

    entity = await ResumeUploadService().upload(FakeDB(), b"same pdf", "resume.pdf", "application/pdf", user_id=2)

    assert persistence.find_calls == [("same-file-hash", 2)]
    assert persistence.saved is entity
    assert entity.user_id == 2
    assert entity.file_hash == "same-file-hash"
    assert entity.resume_text == "parsed resume text"
    assert entity.analyze_status == AsyncTaskStatus.PENDING


async def test_upload_reuses_same_user_resume(monkeypatch):
    existing = ResumeEntity(
        id=2,
        user_id=2,
        file_hash="same-file-hash",
        original_filename="resume.pdf",
        access_count=0,
        analyze_status=AsyncTaskStatus.COMPLETED,
    )
    persistence = FakeResumePersistenceService(existing_by_user={2: existing})
    _patch_upload_dependencies(monkeypatch, persistence)

    db = FakeDB()
    entity = await ResumeUploadService().upload(db, b"same pdf", "resume.pdf", "application/pdf", user_id=2)

    assert entity is existing
    assert existing.access_count == 1
    assert db.flush_count == 1
    assert persistence.saved is None
