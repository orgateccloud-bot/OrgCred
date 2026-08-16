"""
Camada de serviço para o ciclo de vida de uma operação de crédito.

Princípio: a API executa a transição de status e DEIXA O BANCO decidir.
Os triggers (migrations 001+003) são a fonte única de verdade sobre:
teto de capital, gate geográfico, máquina de estados e exigência de
registro na entidade registradora.

Identificação de erro por SQLSTATE (classe 'OC'), não por substring da
mensagem — a revisão de 2026-07-11 apontou que matching por texto quebra
silenciosamente se a mensagem do trigger mudar. Códigos:
  OC001 teto de capital excedido
  OC002 tomador fora da área de atuação
  OC003 transição de status inválida
  OC004 ativação sem registro na entidade registradora
  OC005 redução de capital abaixo do comprometido
  OC008 renegociação/substituta fora da novação atômica
  OC022 liquidação sem quitação comprovada (migration 017)

Capital COMPROMETIDO = operações em 'ativa', 'inadimplente' OU
'baixada_prejuizo'. Inadimplente entra porque o dinheiro não voltou: o título
saiu de 'ativa', mas continua ocupando o teto do Art. 5º até ser efetivamente
liquidado. Antes da migration 006 o comprometido contava só 'ativa', e marcar
inadimplência liberava o capital de um empréstimo não pago — permitindo
emprestá-lo de novo (furo comprovado contra Postgres real, ver
006_novacao_e_inadimplencia.sql).

'baixada_prejuizo' (write-off, migration 017) entra pela mesma razão levada ao
limite: o dinheiro não só continua fora como não vai voltar. Encerrar a
cobrança é ato de gestão; devolver o capital ao teto seria autorizar emprestar
de novo o mesmo dinheiro que já se perdeu. O teto encolhe permanentemente a
cada baixa como prejuízo, e recuperar capacidade exige APORTE de capital — é
consequência decidida, não efeito colateral (DECISOES_PENDENTES.md §6).

DOIS CONJUNTOS QUE DEIXARAM DE SER O MESMO, e é a distinção que estas queries
precisam respeitar: 'baixada_prejuizo' ocupa o teto mas NÃO está em cobrança
(fica fora de `v_aging_operacoes` e de `fn_processar_aging`, migration 008).
Quem for acrescentar um status novo tem que responder às duas perguntas
separadamente.
"""

from datetime import date
from decimal import Decimal
from typing import Dict, NamedTuple, Optional, Sequence
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db_errors import extrair_sqlstate, traduzir_erro_banco
from app.core.exceptions import MovimentoDuplicado, OperacaoNaoEncontrada
from app.core.metrics import registrar_ativacao
from app.models import EscCapitalSocial, OperacaoCredito
from app.ofx import TransacaoOfx


# Tradução SQLSTATE -> exceção vive em app/core/db_errors.py desde que
# cobrança e fiscal passaram a precisar dela. Os aliases privados ficam para
# não reescrever as ~8 chamadas internas, e porque o docstring de conftest.py
# referencia este nome.
_extrair_sqlstate = extrair_sqlstate
_traduz_erro_banco = traduzir_erro_banco


def consultar_capital_disponivel(db: Session) -> Decimal:
    """Leitura informativa para UX — a validação real é o trigger.

    Nota de revisão: entre esta leitura e a ativação, outra transação
    pode consumir o capital exibido. O advisory lock garante que o teto
    nunca é violado, mas NÃO garante que o valor mostrado ao usuário
    ainda estará disponível ao clicar. A UI deve tratar OC001 como
    resultado normal, não como erro inesperado.
    """
    row = db.execute(
        text("""
        select (select capital_atual from v_capital_atual)
             - coalesce((select sum(valor_principal) from operacao_credito
                         where status in ('ativa', 'inadimplente', 'baixada_prejuizo')),
                        0) as disponivel
    """)
    ).first()
    if row is None:
        return Decimal("0")
    return Decimal(row.disponivel)


class CapitalSnapshot(NamedTuple):
    """Leitura informativa para UX (dashboard) — mesma ressalva de
    `consultar_capital_disponivel`: pode ficar desatualizada entre a
    leitura e uma ativação concorrente."""

    total: Decimal
    comprometido: Decimal
    disponivel: Decimal


