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

    Desde a migration 027 os dois últimos caminhos valem por QUALQUER porta, e
    não só pela função de baixa: a cobertura de valor passou a ser verificada
    também no trigger de linha. Até ali ela morava apenas em
    `fn_baixar_parcela`, e um `update parcela set status='paga',
    movimento_id=<tarifa de R$ 0,01>` atravessava as guardas — que perguntavam
    se existe movimento apontado, nunca quanto ele vale. O código é o MESMO de
    propósito: a recusa é a mesma frase e manda conferir a mesma coisa (o
    extrato), venha ela da função ou do trigger.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC011", http_status=422)


class MovimentoDuplicado(RegraNegocioViolada):
    """Documento de extrato já registrado (violação do UNIQUE de `documento`).

    Código próprio, e não OC011, porque reimportar o mesmo extrato — coisa
    rotineira na operação real — NÃO é "baixa sem lastro". Enquanto OC011 não
    estava no dicionário do frontend, a mensagem específica desta exceção
    vazava e disfarçava a confusão; assim que OC011 ganhou tradução, quem
    repetia um FITID passou a ler "a baixa não tem lastro bancário válido",
    que descreve outro problema e manda conferir a coisa errada. Um código
    que significa duas situações não produz uma mensagem correta para as duas.

    Não tem SQLSTATE: a violação é de constraint (23505), capturada como
    IntegrityError na aplicação, não levantada por trigger com `errcode`.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="MOVIMENTO_DUPLICADO", http_status=409)


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


class NovacaoSemLastro(RegraNegocioViolada):
    """OC024: novação que reduziria o comprometido sem o dinheiro ter voltado.

    Renegociar não é pagar. A substituta tem que cobrir o SALDO DEVEDOR da
    original — o principal menos o que foi amortizado contra movimento
    bancário (`parcela.valor_amortizacao` das parcelas pagas com
    `movimento_id`). Sem o gate da migration 026, `fn_novar_operacao` aceitava
    qualquer valor: renegociar R$ 30.000 por R$ 0,01, com as doze parcelas em
    aberto, devolvia os R$ 30.000 inteiros ao teto e permitia pôr R$ 80.000 na
    rua sobre R$ 50.000 de capital próprio.

    TRÊS RECUSAS SOB O MESMO CÓDIGO, pelo precedente do OC022 (que tem duas):
    substituta menor que o saldo devedor na novação; substituta menor que o
    saldo devedor na ativação (entre uma coisa e outra o valor de uma operação
    'registrada' ainda pode mudar — a 015 só congela quem ocupa o teto); e
    substituta órfã, cuja original não está mais em condição de ser trocada.
    As três são a mesma frase: esta troca reduziria o comprometido sem prova
    de pagamento.

    A ÓRFÃ TEM DOIS SUBCASOS, e a mensagem do banco os separa porque a
    instrução ao operador difere. Original liquidada, cancelada ou já trocada
    por outra substituta: saiu do comprometido, não há lugar a ceder e a
    substituta somaria por fora da conta do teto. Original BAIXADA COMO
    PREJUÍZO: ela CONTINUA no comprometido — 'baixada_prejuizo' está no
    conjunto que ocupa o teto desde a migration 017, e é disso que depende a
    regra de que write-off não devolve capital. Ali o problema é o inverso de
    um lugar vazio: a perda já foi reconhecida, o valor segue consumindo o
    teto e não volta, e ressuscitar a dívida como título novo somaria o mesmo
    dinheiro duas vezes. Dizer a esse operador que a original "já não ocupa o
    teto" o mandaria procurar o erro no lugar errado.

    422 e não 409, como OC001 e OC022: não é conflito de estado — o caminho
    'renegociar' existe e continua disponível assim que a substituta cobrir o
    saldo devedor, ou assim que parcelas forem baixadas contra o extrato. A
    saída para encerrar sem pagamento é outra e a mensagem a cita: a baixa
    como prejuízo, que não devolve capital.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC024", http_status=422)


class ParcelaForaDaEmissao(RegraNegocioViolada):
    """OC025: parcela inserida fora da emissão da agenda (migration 027).

    `fn_parcela_imutavel` nasceu (007) como `before update or delete` e a 016,
    que reescreveu a função inteira, manteve o gatilho — o INSERT nunca teve
    dono. A agenda que o banco emite na ativação aceitava APÊNDICE: uma décima
    terceira parcela num contrato de doze, que entrava no aging (008, que soma
    toda parcela 'aberta' vencida) e na apuração fiscal (011, que no regime
    caixa soma toda parcela 'paga'). Inventar inadimplência e inventar receita
    pelo mesmo comando.

    QUATRO RECUSAS SOB O MESMO CÓDIGO, todas a mesma frase para quem está do
    lado de fora — "a agenda é emitida pelo banco na ativação e nada se insere
    nela por fora": operação inexistente, operação que não está sendo ativada,
    agenda já completa (ou número acima do contratado) e parcela que tentaria
    nascer já paga.

    CÓDIGO PRÓPRIO E NÃO OC009, que é o vizinho óbvio e o errado. OC009 diz
    "parcela já emitida não pode ser alterada nem apagada", e a mensagem que a
    UI associa a ele manda o operador fazer a baixa da parcela contra o
    movimento bancário — exatamente o que quem tenta acrescentar uma parcela
    não deve fazer. Instrução diferente, código diferente.

    422 e não 409: não é conflito de estado, é regra sobre quem escreve a
    agenda. A saída para mudar as condições de uma operação ativa existe e é
    outra — renegociar, e a substituta nasce com agenda própria.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, sqlstate="OC025", http_status=422)


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
