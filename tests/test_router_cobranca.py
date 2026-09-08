"""
Testes do router HTTP /cobranca — painel de aging e execução da régua.

O ponto sensível é a autorização: declarar inadimplência em lote não é
operação de rotina, e o teste prova que operador não consegue disparar.
"""

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.security import get_admin_user, get_current_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from app.routers import cobranca
from app.routers.cobranca import TAMANHO_MAXIMO_OFX_BYTES
from tests.conftest import confirmar_registro, sqlstate_de


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_user() -> Usuario:
    """O usuário por trás de `admin_client`, exposto como fixture própria.

    Existe porque a autoria da baixa (migration 016, ligada de fato na 027) só
    é verificável comparando `parcela.baixado_por` com o id de QUEM fez a
    requisição — "gravou alguma coisa não nula" não distingue a autoria certa
    da herdada de outra conexão do pool.
    """
    return Usuario(
        id=uuid.uuid4(), email="admin@orgatec.com", nome="Admin Teste", papel="admin", ativo=True
    )


@pytest.fixture()
def admin_client(client: TestClient, admin_user: Usuario) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_admin_user] = lambda: admin_user
    return client


@pytest.fixture()
def operador_client(client: TestClient) -> TestClient:
    """Só sobrescreve get_current_user — a checagem de papel em
    get_admin_user roda de verdade."""
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    return client


def _operacao_atrasada(db_session: Session, tomador_id: uuid.UUID, dias: int) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 2.5, 'PRICE', 12, 'registrada', 'REG-COB')
        returning id
        """),
        {"t": str(tomador_id)},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)

    # Vencimento é imutável (OC009); o trigger é desabilitado só para
    # fabricar o cenário — pela API isso é impossível, por construção.
    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    # Ancorado em `current_date` do BANCO — ver a explicação em
    # tests/test_aging.py::_envelhecer. Usar date.today() do Python quebrava
    # este teste todo dia na janela em que os dois relógios discordam.
    db_session.execute(
        text(
            "update parcela set vencimento = current_date - cast(:dias as int) "
            "where operacao_id = :id and numero = 1"
        ),
        {"dias": dias, "id": str(op_id)},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()
    return op_id


class TestGetAging:
    def test_exige_autenticacao(self, client: TestClient) -> None:
        assert client.get("/api/cobranca/aging").status_code == 401

    def test_sem_operacoes_traz_todas_as_faixas_zeradas(self, admin_client: TestClient) -> None:
        """Faixa vazia aparece com zero em vez de sumir: um painel que omite
        'acima de 90' não distingue 'não há nada' de 'não carregou'."""
        response = admin_client.get("/api/cobranca/aging")

        assert response.status_code == 200
        body = response.json()
        assert body["operacoes"] == []
        assert [f["faixa"] for f in body["resumo"]] == [
            "em_dia",
            "ate_30",
            "de_31_a_60",
            "de_61_a_90",
            "acima_de_90",
        ]
        assert all(f["quantidade"] == 0 for f in body["resumo"])

    def test_classifica_e_soma_por_faixa(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        _operacao_atrasada(db_session, tomador_autorizado, dias=100)
        _operacao_atrasada(db_session, tomador_autorizado, dias=45)

        body = admin_client.get("/api/cobranca/aging").json()

        assert len(body["operacoes"]) == 2
        # Mais atrasada primeiro — a ordem é a prioridade de cobrança.
        assert body["operacoes"][0]["dias_atraso"] == 100
        assert body["operacoes"][0]["faixa"] == "acima_de_90"
        assert body["operacoes"][1]["faixa"] == "de_31_a_60"

        por_faixa = {f["faixa"]: f for f in body["resumo"]}
        assert por_faixa["acima_de_90"]["quantidade"] == 1
        assert por_faixa["de_31_a_60"]["quantidade"] == 1
        assert Decimal(por_faixa["acima_de_90"]["valor_vencido"]) > 0


class TestProcessarAging:
    def test_operador_nao_pode_disparar_a_regua(self, operador_client: TestClient) -> None:
        """Declarar inadimplência em lote tem consequência para os tomadores
        — é ato de admin."""
        response = operador_client.post("/api/cobranca/aging/processar", json={})
        assert response.status_code == 403

    def test_transiciona_e_e_idempotente(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=100)

        primeira = admin_client.post("/api/cobranca/aging/processar", json={})
        assert primeira.status_code == 200
        assert primeira.json() == {"transicionadas": 1, "limite_dias": 90}

        segunda = admin_client.post("/api/cobranca/aging/processar", json={})
        assert segunda.json()["transicionadas"] == 0

        status = db_session.execute(
            text("select status from operacao_credito where id = :id"), {"id": str(op_id)}
        ).scalar_one()
        assert status == "inadimplente"

    def test_limite_customizado(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O prazo é parâmetro de negócio: a ESC pode adotar outro sem
        alterar a lógica."""
        _operacao_atrasada(db_session, tomador_autorizado, dias=45)

        assert (
            admin_client.post("/api/cobranca/aging/processar", json={}).json()["transicionadas"]
            == 0
        )
        assert (
            admin_client.post("/api/cobranca/aging/processar", json={"limite_dias": 30}).json()[
                "transicionadas"
            ]
            == 1
        )

    def test_limite_invalido_e_recusado(self, admin_client: TestClient) -> None:
        assert (
            admin_client.post("/api/cobranca/aging/processar", json={"limite_dias": 0}).status_code
            == 422
        )


