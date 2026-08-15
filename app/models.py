"""Modelos SQLAlchemy espelhando o schema PostgreSQL."""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
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


class ContratoEmprestimo(Base):
    """Instrumento contratual emitido (migration 012).

    "Contrato de Empréstimo ESC", não CCB: a CCB (Lei 10.931/2004) é
    instrumento de instituição financeira, e uma ESC não é. `tipo_instrumento`
    é coluna para o advogado poder mudar isso sem migration nova.

    O `sha256` é calculado pelo BANCO no INSERT (trigger `trg_contrato_hash`),
    nunca enviado pela aplicação: assim corpo e hash não podem divergir nem
    ser forjados. Imutável depois de emitido (OC017) — reemitir cria versão.
    """

    __tablename__ = "contrato_emprestimo"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    operacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("operacao_credito.id"), nullable=False)
    versao = Column(Integer, nullable=False, default=1)
    tipo_instrumento = Column(String(50), nullable=False)
    corpo = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False)
    emitido_em = Column(DateTime, nullable=False, default=datetime.utcnow)
    usuario_id = Column(String(255), nullable=True)


class RegistroOperacao(Base):
    """Registro em entidade registradora (migration 012).

    Substitui o `operacao_credito.registro_entidade_ref` de texto livre, que
    o trigger OC004 só checava por não-vazio — escrever "x" passava pelo
    gate do Art. 5º §3º.

    `confirmado` exige protocolo por constraint, e é terminal (OC018).
    """

    __tablename__ = "registro_operacao"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    operacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("operacao_credito.id"), nullable=False)
    entidade = Column(String(100), nullable=False)
    protocolo = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="pendente")
    enviado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
    confirmado_em = Column(DateTime, nullable=True)
    motivo_rejeicao = Column(String, nullable=True)
    usuario_id = Column(String(255), nullable=True)


class TomadorDocumento(Base):
    """Evidência de identificação arquivada (migrations 010 e 019).

    O banco guarda o HASH e o ENDEREÇO; os bytes ficam no storage
    (`storage_objeto`, migration 019). A divisão é deliberada: guardar o
    binário no Postgres inflaria o banco sem acrescentar garantia — o que se
    precisa provar é que o documento apresentado numa fiscalização é bit a
    bit o mesmo que foi arquivado, e para isso basta o hash. O que NÃO basta
    é o hash sozinho, e foi assim que o sistema ficou da 010 até a 019: sem
    storage nenhum, `sha256` chegava do cliente como texto e a identificação
    exigida pela Lei 9.613/98 (art. 10, I) era satisfeita por 64 caracteres
    digitados. Hoje o servidor recebe o arquivo, calcula o hash dos bytes e
    guarda os bytes antes de gravar esta linha.

    `storage_objeto` é nulo apenas nas evidências anteriores à 019, cujos
    bytes nunca existiram em lugar nenhum — ver a justificativa no cabeçalho
    da migration.

    `retencao_ate` é materializada, não calculada na leitura — se o prazo
    legal mudar, os documentos já arquivados mantêm a regra vigente à época,
    que é o que se defende numa fiscalização. Apagar antes do prazo é
    recusado pelo banco (OC013, Lei 9.613/98 art. 10, III), e o mesmo OC013
    recusa QUALQUER update: repontar `storage_objeto` para outro objeto
    trocaria o documento arquivado mantendo o hash, então nem isso passa.
    """

    __tablename__ = "tomador_documento"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    tomador_id = Column(PG_UUID(as_uuid=True), ForeignKey("tomador.id"), nullable=False)
    tipo = Column(String(30), nullable=False)
    nome_arquivo = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False)
    arquivado_em = Column(DateTime, nullable=False, default=datetime.utcnow)
    retencao_ate = Column(Date, nullable=False)
    usuario_id = Column(String(255), nullable=True)
    # '<bucket>/<caminho>' — o bucket vai junto porque a retenção é de 5 anos
    # e o bucket configurado muda (migration 019).
    storage_objeto = Column(String, nullable=True)


