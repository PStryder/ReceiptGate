"""Main entry point for ReceiptGate service."""

from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from receiptgate import __version__
from receiptgate.config import settings
from receiptgate.db import init_db
from receiptgate.middleware import configure_middleware
from receiptgate.mcp.routes import router as mcp_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ReceiptGate",
        description="Canonical receipt ledger for obligation truth (MemoryGate profile)",
        version=__version__,
        lifespan=lifespan,
    )

    configure_middleware(app)
    app.include_router(mcp_router)

    @app.get("/health")
    def health():
        return {"ok": True, "service": settings.service_name}

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        payload = {
            "ok": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": {"errors": exc.errors()},
            },
        }
        return JSONResponse(status_code=422, content=payload)

    return app


app = create_app()


def main():
    uvicorn.run(
        "receiptgate.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
