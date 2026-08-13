"""
Aplicação FastAPI — OrgCred ESC.

Monta a API e registra todos os routers. Validação de config ocorre no startup.
Integra: autenticação (JWT), rate limiting, CORS, logging estruturado, exception handlers.

A montagem vive em `criar_app()` (fábrica) e não no corpo do módulo porque o
endurecimento do passo 14 é CONDICIONAL AO AMBIENTE: `/docs`, `/redoc`,
`/openapi.json` e o limitador de requisições ligam ou desligam conforme
`settings.environment`. Com a montagem no import, provar "em produção /docs
responde 404" exigiria recarregar o módulo inteiro no meio da suíte — um
truque que passa a impressão de teste e não prova nada, porque o `app` que o
resto da suíte usa continuaria sendo o de desenvolvimento. Com a fábrica, o
teste constrói uma segunda aplicação em modo produção e interroga a de
verdade. `app = criar_app()` no fim preserva `from app.main import app`.
"""

from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import AsyncGenerator, Dict

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Scope

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
    me,
    operacoes,
    tomadores,
)


# Configurar logging estruturado
configure_logging()
logger = get_logger("app.main")


# ---------------------------------------------------------------------------
# Rate limiting — antes do passo 14 isto era código morto: o `Limiter` estava
# instanciado, nenhuma rota decorada e o middleware nunca registrado, de modo
# que a dependência do slowapi existia só no pyproject. Agora o
# `SlowAPIMiddleware` é registrado de fato (ver `criar_app`).
#
# LIMITES ESCOLHIDOS (conservadores de propósito — a ESC é single-tenant, com
# um punhado de operadores humanos; qualquer volume acima disto é robô):
#   - leitura  120/min: o painel faz polling de capital, operações e auditoria
#     simultaneamente; 3 requisições a cada poucos segundos cabem com folga.
#   - escrita   30/min: ativar operação, baixar recebimento, emitir contrato.
#     Nenhum humano faz 30 dessas por minuto no mesmo endpoint; um laço que
#     faz é engano ou ataque, e cada uma delas move capital.
# O slowapi já isola o balde por CAMINHO (o "scope" do limite é o path da
# requisição) e a biblioteca `limits` embute quantidade+janela na chave de
# armazenamento — leitura e escrita do mesmo path caem em baldes distintos
# sem precisar de key_func customizada.
METODOS_DE_ESCRITA = frozenset({"POST", "PUT", "PATCH", "DELETE"})
LIMITE_LEITURA = "120/minute"
LIMITE_ESCRITA = "30/minute"

# O slowapi 0.1.9 é cego à requisição fora da `key_func`: `default_limits`
# aceita um provedor CALLABLE, mas o chama sem argumento nenhum. Este
# ContextVar é a ponte — `LimiteAdaptativo.dispatch` o preenche imediatamente
# antes de delegar ao dispatch do slowapi, que consulta os limites de forma
# SÍNCRONA dentro da mesma corrotina (sem task filha no meio), então o valor
# lido é sempre o da requisição corrente. Sem isso só existiria um número
# único para leitura e escrita.
_classe_do_metodo: ContextVar[str] = ContextVar("orgcred_classe_metodo", default="leitura")


def _limite_da_requisicao() -> str:
    """Limite aplicável à requisição corrente, por classe de método HTTP."""
    return LIMITE_ESCRITA if _classe_do_metodo.get() == "escrita" else LIMITE_LEITURA


class LimiteAdaptativo(SlowAPIMiddleware):
    """SlowAPIMiddleware que classifica o método antes de avaliar o limite."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        _classe_do_metodo.set(
            "escrita" if request.method.upper() in METODOS_DE_ESCRITA else "leitura"
        )
        return await super().dispatch(request, call_next)


def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """429 no mesmo envelope do resto da API (`detail` + `codigo`).

    Precisa ser SÍNCRONO: o `SlowAPIMiddleware` chama `sync_check_limits`, que
    descarta handlers assíncronos e cai no default do slowapi — que devolve
    `{"error": "Rate limit exceeded: 30 per 1 minute"}`, contando ao atacante
    exatamente qual é a janela. Aqui a resposta não revela o limite.
    """
    logger.warning(
        "rate_limit_excedido",
        path=str(request.url.path),
        method=request.method,
        client=get_remote_address(request),
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Muitas requisições. Tente novamente em instantes.", "codigo": "OC429"},
        headers={"Retry-After": "60"},
    )


# ---------------------------------------------------------------------------
# Frontend (Fase F4): serve o build do Vite (frontend/dist/, copiado para
# static/ na imagem Docker — ver Dockerfile) num único serviço, sem CORS ou
# domínio extra. Em dev/CI, static/ não existe.
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class _SPAStaticFiles(StaticFiles):
    """Qualquer caminho sem arquivo correspondente cai para index.html —
    o roteamento real (TanStack Router) acontece no cliente."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


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


