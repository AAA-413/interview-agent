from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.common.exception import BusinessException
from app.common.result import Result


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=200,
            content=Result.error(message=exc.message, code=exc.error_code).model_dump(),
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        return JSONResponse(
            status_code=500,
            content=Result.error(message=f"数据库操作失败: {exc}", code=500).model_dump(),
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=Result.error(message=f"内部服务器错误: {exc}", code=500).model_dump(),
        )
