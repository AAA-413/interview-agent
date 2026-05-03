import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.common.exception import BusinessException
from app.common.result import Result

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):
        return JSONResponse(
            status_code=exc.status_code,
            content=Result.error(message=exc.message, code=exc.error_code).model_dump(),
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        logger.error("数据库操作异常: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=Result.error(message="数据库操作失败，请稍后重试", code=500).model_dump(),
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("未处理异常: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=Result.error(message="服务器内部错误，请稍后重试", code=500).model_dump(),
        )
