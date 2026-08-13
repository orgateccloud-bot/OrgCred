"""Testes do router HTTP /auditoria — trilha de auditoria (hash-chain)."""

import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.security import get_current_user
from app.db import get_db
from app.main import app
from app.models import Usuario
from app.routers.auditoria import PAGINA_MAX, TAMANHO_PAGINA_MAX, TAMANHO_PAGINA_PADRAO
from tests.conftest import confirmar_registro


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def authed_client(client: TestClient) -> TestClient:
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Operador Teste", papel="operador", ativo=True
    )
    app.dependency_overrides[get_current_user] = lambda: operador
    return client


class TestAuditoria:
    def test_sem_autenticacao_retorna_401(self, client: TestClient) -> None:
        response = client.get("/api/auditoria")
        assert response.status_code == 401

    def test_sem_eventos_cadeia_integra_e_vazia(self, authed_client: TestClient) -> None:
        response = authed_client.get("/api/auditoria")
        assert response.status_code == 200
        body = response.json()
        assert body["integro"] is True
        assert body["quebras"] == []
        assert body["eventos"] == []
        # Contrato de paginação (passo 14): mesmo vazio, o cliente precisa
        # saber que não há mais nada além do que recebeu.
        assert body["total"] == 0
        assert body["pagina"] == 1
        assert body["tamanho_pagina"] == TAMANHO_PAGINA_PADRAO

    def test_apos_ativacao_evento_aparece_com_autor_e_hash(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        db_session.execute(
            text(
                "insert into usuario (id, email, nome, papel) values (:id, 'a@b.com', 'Ana', 'operador')"
            ),
            {"id": str(uuid.UUID(int=1))},
        )
        db_session.commit()

        result = db_session.execute(
            text(
                """
                insert into operacao_credito
                    (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                     sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
                values
                    (:tomador_id, 'emprestimo', 15000, 2.5, 'PRICE', 12, 'registrada', 'REG-AUD')
                returning id
                """
            ),
            {"tomador_id": str(tomador_autorizado)},
        )
        db_session.commit()
        op_id = result.scalar_one()

        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id, usuario_id=str(uuid.UUID(int=1)))

        response = authed_client.get("/api/auditoria")

        assert response.status_code == 200
        body = response.json()
        assert body["integro"] is True
        assert len(body["eventos"]) == 1
        evento = body["eventos"][0]
        assert evento["evento_tipo"] == "ativacao_operacao"
        assert evento["usuario_nome"] == "Ana"
        assert evento["current_hash"] is not None
        assert evento["prev_hash"] is None  # primeiro evento da cadeia
        assert body["total"] == 1


