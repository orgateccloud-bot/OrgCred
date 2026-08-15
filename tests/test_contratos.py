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
4. Que a seção de registro do corpo cite o registro CONFIRMADO (entidade e
   protocolo), e nunca mais o `registro_entidade_ref` de texto livre — e que
   diga, em letras de forma, quando não há registro confirmado a citar.
"""

import base64
import hashlib
import uuid
from types import SimpleNamespace
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.contrato import gerar_corpo
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


# Os mesmos dados que `esc_identificada` põe em settings, para os testes que
# chamam `gerar_corpo` direto em vez de passar pelo endpoint.
_CREDOR_STUB = SimpleNamespace(
    razao_social="ORGATEC ESC LTDA",
    cnpj="11222333000181",
    municipio="Formoso",
    uf="GO",
)


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

    def test_corpo_cita_entidade_e_protocolo_do_registro_confirmado(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        esc_identificada: None,
    ) -> None:
        """O instrumento vai a terceiros: o que ele afirma sobre o registro
        tem de ser o que o sistema conseguiu PROVAR — a linha confirmada de
        `registro_operacao`, com protocolo garantido por constraint."""
        op_id = _operacao(db_session, tomador_autorizado, ativar=True)
        protocolo = db_session.execute(
            text("""
            select protocolo from registro_operacao
            where operacao_id = :o and status = 'confirmado'
            """),
            {"o": str(op_id)},
        ).scalar_one()

        corpo = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()["corpo"]

        assert "Entidade registradora: CRDC" in corpo
        assert f"Protocolo do registro: {protocolo}" in corpo
        assert "Registro confirmado em:" in corpo
        # O texto livre da operação não entra mais no documento: a operação
        # tem `registro_entidade_ref = 'REG-CONTRATO'`, que ninguém validou.
        assert "REG-CONTRATO" not in corpo
        assert "SEM REGISTRO CONFIRMADO" not in corpo

    def test_sem_registro_confirmado_o_corpo_marca_a_ausencia(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        esc_identificada: None,
    ) -> None:
        """Emitir antes do registro é legítimo — a registradora costuma pedir
        o instrumento para registrar. O que não pode é o papel citar como
        prova o texto livre que o gate já rebaixou."""
        op_id = _operacao(db_session, tomador_autorizado)

        corpo = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()["corpo"]

        assert "SEM REGISTRO CONFIRMADO" in corpo
        assert "nenhum valor é liberado" in corpo
        assert "REG-CONTRATO" not in corpo
        assert "Protocolo do registro" not in corpo

    def test_registro_pendente_ou_rejeitado_nao_vira_citacao(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        esc_identificada: None,
    ) -> None:
        """Abrir o registro é intenção; confirmar é fato. Só o fato vai ao
        papel — a mesma régua do gate da migration 013."""
        op_id = _operacao(db_session, tomador_autorizado)
        registro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()

        pendente = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()[
            "corpo"
        ]
        assert "SEM REGISTRO CONFIRMADO" in pendente
        assert "CRDC" not in pendente

        operador_client.post(
            f"/api/contratos/registros/{registro['id']}/rejeitar",
            json={"motivo": "CNPJ do tomador inconsistente"},
        )
        rejeitado = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()[
            "corpo"
        ]
        assert "SEM REGISTRO CONFIRMADO" in rejeitado
        assert "CNPJ do tomador inconsistente" not in rejeitado

    def test_confirmar_depois_muda_a_versao_nova_e_preserva_a_antiga(
        self,
        operador_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        esc_identificada: None,
    ) -> None:
        """A verdade nova entra por VERSÃO NOVA. O contrato emitido antes do
        registro continua bit a bit o que foi entregue ao tomador, com o hash
        que o banco calculou na emissão — nada é recalculado."""
        op_id = _operacao(db_session, tomador_autorizado)
        antes = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()

        registro = operador_client.post(
            f"/api/contratos/operacoes/{op_id}/registros", json={"entidade": "CRDC"}
        ).json()
        operador_client.post(
            f"/api/contratos/registros/{registro['id']}/confirmar",
            json={"protocolo": "CRDC-2026-000123"},
        )
        depois = operador_client.post(f"/api/contratos/operacoes/{op_id}/contrato").json()

        assert "SEM REGISTRO CONFIRMADO" in antes["corpo"]
        assert "CRDC-2026-000123" in depois["corpo"]
        assert depois["versao"] == 2
        assert antes["sha256"] != depois["sha256"]

        # A versão 1 no banco não foi tocada pela emissão da versão 2.
        v1 = db_session.execute(
            text("select corpo, sha256 from contrato_emprestimo where id = :c"),
            {"c": antes["id"]},
        ).one()
        assert v1.corpo == antes["corpo"]
        assert v1.sha256 == hashlib.sha256(antes["corpo"].encode("utf-8")).hexdigest()

    @pytest.mark.parametrize("status", ["ativa", "inadimplente", "liquidada", "renegociada"])
    def test_sem_registro_o_corpo_nao_nega_capital_ja_liberado(
        self, db_session: Session, tomador_autorizado: uuid.UUID, status: str
    ) -> None:
        """A operação SEM registro confirmado que MESMO ASSIM comprometeu
        capital existe — e o instrumento não pode negá-la.

        O gate da migration 013 só roda NA TRANSIÇÃO: a própria migration
        registra que "operações JÁ ativas seguem ativas", e a view
        `v_operacoes_sem_registro_confirmado` foi criada para contar
        exatamente essa população, com coluna `tem_contrato` — ou seja, o
        schema já prevê contrato emitido para operação ativa sem registro.
        Dizer a essa operação "nenhum valor é liberado" seria o mesmo pecado
        que motivou tirar `registro_entidade_ref` do documento: o papel
        afirmando o que o sistema sabe ser falso, só que agora na direção que
        favorece a CREDORA.

        Teste de unidade, e não pelo endpoint, porque o cenário NÃO é
        construível no schema de hoje — é herança de antes do gate, e tentar
        montá-lo por SQL cru esbarra no próprio OC004 (ver
        TestGateAtivacao). O que se prova aqui é o contrato de `gerar_corpo`.
        """
        op_id = _operacao(db_session, tomador_autorizado)
        operacao = db_session.execute(
            text("select * from operacao_credito where id = :o"), {"o": str(op_id)}
        ).one()
        tomador = db_session.execute(
            text("select * from tomador where id = :t"), {"t": str(tomador_autorizado)}
        ).one()
        herdada = SimpleNamespace(**dict(operacao._mapping) | {"status": status})

        corpo = gerar_corpo(herdada, tomador, [], _CREDOR_STUB, None)

        assert "SEM REGISTRO CONFIRMADO" in corpo
        assert "JÁ COMPROMETEU CAPITAL" in corpo
        assert "PENDÊNCIA A REGULARIZAR" in corpo
        assert "nenhum valor é liberado" not in corpo
        # A promessa de reemissão vale nos dois ramos: é ela que diz ao leitor
        # que existe versão posterior a exigir.
        assert "reemitido em nova" in corpo

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

    # -----------------------------------------------------------------
    # Nascimento do registro (migration 021)
    # -----------------------------------------------------------------
    # A 012 guardava `update` e `delete` e deixava o `insert` aberto: dava para
    # criar a linha já 'confirmado', com protocolo, sem nunca passar por
    # 'pendente'. Como o gate OC004 (013) só pergunta se existe registro
    # confirmado, ele voltava a atestar digitação — o mesmo defeito que a 013
    # dizia ter corrigido ao aposentar o texto livre de `registro_entidade_ref`.
    #
    # Todos os bloqueios abaixo são por SQL cru de propósito: nenhum endpoint
    # aceita `status` na abertura (`POST /operacoes/{id}/registros` insere só
    # operacao_id/entidade/usuario_id), então o caminho que a 021 fecha é
    # exatamente este — banco aberto, script de carga, job.

    def test_nao_nasce_confirmado(self, db_session: Session, tomador_autorizado: uuid.UUID) -> None:
        """O ataque direto: linha nova já no estado terminal, com protocolo
        inventado. As CHECK constraints da 012 aceitavam (protocolo e
        confirmado_em estão lá); quem recusa é a guarda de nascimento."""
        op_id = _operacao(db_session, tomador_autorizado)

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                insert into registro_operacao
                    (operacao_id, entidade, status, protocolo, confirmado_em)
                values (:o, 'CRDC', 'confirmado', 'PROTO-INVENTADO', clock_timestamp())
                """),
                {"o": str(op_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC018"
        db_session.rollback()

    def test_nao_nasce_rejeitado(self, db_session: Session, tomador_autorizado: uuid.UUID) -> None:
        """'rejeitado' também é terminal. Nascer rejeitado não destrava nada,
        mas fabrica um histórico de tentativa que não houve — e a rejeição é
        o que a próxima tentativa lê para não repetir o erro."""
        op_id = _operacao(db_session, tomador_autorizado)

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                insert into registro_operacao (operacao_id, entidade, status, motivo_rejeicao)
                values (:o, 'CRDC', 'rejeitado', 'motivo fabricado')
                """),
                {"o": str(op_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC018"
        db_session.rollback()

    def test_nao_nasce_pendente_com_protocolo_e_data_de_confirmacao(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """A variante silenciosa: nasce com a palavra 'pendente' mas já com
        protocolo e `confirmado_em` pré-cozidos. Um `update set
        status='confirmado'` depois satisfaz a CHECK da 012 sem tocar em
        nenhum dos dois — e o registro passa a exibir uma data de confirmação
        anterior à confirmação."""
        op_id = _operacao(db_session, tomador_autorizado)

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                insert into registro_operacao
                    (operacao_id, entidade, status, protocolo, confirmado_em)
                values (:o, 'CRDC', 'pendente', 'PROTO-PRE-COZIDO', '2020-01-01 00:00:00')
                """),
                {"o": str(op_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC018"
        db_session.rollback()

    def test_pendente_nao_recebe_protocolo_por_update(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """A MESMA variante silenciosa, um comando mais tarde.

        Fechar o pré-cozimento só no INSERT custaria ao atacante um `update` a
        mais e nada além: abre o registro limpo (passa pela guarda de
        nascimento), pré-cozinha protocolo e `confirmado_em` mantendo a linha
        em 'pendente' — a CHECK da 012 nem se aplica a pendente — e só então
        muda o status num segundo update que não escreve nada. Rodado contra
        esta base antes da guarda gêmea existir: a linha terminava
        'confirmado', com protocolo à escolha e `confirmado_em` de 2020 sobre
        `enviado_em` de 2026.

        `confirmado_em` sai de `clock_timestamp()`, e não de uma data no
        passado, DE PROPÓSITO: com data passada quem recusaria seria a guarda
        de ordem dos carimbos (testada logo abaixo), e este teste passaria
        mesmo com a cláusula que ele diz cobrir desligada. Carimbo no presente
        deixa só uma cláusula capaz de barrar — e é a variante que importa,
        porque é a que produz um `confirmado_em` indistinguível do legítimo.
        """
        op_id = _operacao(db_session, tomador_autorizado)
        registro_id = db_session.execute(
            text("""
            insert into registro_operacao (operacao_id, entidade)
            values (:o, 'CRDC') returning id
            """),
            {"o": str(op_id)},
        ).scalar_one()

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                update registro_operacao
                   set protocolo = 'PROTO-PRE-COZIDO',
                       confirmado_em = clock_timestamp()
                 where id = :r
                """),
                {"r": str(registro_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC018"
        db_session.rollback()

    def test_confirmacao_nao_antecede_o_envio(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """E a última forma de produzir o mesmo defeito: um único UPDATE, com
        a forma exata do endpoint de confirmar, mas com `confirmado_em`
        escolhido no passado. A entidade não confirma o que ainda não
        recebeu — e é a ordem dos dois carimbos que a varredura da revisão
        alembic usa para achar registros forjados em base existente."""
        op_id = _operacao(db_session, tomador_autorizado)
        registro_id = db_session.execute(
            text("""
            insert into registro_operacao (operacao_id, entidade)
            values (:o, 'CRDC') returning id
            """),
            {"o": str(op_id)},
        ).scalar_one()

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                update registro_operacao
                   set status = 'confirmado', protocolo = 'CRDC-2026-000123',
                       confirmado_em = '2020-01-01 00:00:00'
                 where id = :r
                """),
                {"r": str(registro_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC018"
        db_session.rollback()

    def test_nasce_pendente_e_confirma_por_update(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """CAMINHO FELIZ, em SQL cru — a prova de que a 021 fechou o INSERT
        forjado sem fechar o INSERT legítimo.

        É a sequência que `confirmar_registro` (conftest) e os dois endpoints
        emitem: abre sem status (o default é 'pendente') e confirma por UPDATE.
        `confirmado_em` fica DEPOIS de `enviado_em` porque cada
        `clock_timestamp()` é lido no seu próprio comando — o que também é a
        assinatura que distingue este caminho do INSERT direto.
        """
        op_id = _operacao(db_session, tomador_autorizado)

        registro_id = db_session.execute(
            text("""
            insert into registro_operacao (operacao_id, entidade)
            values (:o, 'CRDC') returning id
            """),
            {"o": str(op_id)},
        ).scalar_one()
        db_session.execute(
            text("""
            update registro_operacao
               set status = 'confirmado', protocolo = 'CRDC-2026-000123',
                   confirmado_em = clock_timestamp()
             where id = :r
            """),
            {"r": str(registro_id)},
        )
        db_session.commit()

        linha = db_session.execute(
            text("select status, protocolo, enviado_em, confirmado_em from registro_operacao"),
            {},
        ).one()
        assert linha.status == "confirmado"
        assert linha.protocolo == "CRDC-2026-000123"
        assert linha.confirmado_em > linha.enviado_em

        # E o gate do Art. 5º §3º abre — o registro confirmado por processo
        # vale exatamente como o forjado valia, que é o ponto.
        ativar_operacao(db_session, op_id)
        assert (
            db_session.execute(
                text("select status from operacao_credito where id = :o"), {"o": str(op_id)}
            ).scalar_one()
            == "ativa"
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