class TestMovimentosEBaixa:
    def test_registrar_movimento_e_listar(self, admin_client: TestClient) -> None:
        response = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": "1500.00",
                "documento": "FITID-ROUTER-1",
                "descricao": "TED recebida",
            },
        )
        assert response.status_code == 201
        assert response.json()["conciliado"] is False

        lista = admin_client.get("/api/cobranca/movimentos").json()
        assert [m["documento"] for m in lista] == ["FITID-ROUTER-1"]

    def test_documento_duplicado_vira_409(self, admin_client: TestClient) -> None:
        """Reimportar o mesmo extrato é rotina; a resposta precisa dizer o
        que houve, não vazar o nome da constraint."""
        corpo = {
            "data_movimento": str(date.today()),
            "valor": "1500.00",
            "documento": "FITID-DUP",
        }
        assert admin_client.post("/api/cobranca/movimentos", json=corpo).status_code == 201

        # 409 e não 422: o corpo enviado está correto: o conflito é com o
        # estado do servidor, que já tem esse documento. E o código próprio
        # impede que a UI traduza isto como "baixa sem lastro" (OC011).
        repetido = admin_client.post("/api/cobranca/movimentos", json=corpo)
        assert repetido.status_code == 409
        assert repetido.json()["codigo"] == "MOVIMENTO_DUPLICADO"
        assert "Já existe um movimento" in repetido.json()["detail"]

    def test_baixa_pelo_endpoint(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=10)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
            {"op": str(op_id)},
        ).one()

        movimento_id = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": str(parcela.valor_total),
                "documento": "FITID-BAIXA",
            },
        ).json()["id"]

        baixa = admin_client.post(
            f"/api/cobranca/parcelas/{parcela.id}/baixar", json={"movimento_id": movimento_id}
        )
        assert baixa.status_code == 204

        # O movimento sai da lista de disponíveis: o diálogo de baixa não
        # pode oferecer algo que o banco recusaria.
        disponiveis = admin_client.get(
            "/api/cobranca/movimentos", params={"apenas_disponiveis": True}
        ).json()
        assert disponiveis == []

    def test_baixa_sem_lastro_suficiente_vira_422(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=10)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
            {"op": str(op_id)},
        ).one()

        movimento_id = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": "1.00",
                "documento": "FITID-CURTO",
            },
        ).json()["id"]

        resposta = admin_client.post(
            f"/api/cobranca/parcelas/{parcela.id}/baixar", json={"movimento_id": movimento_id}
        )
        assert resposta.status_code == 422
        assert resposta.json()["codigo"] == "OC011"


# ---------------------------------------------------------------------
# Importação de extrato OFX
# ---------------------------------------------------------------------
# O que estes testes defendem: até a migration 024, o lastro bancário da
# carteira inteira era AUTO-DECLARADO — o único produtor de
# `movimento_bancario` era o formulário acima, que aceita data, valor e
# documento arbitrários. O invariante da 009 ("não há parcela paga sem
# movimento apontado") é estrutural, não probatório. Aqui o movimento nasce dos
# bytes que o banco emitiu.
#
# A leitura do arquivo é provada em tests/test_ofx.py, sem banco. O que se prova
# AQUI é o que só existe contra Postgres: idempotência, filtro de débito,
# proveniência gravada e o relatório fechando com o arquivo.

_ROTA_IMPORTAR = "/api/cobranca/movimentos/importar-ofx"


def _upload(conteudo: str, nome: str = "extrato.ofx") -> dict[str, tuple[str, bytes, str]]:
    return {"arquivo": (nome, conteudo.encode("utf-8"), "application/x-ofx")}


def _ofx(*blocos: str, bankid: str = "001", acctid: str = "12345-6") -> str:
    """OFX 1.x mínimo mas realista — folhas abertas, agregados fechados."""
    corpo = "".join(blocos)
    return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
ENCODING:USASCII
CHARSET:1252

<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>{bankid}
<ACCTID>{acctid}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260101
<DTEND>20260131
{corpo}</BANKTRANLIST>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


