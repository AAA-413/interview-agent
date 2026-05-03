import json
import logging
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.common.error_code import ErrorCode
from app.common.exception import BusinessException

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=DeclarativeBase)


class BasePersistenceService(Generic[T]):
    """泛型持久化服务基类，提供通用 CRUD 操作。

    子类需要设置:
        model: ORM 实体类
        not_found_error: 查询不到时的错误码
    """

    model: type[T]
    not_found_error: ErrorCode = ErrorCode.INTERNAL_ERROR

    async def find_by_id(self, db: AsyncSession, entity_id: int) -> T | None:
        result = await db.execute(select(self.model).where(self.model.id == entity_id))
        return result.scalar_one_or_none()

    async def find_by_id_or_throw(self, db: AsyncSession, entity_id: int) -> T:
        entity = await self.find_by_id(db, entity_id)
        if entity is None:
            raise BusinessException(self.not_found_error)
        return entity

    async def find_all(
        self,
        db: AsyncSession,
        order_by=None,
        limit: int | None = None,
    ) -> list[T]:
        query = select(self.model)
        if order_by is not None:
            query = query.order_by(order_by)
        else:
            query = query.order_by(self.model.id.desc())
        if limit is not None:
            query = query.limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def save(self, db: AsyncSession, entity: T) -> T:
        db.add(entity)
        await db.flush()
        return entity

    async def delete_by_id(self, db: AsyncSession, entity_id: int) -> None:
        entity = await self.find_by_id_or_throw(db, entity_id)
        await db.delete(entity)
        await db.flush()


def safe_json_loads(json_str: str | None, default=None):
    """安全解析 JSON 字符串，解析失败返回默认值。"""
    if not json_str:
        return default if default is not None else []
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []
