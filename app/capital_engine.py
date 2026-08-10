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

Capital COMPROMETIDO = operações em 'ativa' OU 'inadimplente'. Inadimplente
entra porque o dinheiro não voltou: o título saiu de 'ativa', mas continua
ocupando o teto do Art. 5º até ser efetivamente liquidado. Antes da
migration 006 o comprometido contava só 'ativa', e marcar inadimplência
liberava o capital de um empréstimo não pago — permitindo emprestá-lo de
novo (furo comprovado contra Postgres real, ver 006_novacao_e_inadimplencia.sql).
"""

from datetime import date
from decimal import Decimal
from typing import NamedTuple, Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.core.db_errors import extrair_sqlstate, traduzir_erro_banco
from app.core.exceptions import BaixaInvalida, OperacaoNaoEncontrada
from app.core.metrics import registrar_ativacao
from app.models import EscCapitalSocial, OperacaoCredito


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
                         where status in ('ativa', 'inadimplente')), 0) as disponivel
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
                      where status in ('ativa', 'inadimplente')), 0) as comprometido
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
    origem: str = "manual",
    usuario_id: Optional[str] = None,
) -> UUID:
    """
    Registra uma linha de extrato. Devolve o id do movimento.

    `documento` é UNIQUE no banco: reimportar o mesmo extrato — coisa
    rotineira na operação real — não duplica crédito. A violação de unique
    sobe como IntegrityError e é traduzida aqui para uma mensagem que diz o
    que de fato aconteceu, em vez de vazar o nome da constraint.
    """
    try:
        movimento_id = db.execute(
            text("""
            insert into movimento_bancario
                (data_movimento, valor, documento, descricao, origem, usuario_id)
            values (:data, :valor, :documento, :descricao, :origem, :usuario)
            returning id
            """),
            {
                "data": data_movimento,
                "valor": valor,
                "documento": documento,
                "descricao": descricao,
                "origem": origem,
                "usuario": usuario_id,
            },
        ).scalar_one()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BaixaInvalida(
            f"Já existe um movimento bancário com o documento '{documento}'."
        ) from exc
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc
    return movimento_id  # type: ignore[no-any-return]


def baixar_parcela(db: Session, parcela_id: UUID, movimento_id: UUID) -> None:
    """
    Dá uma parcela por paga, amarrada a um movimento bancário.

    Toda a validação vive em `fn_baixar_parcela` (migration 009) — parcela
    em aberto, movimento existente, movimento ainda não usado, valor
    suficiente. Replicar essas checagens aqui criaria uma segunda fonte de
    verdade que dessincroniza, e a aplicação não é a única porta do banco.
    """
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
