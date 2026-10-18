from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1 import router as v1_router
from app.db import engine
from app.domain.errors import DomainError

app = FastAPI(title="Francisco System", description="Cuentas del negocio de huevos.")
app.include_router(v1_router)


@app.exception_handler(DomainError)
async def domain_error(_: Request, error: DomainError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": error.message})


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok"}
