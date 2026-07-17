"""
Aplicação FastAPI — OrgCred ESC.

Monta a API e registra todos os routers. Validação de config ocorre no startup.
Integra: autenticação (JWT), rate limiting, CORS, logging estruturado, exception handlers.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import (
    PermissaoNegada,
    RegraNegocioViolada,
    TokenAusente,
    TokenInvalido,
)
from app.core.logging import configure_logging, get_logger
from app.core.metrics import registrar_bloqueio, registrar_falha_auth
from app.core.security import get_current_user
from app.db import engine
from app.routers import (
    auditoria,
    capital,
    cobranca,
    compliance,
    contratos,
    fiscal,
    operacoes,
    tomadores,
)


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
        "http://localhost:5173",  # Vite dev server (frontend/)
        # Em produção, adicionar URLs do painel aqui
    ]
    if settings.environment == "development"
    else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registra routers com segurança Zero-Trust, sob /api — necessário desde a
# Fase F4: o frontend serve rotas client-side em caminhos que colidem
# literalmente com endpoints da API (/operacoes, /auditoria). Sem o
# prefixo, um refresh de página nessas rotas do SPA batia direto no
# endpoint da API (JSON 401) em vez de cair no fallback do index.html.
# /health, /health/ready e /metrics ficam fora do prefixo de propósito —
# são endpoints de infraestrutura (probes, scraping), não do app.
app.include_router(capital.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(operacoes.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(tomadores.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(contratos.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(fiscal.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(compliance.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(cobranca.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(auditoria.router, prefix="/api", dependencies=[Depends(get_current_user)])


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


# ---------------------------------------------------------------------------
# Frontend (Fase F4): serve o build do Vite (frontend/dist/, copiado para
# static/ na imagem Docker — ver Dockerfile) num único serviço, sem CORS ou
# domínio extra. Registrado por último de propósito: rotas de API já
# declaradas acima (/health, /capital/..., etc.) sempre têm precedência
# sobre o fallback do SPA, já que o Starlette casa rotas na ordem de
# registro. Em dev/CI, static/ não existe — a raiz responde com um JSON
# simples em vez de tentar servir um build que não foi gerado.
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class _SPAStaticFiles(StaticFiles):
    """Qualquer caminho sem arquivo correspondente cai para index.html —
    o roteamento real (TanStack Router) acontece no cliente."""

    async def get_response(self, path: str, scope) -> JSONResponse:  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


if _STATIC_DIR.is_dir():
    app.mount("/", _SPAStaticFiles(directory=str(_STATIC_DIR), html=True), name="spa")
else:

    @app.get("/")
    def root() -> Dict[str, str]:
        """Raiz da API (dev/CI — sem build do frontend disponível)."""
        return {
            "service": "OrgCred",
            "environment": settings.environment,
            "docs": "/docs",
        }
