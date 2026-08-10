"""
Instrumento contratual e registro em entidade registradora (migration 012).

Três coisas que este arquivo trava:

1. Que o hash seja do BANCO, não da aplicação — corpo e hash não podem
   divergir, nem por bug no gerador nem por escrita direta.
2. Que o corpo seja DETERMINÍSTICO — sem isso, conferir a via do tomador
   contra a do sistema seria impossível.
3. Que 'confirmado' exija protocolo e seja terminal — registro confirmado
   sem número é indistinguível de alguém marcando a caixinha, que é o
   problema do `registro_entidade_ref` de texto livre.
"""

import base64
import hashlib
import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.config import settings
from app.core.security import get_current_user, get_operador_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from tests.conftest import confirmar_registro, sqlstate_de


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def operador_client(client: TestClient) -> TestClient:
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    app.dependency_overrides[get_operador_user] = lambda: operador
    return client


@pytest.fixture()
def esc_identificada() -> Generator[None, None, None]:
    """Identifica a ESC só durante o teste.

    Fixture em vez de valor fixo em `.env` porque o padrão do sistema é
    ficar SEM identificação — é isso que faz a emissão ser recusada, e há
    teste para esse caminho."""
    anterior = (
        settings.esc_razao_social,
        settings.esc_cnpj,
        settings.esc_municipio,
        settings.esc_uf,
    )
    settings.esc_razao_social = "ORGATEC ESC LTDA"
    settings.esc_cnpj = "11222333000181"
    settings.esc_municipio = "Formoso"
    settings.esc_uf = "GO"
    yield
    (
        settings.esc_razao_social,
        settings.esc_cnpj,
        settings.esc_municipio,
        settings.esc_uf,
    ) = anterior


