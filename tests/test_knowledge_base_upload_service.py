from app.common.model import AsyncTaskStatus
from app.modules.knowledge_base.models import KnowledgeBaseEntity
from app.modules.knowledge_base.upload_service import KnowledgeBaseUploadService


class FakeDB:
    def __init__(self):
        self.commit_count = 0

    async def commit(self):
        self.commit_count += 1


class FakeFileHashService:
    def calculate_hash(self, file_bytes: bytes) -> str:
        return "same-kb-file-hash"


class FakeFileValidationService:
    def validate_file(self, **kwargs) -> str:
        return kwargs["filename"]


class FakeFileStorageService:
    async def upload_knowledge_base(self, file_bytes: bytes, safe_filename: str, content_type: str | None):
        return "knowledgebases/key.md", "https://storage.local/knowledgebases/key.md"


class FakeDocumentParseService:
    async def parse_content(self, file_bytes: bytes, filename: str) -> str:
        return "parsed knowledge base text"


class FakeKnowledgeBasePersistenceService:
    def __init__(self, existing_by_user: dict[int, KnowledgeBaseEntity] | None = None):
        self.existing_by_user = existing_by_user or {}
        self.find_calls: list[tuple[str, int | None]] = []
        self.saved: KnowledgeBaseEntity | None = None

    async def find_by_file_hash(self, db, file_hash: str, user_id: int | None = None):
        self.find_calls.append((file_hash, user_id))
        return self.existing_by_user.get(user_id)

    async def save(self, db, entity: KnowledgeBaseEntity) -> KnowledgeBaseEntity:
        entity.id = 200
        self.saved = entity
        return entity

    async def update_index_status(
        self, db, kb_id: int, status: AsyncTaskStatus, error: str | None = None
    ) -> None:
        return None


def _patch_upload_dependencies(monkeypatch, persistence: FakeKnowledgeBasePersistenceService) -> None:
    monkeypatch.setattr("app.modules.knowledge_base.upload_service.file_hash_service", FakeFileHashService())
    monkeypatch.setattr("app.modules.knowledge_base.upload_service.file_validation_service", FakeFileValidationService())
    monkeypatch.setattr("app.modules.knowledge_base.upload_service.file_storage_service", FakeFileStorageService())
    monkeypatch.setattr("app.modules.knowledge_base.upload_service.document_parse_service", FakeDocumentParseService())
    monkeypatch.setattr("app.modules.knowledge_base.upload_service.knowledge_base_persistence_service", persistence)


async def test_knowledge_base_upload_deduplicates_only_within_current_user(monkeypatch):
    persistence = FakeKnowledgeBasePersistenceService(
        existing_by_user={
            1: KnowledgeBaseEntity(
                id=1,
                user_id=1,
                name="KB",
                file_hash="same-kb-file-hash",
                original_filename="kb.md",
                index_status=AsyncTaskStatus.COMPLETED,
            )
        }
    )
    _patch_upload_dependencies(monkeypatch, persistence)

    service = KnowledgeBaseUploadService()
    service._enqueue_index = _noop_enqueue
    entity = await service.upload(
        FakeDB(),
        file_bytes=b"same markdown",
        filename="kb.md",
        content_type="text/markdown",
        name=None,
        description=None,
        user_id=2,
    )

    assert persistence.find_calls == [("same-kb-file-hash", 2)]
    assert persistence.saved is entity
    assert entity.user_id == 2
    assert entity.file_hash == "same-kb-file-hash"
    assert entity.source_text == "parsed knowledge base text"
    assert entity.index_status == AsyncTaskStatus.PENDING


async def test_knowledge_base_upload_reuses_same_user_document(monkeypatch):
    existing = KnowledgeBaseEntity(
        id=2,
        user_id=2,
        name="KB",
        file_hash="same-kb-file-hash",
        original_filename="kb.md",
        index_status=AsyncTaskStatus.COMPLETED,
    )
    persistence = FakeKnowledgeBasePersistenceService(existing_by_user={2: existing})
    _patch_upload_dependencies(monkeypatch, persistence)

    entity = await KnowledgeBaseUploadService().upload(
        FakeDB(),
        file_bytes=b"same markdown",
        filename="kb.md",
        content_type="text/markdown",
        name=None,
        description=None,
        user_id=2,
    )

    assert persistence.find_calls == [("same-kb-file-hash", 2)]
    assert entity is existing
    assert persistence.saved is None


async def _noop_enqueue(kb_id: int) -> None:
    return None