def consultar_capital_snapshot(db: Session) -> CapitalSnapshot:
    """Total (capital social), comprometido (operações ativas) e
    disponível (total - comprometido) — usado pelo dashboard para a
    barra de utilização do teto."""
    row = db.execute(
        text("""
        select
            (select capital_atual from v_capital_atual) as total,
            coalesce((select sum(valor_principal) from operacao_credito
                      where status in ('ativa', 'inadimplente', 'baixada_prejuizo')),
                     0) as comprometido
    """)
    ).first()
    if row is None:
        return CapitalSnapshot(Decimal("0"), Decimal("0"), Decimal("0"))
    total = Decimal(row.total)
    comprometido = Decimal(row.comprometido)
    return CapitalSnapshot(total=total, comprometido=comprometido, disponivel=total - comprometido)


def ativar_operacao(
    db: Session, operacao_id: UUID, usuario_id: Optional[str] = None
) -> OperacaoCredito:
    """
    Tenta 'registrada' -> 'ativa'; o banco valida tudo que importa.

    `usuario_id` (tipicamente str(Usuario.id), ver app/core/security.py)
    é propagado ao trigger via `set_config('app.user_id', ..., true)`
    (equivalente a `SET LOCAL`, válido só nesta transação) — a migration
    004 usa `current_setting('app.user_id', true)` para registrar o autor
    no capital_ledger. Sem isso, a trilha de auditoria segue funcionando,
    só sem autor (equivalente ao comportamento antes da Fase 6).

    Usa `set_config()` (função regular) em vez do comando `SET LOCAL var =
    :valor` porque o Postgres não aceita parâmetro bind ($1) dentro de um
    comando SET — só literais. Com psycopg2 isso passava despercebido
    (driver antigo enviava os parâmetros já interpolados client-side); com
    psycopg3 (driver atual) o protocolo extended query manda um bind real,
    e o Postgres rejeita com "syntax error at or near $1". `set_config` é
    uma função normal, aceita bind parameter sem esse problema.

    Sempre executa o set_config (com o valor ou com NULL) para não
    depender do estado anterior da conexão física: como as conexões vêm de
    um pool, uma sessão sem usuario_id poderia herdar o valor setado por uma
    ativação anterior na mesma conexão se o guard fosse condicional.
    """
    db.execute(
        text("select set_config('app.user_id', :usuario_id, true)"),
        {"usuario_id": usuario_id},
    )

    op: Optional[OperacaoCredito] = (
        db.query(OperacaoCredito).filter(OperacaoCredito.id == operacao_id).one_or_none()
    )
    if op is None:
        raise OperacaoNaoEncontrada(f"Operação {operacao_id} não existe.")

    op.status = "ativa"  # type: ignore[assignment]
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    db.refresh(op)
    registrar_ativacao()
    return op


def transicionar_operacao(
    db: Session,
    operacao_id: UUID,
    novo_status: str,
    usuario_id: Optional[str] = None,
    registro_entidade_ref: Optional[str] = None,
) -> OperacaoCredito:
    """
    Transição genérica de status — mesma disciplina de ativar_operacao:
    a aplicação só escreve o status desejado; a máquina de estados real
    (quais transições são válidas, OC003) vive no trigger. Não há lista
    de status válidos aqui de propósito — duplicá-la criaria uma segunda
    fonte de verdade que dessincroniza em silêncio.

    `registro_entidade_ref` só faz sentido na transição para 'registrada'
    (exigência do Art. 5º §3º para a futura ativação); é ignorado nas
    demais.
    """
    db.execute(
        text("select set_config('app.user_id', :usuario_id, true)"),
        {"usuario_id": usuario_id},
    )

    op: Optional[OperacaoCredito] = (
        db.query(OperacaoCredito).filter(OperacaoCredito.id == operacao_id).one_or_none()
    )
    if op is None:
        raise OperacaoNaoEncontrada(f"Operação {operacao_id} não existe.")

    if novo_status == "registrada" and registro_entidade_ref:
        op.registro_entidade_ref = registro_entidade_ref  # type: ignore[assignment]
    op.status = novo_status  # type: ignore[assignment]
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    db.refresh(op)
    return op


