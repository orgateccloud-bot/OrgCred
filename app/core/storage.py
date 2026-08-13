"""
Storage de objetos — onde os BYTES da evidência de identificação vivem.

POR QUE ESTE MÓDULO EXISTE. A migration 010 criou `tomador_documento`
guardando só o SHA-256 do documento e escreveu que "o binário vive no
storage". Storage nenhum foi construído, e a 014 ligou o gate OC019 em cima
disso: ativar operação passou a exigir evidência de identificação arquivada
(Lei 9.613/98, art. 10, I) — evidência que era um hash digitado. Este módulo
é o "storage" daquela frase, três migrations depois.

POR QUE ISOLADO, e não `httpx.post` no meio do router. Duas razões, e a
segunda é a que importa:

1. O router não deve saber que o storage é HTTP, nem que é Supabase. Trocar
   o provedor (S3, disco, o que for) é escrever outra implementação de
   `Storage`, não reescrever compliance.

2. TESTE SEM REDE. A suíte precisa provar que o hash é calculado dos bytes
   recebidos, que arquivo adulterado não confere e que sem chave o
   arquivamento é RECUSADO. Nenhuma dessas três coisas é sobre o Supabase, e
   todas ficariam reféns de uma credencial e de uma conexão se a chamada
   estivesse embutida no endpoint. Com a interface pequena aqui, o teste
   injeta um storage falsificado e as três provas rodam offline.

FAIL-CLOSED É O PONTO INTEIRO. `get_storage()` RECUSA devolver um storage
quando a service_role key não está configurada, em vez de devolver um
"storage nulo" que aceita bytes e os joga fora. Um storage que finge guardar
reproduziria, com mais código, exatamente o defeito que este módulo corrige:
o sistema afirmando que a identificação está arquivada quando não está. Sem
chave, arquivar documento falha — e o resto do sistema (que não depende de
compliance para operar) continua de pé.
"""

from typing import Protocol

import httpx

from app.core.config import settings


# Um documento de identificação é um PDF, um JPEG ou um PNG escaneado. 20 MiB
# é folgado para qualquer um dos três e ainda assim recusa o upload que
# encheria o bucket por acidente ou de propósito. O limite mora aqui, e não
# só no router, porque é propriedade do storage: quem chamar `guardar` por
# outro caminho encontra a mesma recusa.
TAMANHO_MAXIMO_BYTES = 20 * 1024 * 1024

# Timeout curto e explícito. O default do httpx é `None` em algumas versões —
# sem timeout, uma indisponibilidade do storage vira um worker do uvicorn
# pendurado, e o sintoma que chega ao operador é "o sistema travou", não
# "o arquivamento falhou".
TIMEOUT_SEGUNDOS = 30.0


class StorageError(RuntimeError):
    """Base das falhas de storage.

    Não herda de `RegraNegocioViolada` de propósito: falha de storage não é
    regra de negócio violada, é infraestrutura indisponível. Confundir as
    duas faria a UI dizer ao operador que ele fez algo errado quando o
    problema é que o bucket está fora do ar.
    """


class StorageNaoConfigurado(StorageError):
    """Falta a URL do projeto ou a service_role key.

    É a recusa FAIL-CLOSED: sem onde guardar, arquivar evidência tem que
    falhar de forma visível. Aceitar o hash sem guardar o arquivo é o defeito
    histórico, não o modo degradado aceitável.
    """


class ObjetoNaoEncontrado(StorageError):
    """A linha do banco aponta para um objeto que o storage não tem.

    Numa evidência sob retenção legal isso é um incidente, não um 404
    banal: significa que a prova de identificação foi apagada do bucket por
    fora do sistema, enquanto o banco continua afirmando que ela existe.
    """


class FalhaNoStorage(StorageError):
    """O storage respondeu erro, ou não respondeu."""


class Storage(Protocol):
    """A interface, deliberadamente mínima: guardar bytes e recuperar bytes.

    `referencia` é o que fica gravado em `tomador_documento.storage_objeto`,
    no formato '<bucket>/<caminho>' — o bucket vai junto porque a retenção é
    de 5 anos e o bucket configurado muda (ver migrations/019).

    Não há `apagar` nesta interface, e a ausência é intencional: apagar
    evidência de identificação dentro do prazo é recusado pelo banco (OC013,
    Lei 9.613/98 art. 10, III). Uma API de storage que oferecesse o método
    convidaria a contornar o trigger pelo lado do bucket, que é o único lado
    onde o Postgres não alcança.
    """

    def guardar(self, referencia: str, conteudo: bytes, content_type: str) -> None:
        """Grava os bytes. Regravar a mesma referência com os mesmos bytes é
        idempotente — ver a nota sobre `x-upsert` em `SupabaseStorage`."""
        ...

    def recuperar(self, referencia: str) -> bytes:
        """Devolve os bytes, ou levanta `ObjetoNaoEncontrado`."""
        ...


def _partir(referencia: str) -> tuple[str, str]:
    """Quebra '<bucket>/<caminho>' nas duas partes.

    A validação de forma da referência é do BANCO (CHECK
    `tomador_documento_storage_objeto_valido`, migration 019), que é onde ela
    tem efeito sobre o dado gravado. Aqui a checagem é de sanidade contra
    chamada programática errada — e existe porque o valor entra num caminho
    de URL: uma referência sem bucket montaria uma URL que aponta para outro
    recurso da API do storage, não para um objeto.
    """
    bucket, _, caminho = referencia.partition("/")
    if not bucket or not caminho or ".." in referencia:
        raise FalhaNoStorage(
            f"Referência de objeto inválida: {referencia!r} "
            "(esperado '<bucket>/<caminho>', sem '..')."
        )
    return bucket, caminho


