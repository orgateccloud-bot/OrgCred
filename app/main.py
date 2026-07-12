"""
Aplicação FastAPI — OrgCred ESC.

Monta a API e registra todos os routers. Validação de config ocorre no startup.
Integra: autenticação (JWT), rate limiting, CORS, logging estruturado, exception handlers.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from app.core.config import settings
from app.core.exceptions import (
    PermissaoNegada,
    RegraNegocioViolada,
    TokenAusente,
    TokenInvalido,
)
from app.core.logging import configure_logging, get_logger
from app.core.metrics import registrar_bloqueio, registrar_falha_auth
from app.db import engine
from app.routers import capital, cobranca, compliance, contratos, fiscal, operacoes, tomadores


# Configurar logging estruturado
configure_logging()
logger = get_logger("app.main")


limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Contexto de vida útil da aplicação: startup e shutdown."""
    # Startup
    logger.info(
        "app_startup",
        environment=settings.environment,
        database=settings.database_url.split("/")[-1],
    )
    yield
    # Shutdown
    logger.info("app_shutdown")


app = FastAPI(
    title="OrgCred",
    description="Módulo de microcrédito ESC (Empresa Simples de Crédito, LC 167/2019)",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        # Em produção, adicionar URLs do painel aqui
    ]
    if settings.environment == "development"
    else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registra routers
app.include_router(capital.router)
app.include_router(operacoes.router)
# Stubs — ver docstring de cada módulo para o bloqueador ou escopo pendente
app.include_router(tomadores.router)
app.include_router(contratos.router)
app.include_router(fiscal.router)
app.include_router(compliance.router)
app.include_router(cobranca.router)


@app.get("/health")
def health_check() -> Dict[str, str]:
    """
    Liveness probe: a aplicação está de pé? Não verifica dependências externas.
    Use /health/ready para readiness (verifica banco de dados).
    """
    return {"status": "ok", "service": "orgcred"}


@app.get("/health/ready")
def readiness_check() -> JSONResponse:
    """
    Readiness probe: a aplicação está pronta para receber tráfego?
    Verifica conectividade com o banco de dados.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return JSONResponse(status_code=200, content={"status": "ready", "database": "ok"})
    except Exception as e:
        logger.error("readiness_check_falhou", erro=str(e))
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "database": "unreachable"}
        )


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    """Métricas Prometheus para scraping."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root() -> Dict[str, str]:
    """Raiz da API."""
    return {
        "service": "OrgCred",
        "environment": settings.environment,
        "docs": "/docs",
    }


# Exception handlers para auth
@app.exception_handler(TokenAusente)
async def token_ausente_handler(request: Request, exc: TokenAusente) -> JSONResponse:
    """Token ausente ou malformado."""
    logger.warning("auth_token_ausente", path=str(request.url.path), method=request.method)
    registrar_falha_auth("token_ausente")
    return JSONResponse(status_code=401, content={"detail": exc.message, "codigo": "TOKEN_AUSENTE"})


@app.exception_handler(TokenInvalido)
async def token_invalido_handler(request: Request, exc: TokenInvalido) -> JSONResponse:
    """Token inválido ou expirado."""
    logger.warning("auth_token_invalido", path=str(request.url.path), reason=exc.message)
    registrar_falha_auth("token_invalido")
    return JSONResponse(
        status_code=401, content={"detail": exc.message, "codigo": "TOKEN_INVALIDO"}
    )


@app.exception_handler(PermissaoNegada)
async def permissao_negada_handler(request: Request, exc: PermissaoNegada) -> JSONResponse:
    """Usuário sem permissão."""
    logger.warning("auth_permissao_negada", path=str(request.url.path), reason=exc.message)
    registrar_falha_auth("permissao_negada")
    return JSONResponse(
        status_code=403, content={"detail": exc.message, "codigo": "PERMISSAO_NEGADA"}
    )


@app.exception_handler(RegraNegocioViolada)
async def regra_negocio_handler(request: Request, exc: RegraNegocioViolada) -> JSONResponse:
    """Regra de negócio violada."""
    logger.warning(
        "regra_negocio_violada",
        path=str(request.url.path),
        sqlstate=exc.sqlstate,
        message=exc.message,
    )
    if exc.sqlstate:
        registrar_bloqueio(exc.sqlstate)
    return JSONResponse(
        status_code=exc.http_status,
        content={"detail": exc.message, "codigo": exc.sqlstate},
    )


# Exception handler global para erros não tratados
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler genérico para exceções não capturadas."""
    logger.error("unhandled_exception", path=str(request.url.path), error=str(exc))
    if settings.environment == "development":
        raise
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno do servidor"},
    )