def criar_operacao(
    db: Session,
    *,
    tomador_id: UUID,
    tipo: str,
    valor_principal: Decimal,
    taxa_juros_mensal: Decimal,
    sistema_amortizacao: str,
    numero_parcelas: int,
) -> OperacaoCredito:
    """
    Cria a operação no status inicial 'proposta'. O trigger valida que
    INSERTs só nascem em proposta/registrada (OC003); teto e gate
    geográfico só são checados na ativação — proposta não compromete
    capital.
    """
    # id gerado client-side: o default uuid_generate_v4() existe só no DDL —
    # o model não o declara, então o ORM enviaria NULL explícito e o default
    # do banco não se aplicaria.
    op = OperacaoCredito(
        id=uuid4(),
        tomador_id=tomador_id,
        tipo=tipo,
        valor_principal=valor_principal,
        taxa_juros_mensal=taxa_juros_mensal,
        sistema_amortizacao=sistema_amortizacao,
        numero_parcelas=numero_parcelas,
        status="proposta",
    )
    db.add(op)
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    db.refresh(op)
    return op


def registrar_evento_capital(db: Session, *, valor: Decimal, tipo_evento: str) -> EscCapitalSocial:
    """
    Insere evento no histórico de capital social. A proteção real (OC005:
    redução não pode deixar o capital abaixo do comprometido) é o trigger
    trg_check_reducao_capital — aqui só se traduz o erro.
    """
    evento = EscCapitalSocial(id=uuid4(), valor=valor, tipo_evento=tipo_evento)
    db.add(evento)
    try:
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    db.refresh(evento)
    return evento


def registrar_movimento_bancario(
    db: Session,
    *,
    data_movimento: date,
    valor: Decimal,
    documento: str,
    descricao: Optional[str] = None,
    usuario_id: Optional[str] = None,
) -> UUID:
    """
    Registra uma linha de extrato DIGITADA. Devolve o id do movimento.

    `documento` é UNIQUE no banco: reimportar o mesmo extrato — coisa
    rotineira na operação real — não duplica crédito. A violação de unique
    sobe como IntegrityError e é traduzida aqui para uma mensagem que diz o
    que de fato aconteceu, em vez de vazar o nome da constraint.

    `origem` DEIXOU DE SER PARÂMETRO na migration 024, e a fixação em 'manual'
    é o ponto: esta função é o caminho da digitação, e não coleta arquivo
    nenhum. Desde a 024, `origem = 'ofx'` exige `arquivo_sha256` — deixar o
    valor aberto aqui só ofereceria um jeito de carimbar de importado algo que
    ninguém importou (recusado pelo banco com 23514, que a API devolveria como
    500). Importação de extrato tem função própria: `importar_extrato_ofx`.
    """
    try:
        movimento_id = db.execute(
            text("""
            insert into movimento_bancario
                (data_movimento, valor, documento, descricao, origem, usuario_id)
            values (:data, :valor, :documento, :descricao, 'manual', :usuario)
            returning id
            """),
            {
                "data": data_movimento,
                "valor": valor,
                "documento": documento,
                "descricao": descricao,
                "usuario": usuario_id,
            },
        ).scalar_one()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise MovimentoDuplicado(
            f"Já existe um movimento bancário com o documento '{documento}'."
        ) from exc
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc
    return movimento_id  # type: ignore[no-any-return]


class ResultadoImportacaoOfx(NamedTuple):
    """O que a importação de um extrato fez — em números, sempre todos.

    Nenhum campo é omitido quando zera. Um relatório que só mostra o que
    aconteceu deixa o operador sem distinguir "o arquivo não tinha débito" de
    "débito não foi considerado", e é justamente nessa dúvida que ele decide
    se precisa lançar algo à mão.

    Os quatro últimos números fecham em `lidas`:
        lidas = criados + ja_registrados + repetidos_no_arquivo + debitos_ignorados
    """

    lidas: int
    creditos: int
    criados: int
    ja_registrados: int
    repetidos_no_arquivo: int
    debitos_ignorados: int
    periodo_inicio: Optional[date]
    periodo_fim: Optional[date]


