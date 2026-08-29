"""
O portal do tomador (migration 031 + app/routers/portal.py).

O QUE ESTE ARQUIVO PRECISA PROVAR, em ordem de gravidade — e a ordem é a mesma
da superfície de ataque de um portal de cliente:

1. QUE UM TOMADOR NÃO VÊ O DE OUTRO. É o invariante do portal. Testado pelos
   dois caminhos: a listagem só traz as operações dele, e o acesso direto à
   operação de outro responde 404 (não 403 — a existência já é informação).
2. QUE O ESCOPO NÃO É FORJÁVEL. O tomador não passa o `tomador_id`; ele vem do
   login. Não há parâmetro que o deixe escolher outra empresa.
3. QUE OS PAPÉIS SÃO ESTANQUES. Tomador não entra no painel; operador não entra
   no portal. As duas direções, porque um vazamento em qualquer uma basta.
4. QUE O BANCO RECUSA O VÍNCULO INCOERENTE. Um 'tomador' sem empresa, ou um
   'operador' com empresa, é recusado no INSERT — o CHECK da 031.
"""

import uuid
from decimal import Decimal
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao
from app.core.security import get_current_user
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


def _tomador(db_session: Session, razao: str, cnpj: str) -> uuid.UUID:
    tid = db_session.execute(
        text("""
        insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
        values (:c, :r, 'ME', 'Sao Paulo', 'SP', true)
        returning id
        """),
        {"c": cnpj, "r": razao},
    ).scalar_one()
    db_session.execute(
        text("""
        insert into tomador_documento (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
        values (:t, 'contrato_social', 'cs.pdf', :sha, current_date + interval '5 years')
        """),
        {"t": str(tid), "sha": "c" * 64},
    )
    db_session.commit()
    return tid