def criar_app() -> FastAPI:
    """Monta a aplicação conforme o ambiente vigente em `settings`."""
    modo_producao = settings.environment == "production"

    # Esquema interativo desligado em produção. /openapi.json entrega o mapa
    # completo da API — todos os caminhos, todos os campos de todos os
    # schemas — a quem não apresentou credencial nenhuma; /docs e /redoc são
    # a mesma informação com botão de "experimentar". Em desenvolvimento os
    # três continuam ligados de propósito: o cliente Hey API do frontend é
    # gerado a partir de /openapi.json (ver frontend/openapi-ts.config.ts),
    # e essa geração roda contra o backend local.
    app = FastAPI(
        title="OrgCred",
        description="Módulo de microcrédito ESC (Empresa Simples de Crédito, LC 167/2019)",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if modo_producao else "/docs",
        redoc_url=None if modo_producao else "/redoc",
        openapi_url=None if modo_producao else "/openapi.json",
    )

    # Rate limiting. Ligado só em produção: em desenvolvimento a suíte e o
    # e2e do Playwright disparam centenas de requisições da mesma origem para
    # o mesmo caminho em segundos, e um 429 no meio de um teste seria um
    # falso vermelho difícil de ler. O teste que prova o 429 constrói uma
    # aplicação em modo produção justamente para exercitar a configuração
    # real, e não uma variante frouxa.
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[_limite_da_requisicao],
        enabled=modo_producao,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(LimiteAdaptativo)

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
    # /health e /health/ready ficam fora do prefixo de propósito — são
    # endpoints de infraestrutura (probes), não do app. /metrics também fica
    # fora do prefixo, mas NÃO fica fora da autenticação (ver abaixo).
    app.include_router(capital.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(operacoes.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(tomadores.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(contratos.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(fiscal.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(compliance.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(cobranca.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(auditoria.router, prefix="/api", dependencies=[Depends(get_current_user)])
    app.include_router(me.router, prefix="/api", dependencies=[Depends(get_current_user)])

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

    # /metrics EXIGE credencial, em todos os ambientes — não é desligado em
    # produção. Desligar resolveria a exposição e mataria junto a única
    # observabilidade do serviço: `orgcred_operacoes_bloqueadas_total` por
    # SQLSTATE é o sinal de que um invariante legal está sendo tocado em
    # produção, e `orgcred_auth_falhas_total` é o sinal de ataque. Aberto,
    # porém, o mesmo endpoint conta a qualquer um sem credencial quantas
    # operações a ESC ativou e quantas recusas de teto o motor deu — volume
    # de negócio e postura de risco, deduzíveis de contadores públicos.
    # O scraper do Prometheus autentica como qualquer outro cliente: um JWT
    # de conta de serviço no header Authorization (`bearer_token` no
    # scrape_config). Sem dependência de config nova, sem segundo mecanismo
    # de segredo para alguém esquecer de rotacionar.
    @app.get("/metrics", dependencies=[Depends(get_current_user)])
    def metrics() -> PlainTextResponse:
        """Métricas Prometheus para scraping (requer autenticação)."""
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # Exception handlers para auth
    @app.exception_handler(TokenAusente)
    async def token_ausente_handler(request: Request, exc: TokenAusente) -> JSONResponse:
        """Token ausente ou malformado."""
        logger.warning("auth_token_ausente", path=str(request.url.path), method=request.method)
        registrar_falha_auth("token_ausente")
        return JSONResponse(
            status_code=401, content={"detail": exc.message, "codigo": "TOKEN_AUSENTE"}
        )

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

    # Exception handler global para erros não tratados.
    #
    # O detalhe interno fica no LOG e nunca no corpo da resposta: `str(exc)`
    # de um erro de driver carrega a query, o nome da tabela e às vezes o
    # valor que a violou. Em desenvolvimento o `raise` devolve o traceback ao
    # console de quem está depurando — quem chama é o próprio dev. Em
    # produção a resposta é a mesma string genérica para qualquer causa: um
    # 500 que varia de texto conforme a falha é um oráculo de enumeração.
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

    # Monta o SPA por último de propósito: rotas de API já declaradas acima
    # (/health, /metrics, /api/...) sempre têm precedência sobre o fallback do
    # SPA, já que o Starlette casa rotas na ordem de registro. Em dev/CI,
    # static/ não existe — a raiz responde com um JSON simples em vez de
    # tentar servir um build que não foi gerado.
    #
    # Efeito colateral do fallback em produção: com o build presente, GET
    # /docs não dá 404 e sim o index.html do painel, porque não há rota /docs
    # registrada e tudo que sobra cai no SPA. Não é vazamento — o que estava
    # exposto era o ESQUEMA (/openapi.json), e ele deixou de existir.
    if _STATIC_DIR.is_dir():
        app.mount("/", _SPAStaticFiles(directory=str(_STATIC_DIR), html=True), name="spa")
    else:

        @app.get("/")
        def root() -> Dict[str, str]:
            """Raiz da API (dev/CI — sem build do frontend disponível)."""
            # Sem `environment` no corpo: é a raiz pública (não passa por
            # get_current_user) e dizer a um anônimo em que ambiente ele
            # está é entregar de graça metade do reconhecimento.
            return {"service": "OrgCred", "docs": app.docs_url or "desativado"}

    return app


app = criar_app()
