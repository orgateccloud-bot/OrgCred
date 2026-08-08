"""
Exceções de negócio e autenticação.

Hierarquia: tudo herda de RegraNegocioViolada ou AutenticacaoErro.
Cada exceção mapeia para um HTTP status: 401/403/422/etc.
"""

from typing import Optional


class RegraNegocioViolada(Exception):
    """Base para exceções de regras de negócio violadas (teto, estado, etc.)."""

    def __init__(
        self,
        message: str,
        sqlstate: Optional[str] = None,
        http_status: int = 422,
    ) -> None:
        self.message = message
        self.sqlstate = sqlstate
        self.http_status = http_status
        super().__init__(message)


class TetoCapitalExcedido(RegraNegocioViolada):
    """OC001: Teto de capital excedido."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC001", http_status=422)


class MunicipioNaoAutorizado(RegraNegocioViolada):
    """OC002: Tomador fora da área de atuação."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC002", http_status=422)


class TransicaoInvalida(RegraNegocioViolada):
    """OC003: Transição de status inválida."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC003", http_status=409)


class RegistroEntidadeAusente(RegraNegocioViolada):
    """OC004: Ativação sem registro na entidade registradora."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC004", http_status=422)


class ReducaoCapitalBloqueada(RegraNegocioViolada):
    """OC005: Redução de capital abaixo do comprometido."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC005", http_status=422)


class NovacaoForaDaTransacaoAtomica(RegraNegocioViolada):
    """OC008: renegociação ou substituta criada fora de fn_novar_operacao.

    Renegociar em duas etapas separadas abre a janela em que a original e a
    substituta contam capital ao mesmo tempo — dupla contagem que fura o
    teto do Art. 5º sem ninguém agir de má-fé.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC008", http_status=422)


class OperacaoNaoEncontrada(Exception):
    """Operação não existe."""

    pass


class AutenticacaoErro(Exception):
    """Base para erros de autenticação/autorização."""

    def __init__(self, message: str, http_status: int = 401) -> None:
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class TokenAusente(AutenticacaoErro):
    """Authorization header ausente ou malformado."""

    def __init__(self) -> None:
        super().__init__(
            "Token de autenticação ausente ou inválido (Bearer <token> esperado)",
            http_status=401,
        )


class TokenInvalido(AutenticacaoErro):
    """JWT inválido ou expirado."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Token inválido: {reason}", http_status=401)


class PermissaoNegada(AutenticacaoErro):
    """Usuário não tem permissão para esta ação."""

    def __init__(self, message: str = "Permissão negada") -> None:
        super().__init__(message, http_status=403)
