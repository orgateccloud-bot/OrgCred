"""Modelos SQLAlchemy espelhando o schema PostgreSQL."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import declarative_base, relationship


Base: Any = declarative_base()


class TipoOperacao(str, enum.Enum):
    """Tipos de operação de crédito."""

    emprestimo = "emprestimo"
    financiamento = "financiamento"


class SistemaAmortizacao(str, enum.Enum):
    """Sistemas de amortização suportados."""

    PRICE = "PRICE"
    SAC = "SAC"


class StatusOperacao(str, enum.Enum):
    """Estados válidos de uma operação de crédito."""

    proposta = "proposta"
    registrada = "registrada"
    ativa = "ativa"
    liquidada = "liquidada"
    inadimplente = "inadimplente"
    renegociada = "renegociada"
    cancelada = "cancelada"


class Tomador(Base):
    """Tomadores de crédito."""

    __tablename__ = "tomador"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    cnpj = Column(String(14), unique=True, nullable=False)
    razao_social = Column(String(255), nullable=False)
    porte = Column(String(10), nullable=False)  # ME, EPP, etc.
    municipio = Column(String(255), nullable=False)
    uf = Column(String(2), nullable=False)
    municipio_autorizado = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    operacoes = relationship("OperacaoCredito", back_populates="tomador")


class OperacaoCredito(Base):
    """Operações de crédito."""

    __tablename__ = "operacao_credito"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    tomador_id = Column(PG_UUID(as_uuid=True), ForeignKey("tomador.id"), nullable=False)
    tipo = Column(String(20), nullable=False)  # emprestimo, financiamento
    valor_principal = Column(Numeric(14, 2), nullable=False)
    taxa_juros_mensal = Column(Numeric(5, 2), nullable=False)
    sistema_amortizacao = Column(String(10), nullable=False)  # PRICE, SAC
    numero_parcelas = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="proposta")
    registro_entidade_ref = Column(String(255), nullable=True)
    # Novação (migration 006): aponta para a operação que esta substituiu.
    # Só é preenchida por fn_novar_operacao — criar uma substituta fora dela
    # é bloqueado pelo trigger (OC008), porque a baixa da original e a
    # criação da substituta precisam ser atômicas para não contar o mesmo
    # capital duas vezes.
    substitui_operacao_id = Column(
        PG_UUID(as_uuid=True), ForeignKey("operacao_credito.id"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    tomador = relationship("Tomador", back_populates="operacoes")


class Parcela(Base):
    """Parcela da agenda de amortização (migration 007).

    Gerada pelo BANCO na ativação (trigger `trg_gerar_parcelas` chamando
    `fn_gerar_parcelas`), nunca pela aplicação. Depois de emitida, só
    `status` e `pago_em` podem mudar — qualquer alteração de valor, data ou
    número é recusada com OC009. Reescrever a agenda depois de emitida
    destruiria a base documental da cobrança.
    """

    __tablename__ = "parcela"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    operacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("operacao_credito.id"), nullable=False)
    numero = Column(Integer, nullable=False)
    vencimento = Column(Date, nullable=False)
    valor_amortizacao = Column(Numeric(14, 2), nullable=False)
    valor_juros = Column(Numeric(14, 2), nullable=False)
    valor_total = Column(Numeric(14, 2), nullable=False)
    saldo_devedor_pos = Column(Numeric(14, 2), nullable=False)
    status = Column(String(20), nullable=False, default="aberta")  # aberta, paga, baixada
    pago_em = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CapitalLedger(Base):
    """Ledger imutável de movimentações de capital.

    `prev_hash`/`current_hash`: cadeia SHA-256 adicionada na migration 005
    (append-only enforced por trigger) — calculadas pelo banco em cada
    INSERT, nunca escritas pela aplicação.
    """

    __tablename__ = "capital_ledger"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    evento_tipo = Column(String(50), nullable=False)  # ativacao_operacao, liquidacao, etc.
    valor = Column(Numeric(14, 2), nullable=False)
    operacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("operacao_credito.id"), nullable=True)
    saldo_disponivel_pos = Column(Numeric(14, 2), nullable=False)
    usuario_id = Column(String(255), nullable=True)  # preenchido em autenticação
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    prev_hash = Column(String(64), nullable=True)
    current_hash = Column(String(64), nullable=True)


class EscCapitalSocial(Base):
    """Histórico de capital social (constituição e reduções)."""

    __tablename__ = "esc_capital_social"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    valor = Column(Numeric(14, 2), nullable=False)
    tipo_evento = Column(String(50), nullable=False)  # constituicao, reducao
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Usuario(Base):
    """Usuários do painel de operações."""

    __tablename__ = "usuario"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    nome = Column(String(255), nullable=False)
    papel = Column(String(20), nullable=False)  # admin, operador
    ativo = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