def _operacao(db_session: Session, tomador_id: uuid.UUID, ativar: bool = False) -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', 12000, 2.0, 'PRICE', 12, 'registrada', 'REG-CONTRATO')
        returning id
        """),
        {"t": str(tomador_id)},
    ).scalar_one()
    db_session.commit()
    if ativar:
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
    return op_id


# ---------------------------------------------------------------------
# Instrumento contratual
# ---------------------------------------------------------------------


class TestContrato:
    def test_sem_esc_identificada_recusa(
        self, operador_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Emitir sem credora produziria um documento com efeito jurídico e
        sem uma das partes."""
        op_id = _operacao(db_session, tomador_autorizado)

        resposta = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato")
        assert resposta.status_code == 422
        assert "Dados da ESC não configurados" in resposta.json()["detail"]

    def test_nao_emitido_devolve_null(
        self, operador_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """A tela precisa distinguir 'não emitido' de 'erro ao carregar'."""
        op_id = _operacao(db_session, tomador_autorizado)
        assert operador_client.get(f"/api/contratos/operacoes/{op_id}/contrato").json() is None

    def test_emissao_traz_partes_condicoes_e_agenda(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)

        corpo = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()["corpo"]

        assert "CONTRATO DE EMPRÉSTIMO — EMPRESA SIMPLES DE CRÉDITO (ESC)" in corpo
        assert "ORGATEC ESC LTDA" in corpo
        assert "11.222.333/0001-81" in corpo  # CNPJ formatado
        assert "Padaria Teste ME" in corpo
        assert "R$ 12.000,00" in corpo
        assert "Tabela Price" in corpo
        # A agenda emitida na ativação integra o contrato.
        assert "AGENDA DE PAGAMENTOS" in corpo
        assert corpo.count("R$") > 12

    def test_operacao_sem_agenda_diz_isso_no_corpo(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        esc_identificada: None,
    ) -> None:
        """Emitir um documento que parece completo sem a agenda seria pior
        do que dizer que ela ainda não existe."""
        op_id = _operacao(db_session, tomador_autorizado)

        corpo = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()["corpo"]
        assert "não for ativada, não há agenda" in corpo

    def test_hash_e_do_banco_e_bate_com_o_corpo(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        """O hash nunca é enviado pela aplicação — o trigger o calcula. Assim
        corpo e hash não podem divergir."""
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)

        contrato = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()
        esperado = hashlib.sha256(contrato["corpo"].encode("utf-8")).hexdigest()
        assert contrato["sha256"] == esperado

    def test_corpo_e_deterministico(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        """Mesma operação, mesmo corpo, mesmo hash. Se o corpo trouxesse data
        de geração, conferir a via do tomador seria impossível."""
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)

        primeiro = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()
        segundo = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()

        assert primeiro["sha256"] == segundo["sha256"]
        assert segundo["versao"] == 2  # ...mas é uma nova versão

    def test_reemissao_preserva_a_anterior(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        """O tomador tem uma via do documento antigo."""
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)
        operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato")
        operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato")

        assert (
            db_session.execute(
                text("select count(*) from contrato_emprestimo where operacao_id = :o"),
                {"o": str(op_id)},
            ).scalar_one()
            == 2
        )
        # A leitura traz a vigente.
        assert (
            operador_client.get(f"/api/contratos/operacoes/{op_id}/contrato").json()["versao"] == 2
        )

    def test_contrato_e_imutavel(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)
        operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato")

        with pytest.raises(Exception) as exc:
            db_session.execute(text("update contrato_emprestimo set corpo = 'adulterado'"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC017"
        db_session.rollback()

        with pytest.raises(Exception) as exc:
            db_session.execute(text("delete from contrato_emprestimo"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC017"
        db_session.rollback()

    def test_verificacao_confere_bit_a_bit(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)
        contrato = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()

        igual = operador_client.post(
            f"/api/contratos/{contrato['id']}/verificar",
            json={"conteudo_base64": base64.b64encode(contrato["corpo"].encode()).decode()},
        ).json()
        assert igual["confere"] is True

        adulterado = operador_client.post(
            f"/api/contratos/{contrato['id']}/verificar",
            json={"conteudo_base64": base64.b64encode((contrato["corpo"] + " ").encode()).decode()},
        ).json()
        assert adulterado["confere"] is False

    def test_operacao_inexistente_404(
        self, operador_client: TestClient, esc_identificada: None
    ) -> None:
        assert (
            operador_client.post(f"/api/contratos/operacoes/{uuid.uuid4()}/contrato").status_code
            == 404
        )

    def test_verificar_contrato_inexistente_404(self, operador_client: TestClient) -> None:
        resposta = operador_client.post(
            f"/api/contratos/{uuid.uuid4()}/verificar",
            json={"conteudo_base64": base64.b64encode(b"x").decode()},
        )
        assert resposta.status_code == 404

    def test_base64_invalido_422(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)
        contrato = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()

        resposta = operador_client.post(
            f"/api/contratos/{contrato['id']}/verificar",
            json={"conteudo_base64": "!!! não é base64 !!!"},
        )
        assert resposta.status_code == 422


# ---------------------------------------------------------------------
# Registro em entidade registradora
# ---------------------------------------------------------------------


class TestRegistro:
    def test_abrir_e_confirmar(
        self, operador_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado)

        aberto = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()
        assert aberto["status"] == "pendente"
        assert aberto["protocolo"] is None

        confirmado = operador_client.post(
            f"/api/contratos/registros/{aberto['id']}/confirmar",
            json={"protocolo": "CRDC-2026-000123"},
        ).json()
        assert confirmado["status"] == "confirmado"
        assert confirmado["protocolo"] == "CRDC-2026-000123"
        assert confirmado["confirmado_em"] is not None

    def test_confirmado_e_terminal(
        self, operador_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Reverter um registro confirmado apagaria a prova de que a operação
        existe legalmente."""
        op_id = _operacao(db_session, tomador_autorizado)
        registro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()
        operador_client.post(
            f"/api/contratos/registros/{registro['id']}/confirmar", json={"protocolo": "P-1"}
        )

        resposta = operador_client.post(
            f"/api/contratos/registros/{registro['id']}/rejeitar", json={"motivo": "mudei de ideia"}
        )
        assert resposta.status_code == 409
        assert resposta.json()["codigo"] == "OC018"

    def test_rejeitado_e_terminal(
        self, operador_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado)
        registro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "Nuclea"}
        ).json()
        rejeitado = operador_client.post(
            f"/api/contratos/registros/{registro['id']}/rejeitar",
            json={"motivo": "CNPJ do tomador inconsistente"},
        ).json()
        assert rejeitado["status"] == "rejeitado"

        segunda = operador_client.post(
            f"/api/contratos/registros/{registro['id']}/confirmar", json={"protocolo": "P-2"}
        )
        assert segunda.status_code == 409

        # Mas nova tentativa de registro é permitida — rejeição não é o fim
        # da operação, só daquela tentativa.
        nova = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "Nuclea"}
        )
        assert nova.status_code == 201

    def test_dois_confirmados_na_mesma_operacao_e_recusado(
        self, operador_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Dois confirmados significariam a mesma operação registrada duas
        vezes — e nenhum sistema saberia qual vale."""
        op_id = _operacao(db_session, tomador_autorizado)
        primeiro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()
        segundo = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "Nuclea"}
        ).json()

        operador_client.post(
            f"/api/contratos/registros/{primeiro['id']}/confirmar", json={"protocolo": "P-1"}
        )
        conflito = operador_client.post(
            f"/api/contratos/registros/{segundo['id']}/confirmar", json={"protocolo": "P-2"}
        )
        assert conflito.status_code == 409
        assert "já tem um registro confirmado" in conflito.json()["detail"]

    def test_registro_nao_pode_ser_apagado(
        self, operador_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado)
        operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        )

        with pytest.raises(Exception) as exc:
            db_session.execute(text("delete from registro_operacao"))
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC018"
        db_session.rollback()

    def test_operacao_inexistente_404(self, operador_client: TestClient) -> None:
        assert (
            operador_client.post(
                f"/api/contratos/operacoes/{uuid.uuid4()}/registros", json={"entidade": "CRDC"}
            ).status_code
            == 404
        )

    def test_confirmar_registro_inexistente_404(self, operador_client: TestClient) -> None:
        assert (
            operador_client.post(
                f"/api/contratos/registros/{uuid.uuid4()}/confirmar", json={"protocolo": "P"}
            ).status_code
            == 404
        )

    def test_rejeitar_registro_inexistente_404(self, operador_client: TestClient) -> None:
        assert (
            operador_client.post(
                f"/api/contratos/registros/{uuid.uuid4()}/rejeitar", json={"motivo": "x"}
            ).status_code
            == 404
        )


class TestPendencias:
    def test_mede_a_lacuna_do_gate(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Operação em 'registrada' sem registro confirmado: com o gate
        ligado (migration 013), é exatamente o que NÃO consegue ativar."""
        op_id = _operacao(db_session, tomador_autorizado)

        pendencias = operador_client.get("/api/contratos/registros/pendencias").json()
        assert len(pendencias) == 1
        assert pendencias[0]["operacao_id"] == str(op_id)
        assert pendencias[0]["registro_entidade_ref"] == "REG-CONTRATO"
        assert pendencias[0]["tem_registro_pendente"] is False
        assert pendencias[0]["tem_contrato"] is False

    def test_confirmado_sai_da_lista(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado)
        registro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()

        assert len(operador_client.get("/api/contratos/registros/pendencias").json()) == 1

        operador_client.post(
            f"/api/contratos/registros/{registro['id']}/confirmar", json={"protocolo": "P-1"}
        )
        assert operador_client.get("/api/contratos/registros/pendencias").json() == []


class TestGateAtivacao:
    """Migration 013: o Art. 5º §3º deixou de ser honrado na palavra."""

    def test_ativar_sem_registro_confirmado_e_bloqueado(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A operação tem `registro_entidade_ref = 'REG-CONTRATO'` — texto
        que antes bastava. Agora não basta."""
        op_id = _operacao(db_session, tomador_autorizado)

        resposta = operador_client.post(f"/api/operacoes/{op_id}/ativar")
        assert resposta.status_code == 422
        assert resposta.json()["codigo"] == "OC004"
        assert "CONFIRMADO" in resposta.json()["detail"]

    def test_registro_pendente_nao_basta(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Abrir o registro é intenção; confirmar é fato. Só o fato ativa."""
        op_id = _operacao(db_session, tomador_autorizado)
        operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        )

        assert operador_client.post(f"/api/operacoes/{op_id}/ativar").status_code == 422

    def test_registro_rejeitado_nao_basta(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado)
        registro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()
        operador_client.post(
            f"/api/contratos/registros/{registro['id']}/rejeitar", json={"motivo": "CNPJ errado"}
        )

        assert operador_client.post(f"/api/operacoes/{op_id}/ativar").status_code == 422

    def test_confirmado_libera_a_ativacao(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        op_id = _operacao(db_session, tomador_autorizado)
        registro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()
        operador_client.post(
            f"/api/contratos/registros/{registro['id']}/confirmar",
            json={"protocolo": "CRDC-2026-000123"},
        )

        assert operador_client.post(f"/api/operacoes/{op_id}/ativar").status_code == 200

    def test_reativar_inadimplente_nao_revalida_o_registro(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Regularizar uma inadimplente é ato sobre operação que JÁ comprometia
        capital. Exigir registro de novo travaria a regularização por um ato
        que já aconteceu — e o registro daquela operação continua válido."""
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)
        operador_client.post(f"/api/operacoes/{op_id}/marcar-inadimplente")

        assert operador_client.post(f"/api/operacoes/{op_id}/ativar").status_code == 200

    def test_operacao_ja_ativa_nao_e_afetada(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O gate roda na TRANSIÇÃO. Uma operação já ativa segue ativa, e
        alterações que não mexem no status não o revalidam — revogar
        retroativamente o que já foi emprestado não devolveria o dinheiro,
        só quebraria a carteira existente."""
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)

        db_session.execute(
            text("update operacao_credito set registro_entidade_ref = 'OUTRO' where id = :o"),
            {"o": str(op_id)},
        )
        db_session.commit()

        status = db_session.execute(
            text("select status from operacao_credito where id = :o"), {"o": str(op_id)}
        ).scalar_one()
        assert status == "ativa"
