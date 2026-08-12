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

from app.capital_engine import (
    ativar_operacao,
    baixar_parcela,
    registrar_movimento_bancario,
    transicionar_operacao,
)
from app.core.exceptions import IdentificacaoAusente
from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.conftest import arquivar_identificacao, confirmar_registro, sqlstate_de


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
        self, admin_client: TestClient, tomador_sem_identificacao: uuid.UUID
    ) -> None:
        conteudo = b"contrato social em pdf"
        resposta = admin_client.post(
            f"/api/compliance/tomadores/{tomador_sem_identificacao}/documentos",
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
            f"/api/compliance/tomadores/{tomador_sem_identificacao}/documentos"
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
        tomador_sem_identificacao: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A lista mostra quem NÃO tem evidência arquivada.

        Desde a migration 014 a exigência está ligada, então esta lista
        deixou de ser só informativa: é a relação de tomadores com quem não
        se consegue mais ativar operação nenhuma."""
        tomador_autorizado = tomador_sem_identificacao
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
        confirmar_registro(db_session, op_id)

        # A operação NÃO consegue mais ativar: é exatamente o efeito do gate.
        with pytest.raises(IdentificacaoAusente) as exc:
            ativar_operacao(db_session, op_id)
        assert exc.value.sqlstate == "OC019"

        pendencias = admin_client.get("/api/compliance/identificacao/pendencias").json()
        assert len(pendencias) == 1
        # Capital exposto zero porque o gate impediu o comprometimento — que
        # é o resultado desejado da migration 014.
        assert Decimal(pendencias[0]["capital_exposto"]) == Decimal("0")

        # Depois de arquivar, o tomador sai da lista E a operação ativa.
        admin_client.post(
            f"/api/compliance/tomadores/{tomador_autorizado}/documentos",
            json={"tipo": "contrato_social", "nome_arquivo": "c.pdf", "sha256": _sha(b"c")},
        )
        assert admin_client.get("/api/compliance/identificacao/pendencias").json() == []
        assert ativar_operacao(db_session, op_id).status == "ativa"


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

        db_session.execute(text("delete from tomador_documento where nome_arquivo = 'antigo.pdf'"))
        db_session.commit()
        assert (
            db_session.execute(
                text("select count(*) from tomador_documento where nome_arquivo = 'antigo.pdf'")
            ).scalar_one()
            == 0
        )

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

    def test_truncate_na_evidencia_e_recusado(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """O furo fechado pela migration 016.

        O trigger da 010 é BEFORE UPDATE/DELETE FOR EACH ROW, e TRUNCATE não
        visita linhas: `truncate table tomador_documento` apagava todas as
        evidências de identificação — as que estão sob retenção legal de 5
        anos junto (Lei 9.613/98, art. 10, III) — sem levantar erro. Pior do
        que o DELETE que o banco já recusava, e mais fácil de escrever.
        """
        db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
            values (:t, 'contrato_social', 'retido.pdf', :sha, current_date + 1825)
            """),
            {"t": str(tomador_autorizado), "sha": _sha(b"retido")},
        )
        db_session.commit()

        with pytest.raises(Exception) as exc:
            db_session.execute(text("truncate table tomador_documento cascade"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

        assert (
            db_session.execute(
                text("select count(*) from tomador_documento where nome_arquivo = 'retido.pdf'")
            ).scalar_one()
            == 1
        )

    def test_expurgo_seletivo_continua_permitido(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Caminho feliz da 016: a trava é contra apagar a trilha INTEIRA de
        uma vez, não contra a minimização de dados. Um DELETE que seleciona o
        que já venceu o prazo passa exatamente como antes — a diferença é que
        agora não existe atalho que dispense a seleção."""
        db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
            values (:t, 'contrato_social', 'vencido.pdf', :sha, current_date - 1),
                   (:t, 'cartao_cnpj', 'vigente.pdf', :sha2, current_date + 1825)
            """),
            {
                "t": str(tomador_autorizado),
                "sha": _sha(b"vencido"),
                "sha2": _sha(b"vigente"),
            },
        )
        db_session.commit()

        db_session.execute(text("delete from tomador_documento where retencao_ate < current_date"))
        db_session.commit()

        restantes = (
            db_session.execute(
                text("select nome_arquivo from tomador_documento order by nome_arquivo")
            )
            .scalars()
            .all()
        )
        # 'contrato_social.pdf' vem da fixture `tomador_autorizado`, que arquiva
        # a identificação exigida pelo gate da 014 — e está dentro do prazo.
        assert restantes == ["contrato_social.pdf", "vigente.pdf"]


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
        confirmar_registro(db_session, op_id)
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

    def test_truncate_na_ocorrencia_e_recusado(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A migration 016 fecha o atalho que tornava o append-only da 010
        decorativo: o DELETE era recusado linha a linha, mas `truncate table
        ocorrencia_atipicidade` limpava o painel de PLD inteiro sem erro —
        exatamente o que faria quem quisesse esconder um alerta, e mais curto
        de escrever do que o DELETE que o banco recusava."""
        for _ in range(3):
            _operacao(db_session, tomador_autorizado, "4000")
        admin_client.post("/api/compliance/atipicidades/detectar", json={})

        antes = db_session.execute(text("select count(*) from ocorrencia_atipicidade")).scalar_one()
        assert antes >= 1

        with pytest.raises(Exception) as exc:
            db_session.execute(text("truncate table ocorrencia_atipicidade"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC014"
        db_session.rollback()

        assert (
            db_session.execute(text("select count(*) from ocorrencia_atipicidade")).scalar_one()
            == antes
        )

    def test_deteccao_continua_gravando_apos_a_trava(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Caminho feliz: BEFORE TRUNCATE não toca em INSERT. A varredura
        continua gravando ocorrências novas e o adaptador do canal externo
        continua preenchível — travar a saída não pode travar a entrada."""
        for _ in range(3):
            _operacao(db_session, tomador_autorizado, "4000")

        resposta = admin_client.post("/api/compliance/atipicidades/detectar", json={})
        assert resposta.status_code == 200
        assert resposta.json()["novas_ocorrencias"] >= 1

        db_session.execute(
            text("update ocorrencia_atipicidade set comunicado_em = clock_timestamp()")
        )
        db_session.commit()

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


class TestGateIdentificacao:
    """Migration 014: emprestar para quem não se sabe quem é passou a ser
    recusado pelo banco (Lei 9.613/98, art. 10, I)."""

    def _operacao_pronta(self, db_session: Session, tomador_id: uuid.UUID) -> uuid.UUID:
        """Operação registrada, com registro confirmado — só falta a
        identificação. Isola OC019 de OC004."""
        op_id = _operacao(db_session, tomador_id, "10000")
        confirmar_registro(db_session, op_id)
        return op_id

    def test_sem_identificacao_bloqueia(
        self,
        db_session: Session,
        tomador_sem_identificacao: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = self._operacao_pronta(db_session, tomador_sem_identificacao)

        with pytest.raises(IdentificacaoAusente) as exc:
            ativar_operacao(db_session, op_id)
        assert exc.value.sqlstate == "OC019"
        assert exc.value.http_status == 422

    def test_qualquer_evidencia_basta(
        self,
        db_session: Session,
        tomador_sem_identificacao: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A regra mínima defensável é UMA evidência. Exigir um tipo
        específico é política de KYC da ESC, não decisão de quem escreve o
        sistema — `tomador_documento.tipo` existe para quando ela sair."""
        op_id = self._operacao_pronta(db_session, tomador_sem_identificacao)
        arquivar_identificacao(db_session, tomador_sem_identificacao, tipo="comprovante_endereco")

        assert ativar_operacao(db_session, op_id).status == "ativa"

    def test_evidencia_expurgada_volta_a_bloquear(
        self,
        db_session: Session,
        tomador_sem_identificacao: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Documento apagado depois do prazo de retenção deixa de contar — e
        é correto: se a evidência não existe mais, não há o que apresentar
        numa fiscalização."""
        db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
            values (:t, 'contrato_social', 'vencido.pdf', :sha, current_date - 1)
            """),
            {"t": str(tomador_sem_identificacao), "sha": _sha(b"vencido")},
        )
        db_session.commit()

        op_id = self._operacao_pronta(db_session, tomador_sem_identificacao)
        assert ativar_operacao(db_session, op_id).status == "ativa"

        # Expurgado o documento, uma NOVA operação já não ativa.
        transicionar_operacao(db_session, op_id, "liquidada")
        db_session.execute(text("delete from tomador_documento where nome_arquivo = 'vencido.pdf'"))
        db_session.commit()

        outra = self._operacao_pronta(db_session, tomador_sem_identificacao)
        with pytest.raises(IdentificacaoAusente):
            ativar_operacao(db_session, outra)

    def test_reativar_inadimplente_nao_revalida(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Mesma disciplina do gate de registro: regularizar é ato sobre
        operação que JÁ comprometia capital."""
        op_id = self._operacao_pronta(db_session, tomador_autorizado)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "inadimplente")

        assert ativar_operacao(db_session, op_id).status == "ativa"

    def test_identificacao_e_verificada_antes_do_gate_geografico(
        self, db_session: Session, capital_constituido: None
    ) -> None:
        """Não saber quem é o tomador é falha mais grave do que ele estar
        fora da área — e a mensagem mais útil é a da falha mais grave."""
        tomador_id = db_session.execute(
            text("""
            insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
            values (:cnpj, 'Fora e Sem Papel ME', 'ME', 'Goiania', 'GO', false)
            returning id
            """),
            {"cnpj": f"{uuid.uuid4().int % 10**14:014d}"},
        ).scalar_one()
        db_session.commit()

        op_id = self._operacao_pronta(db_session, tomador_id)

        with pytest.raises(IdentificacaoAusente):
            ativar_operacao(db_session, op_id)
