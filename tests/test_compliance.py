"""
Compliance PLD/FT interno (migrations 010, 014 e 019) contra Postgres real.

Três coisas que não dependem de terceiro e por isso são testáveis hoje:
evidência de identificação com ARQUIVO guardado e hash verificável, retenção
de 5 anos garantida pelo banco, e detecção de atipicidade sobre os dados
existentes.

O STORAGE É FALSIFICADO AQUI, e essa é uma decisão de projeto, não um
atalho. O que precisa ser provado — que o hash sai dos bytes recebidos e não
do que o cliente afirma, que sem chave o arquivamento é recusado, que arquivo
adulterado não confere — não é sobre o Supabase. Amarrar essas provas a uma
credencial e a uma conexão de rede as tornaria as primeiras a serem
desligadas no dia em que a rede oscilasse na CI, que é o dia em que elas mais
importam. Por isso `app/core/storage.py` é uma interface de dois métodos:
para caber num dicionário aqui dentro.
"""

import hashlib
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, Generator
from urllib.parse import quote

import httpx
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
from app.core import storage as storage_mod
from app.core.config import settings
from app.core.exceptions import IdentificacaoAusente
from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.core.storage import (
    TAMANHO_MAXIMO_BYTES,
    FalhaNoStorage,
    ObjetoNaoEncontrado,
    StorageNaoConfigurado,
    SupabaseStorage,
    get_storage,
    referencia_para,
)
from app.db import get_db
from app.main import app
from app.models import Usuario
from app.routers.compliance import storage_de_documentos
from tests.conftest import (
    arquivar_identificacao,
    confirmar_registro,
    quitar_operacao,
    sqlstate_de,
)


class StorageFalsificado:
    """Storage em memória com a mesma interface de `app.core.storage.Storage`.

    `adulterar` não existe no protocolo de propósito — é o gancho de TESTE
    para simular o único ataque que o trigger OC013 não alcança: trocar os
    bytes do lado do bucket, onde o Postgres não tem jurisdição. Um storage
    de produção não oferece esse método; este oferece justamente para provar
    que o sistema percebe quando alguém o faz por fora.
    """

    def __init__(self) -> None:
        self.objetos: Dict[str, bytes] = {}

    def guardar(self, referencia: str, conteudo: bytes, content_type: str) -> None:
        self.objetos[referencia] = conteudo

    def recuperar(self, referencia: str) -> bytes:
        try:
            return self.objetos[referencia]
        except KeyError as exc:
            raise ObjetoNaoEncontrado(f"Objeto {referencia!r} não está no storage.") from exc

    def adulterar(self, referencia: str, conteudo: bytes) -> None:
        self.objetos[referencia] = conteudo


@pytest.fixture()
def storage_falso() -> StorageFalsificado:
    return StorageFalsificado()