def importar_extrato_ofx(
    db: Session,
    *,
    transacoes: Sequence[TransacaoOfx],
    arquivo_sha256: str,
    usuario_id: Optional[str] = None,
) -> ResultadoImportacaoOfx:
    """
    Cria movimentos bancários a partir das transações lidas de um OFX.

    NÃO BAIXA PARCELA NENHUMA, de propósito. Amarrar crédito a parcela continua
    sendo ato do operador (`POST /cobranca/parcelas/{id}/baixar`): a conciliação
    automática por valor erraria exatamente onde dói — duas parcelas de mesmo
    valor, pagamento parcial, juros de mora — e a baixa é o único ato
    irreversível do ciclo (não há estorno, migration 009). O import entrega o
    lastro; quem decide contra o quê ele vale é gente, com nome na trilha.

    TRÊS DECISÕES QUE VALEM A PENA ESTAREM ESCRITAS:

    1) REIMPORTAR É ROTINA, NÃO ERRO. O extrato do mês seguinte contém os dias
       do anterior; o operador reimporta o mesmo arquivo por dúvida; o banco
       reemite com mais uma linha. Nos três casos o certo é criar o que falta e
       PULAR o resto. Daí `on conflict (documento) do nothing` em vez do
       `IntegrityError` de `registrar_movimento_bancario`: a duplicidade de um
       lançamento digitado é engano de quem digitou e merece 409; a de um
       arquivo é o funcionamento normal e merece um número no relatório.

    2) SÓ CRÉDITO ENTRA. `movimento_bancario` tem check `valor > 0` (009) e
       débito não baixa parcela — importar despesa da ESC nesta tabela criaria
       linhas que nenhum caminho consome e poluiria a lista de movimentos
       disponíveis para conciliação. Débito é contabilidade, não recebimento.
       Os ignorados são CONTADOS: sumir com eles em silêncio faria o operador
       procurar por um lançamento que o sistema decidiu descartar sem dizer.

    3) UM ÚNICO INSERT, e não um laço de N inserts. É o que impede o arquivo
       grande de virar timeout: um extrato anual com milhares de linhas custa
       UMA ida ao banco (`unnest` das colunas em paralelo) em vez de milhares
       de round-trips, cada um com seu commit. O `returning id` devolve
       exatamente as linhas criadas, o que dá a contagem sem uma segunda
       consulta e sem confiar em `rowcount`.

    A DEDUPLICAÇÃO DENTRO DO ARQUIVO é feita aqui, em Python, antes do INSERT.
    Não é só defesa contra o `ON CONFLICT` sobre linhas repetidas no mesmo
    comando: é o que permite contar `repetidos_no_arquivo` separado de
    `ja_registrados`. Os dois viram "não criado", mas significam coisas
    diferentes — o segundo é reimportação normal, o primeiro é um FITID
    duplicado pelo BANCO, anomalia do arquivo que o operador deve enxergar.
    """
    lidas = len(transacoes)
    creditos = [t for t in transacoes if t.valor > 0]
    debitos_ignorados = lidas - len(creditos)

    # Primeira ocorrência vence: se o mesmo FITID aparece duas vezes com dados
    # divergentes, a de cima é a que o banco emitiu primeiro no arquivo.
    unicas: Dict[str, TransacaoOfx] = {}
    for transacao in creditos:
        unicas.setdefault(transacao.fitid, transacao)
    repetidos_no_arquivo = len(creditos) - len(unicas)

    datas = [t.data_movimento for t in transacoes] if transacoes else []
    periodo_inicio = min(datas) if datas else None
    periodo_fim = max(datas) if datas else None

    def _resultado(criados: int) -> ResultadoImportacaoOfx:
        return ResultadoImportacaoOfx(
            lidas=lidas,
            creditos=len(creditos),
            criados=criados,
            ja_registrados=len(unicas) - criados,
            repetidos_no_arquivo=repetidos_no_arquivo,
            debitos_ignorados=debitos_ignorados,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
        )

    if not unicas:
        # Arquivo sem crédito novo: nem chega ao banco. Um INSERT com arrays
        # vazios funcionaria, mas gastar uma transação para não escrever nada
        # não é de graça num endpoint que a UI pode chamar em sequência.
        return _resultado(0)

    valores = list(unicas.values())
    try:
        criadas = db.execute(
            text("""
            insert into movimento_bancario
                (data_movimento, valor, documento, descricao, origem, usuario_id,
                 conta_origem, arquivo_sha256)
            select t.data, t.valor, t.documento, t.descricao, 'ofx', :usuario,
                   t.conta, :sha
              from unnest(
                     cast(:datas as date[]),
                     cast(:valores as numeric[]),
                     cast(:documentos as text[]),
                     cast(:descricoes as text[]),
                     cast(:contas as text[])
                   ) as t(data, valor, documento, descricao, conta)
             on conflict (documento) do nothing
             returning id
            """),
            {
                "usuario": usuario_id,
                "sha": arquivo_sha256,
                "datas": [t.data_movimento for t in valores],
                "valores": [t.valor for t in valores],
                "documentos": [t.fitid for t in valores],
                "descricoes": [t.descricao for t in valores],
                "contas": [t.conta for t in valores],
            },
        ).all()
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    return _resultado(len(criadas))