class SupabaseStorage:
    """Implementação sobre a API HTTP do Supabase Storage.

    A CHAVE É A service_role, e ela é uma TERCEIRA coisa no painel do
    Supabase — não é a anon key (pública, assada no bundle do frontend) nem o
    JWT Secret (usado para VALIDAR tokens em app/core/security.py). Trocar
    uma pela outra aqui não dá erro de configuração: dá 401 do bucket na hora
    de arquivar, com a aplicação inteira de pé. Ver o comentário em
    app/core/config.py e o .env.example.

    A service_role atravessa RLS. É por isso que ela NUNCA pode chegar ao
    frontend — o Dockerfile já diz o mesmo sobre a anon key pelo motivo
    oposto (aquela pode, esta não).
    """

    def __init__(self, url_projeto: str, service_key: str, timeout: float = TIMEOUT_SEGUNDOS):
        self._base = url_projeto.rstrip("/")
        self._service_key = service_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        # `apikey` E `Authorization`: o gateway do Supabase exige o primeiro
        # para rotear, e o storage exige o segundo para autorizar. Mandar só
        # um dos dois responde 401 sem dizer qual faltou.
        return {
            "apikey": self._service_key,
            "Authorization": f"Bearer {self._service_key}",
        }

    def guardar(self, referencia: str, conteudo: bytes, content_type: str) -> None:
        if not conteudo:
            raise FalhaNoStorage("Recusado guardar objeto vazio — zero byte não é evidência.")
        if len(conteudo) > TAMANHO_MAXIMO_BYTES:
            raise FalhaNoStorage(
                f"Objeto de {len(conteudo)} bytes excede o limite de "
                f"{TAMANHO_MAXIMO_BYTES} bytes."
            )

        bucket, caminho = _partir(referencia)
        headers = self._headers()
        headers["Content-Type"] = content_type
        # `x-upsert: true` de propósito. O caminho do objeto é derivado do
        # SHA-256 do próprio conteúdo (ver app/routers/compliance.py), então
        # "objeto já existe nessa referência" significa "os mesmos bytes já
        # foram gravados aí". Sem o upsert, uma retentativa depois de uma
        # falha de rede no meio do arquivamento bateria em 409 no storage e
        # o operador receberia um conflito de infraestrutura no lugar da
        # recusa de negócio correta (422, "este arquivo já está arquivado
        # para este tomador"), que quem decide é o banco.
        headers["x-upsert"] = "true"

        try:
            resposta = httpx.post(
                f"{self._base}/storage/v1/object/{bucket}/{caminho}",
                content=conteudo,
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise FalhaNoStorage(f"Falha ao contatar o storage: {exc}") from exc

        if resposta.status_code >= 400:
            raise FalhaNoStorage(
                f"Storage recusou gravar {referencia!r}: HTTP {resposta.status_code}."
            )

    def recuperar(self, referencia: str) -> bytes:
        bucket, caminho = _partir(referencia)
        try:
            resposta = httpx.get(
                f"{self._base}/storage/v1/object/{bucket}/{caminho}",
                headers=self._headers(),
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise FalhaNoStorage(f"Falha ao contatar o storage: {exc}") from exc

        if resposta.status_code == 404:
            raise ObjetoNaoEncontrado(
                f"Objeto {referencia!r} não está no storage — a evidência foi "
                "removida por fora do sistema."
            )
        if resposta.status_code >= 400:
            raise FalhaNoStorage(
                f"Storage recusou ler {referencia!r}: HTTP {resposta.status_code}."
            )
        return resposta.content


def get_storage() -> Storage:
    """Devolve o storage configurado, ou RECUSA.

    Lê `settings` na chamada, e não no import, porque o teste que prova a
    recusa fail-closed precisa poder zerar a chave depois de a aplicação já
    ter sido importada — e porque a ausência de chave não pode derrubar o
    startup: o OrgCred opera sem compliance ativo, só não arquiva documento.
    """
    if not settings.storage_configurado:
        raise StorageNaoConfigurado(
            "Storage de documentos não configurado: defina ORGCRED_SUPABASE_URL e "
            "ORGCRED_SUPABASE_SERVICE_KEY (a service_role key do painel do Supabase — "
            "NÃO a anon key, NÃO o JWT Secret). Arquivar evidência de identificação "
            "está recusado até lá: aceitar o hash sem guardar o arquivo produziria "
            "uma identificação que não existe."
        )
    return SupabaseStorage(settings.supabase_url, settings.supabase_service_key)


def referencia_para(tomador_id: str, sha256: str) -> str:
    """Monta a referência do objeto a partir do bucket configurado.

    O caminho é DERIVADO do conteúdo (`<tomador>/<sha256 dos bytes>`) e não
    tem um único caractere vindo do cliente. Isso resolve três coisas de uma
    vez: não há travessia de diretório possível, o mesmo arquivo do mesmo
    tomador sempre cai na mesma referência (o que torna a regravação
    idempotente e a retentativa segura), e o nome do arquivo enviado — que é
    dado do usuário — fica só na coluna `nome_arquivo`, onde é rótulo e não
    endereço.
    """
    return f"{settings.supabase_storage_bucket}/{tomador_id}/{sha256}"
