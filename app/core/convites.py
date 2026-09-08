"""Convite de login ao portal do tomador — a ponte com o Supabase Auth.

POR QUE ISOLADO, como app/core/storage.py: o router precisa poder ser testado
(e o convite, falsificado) sem rede e sem FastAPI aqui dentro. Este módulo só
sabe conversar com o GoTrue; quem traduz as falhas para HTTP é o router.

A CREDENCIAL É A MESMA DO STORAGE — a service_role key. Convidar um usuário é
operação de SERVIDOR (o endpoint /auth/v1/invite recusa a anon key), e vale o
mesmo aviso de app/core/config.py: a service_role atravessa RLS e NUNCA pode
aparecer em log, mensagem de erro ou frontend.

O QUE O CONVITE FAZ, do lado do Supabase: cria o usuário no Auth (ainda sem
senha) e envia o e-mail com o link mágico. O link leva o convidado a
/definir-senha (rota que o frontend já tem para recuperação — o SDK trata os
dois tipos de token do mesmo jeito), onde ele mesmo digita a senha: ela nunca
trafega por aqui. O `id` devolvido é o `sub` dos JWTs futuros — e por isso a
linha de `usuario` criada pelo router PRECISA nascer com este id, senão o
login autentica no Supabase e morre em PERMISSAO_NEGADA no backend.
"""

from uuid import UUID

import httpx

from app.core.config import settings


# Mesmo racional do storage: o default do httpx pode ser sem timeout, e uma
# chamada de convite pendurada seguraria o request do admin indefinidamente.
_TIMEOUT_SEGUNDOS = 15.0


class ConvitesNaoConfigurados(RuntimeError):
    """Falta a URL do projeto ou a service_role key.

    A mensagem é instrução de infraestrutura — é o `detail` do 503 que o
    router devolve, lido por quem administra o ambiente, não pelo operador.
    """

    def __init__(self) -> None:
        super().__init__(
            "Convite ao portal indisponível: o servidor está sem as credenciais "
            "do Supabase Auth (ORGCRED_SUPABASE_URL e ORGCRED_SUPABASE_SERVICE_KEY "
            "— o mesmo par usado pelo acervo de evidências). Configure-as e tente "
            "novamente; nenhum convite foi criado."
        )


class EmailJaRegistrado(RuntimeError):
    """O e-mail já tem conta no Supabase Auth.

    Caso distinto de 'já tem linha em usuario' (que o router pré-checa): aqui a
    conta existe SÓ no Auth — tipicamente um convite anterior interrompido no
    meio. A saída é operacional, não de formulário, e a mensagem diz qual é.
    """

    def __init__(self, email: str) -> None:
        super().__init__(
            f"O e-mail {email} já tem conta no serviço de autenticação, mas não tem "
            "login no OrgCred — provavelmente um convite anterior que não completou. "
            "Peça a remoção da conta no painel do Supabase (Authentication → Users) "
            "e convide de novo."
        )


class ConviteFalhou(RuntimeError):
    """O GoTrue respondeu erro que não sabemos traduzir, ou a rede falhou."""


def convidar_no_supabase(email: str, redirect_to: str) -> UUID:
    """Cria o usuário no Supabase Auth e dispara o e-mail de convite.

    Devolve o id do usuário criado — obrigatoriamente o `id` da linha de
    `usuario` que o chamador vai inserir (ver cabeçalho do módulo).
    """
    if not settings.storage_configurado:
        # `storage_configurado` E não um espelho novo: o par de credenciais é
        # LITERALMENTE o mesmo (URL do projeto + service_role). Uma segunda
        # property diria a quem configura que existem dois pares.
        raise ConvitesNaoConfigurados()

    try:
        resposta = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/invite",
            params={"redirect_to": redirect_to},
            json={"email": email},
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            },
            timeout=_TIMEOUT_SEGUNDOS,
        )
    except httpx.HTTPError as exc:
        # Sem repassar `exc` cru para a mensagem: erros do httpx podem embutir
        # a URL com credencial em querystring de redirect. Aqui não há, mas a
        # disciplina é não depender disso.
        raise ConviteFalhou(
            "Não foi possível falar com o serviço de autenticação. "
            "Verifique a conectividade do servidor e tente de novo."
        ) from exc

    if resposta.status_code == 200:
        corpo = resposta.json()
        return UUID(corpo["id"])

    # `error_code` é o campo estável do GoTrue moderno; casar substring da
    # mensagem seria o anti-padrão que app/api/errors.ts documenta.
    try:
        error_code = resposta.json().get("error_code")
    except ValueError:
        error_code = None
    if error_code == "email_exists":
        raise EmailJaRegistrado(email)

    raise ConviteFalhou(
        f"O serviço de autenticação recusou o convite (HTTP {resposta.status_code}). "
        "Tente de novo; persistindo, confira as credenciais do Supabase no servidor."
    )