def _operacao_ativa(db_session: Session, tomador_id: uuid.UUID, valor: str = "12000") -> uuid.UUID:
    op_id = db_session.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
        values (:t, 'emprestimo', :v, 2, 'PRICE', 4, 'registrada', 'REG-PORTAL')
        returning id
        """),
        {"t": str(tomador_id), "v": valor},
    ).scalar_one()
    db_session.commit()
    confirmar_registro(db_session, op_id)
    ativar_operacao(db_session, op_id)
    return op_id


def _login_tomador(db_session: Session, tomador_id: uuid.UUID) -> Usuario:
    return Usuario(
        id=uuid.uuid4(),
        email=f"tomador-{uuid.uuid4().hex[:6]}@empresa.com",
        nome="Login do Tomador",
        papel="tomador",
        tomador_id=tomador_id,
        ativo=True,
    )


def _como(client: TestClient, user: Usuario) -> TestClient:
    """Autentica como `user` sobrescrevendo SÓ get_current_user — os portões de
    papel (get_painel_user, get_tomador_user) rodam de verdade."""
    app.dependency_overrides[get_current_user] = lambda: user
    return client


# ---------------------------------------------------------------------
# 1 e 2. Um tomador vê só o dele, e o escopo não é forjável
# ---------------------------------------------------------------------


def test_a_listagem_traz_so_as_operacoes_do_proprio_tomador(
    client: TestClient, db_session: Session, capital_constituido
) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    b = _tomador(db_session, "Empresa B", "44555666000199")
    _operacao_ativa(db_session, a)
    _operacao_ativa(db_session, a)
    _operacao_ativa(db_session, b)

    resp = _como(client, _login_tomador(db_session, a)).get("/api/portal/operacoes")
    assert resp.status_code == 200
    corpo = resp.json()
    assert len(corpo) == 2, "a listagem vazou a operação da outra empresa"


def test_operacao_de_outro_tomador_responde_404_e_nao_403(
    client: TestClient, db_session: Session, capital_constituido
) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    b = _tomador(db_session, "Empresa B", "44555666000199")
    op_de_b = _operacao_ativa(db_session, b)

    como_a = _como(client, _login_tomador(db_session, a))
    for sufixo in ("", "/parcelas", "/contrato"):
        resp = como_a.get(f"/api/portal/operacoes/{op_de_b}{sufixo}")
        assert (
            resp.status_code == 404
        ), f"{sufixo!r} devolveu {resp.status_code}: 403 confirmaria que a operação existe"


def test_a_agenda_do_proprio_tomador_abre(
    client: TestClient, db_session: Session, capital_constituido
) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    op = _operacao_ativa(db_session, a)

    resp = _como(client, _login_tomador(db_session, a)).get(f"/api/portal/operacoes/{op}/parcelas")
    assert resp.status_code == 200
    corpo = resp.json()
    assert len(corpo["parcelas"]) == 4
    assert Decimal(corpo["total_geral"]) > 0
    # O portal não expõe o lastro interno: a agenda do tomador não traz
    # movimento_documento nem valor de conciliação.
    assert "movimento_documento" not in corpo["parcelas"][0]


def test_o_perfil_conta_as_proprias_operacoes(
    client: TestClient, db_session: Session, capital_constituido
) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    _operacao_ativa(db_session, a)
    b = _tomador(db_session, "Empresa B", "44555666000199")
    _operacao_ativa(db_session, b)

    resp = _como(client, _login_tomador(db_session, a)).get("/api/portal/perfil")
    assert resp.status_code == 200
    corpo = resp.json()
    assert corpo["razao_social"] == "Empresa A"
    assert corpo["operacoes_total"] == 1
    assert corpo["operacoes_ativas"] == 1


# ---------------------------------------------------------------------
# 3. Papéis estanques, nas duas direções
# ---------------------------------------------------------------------


def test_tomador_e_barrado_no_painel(
    client: TestClient, db_session: Session, capital_constituido
) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    como_a = _como(client, _login_tomador(db_session, a))

    # As rotas de painel que só pedem get_current_user por dentro — é
    # exatamente onde um tomador vazaria sem o portão get_painel_user.
    for rota in ("/api/operacoes", "/api/capital/snapshot", "/api/auditoria/rotinas"):
        resp = como_a.get(rota)
        assert resp.status_code == 403, f"{rota} deixou um tomador entrar ({resp.status_code})"


def test_operador_e_barrado_no_portal(client: TestClient) -> None:
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Op", papel="operador", ativo=True
    )
    resp = _como(client, operador).get("/api/portal/operacoes")
    assert resp.status_code == 403


def test_me_serve_o_tomador_tambem(client: TestClient, db_session: Session) -> None:
    """`/api/me` é identidade — aberto a qualquer login, inclusive tomador. É o
    que a UI usa para saber para qual home mandar."""
    a = _tomador(db_session, "Empresa A", "11222333000181")
    resp = _como(client, _login_tomador(db_session, a)).get("/api/me")
    assert resp.status_code == 200
    assert resp.json()["papel"] == "tomador"


# ---------------------------------------------------------------------
# 4. O banco recusa o vínculo incoerente
# ---------------------------------------------------------------------


def test_tomador_sem_vinculo_e_recusado(db_session: Session) -> None:
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("""
            insert into usuario (id, email, nome, papel, tomador_id)
            values (:id, 'orfao@x.com', 'Orfao', 'tomador', null)
            """),
            {"id": str(uuid.uuid4())},
        )
    db_session.rollback()


def test_operador_com_vinculo_e_recusado(db_session: Session) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("""
            insert into usuario (id, email, nome, papel, tomador_id)
            values (:id, 'confuso@x.com', 'Confuso', 'operador', :t)
            """),
            {"id": str(uuid.uuid4()), "t": str(a)},
        )
    db_session.rollback()


def test_papel_desconhecido_e_recusado(db_session: Session) -> None:
    with pytest.raises(DBAPIError):
        db_session.execute(
            text("""
            insert into usuario (id, email, nome, papel)
            values (:id, 'estranho@x.com', 'Estranho', 'gerente')
            """),
            {"id": str(uuid.uuid4())},
        )
    db_session.rollback()


# ---------------------------------------------------------------------
# 5. A trilha de convites é append-only (OC027)
# ---------------------------------------------------------------------


def test_convite_nao_pode_ser_apagado(db_session: Session) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    cid = db_session.execute(
        text("""
        insert into convite_portal (tomador_id, email, convidado_por)
        values (:t, 'socio@empresa.com', 'admin-1')
        returning id
        """),
        {"t": str(a)},
    ).scalar_one()
    db_session.commit()

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(text("delete from convite_portal where id = :id"), {"id": str(cid)})
    db_session.rollback()
    assert sqlstate_de(exc.value) == "OC027"


def _admin_persistido(db_session: Session) -> Usuario:
    """Admin gravado de verdade na tabela: a listagem de convites resolve o
    nome de quem convidou por join em `usuario`, e um admin só em memória
    apareceria como nulo."""
    admin_id = uuid.uuid4()
    db_session.execute(
        text("""
        insert into usuario (id, email, nome, papel, ativo)
        values (:id, :email, 'Admin da ESC', 'admin', true)
        """),
        {"id": str(admin_id), "email": f"admin-{admin_id.hex[:6]}@orgatec.com"},
    )
    db_session.commit()
    return db_session.query(Usuario).filter(Usuario.id == admin_id).one()


def test_convidar_sem_supabase_configurado_responde_503_e_nao_grava_nada(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_service_key", "")

    a = _tomador(db_session, "Empresa A", "11222333000181")
    resp = _como(client, _admin_persistido(db_session)).post(
        f"/api/tomadores/{a}/portal/convites",
        json={"email": "socio@empresa.com", "nome": "Sócio"},
    )
    assert resp.status_code == 503

    # Fail-closed de verdade: nem login, nem trilha. Um convite meio-gravado
    # seria um login prometido que não autentica nunca.
    assert (
        db_session.execute(
            text("select count(*) from usuario where email = 'socio@empresa.com'")
        ).scalar_one()
        == 0
    )
    assert (
        db_session.execute(
            text("select count(*) from convite_portal where tomador_id = :t"), {"t": str(a)}
        ).scalar_one()
        == 0
    )


def test_convidar_cria_login_vinculado_e_trilha(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.routers.tomadores as tomadores_router

    auth_id = uuid.uuid4()
    monkeypatch.setattr(
        tomadores_router, "convidar_no_supabase", lambda email, redirect_to: auth_id
    )

    a = _tomador(db_session, "Empresa A", "11222333000181")
    admin = _admin_persistido(db_session)
    resp = _como(client, admin).post(
        f"/api/tomadores/{a}/portal/convites",
        # Caixa alta de propósito: o e-mail é normalizado antes de virar chave.
        json={"email": "Socio@Empresa.com", "nome": "Sócio da Empresa"},
    )
    assert resp.status_code == 201, resp.text
    corpo = resp.json()
    assert corpo["email"] == "socio@empresa.com"
    assert corpo["aceito_em"] is None
    assert corpo["convidado_por_nome"] == "Admin da ESC"

    # O login nasce com o ID DO AUTH (o `sub` dos JWTs futuros) e com o
    # vínculo que o CHECK da 031 exige.
    login = db_session.execute(
        text("select id, papel, tomador_id, ativo from usuario where email = 'socio@empresa.com'")
    ).one()
    assert login.id == auth_id
    assert login.papel == "tomador"
    assert login.tomador_id == a
    assert login.ativo is True

    trilha = db_session.execute(
        text("""
        select email, convidado_por, usuario_id, aceito_em
          from convite_portal where tomador_id = :t
        """),
        {"t": str(a)},
    ).one()
    assert trilha.email == "socio@empresa.com"
    assert trilha.convidado_por == str(admin.id)
    assert trilha.usuario_id == auth_id
    assert trilha.aceito_em is None

    # A listagem da ficha mostra a mesma trilha, com o nome de quem convidou.
    lista = _como(client, admin).get(f"/api/tomadores/{a}/portal/convites")
    assert lista.status_code == 200
    assert [c["email"] for c in lista.json()] == ["socio@empresa.com"]


def test_convidar_e_restrito_a_admin(client: TestClient, db_session: Session) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    operador = Usuario(
        id=uuid.uuid4(), email="op@orgatec.com", nome="Op", papel="operador", ativo=True
    )
    resp = _como(client, operador).post(
        f"/api/tomadores/{a}/portal/convites",
        json={"email": "socio@empresa.com", "nome": "Sócio"},
    )
    assert resp.status_code == 403


def test_email_que_ja_tem_login_e_recusado_antes_do_supabase(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pré-checagem local vem ANTES da conta no Auth: se o INSERT fosse
    falhar depois do convite remoto, sobraria a conta órfã que a ordem das
    escritas existe para evitar."""
    import app.routers.tomadores as tomadores_router

    def _nao_deveria_chamar(email: str, redirect_to: str) -> uuid.UUID:
        raise AssertionError("chamou o Supabase para um e-mail que já tem login")

    monkeypatch.setattr(tomadores_router, "convidar_no_supabase", _nao_deveria_chamar)

    a = _tomador(db_session, "Empresa A", "11222333000181")
    db_session.add(_login_tomador(db_session, a))
    ja_logado = db_session.query(Usuario).filter(Usuario.papel == "tomador").one()

    resp = _como(client, _admin_persistido(db_session)).post(
        f"/api/tomadores/{a}/portal/convites",
        json={"email": ja_logado.email, "nome": "Sócio"},
    )
    assert resp.status_code == 409


