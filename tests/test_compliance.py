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
    envelhecer_encerramento,
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


def _documento_arquivado(
    db_session: Session,
    tomador_id: uuid.UUID,
    nome: str,
    dias_piso: int,
    dias_atras: int = 0,
) -> uuid.UUID:
    """Evidência com o PISO e a data de arquivamento sob controle do teste.

    `dias_piso` é relativo a hoje (negativo = piso já vencido) e `dias_atras`
    recua `arquivado_em`. Os dois são escritos direto no INSERT porque é a
    única janela em que isso é possível: depois de gravada, a linha é
    congelada por OC013 em coluna nenhuma.
    """
    return db_session.execute(
        text("""
        insert into tomador_documento
            (tomador_id, tipo, nome_arquivo, sha256, retencao_ate, arquivado_em)
        values (:t, 'contrato_social', :nome, :sha,
                current_date + make_interval(days => :piso),
                clock_timestamp() - make_interval(days => :atras))
        returning id
        """),
        {
            "t": str(tomador_id),
            "nome": nome,
            "sha": _sha(nome.encode()),
            "piso": dias_piso,
            "atras": dias_atras,
        },
    ).scalar_one()


class TestRetencaoAncoradaNoEncerramento:
    """Migration 022: os 5 anos contam do ENCERRAMENTO DA RELAÇÃO.

    O defeito corrigido: `retencao_ate` era materializado como `current_date +
    5 anos` no ato do arquivamento, e a Lei 9.613/98, art. 10, III conta do
    encerramento da relação de negócio. Numa operação de 60 parcelas o prazo
    gravado vencia junto com o contrato — cerca de cinco anos cedo demais, e o
    banco autorizava o DELETE com toda a autoridade de um invariante.

    A coluna continua existindo e continua imutável: virou o PISO. Sobre ela
    entra a derivação, e é ela que o trigger consulta.
    """

    def _operacao_encerrada(
        self, db_session: Session, tomador_id: uuid.UUID, anos_atras: int = 0
    ) -> uuid.UUID:
        """Operação levada até 'liquidada' pelo caminho real, e envelhecida.

        Quitar antes de liquidar não é cerimônia: desde a 017 `ativa ->
        liquidada` exige a agenda inteira baixada contra movimento bancário
        (OC022). O envelhecimento é a única parte artificial, e existe porque
        nenhuma data de encerramento pode nascer no passado — ver
        `envelhecer_encerramento` em tests/conftest.py.
        """
        op_id = _operacao(db_session, tomador_id, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
        quitar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "liquidada")
        if anos_atras:
            envelhecer_encerramento(db_session, op_id, anos_atras)
        return op_id

    def _retencao(self, db_session: Session, documento_id: uuid.UUID) -> Any:
        return db_session.execute(
            text("""
            select retencao_piso, retencao_efetiva, relacao_em_curso,
                   encerramento_relacao, motivo
            from v_documento_retencao where documento_id = :d
            """),
            {"d": str(documento_id)},
        ).one()

    def _apagar(self, db_session: Session, nome: str) -> None:
        db_session.execute(
            text("delete from tomador_documento where nome_arquivo = :n"), {"n": nome}
        )
        db_session.flush()

    # -----------------------------------------------------------------
    # O bloqueio
    # -----------------------------------------------------------------

    def test_prazo_nao_corre_enquanto_a_relacao_esta_viva(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O DEFEITO, no formato mais direto: piso vencido, crédito na rua.

        Antes da 022 este DELETE passava — o banco comparava a data gravada
        com hoje, via que tinha vencido e autorizava apagar a identificação de
        um tomador que ESTÁ DEVENDO. É o pior momento possível para perder a
        evidência de quem ele é.
        """
        doc_id = _documento_arquivado(db_session, tomador_autorizado, "vencido.pdf", dias_piso=-1)
        op_id = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)

        retencao = self._retencao(db_session, doc_id)
        assert retencao.relacao_em_curso is True
        # Indeterminada, não uma data qualquer: os cinco anos não começaram.
        assert retencao.retencao_efetiva is None
        assert "não começou a correr" in retencao.motivo

        with pytest.raises(Exception) as exc:
            self._apagar(db_session, "vencido.pdf")
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_prazo_conta_do_encerramento_e_nao_do_arquivamento(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Relação encerrada HOJE: o relógio começa agora, não terminou ontem."""
        doc_id = _documento_arquivado(db_session, tomador_autorizado, "vencido.pdf", dias_piso=-1)
        self._operacao_encerrada(db_session, tomador_autorizado)

        retencao = self._retencao(db_session, doc_id)
        hoje: date = db_session.execute(text("select current_date")).scalar_one()
        assert retencao.relacao_em_curso is False
        assert retencao.encerramento_relacao == hoje
        assert retencao.retencao_efetiva == date(hoje.year + 5, hoje.month, hoje.day)
        assert retencao.motivo == "ancorado no encerramento da relação + 5 anos"

        with pytest.raises(Exception) as exc:
            self._apagar(db_session, "vencido.pdf")
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_a_ancora_e_a_ultima_operacao_a_encerrar(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """ "Encerramento da relação" não é o encerramento de UMA operação.

        Uma operação encerrada há seis anos já liberaria o expurgo sozinha. A
        segunda, encerrada há um ano, é que manda — a relação com o tomador
        acabou na última, não na primeira.
        """
        doc_id = _documento_arquivado(db_session, tomador_autorizado, "vencido.pdf", dias_piso=-1)
        self._operacao_encerrada(db_session, tomador_autorizado, anos_atras=6)
        self._operacao_encerrada(db_session, tomador_autorizado, anos_atras=1)

        hoje: date = db_session.execute(text("select current_date")).scalar_one()
        retencao = self._retencao(db_session, doc_id)
        assert retencao.encerramento_relacao == date(hoje.year - 1, hoje.month, hoje.day)
        assert retencao.retencao_efetiva == date(hoje.year + 4, hoje.month, hoje.day)

        with pytest.raises(Exception) as exc:
            self._apagar(db_session, "vencido.pdf")
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_relogio_reinicia_quando_o_tomador_volta_a_tomar_credito(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Crédito novo é relação nova, e a proteção VOLTA.

        Um documento cujo prazo já tinha vencido e que ainda não foi expurgado
        volta a ficar protegido quando o tomador reabre a relação. Isso é
        deliberado: a relação de negócio é uma só, e ela recomeçou. É também
        uma consequência que só a derivação entrega — com a data reescrita na
        coluna, "voltar atrás" exigiria justamente o UPDATE que OC013 recusa.
        """
        doc_id = _documento_arquivado(db_session, tomador_autorizado, "vencido.pdf", dias_piso=-1)
        self._operacao_encerrada(db_session, tomador_autorizado, anos_atras=6)

        hoje: date = db_session.execute(text("select current_date")).scalar_one()
        assert self._retencao(db_session, doc_id).retencao_efetiva == hoje - timedelta(days=1)

        nova = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, nova)
        ativar_operacao(db_session, nova)

        assert self._retencao(db_session, doc_id).retencao_efetiva is None
        with pytest.raises(Exception) as exc:
            self._apagar(db_session, "vencido.pdf")
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_o_piso_continua_sendo_piso(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A âncora ESTENDE, nunca encurta.

        Relação encerrada há seis anos, documento arquivado hoje: a âncora
        (encerramento + 5 anos) já venceu, e mesmo assim o documento fica
        guardado cinco anos a contar de hoje. Um prazo de guarda não retroage
        sobre o que ainda não estava guardado — daí `greatest`, e não
        substituição.
        """
        doc_id = _documento_arquivado(
            db_session, tomador_autorizado, "novinho.pdf", dias_piso=5 * 365
        )
        self._operacao_encerrada(db_session, tomador_autorizado, anos_atras=6)

        retencao = self._retencao(db_session, doc_id)
        assert retencao.retencao_efetiva == retencao.retencao_piso
        assert retencao.motivo == "piso do arquivamento é posterior ao encerramento + 5 anos"

        with pytest.raises(Exception) as exc:
            self._apagar(db_session, "novinho.pdf")
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    @pytest.mark.parametrize("status", ["proposta", "registrada"])
    def test_transacao_nao_concluida_tambem_segura_o_expurgo(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        status: str,
    ) -> None:
        """'proposta' e 'registrada' contam como relação viva.

        O art. 10, III fala em encerramento da relação de negócio OU conclusão
        da transação, e um crédito em análise não é nem uma coisa nem outra. É
        justamente o momento em que a identificação do cliente mais importa:
        ele já entregou os documentos e ainda não recebeu nada, então a única
        coisa que o sistema tem sobre ele é a evidência que este teste impede
        de apagar. Sem estes dois status na lista de `v_operacao_encerramento`,
        o piso vencido liberaria o expurgo enquanto a proposta corre.

        A lista é a única coisa que segura isto, e é uma lista de literais num
        `case` — quem acrescentar um status novo à máquina de estados da 017
        tem que decidir de que lado ele fica, e este teste é o que avisa se a
        decisão passar batida.

        Nenhum dos dois ocupa o teto do Art. 5º (017), e por isso o cenário
        não pede capital constituído: a retenção responde a "a relação
        existe?", não a "o dinheiro saiu?".
        """
        nome = f"em_analise_{status}.pdf"
        doc_id = _documento_arquivado(db_session, tomador_autorizado, nome, dias_piso=-1)
        op_id = _operacao(db_session, tomador_autorizado, "10000", status=status)

        retencao = self._retencao(db_session, doc_id)
        assert retencao.relacao_em_curso is True
        # Indeterminada: os cinco anos não têm de onde começar a contar.
        assert retencao.retencao_efetiva is None
        assert retencao.encerramento_relacao is None
        assert "não começou a correr" in retencao.motivo

        # E a operação tem que aparecer como VIVA, não como fail-closed. Os
        # dois caminhos bloqueiam o expurgo igual — status fora da lista de
        # vivos cai no `coalesce(..., 'infinity')` e também segura —, e é
        # justamente por isso que o bloqueio sozinho NÃO prova que
        # 'proposta'/'registrada' estão na lista: tirá-las de lá não muda o
        # que o trigger faz, só o que a trilha diz. E o que ela passaria a
        # dizer é falso — "terminal sem evento que prove quando encerrou", ou
        # seja, trilha adulterada — mandando investigar o que não aconteceu.
        # O `null` aqui é o contrato escrito no comment de
        # `v_operacao_encerramento`, e é ele que ancora a lista de status.
        assert db_session.execute(
            text("select encerrada_em is null from v_operacao_encerramento where operacao_id = :o"),
            {"o": str(op_id)},
        ).scalar_one()

        with pytest.raises(Exception) as exc:
            self._apagar(db_session, nome)
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_status_terminal_sem_evento_na_trilha_segue_protegido(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Encerramento não provado não autoriza apagar prova.

        A âncora sai de `operacao_evento` (008). Operação em status terminal
        cuja trilha não tem o evento que diz QUANDO ela chegou lá não tem data
        de encerramento — e a 022 responde `infinity` em vez de inventar uma.
        É o mesmo `coalesce(..., 'infinity')` da 018, aqui pela razão mais dura
        das duas: sem prova de que a relação acabou, o prazo de cinco anos não
        tem marco inicial, e o preço de errar é destruir a prova.

        O cenário é o mesmo do caminho feliz — encerrado há seis anos, expurgo
        liberado —, e a única diferença é a trilha faltando. Por isso o teste
        confere ANTES que o expurgo estava liberado: sem esse passo ele
        passaria mesmo se a proteção viesse do piso, e não da falta de prova.

        O buraco só se produz desligando o append-only de OC010, e é essa a
        prova de que ele não se produz por acidente — mesma manobra e mesmo
        motivo de `envelhecer_encerramento` em tests/conftest.py.
        """
        doc_id = _documento_arquivado(
            db_session, tomador_autorizado, "sem_trilha.pdf", dias_piso=-1
        )
        op_id = self._operacao_encerrada(db_session, tomador_autorizado, anos_atras=6)
        assert self._retencao(db_session, doc_id).retencao_efetiva is not None

        db_session.execute(
            text("alter table operacao_evento disable trigger trg_operacao_evento_append_only")
        )
        apagados = db_session.execute(
            text(
                "delete from operacao_evento where operacao_id = :o and status_novo = 'liquidada'"
            ),
            {"o": str(op_id)},
        ).rowcount
        db_session.execute(
            text("alter table operacao_evento enable trigger trg_operacao_evento_append_only")
        )
        db_session.commit()
        assert apagados == 1, "o cenário depende de haver exatamente um evento de encerramento"

        # A comparação é feita NO BANCO porque `infinity` não atravessa o
        # driver: psycopg recusa carregar 'infinity'::date com DataError. É o
        # que torna os `nullif(..., 'infinity')` da 022 obrigatórios em toda
        # leitura que chega ao Python, e não um enfeite de apresentação.
        assert db_session.execute(
            text("""
            select encerrada_em = 'infinity'::date
            from v_operacao_encerramento where operacao_id = :o
            """),
            {"o": str(op_id)},
        ).scalar_one()

        assert self._retencao(db_session, doc_id).retencao_efetiva is None
        with pytest.raises(Exception) as exc:
            self._apagar(db_session, "sem_trilha.pdf")
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    def test_estender_a_coluna_por_update_continua_recusado(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
    ) -> None:
        """A saída que a 022 considerou e recusou, provada como recusada.

        "Permitir UPDATE que só aumenta a data" era a solução mais óbvia para
        ancorar no encerramento. Ela abriria em `tomador_documento` a exceção
        que a 019 documentou como fechada ("UPDATE nunca, em coluna nenhuma")
        — e a próxima exceção já encontraria o precedente. O prazo se estende
        por derivação; a linha continua congelada.
        """
        _documento_arquivado(db_session, tomador_autorizado, "congelado.pdf", dias_piso=30)
        db_session.commit()

        with pytest.raises(Exception) as exc:
            db_session.execute(
                text("""
                update tomador_documento
                   set retencao_ate = current_date + 3650
                 where nome_arquivo = 'congelado.pdf'
                """)
            )
            db_session.flush()
        assert sqlstate_de(exc.value) == "OC013"
        db_session.rollback()

    # -----------------------------------------------------------------
    # Os caminhos felizes — a prova de que nada legítimo travou
    # -----------------------------------------------------------------

    def test_expurgo_permitido_cinco_anos_depois_do_encerramento(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A retenção é obrigação de guardar por cinco anos, não para sempre.

        Vencidos o piso E a âncora, o expurgo volta a ser permitido — e é
        desejável, por minimização de dados. Se este teste falhar, a 022
        transformou uma correção de prazo numa proibição de apagar.
        """
        _documento_arquivado(db_session, tomador_autorizado, "expurgavel.pdf", dias_piso=-1)
        self._operacao_encerrada(db_session, tomador_autorizado, anos_atras=6)

        self._apagar(db_session, "expurgavel.pdf")
        db_session.commit()

        assert (
            db_session.execute(
                text("select count(*) from tomador_documento where nome_arquivo = 'expurgavel.pdf'")
            ).scalar_one()
            == 0
        )

    def test_tomador_sem_operacao_continua_valendo_o_piso(
        self,
        db_session: Session,
        tomador_sem_identificacao: uuid.UUID,
    ) -> None:
        """Sem relação de negócio não há encerramento, e a regra da 010 fica.

        É o caso que NÃO podia mudar de comportamento: quem só tem cadastro
        não tem operação para ancorar nada, e a leitura disponível continua
        sendo arquivamento + 5 anos.
        """
        doc_id = _documento_arquivado(
            db_session, tomador_sem_identificacao, "so_cadastro.pdf", dias_piso=-1
        )
        retencao = self._retencao(db_session, doc_id)
        assert retencao.relacao_em_curso is False
        assert retencao.encerramento_relacao is None
        assert retencao.retencao_efetiva == retencao.retencao_piso
        assert retencao.motivo == "tomador sem operação encerrada: vale o piso do arquivamento"

        self._apagar(db_session, "so_cadastro.pdf")
        db_session.commit()

    # -----------------------------------------------------------------
    # A API
    # -----------------------------------------------------------------

    def test_documento_listado_traz_o_prazo_efetivo_ao_lado_do_piso(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A tela deixa de exibir uma data que não é a que vale.

        O piso continua no mesmo campo (`retencao_ate`) para não quebrar quem
        já o consome; `retencao_efetiva` nulo é a forma de dizer "indeterminada
        — a relação não encerrou", que é diferente de "sem prazo".
        """
        resposta = _arquivar(admin_client, tomador_autorizado, b"identidade", nome="rg.pdf")
        assert resposta.status_code == 201
        corpo = resposta.json()
        assert corpo["relacao_em_curso"] is False
        assert corpo["retencao_efetiva"] == corpo["retencao_ate"]

        op_id = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)

        listados = admin_client.get(
            f"/api/compliance/tomadores/{tomador_autorizado}/documentos"
        ).json()
        rg = next(d for d in listados if d["nome_arquivo"] == "rg.pdf")
        assert rg["relacao_em_curso"] is True
        assert rg["retencao_efetiva"] is None
        # O piso segue lá, intacto: é a regra congelada da época do
        # arquivamento, não uma estimativa que a derivação substitui.
        assert rg["retencao_ate"] == corpo["retencao_ate"]

    def test_auditoria_responde_sobre_data_passada(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """ "Este documento podia ter sido apagado naquela data?"

        É a pergunta da fiscalização, e é o argumento decisivo contra
        sobrescrever a coluna: uma data reescrita só sabe dizer o valor de
        hoje. Aqui o cenário é um documento arquivado há sete anos (piso
        vencido há dois) de um tomador cuja relação encerrou há seis — âncora
        em -1 ano. Ele é expurgável HOJE e não era há quatrocentos dias, e as
        duas respostas saem da mesma função que o trigger consulta.
        """
        doc_id = _documento_arquivado(
            db_session,
            tomador_autorizado,
            "antigo.pdf",
            dias_piso=-2 * 365,
            dias_atras=7 * 365,
        )
        self._operacao_encerrada(db_session, tomador_autorizado, anos_atras=6)

        hoje = admin_client.get(f"/api/compliance/documentos/{doc_id}/retencao").json()
        assert hoje["existia_na_referencia"] is True
        assert hoje["relacao_em_curso"] is False
        assert hoje["podia_ser_apagado"] is True

        antes = admin_client.get(
            f"/api/compliance/documentos/{doc_id}/retencao",
            params={"em": (date.today() - timedelta(days=400)).isoformat()},
        ).json()
        assert antes["existia_na_referencia"] is True
        # A âncora (encerramento + 5 anos) ainda não tinha vencido naquele dia.
        assert antes["podia_ser_apagado"] is False
        assert antes["retencao_efetiva"] == hoje["retencao_efetiva"]

    def test_auditoria_nao_responde_sobre_documento_que_nao_existia(
        self,
        admin_client: TestClient,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
    ) -> None:
        """Data anterior ao arquivamento: não havia o que apagar.

        `podia_ser_apagado` falso aqui tem causa diferente de todas as outras,
        e é por isso que `existia_na_referencia` vem junto — sem ele, a
        resposta seria lida como "estava protegido"."""
        doc_id = _documento_arquivado(db_session, tomador_autorizado, "recente.pdf", dias_piso=-1)

        corpo = admin_client.get(
            f"/api/compliance/documentos/{doc_id}/retencao",
            params={"em": (date.today() - timedelta(days=30)).isoformat()},
        ).json()
        assert corpo["existia_na_referencia"] is False
        assert corpo["podia_ser_apagado"] is False


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


def _envelhecer_agenda(db_session: Session, operacao_id: uuid.UUID, dias: int) -> None:
    """Recua a agenda INTEIRA da operação em `dias`.

    Vencimento é imutável (OC009) e a agenda é emitida pelo banco na
    ativação — não existe caminho de produção que a reescreva, que é
    justamente a garantia introduzida pela 007. Para fabricar o cenário o
    teste desliga a guarda pelo tempo de um UPDATE: mesma manobra, e mesmo
    motivo, de `_envelhecer` em tests/test_aging.py.

    O deslocamento é RELATIVO ao vencimento já gravado — que o banco
    calculou a partir do seu próprio `current_date` na ativação — e nunca
    uma data vinda do Python. Os dois relógios divergem (o container roda
    em Etc/UTC e a máquina local em UTC-3), e por três horas todo dia eles
    discordam de um dia inteiro; ancorar o cenário no relógio errado já
    produziu falha diária, no mesmo horário, sem nada de errado no código.

    Recua a agenda toda, e não só a primeira parcela, para que ela continue
    sendo uma agenda coerente: parcelas mensais consecutivas, a um mês uma
    da outra. A REGRA 2 só lê `min(vencimento)`, mas um cenário em que a
    parcela 1 vence depois da 2 descreveria um fato que o sistema não
    produz.
    """
    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    db_session.execute(
        text("""
        update parcela
           set vencimento = vencimento - make_interval(days => :dias)
         where operacao_id = :op
        """),
        {"dias": dias, "op": str(operacao_id)},
    )
    db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.commit()


def _envelhecer_fato(db_session: Session, operacao_id: uuid.UUID, dias: int) -> None:
    """Recua o FATO INTEIRO em `dias` — as DUAS pontas pelo MESMO tanto.

    É a diferença entre simular o tempo passando e fabricar um fato
    diferente, e ela não é sutil: `envelhecer_encerramento(anos=1)` somado a
    `_envelhecer_agenda(dias=60)` não preserva coisa nenhuma. Medido nesta
    suíte: a distância entre a liquidação e o primeiro vencimento salta de 31
    para 336 dias. O cenário resultante continua sendo detectado, mas o que
    ele exercita é uma antecipação de onze meses — um fato MAIS extremo,
    não o mesmo fato visto mais tarde. Um teste montado assim provaria que a
    regra pega antecipação grande e passada; não provaria a propriedade que
    interessa.

    Aqui as duas pontas andam o mesmo número de dias, de modo que a única
    coisa que muda é a POSIÇÃO do fato em relação a `current_date`. É a única
    forma de variar o relógio da varredura sem variar o que se varre.

    Mesma manobra de `envelhecer_encerramento` (tests/conftest.py) para o
    evento terminal e de `_envelhecer_agenda` para a agenda: desligar a guarda
    append-only pelo tempo de um UPDATE, em banco descartável. O
    `capital_ledger` NÃO é envelhecido junto, e isso é deliberado: desde a 020
    seu `created_at` é escrito pelo banco (`new.created_at := now()`) e entra
    no digest da hash-chain, de modo que antedatá-lo exigiria forjar o hash —
    fabricar em teste exatamente o artefato que a 020 existe para tornar
    impossível.
    """
    db_session.execute(
        text("alter table operacao_evento disable trigger trg_operacao_evento_append_only")
    )
    afetados = db_session.execute(
        text("""
        update operacao_evento
           set created_at = created_at - make_interval(days => :dias)
         where operacao_id = :op
           and status_novo in ('liquidada', 'renegociada', 'cancelada', 'baixada_prejuizo')
        """),
        {"op": str(operacao_id), "dias": dias},
    ).rowcount
    db_session.execute(
        text("alter table operacao_evento enable trigger trg_operacao_evento_append_only")
    )
    db_session.commit()

    # Zero aqui é cenário mal montado: sem evento terminal a REGRA 2 cairia no
    # ramo "data não provada" e o teste passaria pelo motivo errado.
    assert afetados > 0, (
        f"operação {operacao_id} não tem evento de encerramento em operacao_evento: "
        "não há fato terminal para envelhecer."
    )

    _envelhecer_agenda(db_session, operacao_id, dias)


class TestLiquidacaoAntecipada:
    """REGRA 2 de `fn_detectar_atipicidades` (migrations 010 e 023).

    Tomar crédito e devolvê-lo antes mesmo da primeira parcela vencer não é
    ilegal, mas é o formato de quem usa a operação para dar aparência lícita
    a recurso que já tinha. A regra existe para pôr um par de olhos nisso.

    A PROPRIEDADE CENTRAL que esta classe prova é que a resposta da varredura
    depende do FATO e não do RELÓGIO. O filtro da 010 comparava o primeiro
    vencimento com `current_date`: a mesma operação era detectada enquanto a
    varredura rodasse antes do vencimento e deixava de ser detectada para
    sempre no dia seguinte, embora nada sobre ela tivesse mudado. Como a
    varredura só roda por clique manual, isso é uma loteria com data de
    validade — e a validade tende a expirar antes do clique.
    """

    def _liquidada_antes_do_primeiro_vencimento(
        self, db_session: Session, tomador_id: uuid.UUID
    ) -> uuid.UUID:
        """Operação levada até 'liquidada' pelo caminho real, sem atalho.

        R$ 10.000 e não menos: abaixo do limiar padrão a mesma operação
        entraria também na REGRA 1 (fracionamento) se houvesse três delas, e
        o teste passaria a contar ocorrências de duas regras diferentes. E a
        baixa é pelo valor exato da parcela, o que mantém a REGRA 3
        (pagamento em excesso) fora do cenário — o total de ocorrências
        esperado é 1, e é sobre esse 1 que a asserção fala.

        Quitar antes de liquidar não é cerimônia: desde a 017 `ativa ->
        liquidada` exige a agenda inteira baixada contra movimento bancário
        (OC022).
        """
        op_id = _operacao(db_session, tomador_id, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
        assert quitar_operacao(db_session, op_id) == 12, "cenário sem agenda para quitar"
        transicionar_operacao(db_session, op_id, "liquidada")
        return op_id

    def _fato(self, db_session: Session, operacao_id: uuid.UUID) -> Any:
        """As três datas que descrevem o fato, lidas NO BANCO.

        `liquidada_em` sai de `operacao_evento` (008) porque é a trilha das
        transições de ESTADO — a que responde "quando isto virou liquidada".
        O `capital_ledger` responde outra pergunta (quanto de capital voltou
        ao teto), e as duas trilhas são separadas de propósito.

        `min()` e não `max()`, igual à REGRA 2: onde a leitura da trilha é o
        objeto do teste, ler diferente da regra seria medir outra coisa.
        """
        return db_session.execute(
            text("""
            select (select min(vencimento) from parcela where operacao_id = :o)
                       as primeiro_venc,
                   (select min(created_at)::date from operacao_evento
                     where operacao_id = :o and status_novo = 'liquidada')
                       as liquidada_em,
                   current_date as hoje
            """),
            {"o": str(operacao_id)},
        ).one()

    def _detectar(self, db_session: Session) -> int:
        return db_session.execute(  # type: ignore[no-any-return]
            text("select fn_detectar_atipicidades()")
        ).scalar_one()

    def _ocorrencias(self, db_session: Session, operacao_id: uuid.UUID) -> list:
        return db_session.execute(
            text("""
            select regra, severidade, detalhe from ocorrencia_atipicidade
             where operacao_id = :o order by regra
            """),
            {"o": str(operacao_id)},
        ).all()

    def test_varredura_logo_depois_da_liquidacao_detecta(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O caso que a REGRA 2 já pegava antes da 023: o vencimento ainda não
        chegou.

        É o cenário fácil — o único em que o filtro da 010 (`primeiro_venc >
        current_date`) coincidia com o fato — e existe para que o teste
        seguinte não possa ser lido como "a regra nunca funcionou". Ela
        funcionava; o que não funcionava era continuar funcionando amanhã.
        """
        op_id = self._liquidada_antes_do_primeiro_vencimento(db_session, tomador_autorizado)

        fato = self._fato(db_session, op_id)
        assert fato.liquidada_em < fato.primeiro_venc
        # A varredura roda ANTES do primeiro vencimento — é isto, e só isto,
        # que distingue este cenário do próximo.
        assert fato.primeiro_venc > fato.hoje

        assert self._detectar(db_session) == 1
        ocorrencias = self._ocorrencias(db_session, op_id)
        assert [o.regra for o in ocorrencias] == ["liquidacao_antecipada"]
        assert ocorrencias[0].severidade == "media"

    # Dois meses, um ano, dez anos. Todos acima de 31 dias de propósito: a
    # primeira parcela vence a ~31 dias da ativação, e um horizonte menor
    # deixaria o vencimento ainda no futuro — o cenário fácil do teste
    # anterior, disfarçado de horizonte novo, em que o filtro da 010 também
    # acertava. O que se quer aqui é o dia em que a regra antiga desistia.
    @pytest.mark.parametrize("dias", [60, 365, 3650])
    def test_o_mesmo_fato_em_qualquer_horizonte_da_o_mesmo_veredito(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
        dias: int,
    ) -> None:
        """A propriedade central: um mês depois, um ano depois, dez anos
        depois — o mesmo fato, o mesmo veredito.

        O fato é montado uma vez e depois DESLOCADO no tempo, as duas pontas
        pelo mesmo número de dias (ver `_envelhecer_fato`). A distância entre
        a liquidação e o primeiro vencimento é medida antes e depois e tem de
        ser IDÊNTICA: se ela mudar, o teste deixou de falar do mesmo fato e a
        propriedade não foi provada, foi só encenada. Deslocar as duas pontas
        junto é o que separa "simular o relógio andando" de "fabricar uma
        operação mais suspeita e comemorar que a regra a pega".

        Em todos os horizontes o primeiro vencimento já ficou no passado — que
        é exatamente a condição sob a qual o filtro da 010 devolvia zero. Cada
        parametrização, portanto, é um dia em que a regra antiga já teria
        desistido do caso.
        """
        op_id = self._liquidada_antes_do_primeiro_vencimento(db_session, tomador_autorizado)
        antes = self._fato(db_session, op_id)
        distancia_antes = (antes.primeiro_venc - antes.liquidada_em).days

        _envelhecer_fato(db_session, op_id, dias=dias)

        fato = self._fato(db_session, op_id)
        # O FATO é o mesmo: mesma folga entre a liquidação e o vencimento.
        assert (fato.primeiro_venc - fato.liquidada_em).days == distancia_antes
        assert fato.liquidada_em < fato.primeiro_venc
        # O que mudou é só a posição dele em relação ao relógio da varredura:
        # o vencimento, que antes estava no futuro, agora está no passado.
        assert antes.primeiro_venc > antes.hoje
        assert fato.primeiro_venc < fato.hoje

        assert self._detectar(db_session) == 1
        ocorrencias = self._ocorrencias(db_session, op_id)
        assert [o.regra for o in ocorrencias] == ["liquidacao_antecipada"]
        assert ocorrencias[0].severidade == "media"

    def test_liquidada_depois_do_primeiro_vencimento_nao_e_marcada(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O caminho feliz, e ele é metade da correção.

        Uma regra que passasse a marcar TODA operação liquidada estaria
        "corrigida" no teste anterior e seria pior do que o defeito: a tela de
        compliance encheria de operação que pagou em dia, e o analista pararia
        de olhar — o resultado que a própria 010 diz querer evitar.

        O cenário é a imagem espelhada do outro: a agenda recua 60 dias ANTES
        da quitação, de modo que o primeiro vencimento fica 30 dias no passado
        e a liquidação acontece hoje, depois dele. Quitação normal, com
        atraso, de quem pagou tudo.
        """
        op_id = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
        _envelhecer_agenda(db_session, op_id, dias=60)
        assert quitar_operacao(db_session, op_id) == 12, "cenário sem agenda para quitar"
        transicionar_operacao(db_session, op_id, "liquidada")

        fato = self._fato(db_session, op_id)
        assert fato.primeiro_venc < fato.liquidada_em

        assert self._detectar(db_session) == 0
        assert self._ocorrencias(db_session, op_id) == []

    def test_liquidada_no_dia_do_primeiro_vencimento_nao_e_marcada(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A BORDA: pagar NO DIA do vencimento é pagar em dia, não antes.

        O teste anterior deixa 30 dias de folga entre o vencimento e a
        quitação, e uma folga desse tamanho não distingue `<` de `<=`. Trocar
        o operador da REGRA 2 por `<=` passaria por ele intacto — e marcaria
        como atipicidade PLD toda operação quitada exatamente no vencimento,
        que é o comportamento MAIS comum que existe num contrato de crédito.
        Seria um falso positivo de massa: a tela de compliance encheria de
        quem pagou certo, e um painel assim é lido uma vez e abandonado.

        Por isso a asserção é sobre a igualdade das três datas, e não sobre
        uma distância. O deslocamento da agenda é MEDIDO NO BANCO
        (`min(vencimento) - current_date`) e aplicado por `_envelhecer_agenda`:
        as duas pontas do cenário passam a sair do mesmo relógio, o do
        Postgres. Ancorar a borda numa data vinda do Python poria o container
        (Etc/UTC) contra a máquina local (UTC-3) e produziria falha diária, no
        mesmo horário, sem nada de errado no código.
        """
        op_id = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
        distancia = db_session.execute(
            text("""
            select (select min(vencimento) from parcela where operacao_id = :o)
                   - current_date
            """),
            {"o": str(op_id)},
        ).scalar_one()
        _envelhecer_agenda(db_session, op_id, dias=distancia)
        assert quitar_operacao(db_session, op_id) == 12, "cenário sem agenda para quitar"
        transicionar_operacao(db_session, op_id, "liquidada")

        fato = self._fato(db_session, op_id)
        assert fato.primeiro_venc == fato.liquidada_em == fato.hoje

        assert self._detectar(db_session) == 0
        assert self._ocorrencias(db_session, op_id) == []

    def test_varredura_continua_idempotente(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Rodar duas vezes não pode produzir duas linhas do mesmo fato.

        A REGRA 2 deixou de se deduplicar pelo TEXTO do detalhe (que agora
        carrega a data da liquidação) e passou a se deduplicar por (regra,
        operacao_id). A troca é invisível pelo lado de fora, e é justamente
        por isso que precisa de asserção: o `on conflict` continua no lugar e
        mascararia a ausência da guarda nova enquanto o texto não mudasse.
        """
        op_id = self._liquidada_antes_do_primeiro_vencimento(db_session, tomador_autorizado)

        assert self._detectar(db_session) == 1
        assert self._detectar(db_session) == 0
        assert len(self._ocorrencias(db_session, op_id)) == 1

    def test_ocorrencia_do_texto_antigo_nao_e_marcada_de_novo(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """A armadilha que a 023 tinha de desarmar, e que só aparece em base
        que já rodou a varredura antes.

        O detalhe da REGRA 2 entra no índice `ocorrencia_unica` (010). A 023
        muda o texto — passa a gravar a data da liquidação ao lado do primeiro
        vencimento, sem a qual a ocorrência é inavaliável — e uma mudança de
        texto, sozinha, reinseriria sob a redação nova tudo que já estava
        gravado sob a antiga. Como a ocorrência é append-only (OC014) e o
        TRUNCATE é recusado (016), a duplicata seria permanente e apareceria
        para sempre duas vezes na tela.

        Aqui a linha antiga é gravada À MÃO, com a redação literal da 010, e
        o que se prova é que a varredura nova a reconhece como o mesmo fato e
        não escreve nada.
        """
        op_id = self._liquidada_antes_do_primeiro_vencimento(db_session, tomador_autorizado)
        fato = self._fato(db_session, op_id)
        detalhe_antigo = f"Liquidada antes do primeiro vencimento ({fato.primeiro_venc})"

        db_session.execute(
            text("""
            insert into ocorrencia_atipicidade
                (regra, severidade, tomador_id, operacao_id, detalhe)
            values ('liquidacao_antecipada', 'media', :t, :o, :d)
            """),
            {"t": str(tomador_autorizado), "o": str(op_id), "d": detalhe_antigo},
        )
        db_session.commit()

        assert self._detectar(db_session) == 0
        ocorrencias = self._ocorrencias(db_session, op_id)
        assert len(ocorrencias) == 1
        assert ocorrencias[0].detalhe == detalhe_antigo

    def test_write_off_antes_do_vencimento_e_outra_regra(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Baixar como prejuízo antes de a primeira parcela vencer.

        Não houve oportunidade de inadimplência — não havia o que pagar
        ainda —, e mesmo assim a ESC declarou o valor irrecuperável. O
        significado econômico é o OPOSTO do da quitação antecipada (lá o
        dinheiro voltou cedo demais; aqui não voltou), a providência do
        analista é outra, e por isso a regra tem nome e severidade próprios em
        vez de dividir o rótulo com a liquidação.

        `ativa -> baixada_prejuizo` não passa pelo gate de quitação (OC022):
        o write-off existe justamente para encerrar a cobrança SEM pagamento,
        e por isso a agenda fica inteira em aberto.

        O fato é envelhecido em bloco ANTES da varredura: a regra nasce já
        ancorada na data do fato, e o cenário que a exercita é o que o filtro
        da 010 nunca teria pego — baixa antiga, com o primeiro vencimento já
        no passado.
        """
        op_id = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
        transicionar_operacao(db_session, op_id, "baixada_prejuizo")
        _envelhecer_fato(db_session, op_id, dias=365)

        baixada_em, primeiro_venc, hoje = db_session.execute(
            text("""
            select (select min(e.created_at)::date from operacao_evento e
                     where e.operacao_id = :o and e.status_novo = 'baixada_prejuizo'),
                   (select min(vencimento) from parcela where operacao_id = :o),
                   current_date
            """),
            {"o": str(op_id)},
        ).one()
        assert baixada_em < primeiro_venc < hoje

        assert self._detectar(db_session) == 1
        ocorrencias = self._ocorrencias(db_session, op_id)
        assert [o.regra for o in ocorrencias] == ["baixa_prejuizo_antecipada"]
        assert ocorrencias[0].severidade == "alta"
        assert "prejuízo" in ocorrencias[0].detalhe

        # E não vira uma segunda linha na varredura seguinte.
        assert self._detectar(db_session) == 0
        assert len(self._ocorrencias(db_session, op_id)) == 1

    def test_write_off_de_inadimplente_veterano_nao_e_marcado(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O write-off ORDINÁRIO, que é a esmagadora maioria deles.

        A regra `baixa_prejuizo_antecipada` nasce com severidade 'alta' — a
        mais alta que existe — e é por severidade que a tela de compliance
        ordena. Uma regra nesse posto sem prova do lado negativo é a receita
        do painel que ninguém lê: bastaria a próxima alteração afrouxar o
        filtro para que todo write-off da carteira subisse ao topo da lista, e
        write-off de inadimplente antigo é justamente o caso NORMAL, o que a
        ESC pratica depois de cobrar e não receber.

        O cenário é o oposto do anterior em uma única coisa: aqui o
        vencimento vem PRIMEIRO. A agenda recua 400 dias, a régua automática
        da 008 (`fn_processar_aging`) faz `ativa -> inadimplente` como faria
        em produção, e só então a perda é declarada. Houve oportunidade de
        pagamento e ela foi desperdiçada — que é exatamente o que o write-off
        precoce não tem, e a única coisa que separa os dois fatos.
        """
        op_id = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
        _envelhecer_agenda(db_session, op_id, dias=400)

        db_session.execute(text("select fn_processar_aging()"))
        db_session.commit()
        assert (
            db_session.execute(
                text("select status from operacao_credito where id = :o"),
                {"o": str(op_id)},
            ).scalar_one()
            == "inadimplente"
        ), "cenário mal montado: a régua da 008 não chegou a declarar a inadimplência"

        transicionar_operacao(db_session, op_id, "baixada_prejuizo")

        primeiro_venc, baixada_em = db_session.execute(
            text("""
            select (select min(vencimento) from parcela where operacao_id = :o),
                   (select min(e.created_at)::date from operacao_evento e
                     where e.operacao_id = :o and e.status_novo = 'baixada_prejuizo')
            """),
            {"o": str(op_id)},
        ).one()
        assert primeiro_venc < baixada_em

        assert self._detectar(db_session) == 0
        assert self._ocorrencias(db_session, op_id) == []

    def test_evento_forjado_com_carimbo_tardio_nao_apaga_a_deteccao(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """O preço da fonte escolhida, cobrado em teste — e a prova de que
        `min()` é o que o torna suportável.

        A 023 lê a data do encerramento de `operacao_evento` e não do
        `capital_ledger`, e paga um preço por isso: o `created_at` de
        `operacao_evento` é DEFAULT `clock_timestamp()`, não imposição do
        banco. O append-only (OC010) recusa UPDATE e DELETE; não recusa uma
        LINHA NOVA com o carimbo que o autor escolher. O INSERT abaixo é
        exatamente isso, e repare no que ele NÃO precisa fazer: nenhum
        `disable trigger`, nenhuma manobra. A trilha aceita a linha forjada de
        primeira. Essa é a diferença concreta para o `capital_ledger`, cujo
        `created_at` é sobrescrito pelo banco desde a 020 e entra no digest da
        hash-chain.

        Quem quer escapar da REGRA 2 precisa que a data lida seja TARDIA — que
        o encerramento pareça ter acontecido DEPOIS do primeiro vencimento. O
        evento forjado aqui carimba exatamente isso: primeiro vencimento mais
        um dia. Com `max()` a regra leria a mentira e a operação sumiria da
        tela; com `min()` o evento real continua sendo o menor e a mentira não
        muda nada — só deixa na trilha uma linha a mais, que é o lado do erro
        que não faz mal a ninguém.

        É a asserção que faltava para que `min()` deixasse de ser uma escolha
        documentada e virasse uma escolha PROVADA. Sem ela, trocar `min` por
        `max` neste ponto passa na suíte inteira — e a troca é o edit mais
        provável que alguém faria aqui, porque a 022 lê a MESMA trilha, para a
        MESMA operação, com `max()` (lá, uma data antecipada encurtaria o
        prazo legal de guarda; o lado perigoso é o oposto).
        """
        op_id = self._liquidada_antes_do_primeiro_vencimento(db_session, tomador_autorizado)
        fato = self._fato(db_session, op_id)

        db_session.execute(
            text("""
            insert into operacao_evento
                (operacao_id, status_anterior, status_novo, origem, usuario_id, created_at)
            values (:o, 'ativa', 'liquidada', 'usuario', 'forjador',
                    (select min(vencimento) + 1 from parcela where operacao_id = :o))
            """),
            {"o": str(op_id)},
        )
        db_session.commit()

        # A trilha passa a ter duas respostas para a mesma pergunta, e elas
        # caem em lados opostos do primeiro vencimento: é isto que faz a
        # escolha entre min() e max() decidir o resultado.
        menor, maior = db_session.execute(
            text("""
            select min(created_at)::date, max(created_at)::date
              from operacao_evento
             where operacao_id = :o and status_novo = 'liquidada'
            """),
            {"o": str(op_id)},
        ).one()
        assert menor < fato.primeiro_venc < maior

        assert self._detectar(db_session) == 1
        ocorrencias = self._ocorrencias(db_session, op_id)
        assert [o.regra for o in ocorrencias] == ["liquidacao_antecipada"]
        # E o detalhe mostra a data REAL, não a forjada: a linha que o analista
        # lê não repete a mentira que alguém plantou na trilha.
        assert str(menor) in ocorrencias[0].detalhe
        assert str(maior) not in ocorrencias[0].detalhe

    def test_sem_evento_na_trilha_detecta_assim_mesmo(
        self,
        db_session: Session,
        tomador_autorizado: uuid.UUID,
        capital_constituido: None,
    ) -> None:
        """Fail-closed: trilha de transições ausente não silencia a regra.

        A REGRA 2 depende de `operacao_evento` para saber QUANDO a operação
        encerrou. Se a resposta for nula, há duas saídas possíveis, e uma delas
        é ruim de um jeito específico: filtrar a linha fora faria do
        `disable trigger trg_registrar_evento_operacao` — um comando de uma
        linha — o jeito mais barato de apagar um alerta de PLD, e o apagamento
        seria invisível, porque a tela mostraria vazio e vazio se lê como "não
        há o que ver". A 023 escolhe a outra: detecta assim mesmo, e escreve no
        detalhe que a data não está provada.

        O cenário reproduz a causa descrita, e não um atalho equivalente: o
        gatilho da 008 fica desligado pelo tempo exato da transição terminal,
        de modo que o evento 'liquidada' nunca chega a existir. Os eventos
        anteriores ficam, que é o formato realista da manipulação — quem
        desliga o gatilho, desliga na hora do ato que quer esconder.

        Sem esta asserção, trocar `(encerrada_em is null or encerrada_em <
        primeiro_venc)` por `encerrada_em < primeiro_venc` passa na suíte
        inteira: `null < data` é NULL, a linha sai do filtro em silêncio, e a
        regra fica fail-open sem que nada acuse.
        """
        op_id = _operacao(db_session, tomador_autorizado, "10000")
        confirmar_registro(db_session, op_id)
        ativar_operacao(db_session, op_id)
        assert quitar_operacao(db_session, op_id) == 12, "cenário sem agenda para quitar"

        db_session.execute(
            text("alter table operacao_credito disable trigger trg_registrar_evento_operacao")
        )
        transicionar_operacao(db_session, op_id, "liquidada")
        db_session.execute(
            text("alter table operacao_credito enable trigger trg_registrar_evento_operacao")
        )
        db_session.commit()

        sem_evento = db_session.execute(
            text("""
            select count(*) from operacao_evento
             where operacao_id = :o and status_novo = 'liquidada'
            """),
            {"o": str(op_id)},
        ).scalar_one()
        assert sem_evento == 0, "cenário não reproduziu a trilha ausente"

        assert self._detectar(db_session) == 1
        ocorrencias = self._ocorrencias(db_session, op_id)
        assert [o.regra for o in ocorrencias] == ["liquidacao_antecipada"]
        assert "data não provada" in ocorrencias[0].detalhe


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
        numa fiscalização.

        O CENÁRIO PRECISOU DE UM PASSO A MAIS DESDE A 022, e o passo é a
        própria correção: piso vencido não basta mais para autorizar o
        expurgo. Como a operação acabara de ser liquidada, a âncora
        (encerramento + 5 anos) segurava o documento — corretamente. Envelhecer
        o encerramento em seis anos põe o cenário no único ponto em que apagar
        é legítimo, que é o ponto que este teste sempre quis descrever.
        """
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
        envelhecer_encerramento(db_session, op_id, anos=6)
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
