"""
Camada de serviço para o ciclo de vida de uma operação de crédito.

Princípio: a API executa a transição de status e DEIXA O BANCO decidir.
Os triggers (migrations 001+003+006) são a fonte única de verdade sobre:
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
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple, Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    MunicipioNaoAutorizado,
    OperacaoNaoEncontrada,
    ReducaoCapitalBloqueada,
    RegistroEntidadeAusente,
    TetoCapitalExcedido,
    TransicaoInvalida,
)
from app.core.metrics import registrar_ativacao, registrar_liquidacao, registrar_renegociacao
from app.models import EscCapitalSocial, OperacaoCredito


_PGCODE_MAP = {
    "OC001": TetoCapitalExcedido,
    "OC002": MunicipioNaoAutorizado,
    "OC003": TransicaoInvalida,
    "OC004": RegistroEntidadeAusente,
    "OC005": ReducaoCapitalBloqueada,
}


def _extrair_sqlstate(exc: DBAPIError) -> Optional[str]:
    """
    Extrai o código SQLSTATE da exceção original do driver.

    psycopg3 (psycopg, o driver em uso — ver pyproject.toml) expõe o código
    via `.sqlstate`; psycopg2 expunha via `.pgcode`. Checa ambos para não
    quebrar silenciosamente se o driver mudar de novo — um bug real desta
    natureza (só `.pgcode`) já vazou para produção quando o projeto migrou
    de psycopg2 para psycopg3 sem atualizar este ponto.
    """
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


def _traduz_erro_banco(exc: DBAPIError) -> Exception:
    sqlstate = _extrair_sqlstate(exc)
    exc_cls = _PGCODE_MAP.get(sqlstate) if sqlstate else None
    msg = str(getattr(exc, "orig", exc)).splitlines()[0]
    if exc_cls:
        return exc_cls(msg)
    return exc


def consultar_capital_disponivel(db: Session) -> Decimal:
    """Leitura informativa para UX — a validação real é o trigger.

    Usa fn_capital_comprometido() (migration 006) — a MESMA definição de
    comprometimento dos triggers (status ativa OU inadimplente), para a
    leitura nunca divergir do que o gate de ativação vai decidir.

    Nota de revisão: entre esta leitura e a ativação, outra transação
    pode consumir o capital exibido. O advisory lock garante que o teto
    nunca é violado, mas NÃO garante que o valor mostrado ao usuário
    ainda estará disponível ao clicar. A UI deve tratar OC001 como
    resultado normal, não como erro inesperado.
    """
    row = db.execute(
        text("""
        select (select capital_atual from v_capital_atual)
             - fn_capital_comprometido() as disponivel
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
    """Total (capital social), comprometido (fn_capital_comprometido —
    operações ativas E inadimplentes, migration 006) e disponível
    (total - comprometido) — usado pelo dashboard para a barra de
    utilização do teto."""
    row = db.execute(
        text("""
        select
            (select capital_atual from v_capital_atual) as total,
            fn_capital_comprometido() as comprometido
    """)
    ).first()
    if row is None:
        return CapitalSnapshot(Decimal("0"), Decimal("0"), Decimal("0"))
    total = Decimal(row.total)
    comprometido = Decimal(row.comprometido)
    return CapitalSnapshot(total=total, comprometido=comprometido, disponivel=total - comprometido)