def test_email_ja_registrado_no_supabase_vira_409(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.routers.tomadores as tomadores_router
    from app.core.convites import EmailJaRegistrado

    def _ja_registrado(email: str, redirect_to: str) -> uuid.UUID:
        raise EmailJaRegistrado(email)

    monkeypatch.setattr(tomadores_router, "convidar_no_supabase", _ja_registrado)

    a = _tomador(db_session, "Empresa A", "11222333000181")
    resp = _como(client, _admin_persistido(db_session)).post(
        f"/api/tomadores/{a}/portal/convites",
        json={"email": "orfao@empresa.com", "nome": "Sócio"},
    )
    assert resp.status_code == 409
    # A instrução operacional (remover a conta no painel do Auth) precisa
    # chegar ao operador — é a única saída do estado órfão.
    assert "Supabase" in resp.json()["detail"]


def test_primeiro_sinal_autenticado_do_convidado_marca_o_aceite(
    client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.routers.tomadores as tomadores_router

    auth_id = uuid.uuid4()
    monkeypatch.setattr(
        tomadores_router, "convidar_no_supabase", lambda email, redirect_to: auth_id
    )

    a = _tomador(db_session, "Empresa A", "11222333000181")
    admin = _admin_persistido(db_session)
    assert (
        _como(client, admin)
        .post(
            f"/api/tomadores/{a}/portal/convites",
            json={"email": "socio@empresa.com", "nome": "Sócio"},
        )
        .status_code
        == 201
    )

    convidado = db_session.query(Usuario).filter(Usuario.id == auth_id).one()
    assert _como(client, convidado).get("/api/me").status_code == 200

    aceito_em = db_session.execute(
        text("select aceito_em from convite_portal where usuario_id = :u"), {"u": str(auth_id)}
    ).scalar_one()
    assert aceito_em is not None

    # Idempotente: o segundo /me não reescreve o aceite (nem poderia — o
    # trigger OC027 recusaria; o WHERE em `aceito_em is null` evita até tentar).
    assert _como(client, convidado).get("/api/me").status_code == 200
    assert (
        db_session.execute(
            text("select aceito_em from convite_portal where usuario_id = :u"),
            {"u": str(auth_id)},
        ).scalar_one()
        == aceito_em
    )


def test_convite_so_deixa_preencher_o_aceite(db_session: Session) -> None:
    a = _tomador(db_session, "Empresa A", "11222333000181")
    login = db_session.execute(
        text("""
        insert into usuario (id, email, nome, papel, tomador_id)
        values (:id, 'socio@empresa.com', 'Socio', 'tomador', :t)
        returning id
        """),
        {"id": str(uuid.uuid4()), "t": str(a)},
    ).scalar_one()
    cid = db_session.execute(
        text("""
        insert into convite_portal (tomador_id, email, convidado_por)
        values (:t, 'socio@empresa.com', 'admin-1')
        returning id
        """),
        {"t": str(a)},
    ).scalar_one()
    db_session.commit()

    # Preencher o vínculo e o aceite, uma vez: passa.
    db_session.execute(
        text("""
        update convite_portal set usuario_id = :u, aceito_em = clock_timestamp()
         where id = :id
        """),
        {"u": str(login), "id": str(cid)},
    )
    db_session.commit()

    # Reescrever o e-mail do convite: recusado.
    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text("update convite_portal set email = 'outro@x.com' where id = :id"),
            {"id": str(cid)},
        )
    db_session.rollback()
    assert sqlstate_de(exc.value) == "OC027"
