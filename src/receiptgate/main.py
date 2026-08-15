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
from receiptgate.mcp.routes import router as mcp_router
from receiptgate.metagate_client import acknowledge_startup, bootstrap_from_metagate
from receiptgate.middleware import configure_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    # Resolve peer endpoints from MetaGate before anything that uses them.
    # Best-effort by design: a failure must never prevent startup, or the
    # bootstrap authority becomes a hidden master.
    _bootstrap = await bootstrap_from_metagate(settings)
    if _bootstrap is not None and _bootstrap.succeeded:
        await acknowledge_startup(settings, _bootstrap)

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