def _propagar_usuario(db: Session, usuario_id: Optional[str]) -> None:
    """
    Propaga o autor da ação ao trigger via `set_config('app.user_id', ...,
    true)` (equivalente a `SET LOCAL`, válido só nesta transação) — a
    migration 004 usa `current_setting('app.user_id', true)` para registrar
    o autor no capital_ledger. Sem isso, a trilha de auditoria segue
    funcionando, só sem autor.

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
    _propagar_usuario(db, usuario_id)

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
    if novo_status == "liquidada":
        registrar_liquidacao()
    return op


def ativar_operacao(
    db: Session, operacao_id: UUID, usuario_id: Optional[str] = None
) -> OperacaoCredito:
    """
    Tenta a transição para 'ativa'; o banco valida tudo que importa
    (teto OC001, município OC002, estado OC003, registro OC004).

    Também é o caminho da regularização (inadimplente -> 'ativa'): nesse
    caso o trigger não re-executa gates nem grava evento — o capital já
    estava comprometido (migration 006).
    """
    op = transicionar_operacao(db, operacao_id, "ativa", usuario_id)
    registrar_ativacao()
    return op


def liquidar_operacao(
    db: Session, operacao_id: UUID, usuario_id: Optional[str] = None
) -> OperacaoCredito:
    """
    'ativa'|'inadimplente' -> 'liquidada'. Libera o capital comprometido;
    o trigger grava o evento 'liquidacao' no ledger sob o lock do teto.
    """
    return transicionar_operacao(db, operacao_id, "liquidada", usuario_id)


def marcar_inadimplente(
    db: Session, operacao_id: UUID, usuario_id: Optional[str] = None
) -> OperacaoCredito:
    """
    'ativa' -> 'inadimplente'. NÃO libera capital (migration 006): a
    operação em atraso continua comprometendo o teto até liquidação ou
    renegociação — interpretação conservadora do Art. 5º.
    """
    return transicionar_operacao(db, operacao_id, "inadimplente", usuario_id)


def regularizar_operacao(
    db: Session, operacao_id: UUID, usuario_id: Optional[str] = None
) -> OperacaoCredito:
    """
    'inadimplente' -> 'ativa' (cura do atraso). Movimento interno ao
    conjunto comprometido: nenhum gate re-executa e nenhum evento de
    capital é gravado — não há capital novo.
    """
    return transicionar_operacao(db, operacao_id, "ativa", usuario_id)


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


@dataclass(frozen=True)
class TermosRenegociacao:
    """Termos negociados da nova operação criada pela novação."""

    valor_principal: Decimal
    taxa_juros_mensal: Decimal
    numero_parcelas: int
    sistema_amortizacao: str
    registro_entidade_ref: str


def renegociar_operacao(
    db: Session,
    operacao_id: UUID,
    termos: TermosRenegociacao,
    usuario_id: Optional[str] = None,
) -> tuple[OperacaoCredito, OperacaoCredito]:
    """
    Novação atômica — a regra explícita exigida pela REVISAO_2026-07-11
    (item 3) para o capital nunca ser contado em dobro:

      1. antiga ('ativa'|'inadimplente') -> 'renegociada'
         O trigger toma o advisory lock do teto AQUI e grava
         'renegociacao_liberacao' no ledger — a partir deste ponto a
         novação inteira está serializada contra qualquer outra
         movimentação de capital.
      2. nova operação criada como 'registrada' (mesmo tomador/tipo,
         termos negociados, registro_entidade_ref PRÓPRIO — novação é
         contrato novo, o Art. 5º §3º exige registro novo).
      3. nova -> 'ativa': o gate completo re-executa (OC001/OC002/OC004)
         já enxergando a antiga fora do conjunto comprometido.

    Tudo em UMA transação: se qualquer passo falhar (ex. OC001 porque os
    novos termos excedem o disponível), o rollback restaura a antiga —
    nenhum estado commitado jamais tem as duas operações comprometendo
    capital ao mesmo tempo, e nenhum capital é liberado sem a nova ativa.

    Nota: o endpoint POST /api/operacoes/{id}/renegociar (transição
    simples, consumido pelo painel) apenas libera a antiga — o fluxo do
    painel formaliza a nova operação em passos manuais. Esta função é o
    caminho que garante a troca atômica em uma única chamada.
    """
    _propagar_usuario(db, usuario_id)

    antiga: Optional[OperacaoCredito] = (
        db.query(OperacaoCredito).filter(OperacaoCredito.id == operacao_id).one_or_none()
    )
    if antiga is None:
        raise OperacaoNaoEncontrada(f"Operação {operacao_id} não existe.")

    nova = OperacaoCredito(
        id=uuid4(),
        tomador_id=antiga.tomador_id,
        tipo=antiga.tipo,
        valor_principal=termos.valor_principal,
        taxa_juros_mensal=termos.taxa_juros_mensal,
        sistema_amortizacao=termos.sistema_amortizacao,
        numero_parcelas=termos.numero_parcelas,
        status="registrada",
        registro_entidade_ref=termos.registro_entidade_ref,
    )

    try:
        # Passo 1: libera a antiga (falha rápido com OC003 se o estado
        # atual não permite renegociar — ex. proposta, liquidada).
        antiga.status = "renegociada"  # type: ignore[assignment]
        db.flush()

        # Passo 2: cria a nova como 'registrada' (INSERT só é aceito em
        # proposta/registrada pela máquina de estados).
        db.add(nova)
        db.flush()

        # Passo 3: ativa a nova — gate completo, sob o mesmo lock.
        nova.status = "ativa"  # type: ignore[assignment]
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise _traduz_erro_banco(exc) from exc

    db.refresh(antiga)
    db.refresh(nova)
    registrar_renegociacao()
    return antiga, nova
