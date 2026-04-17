from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Result(BaseModel, Generic[T]):
    code: int = 0
    message: str = "success"
    data: T | None = None

    @classmethod
    def success(cls, data: T = None, message: str = "success") -> "Result[T]":
        return cls(code=0, message=message, data=data)

    @classmethod
    def error(cls, message: str = "error", code: int = -1) -> "Result[Any]":
        return cls(code=code, message=message, data=None)