def _trn(fitid: str, valor: str, data: str = "20260115", memo: str = "TED RECEBIDA") -> str:
    tipo = "DEBIT" if valor.startswith("-") else "CREDIT"
    return f"""<STMTTRN>
<TRNTYPE>{tipo}
<DTPOSTED>{data}
<TRNAMT>{valor}
<FITID>{fitid}
<MEMO>{memo}
</STMTTRN>
"""


class TestImportacaoOfx:
    def test_exige_autenticacao(self, client: TestClient) -> None:
        resposta = client.post(_ROTA_IMPORTAR, files=_upload(_ofx(_trn("A", "10.00"))))
        assert resposta.status_code == 401

    def test_operador_pode_importar(self, operador_client: TestClient) -> None:
        """Conciliar recebimento é rotina de quem opera a carteira. Diferente
        de `/aging/processar`, que declara inadimplência e exige admin, a
        importação não decide nada — traz o que o banco disse."""
        resposta = operador_client.post(_ROTA_IMPORTAR, files=_upload(_ofx(_trn("OP-1", "10.00"))))
        assert resposta.status_code == 200
        assert resposta.json()["criados"] == 1

    def test_importa_creditos_e_relata_os_numeros(self, admin_client: TestClient) -> None:
        arquivo = _ofx(
            _trn("IMP-1", "1500.00", data="20260105"),
            _trn("IMP-2", "2300.50", data="20260120"),
        )

        corpo = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo)).json()

        assert corpo["lidas"] == 2
        assert corpo["creditos"] == 2
        assert corpo["criados"] == 2
        assert corpo["ja_registrados"] == 0
        assert corpo["periodo_inicio"] == "2026-01-05"
        assert corpo["periodo_fim"] == "2026-01-20"
        assert corpo["contas"] == ["001/12345-6"]

        lista = admin_client.get("/api/cobranca/movimentos").json()
        assert sorted(m["documento"] for m in lista) == ["IMP-1", "IMP-2"]
        assert {Decimal(m["valor"]) for m in lista} == {Decimal("1500.00"), Decimal("2300.50")}

    def test_reimportar_o_mesmo_extrato_nao_duplica(self, admin_client: TestClient) -> None:
        """O CASO CENTRAL. Reimportar é ROTINA — o extrato do mês seguinte
        repete os dias do anterior, o operador sobe o mesmo arquivo por dúvida.
        Estourar no primeiro repetido (como faz, corretamente, o lançamento
        manual com 409) transformaria o funcionamento normal em erro."""
        arquivo = _ofx(_trn("DUP-1", "100.00"), _trn("DUP-2", "200.00"))

        primeira = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo)).json()
        assert (primeira["criados"], primeira["ja_registrados"]) == (2, 0)

        # DUAS E TRÊS VEZES, contando as LINHAS a cada volta: "não deu erro" não
        # é prova de idempotência — um import que estourasse silenciosamente na
        # segunda e criasse duplicata na terceira passaria num teste que só olha
        # o status. O que se conta é a tabela.
        for _ in range(2):
            repetida = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo))
            assert repetida.status_code == 200
            assert (repetida.json()["criados"], repetida.json()["ja_registrados"]) == (0, 2)
            assert len(admin_client.get("/api/cobranca/movimentos").json()) == 2

        # E os ids não mudaram: reimportar não recria a linha com outro id, o que
        # quebraria toda parcela já baixada contra ela.
        lista = admin_client.get("/api/cobranca/movimentos").json()
        assert len(lista) == 2
        assert {m["documento"] for m in lista} == {"DUP-1", "DUP-2"}

    def test_extrato_incremental_cria_so_a_linha_nova(self, admin_client: TestClient) -> None:
        """O arquivo do mês seguinte: repete o que já entrou e traz uma linha
        a mais. A idempotência não pode custar a linha nova."""
        admin_client.post(_ROTA_IMPORTAR, files=_upload(_ofx(_trn("INC-1", "100.00"))))

        corpo = admin_client.post(
            _ROTA_IMPORTAR,
            files=_upload(_ofx(_trn("INC-1", "100.00"), _trn("INC-2", "300.00"))),
        ).json()

        assert (corpo["criados"], corpo["ja_registrados"]) == (1, 1)
        documentos = {m["documento"] for m in admin_client.get("/api/cobranca/movimentos").json()}
        assert documentos == {"INC-1", "INC-2"}

    def test_debito_e_ignorado_e_contado(self, admin_client: TestClient) -> None:
        """Débito não baixa parcela e `movimento_bancario` tem check
        `valor > 0` (009). Descartar em SILÊNCIO faria o operador procurar por
        um lançamento que o sistema decidiu jogar fora sem dizer."""
        arquivo = _ofx(
            _trn("MIX-CRED", "1500.00"),
            _trn("MIX-DEB", "-320.50", memo="TARIFA BANCARIA"),
        )

        corpo = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo)).json()

        assert corpo["lidas"] == 2
        assert corpo["creditos"] == 1
        assert corpo["criados"] == 1
        assert corpo["debitos_ignorados"] == 1

        lista = admin_client.get("/api/cobranca/movimentos").json()
        assert [m["documento"] for m in lista] == ["MIX-CRED"]

    def test_fitid_repetido_dentro_do_arquivo(self, admin_client: TestClient) -> None:
        """Anomalia do arquivo do BANCO, contada separado de `ja_registrados`:
        os dois viram "não criado", mas um é reimportação normal e o outro é
        um extrato com linha duplicada, que o operador precisa enxergar."""
        arquivo = _ofx(
            _trn("REP", "100.00"),
            _trn("REP", "100.00"),
            _trn("UNICO", "50.00"),
        )

        corpo = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo)).json()

        assert corpo["lidas"] == 3
        assert corpo["criados"] == 2
        assert corpo["repetidos_no_arquivo"] == 1
        assert corpo["ja_registrados"] == 0
        assert corpo["lidas"] == (
            corpo["criados"]
            + corpo["ja_registrados"]
            + corpo["repetidos_no_arquivo"]
            + corpo["debitos_ignorados"]
        )

    def test_extrato_sem_movimento_e_arquivo_valido(self, admin_client: TestClient) -> None:
        """Período parado não é arquivo corrompido: 200 com zeros, e a conta
        do extrato informada mesmo assim."""
        resposta = admin_client.post(_ROTA_IMPORTAR, files=_upload(_ofx()))

        assert resposta.status_code == 200
        corpo = resposta.json()
        assert (corpo["lidas"], corpo["criados"]) == (0, 0)
        assert corpo["periodo_inicio"] is None
        assert corpo["contas"] == ["001/12345-6"]

    def test_arquivo_malformado_vira_422_com_a_causa(self, admin_client: TestClient) -> None:
        """O operador que exportou o extrato em CSV precisa ler o motivo, não
        um 500 — a mensagem é o que ele leva ao banco para pedir o OFX."""
        resposta = admin_client.post(
            _ROTA_IMPORTAR, files=_upload("data;valor\n2026-01-15;1500,00\n", nome="extrato.csv")
        )

        assert resposta.status_code == 422
        assert "OFX" in resposta.json()["detail"]
        assert admin_client.get("/api/cobranca/movimentos").json() == []

    def test_arquivo_vazio_vira_422(self, admin_client: TestClient) -> None:
        assert admin_client.post(_ROTA_IMPORTAR, files=_upload("")).status_code == 422

    def test_arquivo_truncado_nao_importa_nada(self, admin_client: TestClient) -> None:
        """Recusa é do ARQUIVO INTEIRO, não da linha ruim: importar as boas e
        omitir a truncada produziria um extrato parcial que ninguém saberia
        estar incompleto."""
        truncado = _ofx(_trn("BOA", "100.00")).split("</BANKTRANLIST>")[0] + (
            "<STMTTRN>\n<TRNTYPE>CREDIT\n<DTPOSTED>20260116\n<TRNAMT>50.00\n<FITID>METADE\n"
        )

        resposta = admin_client.post(_ROTA_IMPORTAR, files=_upload(truncado))

        assert resposta.status_code == 422
        assert admin_client.get("/api/cobranca/movimentos").json() == []

    def test_valor_fora_da_faixa_da_coluna(self, admin_client: TestClient) -> None:
        """`numeric(14,2)` comporta 12 dígitos inteiros. Acima disso o Postgres
        devolve 22003, que não está no PGCODE_MAP e viraria 500 — "erro
        interno" para um arquivo corrompido."""
        resposta = admin_client.post(
            _ROTA_IMPORTAR, files=_upload(_ofx(_trn("ABSURDO", "999999999999999.00")))
        )

        assert resposta.status_code == 422
        assert "ABSURDO" in resposta.json()["detail"]

    def test_valor_com_mais_de_duas_casas_e_recusado(self, admin_client: TestClient) -> None:
        """O OUTRO lado da faixa de `numeric(14,2)`, e o silencioso: o Postgres
        não recusa casa decimal a mais, ele ARREDONDA. `10.005` entraria como
        `10.01` — valor DIFERENTE do que está no arquivo cujo SHA-256 fica
        gravado na mesma linha, desfazendo justamente a prova que a migration
        024 existe para dar."""
        resposta = admin_client.post(_ROTA_IMPORTAR, files=_upload(_ofx(_trn("FRACAO", "10.005"))))

        assert resposta.status_code == 422
        assert "FRACAO" in resposta.json()["detail"]
        assert admin_client.get("/api/cobranca/movimentos").json() == []

    def test_valor_subcentavo_nao_vira_erro_interno(self, admin_client: TestClient) -> None:
        """O caso extremo da escala, que ANTES virava 500. `0.004` é maior que
        zero em Python, passava o filtro de crédito, e no Postgres arredondava
        para `0.00` — violando o check `movimento_valor_positivo` da 009 com
        23514, que não está no PGCODE_MAP e sobe como "erro interno" para o
        operador cujo arquivo é que está errado."""
        resposta = admin_client.post(_ROTA_IMPORTAR, files=_upload(_ofx(_trn("MIGALHA", "0.004"))))

        assert resposta.status_code == 422
        assert "MIGALHA" in resposta.json()["detail"]

    def test_duas_casas_exatas_continuam_passando(self, admin_client: TestClient) -> None:
        """A guarda de escala não pode barrar o extrato normal: centavo é o
        caso comum, e o limite superior é aceito até a última unidade."""
        arquivo = _ofx(
            _trn("CENTAVO", "1234.56"),
            _trn("INTEIRO", "1000"),
            _trn("TETO", "999999999999.99"),
        )

        corpo = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo)).json()

        assert corpo["criados"] == 3

    def test_arquivo_acima_do_teto_de_bytes_vira_413(self, admin_client: TestClient) -> None:
        """O teto de bytes existia sem teste nenhum. Recusa EXPLÍCITA, com o
        número no corpo: um limite que o operador não consegue ler vira "o
        sistema não importa meu arquivo"."""
        # Enchimento fora de qualquer tag: o arquivo é OFX válido, só grande.
        gordura = "\n" + ("X" * (TAMANHO_MAXIMO_OFX_BYTES + 1024))
        resposta = admin_client.post(
            _ROTA_IMPORTAR, files=_upload(_ofx(_trn("G", "10.00")) + gordura)
        )

        assert resposta.status_code == 413
        assert "8 MiB" in resposta.json()["detail"]
        assert admin_client.get("/api/cobranca/movimentos").json() == []

    def test_arquivo_acima_do_teto_de_transacoes_vira_422(
        self, admin_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O segundo teto, e a razão de ele não ser o mesmo que o de bytes: um
        OFX de tags mínimas cabe em poucos bytes por linha, então arquivo
        pequeno e patológico passa pelo teto de bytes e produz um INSERT de
        centenas de milhares de linhas.

        O teto real (50.000) é rebaixado aqui em vez de gerar um arquivo de 6 MB
        a cada rodada da suíte: o que se prova é a RECUSA e o número na
        mensagem, não a constante."""
        monkeypatch.setattr(cobranca, "MAXIMO_TRANSACOES_POR_IMPORTACAO", 2)

        arquivo = _ofx(_trn("T1", "1.00"), _trn("T2", "2.00"), _trn("T3", "3.00"))
        resposta = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo))

        assert resposta.status_code == 422
        assert "3 transações" in resposta.json()["detail"]
        assert admin_client.get("/api/cobranca/movimentos").json() == []


class TestProvenienciaDoMovimento:
    """Migration 024: o movimento diz de qual arquivo e de qual conta veio."""

    def test_importado_grava_origem_conta_arquivo_e_autor(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        conteudo = _ofx(_trn("PROV-1", "1500.00"), bankid="341", acctid="0001-9")
        sha_esperado = hashlib.sha256(conteudo.encode("utf-8")).hexdigest()

        corpo = admin_client.post(_ROTA_IMPORTAR, files=_upload(conteudo)).json()
        assert corpo["arquivo_sha256"] == sha_esperado

        linha = db_session.execute(
            text("""
            select origem, conta_origem, arquivo_sha256, usuario_id, descricao
              from movimento_bancario where documento = 'PROV-1'
            """)
        ).one()

        assert linha.origem == "ofx"
        assert linha.conta_origem == "341/0001-9"
        # O hash é dos BYTES RECEBIDOS: é o arquivo do banco que a ESC arquiva
        # e que o fiscal pede, não uma normalização nossa.
        assert linha.arquivo_sha256 == sha_esperado
        assert linha.usuario_id is not None
        assert linha.descricao == "TED RECEBIDA"

        # E aparece na leitura: proveniência que a tela não mostra não é
        # proveniência.
        movimento = admin_client.get("/api/cobranca/movimentos").json()[0]
        assert movimento["origem"] == "ofx"
        assert movimento["arquivo_sha256"] == sha_esperado

    def test_lancamento_manual_continua_sem_proveniencia_de_arquivo(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """O formulário manual segue existindo — extrato que não se consegue
        exportar ainda precisa de caminho — mas fica DISTINGUÍVEL na leitura."""
        admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": "500.00",
                "documento": "MANUAL-1",
            },
        )

        linha = db_session.execute(
            text("""
            select origem, conta_origem, arquivo_sha256
              from movimento_bancario where documento = 'MANUAL-1'
            """)
        ).one()

        assert linha.origem == "manual"
        assert linha.conta_origem is None
        assert linha.arquivo_sha256 is None

    def test_banco_recusa_carimbo_de_importado_sem_arquivo(self, db_session: Session) -> None:
        """A guarda que faz a proveniência valer alguma coisa. Sem ela, `origem
        = 'ofx'` seria uma palavra a mais na digitação: trocaria o lastro
        auto-declarado por um SELO auto-declarado, que é pior, porque mente com
        aparência de prova.

        Por SQL direto de propósito: nenhum endpoint alcança este caminho (é
        justamente o ponto), e o que se prova aqui é que o BANCO recusa — não a
        aplicação."""
        with pytest.raises(DBAPIError) as excinfo:
            db_session.execute(
                text("""
                insert into movimento_bancario (data_movimento, valor, documento, origem)
                values (current_date, 100, 'FALSO-OFX', 'ofx')
                """)
            )
        db_session.rollback()

        # 23514 = check_violation. Não há SQLSTATE da classe OC aqui de
        # propósito (ver o topo da migration 024): não é regra de operação, é
        # uso indevido do schema.
        assert sqlstate_de(excinfo.value) == "23514"

    def test_banco_recusa_proveniencia_em_lancamento_manual(self, db_session: Session) -> None:
        """O outro lado da constraint. Uma `conta_origem` digitada num
        lançamento manual seria de novo auto-declaração, agora num campo que a
        tela apresenta como se viesse do banco."""
        with pytest.raises(DBAPIError):
            db_session.execute(
                text("""
                insert into movimento_bancario
                    (data_movimento, valor, documento, origem, conta_origem)
                values (current_date, 100, 'MANUAL-COM-CONTA', 'manual', '001/12345-6')
                """)
            )
        db_session.rollback()

    def test_banco_recusa_hash_que_nao_e_sha256(self, db_session: Session) -> None:
        """64 hexadecimais minúsculos, ou nada. Sem o formato, `arquivo_sha256`
        aceitaria "importado-do-banco" e voltaria a ser texto livre."""
        with pytest.raises(DBAPIError):
            db_session.execute(
                text("""
                insert into movimento_bancario
                    (data_movimento, valor, documento, origem, arquivo_sha256)
                values (current_date, 100, 'HASH-RUIM', 'ofx', 'nao-e-um-hash')
                """)
            )
        db_session.rollback()

    def test_proveniencia_nao_pode_ser_reescrita_depois(
        self, admin_client: TestClient, db_session: Session
    ) -> None:
        """Write-once por construção, sem guarda nova: `movimento_bancario` é
        imutável desde a 009 (OC012). Um lançamento digitado em março não vira
        "importado" em agosto."""
        admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": "500.00",
                "documento": "IMUTAVEL-1",
            },
        )

        with pytest.raises(DBAPIError) as excinfo:
            db_session.execute(
                text("""
                update movimento_bancario
                   set origem = 'ofx', arquivo_sha256 = repeat('a', 64)
                 where documento = 'IMUTAVEL-1'
                """)
            )
        db_session.rollback()

        assert sqlstate_de(excinfo.value) == "OC012"


class TestImportacaoNaoBaixaParcela:
    def test_movimento_importado_entra_como_disponivel_e_nao_concilia_nada(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A separação de poderes do módulo: o import entrega o LASTRO; amarrar
        crédito a parcela continua sendo ato do operador, com nome na trilha.

        Conciliação automática por valor erraria exatamente onde dói — duas
        parcelas de mesmo valor, pagamento parcial, juros de mora — e a baixa é
        o único ato irreversível do ciclo (não há estorno, migration 009)."""
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=10)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
            {"op": str(op_id)},
        ).one()

        admin_client.post(
            _ROTA_IMPORTAR,
            files=_upload(_ofx(_trn("LASTRO-1", str(parcela.valor_total)))),
        )

        # Nada foi baixado: a parcela continua em aberto e o movimento
        # continua disponível para conciliação.
        situacao = db_session.execute(
            text("select status, movimento_id from parcela where id = :p"),
            {"p": str(parcela.id)},
        ).one()
        assert situacao.status == "aberta"
        assert situacao.movimento_id is None

        disponiveis = admin_client.get(
            "/api/cobranca/movimentos", params={"apenas_disponiveis": True}
        ).json()
        assert [m["documento"] for m in disponiveis] == ["LASTRO-1"]

        # E serve para a baixa manual — o lastro importado é lastro de verdade.
        baixa = admin_client.post(
            f"/api/cobranca/parcelas/{parcela.id}/baixar",
            json={"movimento_id": disponiveis[0]["id"]},
        )
        assert baixa.status_code == 204