class OcorrenciaAtipicidade(Base):
    """Atipicidade detectada internamente (migration 010).

    Append-only exceto `comunicado_em`/`comunicacao_ref`, que são o
    ADAPTADOR do canal externo: nada os preenche hoje, porque o regime
    PLD/COAF de uma ESC depende de parecer jurídico. Quando sair, liga-se o
    envio sem tocar na detecção, e o histórico já acumulado continua válido.
    """

    __tablename__ = "ocorrencia_atipicidade"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    regra = Column(String(50), nullable=False)
    severidade = Column(String(10), nullable=False)  # baixa, media, alta
    tomador_id = Column(PG_UUID(as_uuid=True), ForeignKey("tomador.id"), nullable=True)
    operacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("operacao_credito.id"), nullable=True)
    detalhe = Column(String, nullable=False)
    comunicado_em = Column(DateTime, nullable=True)
    comunicacao_ref = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class MovimentoBancario(Base):
    """Linha de extrato bancário (migration 009).

    Imutável (OC012): extrato é fato de fora — o sistema registra, não
    edita. `documento` (FITID no OFX) é único, o que torna a importação
    idempotente e impede que o mesmo dinheiro baixe duas parcelas.
    """

    __tablename__ = "movimento_bancario"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    data_movimento = Column(Date, nullable=False)
    valor = Column(Numeric(14, 2), nullable=False)
    descricao = Column(String, nullable=True)
    documento = Column(String, unique=True, nullable=False)
    origem = Column(String(10), nullable=False, default="manual")  # manual, ofx
    usuario_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class OperacaoEvento(Base):
    """Trilha append-only de transições de estado (migration 008).

    Separada do CapitalLedger de propósito: o ledger registra movimentos de
    CAPITAL (e reconstrói o saldo pela hash-chain), enquanto esta tabela
    registra mudanças de ESTADO — inclusive as que não movem dinheiro, como
    `ativa -> inadimplente`, que antes da 008 não deixavam rastro algum.

    `origem` distingue o que uma pessoa fez do que a régua automática fez;
    quando é 'sistema', `usuario_id` é obrigatoriamente nulo, para que um
    ato automático nunca possa ser imputado a alguém.
    """

    __tablename__ = "operacao_evento"

    id = Column(PG_UUID(as_uuid=True), primary_key=True)
    operacao_id = Column(PG_UUID(as_uuid=True), ForeignKey("operacao_credito.id"), nullable=False)
    status_anterior = Column(String(20), nullable=True)
    status_novo = Column(String(20), nullable=False)
    origem = Column(String(10), nullable=False)  # usuario, sistema
    usuario_id = Column(String(255), nullable=True)
    dias_atraso = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


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
    # Lastro da baixa (migration 009): 'paga' sem movimento é recusado pelo
    # banco (OC011), e um movimento só baixa uma parcela (índice único).
    movimento_id = Column(PG_UUID(as_uuid=True), ForeignKey("movimento_bancario.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CapitalLedger(Base):
    """Ledger imutável de movimentações de capital.

    `prev_hash`/`current_hash`: cadeia SHA-256 adicionada na migration 005
    (append-only enforced por trigger) — calculadas pelo banco em cada
    INSERT, nunca escritas pela aplicação.

    `seq`: ordem de gravação da cadeia (migration 020). É por ela que a cadeia
    é encadeada e verificada — `created_at` é o instante de ABERTURA da
    transação (`now()` = `transaction_timestamp()`) e pode sair invertido
    entre transações sobrepostas. Também é atribuída pelo banco (default
    `nextval`), pelo mesmo motivo dos hashes: quem escreve é o banco.
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
    seq = Column(BigInteger, nullable=False)  # default nextval no banco (migration 020)


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