class TestSupabaseStorage:
    """A implementação real, com o `httpx` substituído — não a rede.

    Estes testes não abrem conexão nenhuma e não tocam no banco: o que eles
    provam é a tradução entre o que o Supabase Storage responde e o que o
    resto do sistema entende. É a camada onde um 404 vira "a evidência sumiu
    do bucket" (incidente de retenção legal) em vez de virar um 500 genérico.
    """

    def _storage(self) -> SupabaseStorage:
        return SupabaseStorage("https://projeto.supabase.co/", "service-role-fake")

    def test_guardar_monta_a_url_e_manda_as_duas_credenciais(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`apikey` E `Authorization`: o gateway do Supabase exige o primeiro
        para rotear e o storage exige o segundo para autorizar. Mandar só um
        responde 401 sem dizer qual faltou — daí a checagem explícita."""
        capturado: Dict[str, Any] = {}

        def _post(url: str, **kwargs: Any) -> httpx.Response:
            capturado["url"] = url
            capturado.update(kwargs)
            return httpx.Response(200, request=httpx.Request("POST", url))

        monkeypatch.setattr(storage_mod.httpx, "post", _post)
        self._storage().guardar("bucket/tomador/abc", b"conteudo", "application/pdf")

        assert capturado["url"] == (
            "https://projeto.supabase.co/storage/v1/object/bucket/tomador/abc"
        )
        assert capturado["content"] == b"conteudo"
        cabecalhos = capturado["headers"]
        assert cabecalhos["apikey"] == "service-role-fake"
        assert cabecalhos["Authorization"] == "Bearer service-role-fake"
        assert cabecalhos["Content-Type"] == "application/pdf"
        # Ver a justificativa do upsert em app/core/storage.py: o caminho é
        # derivado do hash do conteúdo, então regravar é regravar o mesmo.
        assert cabecalhos["x-upsert"] == "true"
        assert capturado["timeout"] == storage_mod.TIMEOUT_SEGUNDOS

    def test_guardar_recusa_vazio_e_gigante(self) -> None:
        """O teto mora no storage, e não só no router: quem chamar `guardar`
        por outro caminho encontra a mesma recusa."""
        storage = self._storage()
        with pytest.raises(FalhaNoStorage):
            storage.guardar("bucket/x", b"", "application/pdf")
        with pytest.raises(FalhaNoStorage):
            storage.guardar("bucket/x", b"a" * (TAMANHO_MAXIMO_BYTES + 1), "application/pdf")

    @pytest.mark.parametrize("referencia", ["sem-barra", "/sem-bucket", "bucket/", "bucket/../x"])
    def test_referencia_invalida_nao_vira_url(self, referencia: str) -> None:
        """A referência entra num caminho de URL: sem bucket ela apontaria
        para outro recurso da API do storage, e com '..' para fora dele."""
        with pytest.raises(FalhaNoStorage):
            self._storage().guardar(referencia, b"x", "application/pdf")

    def test_erro_do_storage_ao_gravar_vira_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            storage_mod.httpx,
            "post",
            lambda url, **kw: httpx.Response(403, request=httpx.Request("POST", url)),
        )
        with pytest.raises(FalhaNoStorage):
            self._storage().guardar("bucket/x", b"x", "application/pdf")

    def test_rede_fora_vira_falha_e_nao_estoura_httpx(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """O router só sabe traduzir `StorageError`. Um `httpx.ConnectError`
        vazando daqui viraria 500 — "erro interno" para uma indisponibilidade
        de infraestrutura, que manda o suporte procurar bug no lugar errado."""

        def _explode(url: str, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectError("sem rota para o host")

        monkeypatch.setattr(storage_mod.httpx, "post", _explode)
        monkeypatch.setattr(storage_mod.httpx, "get", _explode)
        with pytest.raises(FalhaNoStorage):
            self._storage().guardar("bucket/x", b"x", "application/pdf")
        with pytest.raises(FalhaNoStorage):
            self._storage().recuperar("bucket/x")

    def test_recuperar_devolve_o_corpo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            storage_mod.httpx,
            "get",
            lambda url, **kw: httpx.Response(
                200, content=b"os bytes", request=httpx.Request("GET", url)
            ),
        )
        assert self._storage().recuperar("bucket/x") == b"os bytes"

    def test_404_do_bucket_vira_objeto_nao_encontrado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A distinção que importa: o banco afirma que a evidência existe e o
        bucket não a tem. Isso é incidente de retenção legal, não um 404
        qualquer, e precisa de um tipo próprio para o router poder dizê-lo."""
        monkeypatch.setattr(
            storage_mod.httpx,
            "get",
            lambda url, **kw: httpx.Response(404, request=httpx.Request("GET", url)),
        )
        with pytest.raises(ObjetoNaoEncontrado):
            self._storage().recuperar("bucket/x")

    def test_erro_do_storage_ao_ler_vira_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            storage_mod.httpx,
            "get",
            lambda url, **kw: httpx.Response(500, request=httpx.Request("GET", url)),
        )
        with pytest.raises(FalhaNoStorage):
            self._storage().recuperar("bucket/x")

    def test_get_storage_recusa_sem_chave_e_aceita_com(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FAIL-CLOSED na origem: sem chave, `get_storage` não devolve um
        storage inerte que engole bytes — ele recusa."""
        monkeypatch.setattr(settings, "supabase_url", "https://projeto.supabase.co")
        monkeypatch.setattr(settings, "supabase_service_key", "")
        with pytest.raises(StorageNaoConfigurado):
            get_storage()

        # Meia configuração é configuração nenhuma: a URL sozinha também não.
        monkeypatch.setattr(settings, "supabase_url", "")
        monkeypatch.setattr(settings, "supabase_service_key", "chave")
        with pytest.raises(StorageNaoConfigurado):
            get_storage()

        monkeypatch.setattr(settings, "supabase_url", "https://projeto.supabase.co")
        assert isinstance(get_storage(), SupabaseStorage)

    def test_referencia_e_derivada_do_conteudo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nenhum caractere da referência vem do cliente — é o que torna a
        travessia de diretório impossível por construção, e não por filtro."""
        monkeypatch.setattr(settings, "supabase_storage_bucket", "meu-bucket")
        tomador = str(uuid.uuid4())
        sha = hashlib.sha256(b"documento").hexdigest()
        assert referencia_para(tomador, sha) == f"meu-bucket/{tomador}/{sha}"


@pytest.fixture()
def client(
    db_session: Session, storage_falso: StorageFalsificado
) -> Generator[TestClient, None, None]:
    def _override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[storage_de_documentos] = lambda: storage_falso
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


def _arquivar(
    client: TestClient,
    tomador_id: uuid.UUID,
    conteudo: bytes,
    tipo: str = "contrato_social",
    nome: str = "contrato.pdf",
) -> "object":
    """Arquiva um documento pelo caminho real: multipart, com os BYTES.

    Não existe mais um jeito de arquivar sem mandar arquivo — era esse o
    ponto da migration 019 — então o helper reflete isso e nenhum teste
    consegue, nem por engano, exercitar o caminho antigo.
    """
    return client.post(
        f"/api/compliance/tomadores/{tomador_id}/documentos",
        data={"tipo": tipo},
        files={"arquivo": (nome, conteudo, "application/pdf")},
    )


def _verificar(client: TestClient, documento_id: str, conteudo: bytes) -> "object":
    return client.post(
        f"/api/compliance/documentos/{documento_id}/verificar",
        files={"arquivo": ("apresentado.pdf", conteudo, "application/pdf")},
    )


# ---------------------------------------------------------------------
# Identificação com evidência arquivada
# ---------------------------------------------------------------------


class TestIdentificacao:
    def test_arquivar_e_listar(
        self,
        admin_client: TestClient,
        tomador_sem_identificacao: uuid.UUID,
        storage_falso: StorageFalsificado,
    ) -> None:
        conteudo = b"contrato social em pdf"
        resposta = _arquivar(admin_client, tomador_sem_identificacao, conteudo)
        assert resposta.status_code == 201

        corpo = resposta.json()
        # O hash é dos BYTES que chegaram, calculado pelo servidor.
        assert corpo["sha256"] == _sha(conteudo)
        # Retenção de 5 anos gravada no ato (Lei 9.613/98, art. 10, III).
        assert date.fromisoformat(corpo["retencao_ate"]) >= date.today() + timedelta(days=5 * 365)
        # E os bytes existem de verdade, no endereço que a linha registra.
        assert storage_falso.objetos[corpo["storage_objeto"]] == conteudo

        lista = admin_client.get(
            f"/api/compliance/tomadores/{tomador_sem_identificacao}/documentos"
        ).json()
        assert [d["nome_arquivo"] for d in lista] == ["contrato.pdf"]

    def test_hash_do_cliente_e_ignorado(
        self,
        admin_client: TestClient,
        tomador_sem_identificacao: uuid.UUID,
        storage_falso: StorageFalsificado,
    ) -> None:
        """O defeito que a migration 019 fechou, com nome e sobrenome.

        Até ela, `sha256` era um CAMPO DE ENTRADA validado só por
        `^[0-9a-f]{64}$`: 64 caracteres digitados satisfaziam a identificação
        exigida pela Lei 9.613/98 (art. 10, I) e nenhum byte era lido pelo
        servidor. Aqui o cliente manda o campo antigo, com um valor
        escolhido a dedo, junto de um arquivo diferente — e o que fica
        gravado é o hash do ARQUIVO. O campo do cliente não tem mais efeito
        nenhum sobre nada.
        """
        conteudo = b"o documento de verdade"
        mentira = "0" * 64

        resposta = admin_client.post(
            f"/api/compliance/tomadores/{tomador_sem_identificacao}/documentos",
            data={"tipo": "contrato_social", "sha256": mentira},
            files={"arquivo": ("contrato.pdf", conteudo, "application/pdf")},
        )
        assert resposta.status_code == 201

        corpo = resposta.json()
        assert corpo["sha256"] == _sha(conteudo)
        assert corpo["sha256"] != mentira
        assert storage_falso.objetos[corpo["storage_objeto"]] == conteudo

    def test_sem_chave_configurada_o_arquivamento_e_recusado(
        self,
        admin_client: TestClient,
        tomador_sem_identificacao: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FAIL-CLOSED: sem storage, recusa — nunca aceita o hash e descarta
        o arquivo.

        O modo degradado tentador seria "grava a linha e segue a vida sem os
        bytes", e é exatamente o defeito histórico com outro nome: o sistema
        afirmando que a identificação está arquivada quando não está. Aqui o
        pedido falha e NADA é gravado, que é a única resposta que não mente.
        """
        app.dependency_overrides.pop(storage_de_documentos, None)
        monkeypatch.setattr(settings, "supabase_url", "")
        monkeypatch.setattr(settings, "supabase_service_key", "")

        resposta = _arquivar(admin_client, tomador_sem_identificacao, b"contrato social em pdf")
        assert resposta.status_code == 503
        assert "service_role" in resposta.json()["detail"]

        assert (
            admin_client.get(
                f"/api/compliance/tomadores/{tomador_sem_identificacao}/documentos"
            ).json()
            == []
        )

    def test_arquivo_vazio_e_recusado(
        self, admin_client: TestClient, tomador_sem_identificacao: uuid.UUID
    ) -> None:
        """Zero byte não é evidência de nada — e passaria pelo hash sem
        reclamar, porque o SHA-256 do vazio é um hash perfeitamente válido."""
        resposta = _arquivar(admin_client, tomador_sem_identificacao, b"")
        assert resposta.status_code == 422
        assert "vazio" in resposta.json()["detail"]

    def test_mesmo_arquivo_duas_vezes_e_recusado(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        conteudo = b"cartao cnpj"
        assert (
            _arquivar(
                admin_client, tomador_autorizado, conteudo, tipo="cartao_cnpj", nome="cnpj.pdf"
            ).status_code
            == 201
        )

        repetido = _arquivar(
            admin_client, tomador_autorizado, conteudo, tipo="cartao_cnpj", nome="cnpj.pdf"
        )
        assert repetido.status_code == 422
        assert "já está arquivado" in repetido.json()["detail"]

    def test_tomador_inexistente_404(self, admin_client: TestClient) -> None:
        resposta = _arquivar(admin_client, uuid.uuid4(), b"x", tipo="outro", nome="x.pdf")
        assert resposta.status_code == 404

    def test_recuperar_devolve_os_bytes_arquivados(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        """Guardar sem conseguir apresentar teria o mesmo valor prático de
        não guardar: numa fiscalização o que se entrega é o arquivo."""
        conteudo = b"%PDF-1.4 contrato social digitalizado"
        doc = _arquivar(
            admin_client, tomador_autorizado, conteudo, nome="contrato social.pdf"
        ).json()

        resposta = admin_client.get(f"/api/compliance/documentos/{doc['id']}/conteudo")
        assert resposta.status_code == 200
        assert resposta.content == conteudo
        assert "contrato social.pdf" in resposta.headers["content-disposition"]

    def test_nome_fora_do_latin_1_nao_derruba_o_download(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        """O nome do arquivo é dado do cliente e vai para dentro de um
        cabeçalho HTTP, que é latin-1.

        O DEFEITO: um nome com caractere fora dessa tabela (cirílico, CJK,
        emoji — nada exótico num documento fotografado por celular) fazia o
        Starlette levantar `UnicodeEncodeError` ao montar a resposta, e o
        download virava 500. O arquivamento tinha aceitado o mesmo nome sem
        reclamar, com os bytes já no bucket.

        E não havia conserto: a linha é imutável por OC013 e rearquivar o
        MESMO arquivo bate na unique `(tomador_id, sha256)` da 010. A
        evidência ficava permanentemente impossível de apresentar — guardar
        os bytes e não conseguir entregá-los numa fiscalização vale o mesmo
        que não os ter guardado, que é o defeito que a 019 existe para
        fechar.
        """
        conteudo = b"%PDF-1.4 contrato digitalizado"
        doc = _arquivar(admin_client, tomador_autorizado, conteudo, nome="контракт-契約.pdf").json()
        assert doc["nome_arquivo"] == "контракт-契約.pdf"

        resposta = admin_client.get(f"/api/compliance/documentos/{doc['id']}/conteudo")
        assert resposta.status_code == 200
        assert resposta.content == conteudo

        # O nome verdadeiro viaja no campo estendido da RFC 6266, que é o que
        # o navegador usa quando os dois estão presentes.
        disposicao = resposta.headers["content-disposition"]
        assert f"filename*=UTF-8''{quote('контракт-契約.pdf')}" in disposicao
        # E o fallback existe, em ASCII, para quem não entender o estendido.
        assert 'filename="' in disposicao
        disposicao.encode("latin-1")

    def test_aspas_no_nome_nao_escapam_do_cabecalho(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        storage_falso: StorageFalsificado,
    ) -> None:
        """Uma aspa no nome fecharia a quoted-string antes da hora, e o
        cabeçalho passaria a dizer outra coisa.

        `_nome_saneado` barra `/`, `\\` e os caracteres de controle — é o que
        impede quebra de resposta por CR/LF —, mas `"` passava direto para
        dentro de `filename="..."`.

        A LINHA É INSERIDA DIRETO, e isso é o teste, não um atalho: o `httpx`
        do TestClient escapa a aspa para `%22` ao montar o multipart, então
        subir o arquivo por ele provaria a higiene do CLIENTE, não a do
        servidor — e passaria com o cabeçalho antigo, quebrado (verificado por
        mutação). O servidor não pode depender de o cliente escapar; e nomes
        assim já podem existir no banco, gravados por qualquer coisa que não
        seja este TestClient.
        """
        referencia = f"identificacao-tomador/{tomador_autorizado}/{'b' * 64}"
        storage_falso.objetos[referencia] = b"aspas"
        doc_id = db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate, storage_objeto)
            values (:t, 'contrato_social', :nome, :sha, current_date + 1825, :obj)
            returning id
            """),
            {
                "t": str(tomador_autorizado),
                "nome": 'rg";cabecalho-falso.pdf',
                "sha": _sha(b"aspas"),
                "obj": referencia,
            },
        ).scalar_one()
        db_session.commit()

        resposta = admin_client.get(f"/api/compliance/documentos/{doc_id}/conteudo")
        assert resposta.status_code == 200
        assert resposta.content == b"aspas"

        disposicao = resposta.headers["content-disposition"]
        # O fallback vem entre UMA abertura e UM fechamento de aspas: o que
        # está dentro delas não pode conter outra aspa, senão o cabeçalho
        # termina onde o nome do arquivo mandar.
        fallback = disposicao.split('filename="', 1)[1].split('"', 1)[0]
        assert '"' not in fallback
        assert fallback.endswith("cabecalho-falso.pdf")

    def test_recuperar_evidencia_sem_bytes_e_409(
        self, admin_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Evidência da era sem storage (anterior à 019): a linha existe, o
        arquivo nunca existiu. 409 e não 404 — o id está certo, o que falta é
        o arquivo, e a resposta precisa dizer isso para o operador não sair
        procurando um documento que não foi digitado errado."""
        doc_id = db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate, storage_objeto)
            values (:t, 'contrato_social', 'legado.pdf', :sha, current_date + 1825, null)
            returning id
            """),
            {"t": str(tomador_autorizado), "sha": _sha(b"legado")},
        ).scalar_one()
        db_session.commit()

        resposta = admin_client.get(f"/api/compliance/documentos/{doc_id}/conteudo")
        assert resposta.status_code == 409
        assert "019" in resposta.json()["detail"]

    def test_recuperar_objeto_sumido_do_bucket_e_410(
        self,
        admin_client: TestClient,
        tomador_autorizado: uuid.UUID,
        storage_falso: StorageFalsificado,
    ) -> None:
        """O banco afirma que a evidência existe e o bucket não a tem.

        É incidente de retenção legal, não pedido malformado: alguém apagou o
        objeto por fora do sistema, onde o OC013 não alcança. 410 Gone diz
        exatamente isso — existiu, não existe mais."""
        doc = _arquivar(admin_client, tomador_autorizado, b"vai sumir").json()
        storage_falso.objetos.clear()

        resposta = admin_client.get(f"/api/compliance/documentos/{doc['id']}/conteudo")
        assert resposta.status_code == 410

    def test_verificacao_confere_bit_a_bit(
        self, admin_client: TestClient, tomador_autorizado: uuid.UUID
    ) -> None:
        """É o que dá sentido a guardar o hash: sem esta conferência, o hash
        seria um número sem uso."""
        conteudo = b"documento original do socio"
        doc_id = _arquivar(
            admin_client, tomador_autorizado, conteudo, tipo="documento_socio", nome="rg.pdf"
        ).json()["id"]

        igual = _verificar(admin_client, doc_id, conteudo).json()
        assert igual["confere"] is True
        assert igual["sha256_calculado"] == igual["sha256_arquivado"] == _sha(conteudo)
        assert igual["storage_integro"] is True

        # Um único byte a mais — o caso realista é o documento reimpresso ou
        # reescaneado, que "é o mesmo" para quem olha e não é para o hash.
        adulterado = _verificar(admin_client, doc_id, conteudo + b" ").json()
        assert adulterado["confere"] is False
        assert adulterado["sha256_calculado"] != adulterado["sha256_arquivado"]
        # O ARQUIVO GUARDADO continua íntegro: quem não confere é o
        # apresentado. As duas perguntas são independentes de propósito.
        assert adulterado["storage_integro"] is True

    def test_verificacao_acusa_adulteracao_no_proprio_storage(
        self,
        admin_client: TestClient,
        tomador_autorizado: uuid.UUID,
        storage_falso: StorageFalsificado,
    ) -> None:
        """O único ataque fora do alcance do OC013.

        O trigger da 010 congela a linha do banco — ninguém troca o hash, o
        nome nem a referência. Mas o objeto vive no bucket, onde o Postgres
        não manda: trocar os bytes lá dentro substituiria o documento
        arquivado sem tocar em nada que o banco protege. `storage_integro`
        existe para que essa troca não passe despercebida.
        """
        conteudo = b"contrato social verdadeiro"
        doc = _arquivar(admin_client, tomador_autorizado, conteudo).json()

        storage_falso.adulterar(doc["storage_objeto"], b"contrato social trocado")

        resultado = _verificar(admin_client, doc["id"], conteudo).json()
        # O documento apresentado continua sendo o verdadeiro...
        assert resultado["confere"] is True
        # ...e o sistema acusa que o que está guardado já não é.
        assert resultado["storage_integro"] is False

    def test_verificacao_de_evidencia_sem_bytes_nao_afirma_integridade(
        self, admin_client: TestClient, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """`storage_integro` é None, não False: não há objeto para conferir.

        False diria "o arquivo guardado está errado" sobre um arquivo que
        nunca foi guardado — afirmação diferente, e falsa. A distinção entre
        "não confere" e "não há o que conferir" é a que separa um incidente
        de uma pendência de migração."""
        doc_id = db_session.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate, storage_objeto)
            values (:t, 'contrato_social', 'legado.pdf', :sha, current_date + 1825, null)
            returning id
            """),
            {"t": str(tomador_autorizado), "sha": _sha(b"legado")},
        ).scalar_one()
        db_session.commit()

        resultado = _verificar(admin_client, str(doc_id), b"legado").json()
        assert resultado["confere"] is True
        assert resultado["storage_integro"] is None

    def test_verificacao_de_documento_inexistente_404(self, admin_client: TestClient) -> None:
        resposta = _verificar(admin_client, str(uuid.uuid4()), b"x")
        assert resposta.status_code == 404

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
        _arquivar(admin_client, tomador_autorizado, b"c", nome="c.pdf")
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


class TestReferenciaDoObjeto:
    """Migration 019: a coluna que liga a linha do banco ao arquivo.

    A evidência de identificação passou a ter bytes; estes testes provam que
    o ENDEREÇO deles é tão protegido quanto o hash — porque repontar a linha
    para outro objeto trocaria o documento arquivado sem trocar nada que o
    banco antes vigiava.
    """

    def _arquivar_direto(
        self, db_session: Session, tomador_id: uuid.UUID, nome: str, referencia: object
    ) -> uuid.UUID:
        return db_session.execute(  # type: ignore[no-any-return]
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate, storage_objeto)
            values (:t, 'contrato_social', :nome, :sha, current_date + 1825, :obj)
            returning id
            """),
            {
                "t": str(tomador_id),
                "nome": nome,
                "sha": _sha(nome.encode()),
                "obj": referencia,
            },
        ).scalar_one()

    def test_referencia_nao_pode_ser_repontada(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """O bloqueio: OC013 já congela a linha inteira, e a coluna nova
        nasceu dentro desse congelamento.

        Sem isto, "corrigir o caminho do objeto" seria a porta dos fundos
        para trocar o documento: o hash continuaria o mesmo, a data de
        arquivamento também, e só mudaria QUAL arquivo é apresentado numa
        fiscalização.
        """
        doc_id = self._arquivar_direto(
            db_session,
            tomador_autorizado,
            "original.pdf",
            f"identificacao-tomador/{tomador_autorizado}/{_sha(b'original.pdf')}",
        )
        db_session.commit()

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("update tomador_documento set storage_objeto = :obj where id = :d"),
                {"obj": "outro-bucket/qualquer/coisa", "d": str(doc_id)},
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_duas_evidencias_nao_apontam_para_o_mesmo_objeto(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Armadilha de expurgo: vencida a retenção de uma das linhas, apagar
        o objeto destruiria a evidência da outra, ainda em retenção legal."""
        referencia = f"identificacao-tomador/{tomador_autorizado}/{'a' * 64}"
        self._arquivar_direto(db_session, tomador_autorizado, "um.pdf", referencia)
        db_session.commit()

        with pytest.raises(Exception):
            self._arquivar_direto(db_session, tomador_autorizado, "dois.pdf", referencia)
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize(
        "referencia",
        [
            "sem-barra-nenhuma",
            "/comeca-com-barra",
            "bucket/termina-com-barra/",
            "bucket/../fuga",
            " bucket/com-espaco-na-ponta",
            "",
        ],
    )
    def test_referencia_malformada_e_recusada(
        self, db_session: Session, tomador_autorizado: uuid.UUID, referencia: str
    ) -> None:
        """A validação é da COLUNA, e não confiança em quem escreve nela.

        O valor gravado é imutável (OC013): uma referência ruim que entre
        aqui não tem como ser corrigida depois, só substituída por uma linha
        nova. E ela é interpolada num caminho de URL na hora de recuperar o
        objeto — '..' e barra inicial não são feiura, são travessia.
        """
        with pytest.raises(Exception):
            self._arquivar_direto(db_session, tomador_autorizado, "ruim.pdf", referencia)
            db_session.flush()
        db_session.rollback()

    def test_evidencia_da_era_sem_storage_continua_valida(
        self, db_session: Session, tomador_autorizado: uuid.UUID
    ) -> None:
        """Caminho feliz do NULL, que não é descuido: as linhas arquivadas
        antes da 019 têm hash e não têm arquivo, porque os bytes nunca
        existiram em lugar nenhum.

        Um `not null` teria exigido backfill, e o único backfill possível
        seria inventar uma referência que não aponta para nada — trocar uma
        lacuna visível por uma mentira invisível. E mais de uma delas
        coexiste sem colidir no índice único, que é parcial exatamente por
        isso.
        """
        self._arquivar_direto(db_session, tomador_autorizado, "legado1.pdf", None)
        self._arquivar_direto(db_session, tomador_autorizado, "legado2.pdf", None)
        db_session.commit()

        sem_bytes = db_session.execute(
            text("""
            select count(*) from tomador_documento
            where tomador_id = :t and storage_objeto is null
            """),
            {"t": str(tomador_autorizado)},
        ).scalar_one()
        assert sem_bytes == 2


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

        # Expurgado o documento, uma NOVA operação já não ativa. Encerrar a
        # primeira exige quitá-la desde a migration 017 — liquidar devolve
        # capital ao teto e por isso passou a exigir a prova do pagamento.
        quitar_operacao(db_session, op_id)
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