def baixar_parcela(
    db: Session, parcela_id: UUID, movimento_id: UUID, usuario_id: Optional[str] = None
) -> None:
    """
    Dá uma parcela por paga, amarrada a um movimento bancário.

    Toda a validação vive em `fn_baixar_parcela` (migration 009) — parcela
    em aberto, movimento existente, movimento ainda não usado, valor
    suficiente. Replicar essas checagens aqui criaria uma segunda fonte de
    verdade que dessincroniza, e a aplicação não é a única porta do banco.

    `usuario_id` é propagado ao banco pelo MESMO mecanismo das transições de
    status (`set_config('app.user_id', ..., true)`, equivalente a SET LOCAL —
    ver a nota longa em `ativar_operacao` sobre por que é `set_config()` e não
    o comando `SET LOCAL`, e por que roda sempre, com valor ou com NULL, em
    vez de condicionalmente: as conexões vêm de um pool e uma baixa sem
    usuário herdaria o autor da anterior na mesma conexão física).
    Desde a migration 016, `fn_baixar_parcela` lê essa GUC e grava
    `parcela.baixado_por`.

    A autoria importa mais aqui do que em qualquer outra transição: a baixa é
    o único ato irreversível do ciclo (não há estorno definido — ver 009), e
    até a 016 era o único sem nome de gente. Uma conciliação errada é
    permanente; sem autor, não havia a quem perguntar.
    """
    db.execute(
        text("select set_config('app.user_id', :usuario_id, true)"),
        {"usuario_id": usuario_id},
    )

    try:
        db.execute(
            text("select fn_baixar_parcela(:parcela, :movimento)"),
            {"parcela": str(parcela_id), "movimento": str(movimento_id)},
        )
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc


def processar_aging(db: Session, limite_dias: int = 90) -> int:
    """
    Roda a régua automática: operações 'ativa' com atraso >= `limite_dias`
    passam a 'inadimplente'. Devolve quantas foram transicionadas.

    Toda a lógica vive em `fn_processar_aging` (migration 008). Fazer o
    laço aqui exigiria ler as operações, decidir em Python e escrever de
    volta — três viagens em que o atraso poderia mudar entre a leitura e a
    escrita, e uma segunda definição de "estar em atraso" fora do banco.

    Não existe caminho automático de volta: a regularização é decisão de
    uma pessoa e fica na trilha com o nome dela.
    """
    try:
        total = db.execute(
            text("select fn_processar_aging(:limite)"), {"limite": limite_dias}
        ).scalar_one()
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc
    return int(total)


def novar_operacao(
    db: Session,
    operacao_id: UUID,
    *,
    valor_principal: Decimal,
    taxa_juros_mensal: Decimal,
    sistema_amortizacao: str,
    numero_parcelas: int,
    registro_entidade_ref: Optional[str] = None,
    usuario_id: Optional[str] = None,
) -> OperacaoCredito:
    """
    Renegocia por novação ATÔMICA: baixa a original e cria a substituta na
    mesma transação, sob o mesmo advisory lock do teto.

    Toda a lógica vive em `fn_novar_operacao` (migration 006), não aqui. Se
    a aplicação fizesse as duas etapas em chamadas separadas, existiria uma
    janela em que a original e a substituta contam capital ao mesmo tempo —
    dupla contagem que fura o Art. 5º. O banco decide, como no resto do
    motor.

    A substituta nasce em 'registrada': ainda não compromete capital, e a
    ativação dela segue passando pelos gates normais (teto, município,
    registro na entidade registradora).
    """
    db.execute(
        text("select set_config('app.user_id', :usuario_id, true)"),
        {"usuario_id": usuario_id},
    )

    try:
        nova_id = db.execute(
            text("select fn_novar_operacao(:op, :valor, :taxa, :sistema, :parcelas, :registro)"),
            {
                "op": str(operacao_id),
                "valor": valor_principal,
                "taxa": taxa_juros_mensal,
                "sistema": sistema_amortizacao,
                "parcelas": numero_parcelas,
                "registro": registro_entidade_ref,
            },
        ).scalar_one()
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    nova: Optional[OperacaoCredito] = (
        db.query(OperacaoCredito).filter(OperacaoCredito.id == nova_id).one_or_none()
    )
    if nova is None:  # pragma: no cover - a função acabou de criar a linha
        raise OperacaoNaoEncontrada(f"Substituta {nova_id} não encontrada após a novação.")
    return nova
