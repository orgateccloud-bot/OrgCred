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


class ParcelaImutavel(RegraNegocioViolada):
    """OC009: tentativa de alterar ou apagar parcela já emitida."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC009", http_status=422)


class BaixaInvalida(RegraNegocioViolada):
    """OC011: baixa de recebimento sem lastro bancário válido.

    Cobre os quatro caminhos: parcela inexistente ou já baixada, movimento
    inexistente, movimento já usado em outra parcela, e movimento de valor
    menor que a parcela. Dar uma parcela como paga sem lastro faria a régua
    de inadimplência (migration 008) parar de ver o atraso.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC011", http_status=422)


class MovimentoImutavel(RegraNegocioViolada):
    """OC012: extrato bancário é fato de fora — registra-se, não se edita."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC012", http_status=422)


class LedgerImutavel(RegraNegocioViolada):
    """OC007: capital_ledger é append-only (UPDATE/DELETE/TRUNCATE).

    O ledger é a prova documental de conformidade com o teto do Art. 5º. Um
    erro dele chegando à API como 500 diria "falha interna" a quem acabou de
    tentar apagar a trilha — a mensagem precisa ser a da regra.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC007", http_status=422)


class EventoOperacaoImutavel(RegraNegocioViolada):
    """OC010: a trilha de eventos da operação (migration 008) é append-only."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC010", http_status=422)


class DocumentoEmRetencao(RegraNegocioViolada):
    """OC013: evidência de identificação dentro do prazo de retenção legal.

    Cobre os dois caminhos do trigger da 010: apagar antes dos 5 anos (Lei
    9.613/98, art. 10, III) e alterar uma evidência arquivada — que se
    substitui por uma nova, nunca se edita.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC013", http_status=422)


class OcorrenciaImutavel(RegraNegocioViolada):
    """OC014: ocorrência de atipicidade é append-only.

    Só o par de campos do adaptador do canal externo (comunicado_em,
    comunicacao_ref) pode ser preenchido depois — uma trilha de PLD que se
    edita não serve como defesa.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC014", http_status=422)


class ApuracaoSemParametro(RegraNegocioViolada):
    """OC015: apuração fiscal sem parâmetro vigente.

    Percentuais de presunção e alíquotas são matéria tributária — sem eles,
    recusar é a única resposta honesta. Calcular com um padrão embutido no
    código produziria um valor plausível e errado, que é pior do que erro.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC015", http_status=422)


class ApuracaoImutavel(RegraNegocioViolada):
    """OC016: apuração fiscal não se edita — retificação cria nova versão."""

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC016", http_status=422)


class ContratoImutavel(RegraNegocioViolada):
    """OC017: instrumento emitido não se edita — reemitir cria nova versão.

    O tomador tem uma via do documento antigo; editar o original destruiria
    a prova do que foi efetivamente acordado.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC017", http_status=422)


class RegistroTransicaoInvalida(RegraNegocioViolada):
    """OC018: transição inválida no registro em entidade registradora.

    Confirmado e rejeitado são terminais: reverter um registro confirmado
    apagaria a prova de que a operação existe legalmente (Art. 5º §3º,
    LC 167/2019).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC018", http_status=409)


class IdentificacaoAusente(RegraNegocioViolada):
    """OC019: ativar operação de tomador sem evidência de identificação.

    Código próprio, e não OC004: são regras e leis diferentes. OC004 é
    registro em entidade registradora (LC 167/2019, art. 5º §3º); esta é
    identificação do cliente (Lei 9.613/98, art. 10, I). Compartilhar código
    faria a UI dar a instrução errada ao operador.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC019", http_status=422)


class LiquidacaoSemQuitacao(RegraNegocioViolada):
    """OC022: liquidar operação cujas parcelas não foram todas baixadas.

    Liquidação é QUITAÇÃO: devolve o valor principal ao teto do Art. 5º
    (LC 167/2019) e por isso exige a prova de que o dinheiro voltou — todas
    as parcelas pagas, cada uma contra um movimento bancário. Sem o gate da
    migration 017, `ativa -> liquidada` liberava 100% do capital com a agenda
    inteira em aberto e zero centavo comprovado.

    422 e não 409: não é conflito de estado (o destino 'liquidada' é
    legítimo e continuará disponível assim que as parcelas forem baixadas) —
    é regra de negócio sobre a prova que falta, como OC001 e OC004. A saída
    para encerrar sem pagamento existe e é outra: a baixa como prejuízo
    ('baixada_prejuizo'), que encerra a cobrança e NÃO devolve capital.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC022", http_status=422)


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
