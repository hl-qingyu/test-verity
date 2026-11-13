import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.router import router
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.session import check_database

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    handler = configure_logging("api")
    try:
        yield
    finally:
        logger.info("service_stopped service=api")
        logging.getLogger("app").removeHandler(handler)
        handler.close()


app = FastAPI(
    title="Test Verity API", version="0.2.0", description="账号登录与工程骨架", lifespan=lifespan
)
app.include_router(router)


@app.exception_handler(AppError)
async def application_error(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("request_rejected status=%s code=%s", exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers
    )


@app.middleware("http")
async def auth_no_store(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    started, status = monotonic(), 500
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        logger.exception("request_failed")
        raise
    finally:
        # Use the registered template, never the actual URL, query, headers or body.
        route = getattr(request.scope.get("route"), "path", "unmatched")
        logger.info(
            "request method=%s route=%s status=%s elapsed_ms=%.1f",
            request.method,
            route,
            status,
            (monotonic() - started) * 1000,
        )
    if request.url.path.startswith(
        ("/api/auth/", "/api/users", "/api/ai-service", "/api/github", "/api/projects")
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.error("database_error", exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=503, content={"detail": "service_unavailable"})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default validation response includes submitted password values.
    return JSONResponse(status_code=422, content={"detail": "invalid_request"})


@app.get("/api/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "test-verity-api"}


@app.get("/api/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    try:
        check_database()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database_unavailable") from None
    return {"status": "ready"}