class TestFitidPorConta:
    """Migration 027: FITID é único DENTRO da conta, nunca no universo.

    O DEFEITO QUE ISTO CORRIGE ERA O PIOR FORMATO POSSÍVEL, e vale dizer por
    quê: com `documento` UNIQUE global, uma ESC que recebe em dois bancos
    importava o extrato do segundo e via o crédito ser contado como
    `ja_registrados`. A linha existia na tabela — mas era a do OUTRO banco,
    com outro valor e outra data. E a aritmética do relatório FECHAVA
    (lidas = criados + ja_registrados + repetidos_no_arquivo +
    debitos_ignorados), de modo que a tela afirmava, com números conferidos,
    que nada faltou. O operador não tinha como descobrir, e a parcela do
    tomador que pagou seguia no aging como atrasada.
    """

    def test_mesmo_fitid_em_dois_bancos_cria_os_dois_creditos(
        self, admin_client: TestClient
    ) -> None:
        """Dois ARQUIVOS, duas contas, o mesmo FITID curto. Antes da 027 o
        segundo virava `ja_registrados` e o dinheiro sumia do lastro."""
        primeiro = admin_client.post(
            _ROTA_IMPORTAR,
            files=_upload(_ofx(_trn("000123", "1500.00"), bankid="001", acctid="111")),
        ).json()
        assert (primeiro["criados"], primeiro["ja_registrados"]) == (1, 0)

        segundo = admin_client.post(
            _ROTA_IMPORTAR,
            files=_upload(_ofx(_trn("000123", "980.00"), bankid="341", acctid="222")),
        ).json()

        assert (segundo["criados"], segundo["ja_registrados"]) == (1, 0)

        # E os dois créditos estão lá, distinguíveis pela conta — que a tela
        # mostra desde a 024. Sem ela, duas linhas de mesmo documento seriam
        # indistinguíveis para quem lê.
        movimentos = admin_client.get("/api/cobranca/movimentos").json()
        assert {(m["documento"], m["conta_origem"], Decimal(m["valor"])) for m in movimentos} == {
            ("000123", "001/111", Decimal("1500.00")),
            ("000123", "341/222", Decimal("980.00")),
        }

    def test_mesmo_fitid_em_contas_diferentes_do_mesmo_arquivo(
        self, admin_client: TestClient
    ) -> None:
        """O mesmo furo dentro de UM arquivo — OFX com dois statements, que o
        leitor já associa a contas distintas.

        Consertar só a chave do banco deixaria este caso de pé: a
        deduplicação de `importar_extrato_ofx` acontece em Python, ANTES do
        INSERT, e enquanto ela foi por FITID a segunda linha era descartada
        como `repetidos_no_arquivo` sem nunca chegar ao banco. Os dois lados
        tinham que mudar juntos.
        """
        um = _ofx(_trn("1", "100.00"), bankid="001", acctid="111")
        dois = _ofx(_trn("1", "200.00"), bankid="341", acctid="222")
        combinado = um.replace("</OFX>\n", "") + dois.split("<OFX>", 1)[1]

        corpo = admin_client.post(_ROTA_IMPORTAR, files=_upload(combinado)).json()

        assert corpo["lidas"] == 2
        assert corpo["criados"] == 2
        assert corpo["repetidos_no_arquivo"] == 0
        assert sorted(corpo["contas"]) == ["001/111", "341/222"]
        assert corpo["lidas"] == (
            corpo["criados"]
            + corpo["ja_registrados"]
            + corpo["repetidos_no_arquivo"]
            + corpo["debitos_ignorados"]
        )

    def test_fitid_repetido_na_mesma_conta_continua_sendo_anomalia(
        self, admin_client: TestClient
    ) -> None:
        """O outro lado da chave nova: DENTRO da mesma conta, FITID repetido
        continua sendo uma linha duplicada pelo banco — contada e não criada.
        Sem esta metade, a correção viraria licença para duplicar crédito."""
        arquivo = _ofx(_trn("REP", "100.00"), _trn("REP", "100.00"))

        corpo = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo)).json()

        assert (corpo["criados"], corpo["repetidos_no_arquivo"]) == (1, 1)

    def test_reimportar_a_mesma_conta_continua_idempotente(self, admin_client: TestClient) -> None:
        """A garantia da 009 que a chave nova não pode ter custado: reimportar
        é rotina, e o mesmo arquivo não cria nada de novo."""
        arquivo = _ofx(_trn("IDEM-1", "100.00"), bankid="001", acctid="111")

        admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo))
        repetida = admin_client.post(_ROTA_IMPORTAR, files=_upload(arquivo)).json()

        assert (repetida["criados"], repetida["ja_registrados"]) == (0, 1)
        assert len(admin_client.get("/api/cobranca/movimentos").json()) == 1

    def test_extrato_sem_conta_declarada_continua_idempotente(
        self, admin_client: TestClient
    ) -> None:
        """O CASO QUE `NULLS NOT DISTINCT` EXISTE PARA COBRIR, e o que mais
        facilmente teria passado despercebido.

        OFX de cartão traz só ACCTID, e exportação capada pode não trazer conta
        nenhuma (ver o comentário de `conta_origem` na 024). Com uma UNIQUE
        comum sobre (documento, conta_origem), essas linhas teriam
        `conta_origem` NULL — e NULL nunca é igual a NULL em SQL, de modo que
        o `ON CONFLICT` não veria conflito NENHUM e a reimportação passaria a
        DUPLICAR o crédito. A idempotência da 009 sumiria em silêncio,
        justamente no arquivo que menos informação traz.
        """
        sem_conta = f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX>