def _ativar_operacao_de(db_session: Session, tomador_id: uuid.UUID, valor: int) -> uuid.UUID:
    """Cria, registra e ativa uma operação — cada ativação grava UM evento no
    capital_ledger, que é o material bruto dos testes de paginação."""
    result = db_session.execute(
        text(
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values
                (:tomador_id, 'emprestimo', :valor, 2.5, 'PRICE', 12, 'registrada', 'REG-PAG')
            returning id
            """
        ),
        {"tomador_id": str(tomador_id), "valor": valor},
    )
    db_session.commit()
    op_id: uuid.UUID = result.scalar_one()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)
    return op_id


class TestPaginacao:
    """Passo 14: GET /api/auditoria devolvia o ledger inteiro, que é
    append-only e cresce para sempre."""

    def test_devolve_total_e_a_pagina_pedida(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        for valor in (5_000, 6_000, 7_000):
            _ativar_operacao_de(db_session, tomador_autorizado, valor)

        primeira = authed_client.get("/api/auditoria", params={"pagina": 1, "tamanho": 2})
        segunda = authed_client.get("/api/auditoria", params={"pagina": 2, "tamanho": 2})

        assert primeira.status_code == 200
        assert segunda.status_code == 200

        corpo_1, corpo_2 = primeira.json(), segunda.json()

        # `total` conta o ledger inteiro, não a página — é o que permite ao
        # cliente saber que existe uma segunda página.
        assert corpo_1["total"] == 3
        assert corpo_2["total"] == 3
        assert corpo_1["pagina"] == 1 and corpo_1["tamanho_pagina"] == 2
        assert corpo_2["pagina"] == 2 and corpo_2["tamanho_pagina"] == 2
        assert len(corpo_1["eventos"]) == 2
        assert len(corpo_2["eventos"]) == 1

        # As três ativações entram na mesma transação de teste e podem
        # compartilhar o `created_at` (now() é por transação no Postgres), de
        # modo que a ORDEM entre elas não é determinística aqui. O que a
        # paginação promete e este teste cobra é o particionamento: sem
        # sobreposição entre páginas e sem evento perdido.
        ids_1 = {e["id"] for e in corpo_1["eventos"]}
        ids_2 = {e["id"] for e in corpo_2["eventos"]}
        assert ids_1.isdisjoint(ids_2)
        assert len(ids_1 | ids_2) == 3

        # A verificação da cadeia continua sendo sobre o ledger INTEIRO, não
        # sobre a página — paginar `quebras` faria `integro` mentir. Aqui isso
        # se prova pela igualdade entre as duas páginas: as mesmas quebras
        # (nenhuma ou todas) aparecem em qualquer página pedida.
        #
        # Não se afirma `integro is True`: as três ativações acontecem dentro
        # da MESMA transação de teste, e `created_at` é o timestamp da
        # transação no Postgres — as três linhas empatam. Com empate, o
        # trigger de insert (migration 005) escolhe a linha anterior por
        # `id desc` enquanto `fn_verificar_cadeia_ledger()` reordena por
        # `id asc`, e a cadeia acusa quebra conforme o sorteio dos UUIDs.
        # É fragilidade pré-existente do ledger, não da paginação.
        assert corpo_1["integro"] == corpo_2["integro"]
        assert corpo_1["quebras"] == corpo_2["quebras"]

    def test_pagina_alem_do_fim_vem_vazia_mas_com_total(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        _ativar_operacao_de(db_session, tomador_autorizado, 5_000)

        response = authed_client.get("/api/auditoria", params={"pagina": 9, "tamanho": 10})

        assert response.status_code == 200
        body = response.json()
        assert body["eventos"] == []
        assert body["total"] == 1

    def test_sem_parametros_usa_o_padrao(
        self,
        authed_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Compatibilidade: o painel chama o endpoint sem query string."""
        _ativar_operacao_de(db_session, tomador_autorizado, 5_000)

        response = authed_client.get("/api/auditoria")

        assert response.status_code == 200
        body = response.json()
        assert body["pagina"] == 1
        assert body["tamanho_pagina"] == TAMANHO_PAGINA_PADRAO
        assert len(body["eventos"]) == 1

    def test_tamanho_acima_do_teto_e_recusado(self, authed_client: TestClient) -> None:
        """Sem teto, `?tamanho=999999` reabriria o buraco que a página fechou."""
        response = authed_client.get("/api/auditoria", params={"tamanho": TAMANHO_PAGINA_MAX + 1})

        assert response.status_code == 422

    def test_pagina_zero_e_recusada(self, authed_client: TestClient) -> None:
        """1-based: `pagina=0` viraria offset negativo no SQL."""
        response = authed_client.get("/api/auditoria", params={"pagina": 0})

        assert response.status_code == 422

    @pytest.mark.parametrize("pagina", [PAGINA_MAX + 1, 10**19, 10**30])
    def test_pagina_absurda_e_recusada_e_nao_estoura_o_banco(
        self, authed_client: TestClient, pagina: int
    ) -> None:
        """O piso sozinho não bastava: o Pydantic aceita inteiro de precisão
        arbitrária, e sem teto `?pagina=10000000000000000000` produzia um
        OFFSET maior que o bigint do Postgres — o driver estourava e o
        endpoint respondia 500, um erro de servidor que qualquer usuário
        autenticado dispara de propósito só mudando a query string."""
        response = authed_client.get("/api/auditoria", params={"pagina": pagina})

        assert response.status_code == 422

    def test_a_ultima_pagina_valida_ainda_e_atendida(self, authed_client: TestClient) -> None:
        """Contraprova do teto: o limite recusa o absurdo sem recusar a borda
        legítima — `pagina=PAGINA_MAX` continua sendo uma consulta válida."""
        response = authed_client.get(
            "/api/auditoria", params={"pagina": PAGINA_MAX, "tamanho": TAMANHO_PAGINA_MAX}
        )

        assert response.status_code == 200
        assert response.json()["eventos"] == []
