from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import check_database
from app.batches.router import router as batches_router
from app.master_data.router import router as master_data_router
from app.alarms.router import router as alarms_router
from app.ingestion.router import router as ingestion_router
from app.twin.router import notify_state_changed, router as twin_router
from app.auth.bootstrap import ensure_bootstrap_account
from app.auth.router import router as auth_router
from app.audit.router import router as audit_router
from app.reports.router import router as reports_router

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    if settings.environment != "test":
        if settings.environment == "production" and (
            settings.jwt_secret == "change-this-development-secret"
            or settings.bootstrap_admin_password == "change-this-development-password"
        ):
            raise RuntimeError("Production requires JWT_SECRET and BOOTSTRAP_ADMIN_PASSWORD")
        from app.core.database import get_session_factory
        with get_session_factory()() as session:
            ensure_bootstrap_account(session)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(batches_router, prefix="/api/v1")
app.include_router(master_data_router, prefix="/api/v1")
app.include_router(alarms_router, prefix="/api/v1")
app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(twin_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    if request.method in {"POST", "PATCH"} and 200 <= response.status_code < 300:
        notify_state_changed()
    return response


def error_response(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", str(uuid4())),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return error_response(request, "http_error", str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(request, "validation_error", "请求参数校验失败", 422)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, "internal_error", "服务器内部错误", 500)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    try:
        check_database()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="数据库暂不可用") from exc
    return {"status": "ok", "database": "ok"}
