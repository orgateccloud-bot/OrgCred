"""
Compliance PLD/FT interno (migration 010) contra Postgres real.

Três coisas que não dependem de terceiro e por isso são testáveis hoje:
evidência de identificação com hash verificável, retenção de 5 anos
garantida pelo banco, e detecção de atipicidade sobre os dados existentes.
"""

import base64
import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, baixar_parcela, registrar_movimento_bancario
from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.conftest import sqlstate_de


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_client(client: TestClient) -> TestClient:
    admin = Usuario(
        id=uuid.uuid4(), email="admin@orgatec.com", nome="Admin", papel="admin", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_admin_user] = lambda: admin
    app.dependency_overrides[get_operador_user] = lambda: admin
    return client


def _sha(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


# ---------------------------------------------------------------------
# Identificação com evidência arquivada
# ---------------------------------------------------------------------


class TestIdentificacao:
    def test_arquivar_e_listar(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        conteudo = b"contrato social em pdf"
        resposta = admin_client.post(
            f"/api/compliance/tomadores/{tomador_autorizado}/documentos",
            json={
                "tipo": "contrato_social",
                "nome_arquivo": "contrato.pdf",
                "sha256": _sha(conteudo),
            },
        )
        assert resposta.status_code == 201

        # Retenção de 5 anos gravada no ato (Lei 9.613/98, art. 10, III).
        corpo = resposta.json()
        assert date.fromisoformat(corpo["retencao_ate"]) >= date.today() + timedelta(days=5 * 365)

        lista = admin_client.get(
            f"/api/compliance/tomadores/{tomador_autorizado}/documentos"
        ).json()
        assert [d["nome_arquivo"] for d in lista] == ["contrato.pdf"]

    def test_mesmo_arquivo_duas_vezes_e_recusado(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        corpo = {
            "tipo": "cartao_cnpj",
            "nome_arquivo": "cnpj.pdf",
            "sha256": _sha(b"cartao cnpj"),
        }
        url = f"/api/compliance/tomadores/{tomador_autorizado}/documentos"
        assert admin_client.post(url, json=corpo).status_code == 201

        repetido = admin_client.post(url, json=corpo)
        assert repetido.status_code == 422
        assert "já está arquivado" in repetido.json()["detail"]

    def test_tomador_inexistente_404(self, admin_client: TestClient) -> None:
        resposta = admin_client.post(
            f"/api/compliance/tomadores/{uuid.uuid4()}/documentos",
            json={"tipo": "outro", "nome_arquivo": "x.pdf", "sha256": _sha(b"x")},
        )
        assert resposta.status_code == 404

    def test_verificacao_confere_bit_a_bit(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        """É o que dá sentido a guardar só o hash: sem esta conferência, o
        hash seria um número sem uso."""
        conteudo = b"documento original do socio"
        doc_id = admin_client.post(
            f"/api/compliance/tomadores/{tomador_autorizado}/documentos",
            json={
                "tipo": "documento_socio",
                "nome_arquivo": "rg.pdf",
                "sha256": _sha(conteudo),
            },
        ).json()["id"]

        igual = admin_client.post(
            f"/api/compliance/documentos/{doc_id}/verificar",
            json={"conteudo_base64": base64.b64encode(conteudo).decode()},
        ).json()
        assert igual["confere"] is True

        adulterado = admin_client.post(
            f"/api/compliance/documentos/{doc_id}/verificar",
            json={"conteudo_base64": base64.b64encode(conteudo + b" ").decode()},
        ).json()
        assert adulterado["confere"] is False

    def test_verificacao_de_documento_inexistente_404(self, admin_client: TestClient) -> None:
        resposta = admin_client.post(
            f"/api/compliance/documentos/{uuid.uuid4()}/verificar",
            json={"conteudo_base64": base64.b64encode(b"x").decode()},
        )
        assert resposta.status_code == 404

    def test_base64_invalido_422(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        doc_id = admin_client.post(
            f"/api/compliance/tomadores/{tomador_autorizado}/documentos",
            json={"tipo": "outro", "nome_arquivo": "a.pdf", "sha256": _sha(b"a")},
        ).json()["id"]

        resposta = admin_client.post(
            f"/api/compliance/documentos/{doc_id}/verificar",
            json={"conteudo_base64": "!!! não é base64 !!!"},
        )
        assert resposta.status_code == 422

    def test_pendencias_ordenadas_por_exposicao(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A lista existe para embasar a decisão de exigir identificação
        antes da ativação — por isso ordena por capital exposto."""
        op_id = db_session.execute(
            text("""
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values (:t, 'emprestimo', 30000, 2.0, 'PRICE', 12, 'registrada', 'REG-PLD')
            returning id
            """),
            {"t": str(tomador_autorizado)},
        ).scalar_one()
        db_session.commit()
        ativar_operacao(db_session, op_id)

        pendencias = admin_client.get("/api/compliance/identificacao/pendencias").json()
        assert len(pendencias) == 1
        assert Decimal(pendencias[0]["capital_exposto"]) == Decimal("30000.00")

        # Depois de arquivar, o tomador sai da lista.
        admin_client.post(
            f"/api/compliance/tomadores/{tomador_autorizado}/documentos",
            json={"tipo": "contrato_social", "nome_arquivo": "c.pdf", "sha256": _sha(b"c")},
        )
        assert admin_client.get("/api/compliance/identificacao/pendencias").json() == []


class TestRetencao:
    def test_apagar_dentro_do_prazo_e_recusado(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """A obrigação de guardar não pode depender de alguém lembrar dela."""
        db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
            values (:t, 'contrato_social', 'c.pdf', :sha, current_date + 1)
            """),
            {"t": str(tomador_autorizado), "sha": _sha(b"c")},
        )
        db_session.commit()

        with pytest.raises(Exception) as exc:
            db_session.execute(text("delete from tomador_documento"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_apagar_depois_do_prazo_e_permitido(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """A retenção é obrigação de guardar por 5 anos, não para sempre —
        depois do prazo, expurgar é legítimo (e desejável, por minimização
        de dados)."""
        db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
            values (:t, 'contrato_social', 'antigo.pdf', :sha, current_date - 1)
            """),
            {"t": str(tomador_autorizado), "sha": _sha(b"antigo")},
        )
        db_session.commit()

        db_session.execute(text("delete from tomador_documento"))
        db_session.commit()
        assert db_session.execute(text("select count(*) from tomador_documento")).scalar_one() == 0

    def test_evidencia_nao_pode_ser_alterada(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Trocar o hash de uma evidência arquivada anularia sua serventia:
        substitui-se por uma nova, não se edita a antiga."""
        db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
            values (:t, 'contrato_social', 'c.pdf', :sha, current_date + 1825)
            """),
            {"t": str(tomador_autorizado), "sha": _sha(b"c")},
        )
        db_session.commit()

        with pytest.raises(Exception) as exc:
            db_session.execute(text(f"update tomador_documento set sha256 = '{_sha(b'outro')}'"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()


# ---------------------------------------------------------------------
# Detecção de atipicidade
# ---------------------------------------------------------------------


def _operacao(
    db_session: Session, tomador_id: uuid.UUID, valor: str, status: str = "registrada"
) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', :v, 0, 'PRICE', 12, :s, 'REG-PLD')
        returning id
        """),
        {"t": str(tomador_id), "v": valor, "s": status},
    ).scalar_one()
    db_session.commit()
    return op_id


class TestAtipicidade:
    def test_fracionamento_detectado(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Padrão clássico de quem quer ficar abaixo do radar de cada
        operação isolada: várias pequenas somando acima do limiar."""
        for _ in range(3):
            _operacao(db_session, tomador_autorizado, "4000")

        resposta = admin_client.post(
            "/api/compliance/atipicidades/detectar", json={"limiar": "10000", "janela_dias": 30}
        )
        assert resposta.status_code == 200
        assert resposta.json()["novas_ocorrencias"] >= 1

        ocorrencias = admin_client.get("/api/compliance/atipicidades").json()
        fracionamento = [o for o in ocorrencias if o["regra"] == "fracionamento"]
        assert len(fracionamento) == 1
        assert fracionamento[0]["severidade"] == "alta"
        assert fracionamento[0]["tomador_razao_social"] == "Padaria Teste ME"

    def test_duas_operacoes_nao_bastam(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Duas operações pequenas são operação normal de crédito. A regra
        precisa de um piso, senão o painel enche de falso positivo e o
        analista para de olhar — o pior resultado para um controle de PLD."""
        for _ in range(2):
            _operacao(db_session, tomador_autorizado, "6000")

        admin_client.post("/api/compliance/atipicidades/detectar", json={})
        assert admin_client.get("/api/compliance/atipicidades").json() == []

    def test_varredura_e_idempotente(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        for _ in range(3):
            _operacao(db_session, tomador_autorizado, "4000")

        primeira = admin_client.post("/api/compliance/atipicidades/detectar", json={}).json()
        segunda = admin_client.post("/api/compliance/atipicidades/detectar", json={}).json()

        assert primeira["novas_ocorrencias"] >= 1
        assert segunda["novas_ocorrencias"] == 0
        assert (
            len(admin_client.get("/api/compliance/atipicidades").json())
            == primeira["novas_ocorrencias"]
        )

    def test_pagamento_em_excesso_detectado(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado, "12000")
        ativar_operacao(db_session, op_id)
        parcela = db_session.execute(
            text("select id, valor_total from parcela where operacao_id = :o and numero = 1"),
            {"o": str(op_id)},
        ).one()

        movimento = registrar_movimento_bancario(
            db_session,
            data_movimento=date.today(),
            valor=parcela.valor_total + Decimal("5000"),
            documento="FITID-EXCESSO",
        )
        baixar_parcela(db_session, parcela.id, movimento)

        admin_client.post("/api/compliance/atipicidades/detectar", json={})
        ocorrencias = admin_client.get("/api/compliance/atipicidades").json()
        assert any(o["regra"] == "pagamento_em_excesso" for o in ocorrencias)

    def test_ocorrencia_e_append_only(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        for _ in range(3):
            _operacao(db_session, tomador_autorizado, "4000")
        admin_client.post("/api/compliance/atipicidades/detectar", json={})

        with pytest.raises(Exception) as exc:
            db_session.execute(text("delete from ocorrencia_atipicidade"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC014"
        db_session.rollback()

        with pytest.raises(Exception) as exc:
            db_session.execute(text("update ocorrencia_atipicidade set severidade = 'baixa'"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC014"
        db_session.rollback()

    def test_adaptador_do_canal_externo_pode_ser_preenchido(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A exceção deliberada ao append-only: quando o regime PLD for
        definido, o envio grava aqui sem tocar na detecção."""
        for _ in range(3):
            _operacao(db_session, tomador_autorizado, "4000")
        admin_client.post("/api/compliance/atipicidades/detectar", json={})

        db_session.execute(
            text("""
            update ocorrencia_atipicidade
               set comunicado_em = now(), comunicacao_ref = 'COAF-2026-0001'
            """)
        )
        db_session.commit()

        ocorrencias = admin_client.get("/api/compliance/atipicidades").json()
        assert all(o["comunicado_em"] is not None for o in ocorrencias)

    def test_operador_nao_dispara_varredura(self, client: TestClient) -> None:
        operador = Usuario(
            id=uuid.uuid4(), email="op@orgatec.com", nome="Op", papel="operador", ativo=True
        )
        app.dependency_overrides[get_current_user] = lambda: operador
        assert client.post("/api/compliance/atipicidades/detectar", json={}).status_code == 403