<BANKMSGSRSV1>
<BANKTRANLIST>
{_trn("SEM-CONTA-1", "742.00")}</BANKTRANLIST>
</BANKMSGSRSV1>
</OFX>
"""
        primeira = admin_client.post(_ROTA_IMPORTAR, files=_upload(sem_conta)).json()
        assert (primeira["criados"], primeira["contas"]) == (1, [])

        segunda = admin_client.post(_ROTA_IMPORTAR, files=_upload(sem_conta)).json()

        assert (segunda["criados"], segunda["ja_registrados"]) == (0, 1)
        movimentos = admin_client.get("/api/cobranca/movimentos").json()
        assert len(movimentos) == 1
        assert movimentos[0]["conta_origem"] is None


class TestAutoriaDaBaixa:
    """Migration 016 (d) + correção da 027: a baixa tem autor DE VERDADE.

    O mecanismo inteiro existia desde a 016 — coluna `parcela.baixado_por`,
    leitura de `app.user_id` em `fn_baixar_parcela`, guarda contra reescrita,
    e o parâmetro `usuario_id` no serviço `baixar_parcela` — e estava
    DESLIGADO por uma linha que faltava: o endpoint, único caminho de baixa da
    aplicação, não passava o usuário. `baixado_por` era NULL em 100% das
    baixas feitas pela API.

    Por isso este teste passa pelo HTTP e não pela função de serviço: a função
    já aceitava o parâmetro e já era testada em
    tests/test_baixa_recebimento.py::test_baixa_grava_autor — ela passava
    verde o tempo todo, enquanto a autoria não era gravada em produção. O que
    faltava provar é que ALGUÉM PASSA o valor.
    """

    def test_baixa_pelo_endpoint_grava_o_usuario_autenticado(
        self,
        admin_client: TestClient,
        admin_user: Usuario,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=10)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
            {"op": str(op_id)},
        ).one()

        movimento_id = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": str(parcela.valor_total),
                "documento": "FITID-AUTORIA",
            },
        ).json()["id"]

        baixa = admin_client.post(
            f"/api/cobranca/parcelas/{parcela.id}/baixar", json={"movimento_id": movimento_id}
        )
        assert baixa.status_code == 204

        baixado_por = db_session.execute(
            text("select baixado_por from parcela where id = :id"), {"id": str(parcela.id)}
        ).scalar_one()

        # O autor é o usuário autenticado da requisição, não uma string
        # qualquer não nula: `app.user_id` é uma GUC de sessão e, num pool,
        # uma baixa sem usuário herdaria o autor da anterior na mesma conexão
        # física. Comparar com o id do usuário do cliente é o que distingue
        # "gravou alguém" de "gravou QUEM".
        assert baixado_por == str(admin_user.id)

    def test_a_autoria_gravada_pelo_endpoint_nao_se_reescreve(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Fecha o ciclo: de nada adianta gravar o autor se ele puder ser
        trocado depois. A guarda é da 016, mas até a 027 ela nunca tinha nada
        para guardar nas baixas feitas pela API."""
        op_id = _operacao_atrasada(db_session, tomador_autorizado, dias=10)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :op and numero = 1"),
            {"op": str(op_id)},
        ).one()
        movimento_id = admin_client.post(
            "/api/cobranca/movimentos",
            json={
                "data_movimento": str(date.today()),
                "valor": str(parcela.valor_total),
                "documento": "FITID-AUTORIA-2",
            },
        ).json()["id"]
        admin_client.post(
            f"/api/cobranca/parcelas/{parcela.id}/baixar", json={"movimento_id": movimento_id}
        )

        with pytest.raises(DBAPIError) as excinfo:
            db_session.execute(
                text("update parcela set baixado_por = 'outra pessoa' where id = :id"),
                {"id": str(parcela.id)},
            )
        db_session.rollback()

        assert sqlstate_de(excinfo.value) == "OC011"
