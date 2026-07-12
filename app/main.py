"""
Aplicação FastAPI — OrgCred ESC.

Monta a API e registra todos os routers. Validação de config ocorre no startup.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.routers import operacoes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Contexto de vida útil da aplicação: startup e shutdown."""
    # Startup
    print(f"[OrgCred] Iniciando em ambiente: {settings.environment}")
    print(f"[OrgCred] Database: {settings.database_url.split('/')[-1]}")
    yield
    # Shutdown
    print("[OrgCred] Encerrando")


app = FastAPI(
    title="OrgCred",
    description="Módulo de microcrédito ESC (Empresa Simples de Crédito, LC 167/2019)",
    version="0.1.0",
    lifespan=lifespan,
)


# Registra routers
app.include_router(operacoes.router)


@app.get("/health")
def health_check() -> dict:
    """Verificação de saúde."""
    return {"status": "ok", "service": "orgcred"}


@app.get("/")
def root() -> dict:
    """Raiz da API."""
    return {
        "service": "OrgCred",
        "environment": settings.environment,
        "docs": "/docs",
    }


# Exception handler global para erros de banco
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handler genérico para exceções não capturadas."""
    if settings.environment == "development":
        raise
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno do servidor"},
    )
