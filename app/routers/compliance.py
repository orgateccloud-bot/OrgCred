"""
Router: compliance PLD/FT — a parte que não depende de terceiro.

O regime PLD/COAF aplicável a uma ESC ainda depende de parecer jurídico
(ver MAPEAMENTO_E_PLANO_DE_COMBATE.md, Frente 4). O que este módulo entrega
sem esperar ninguém:

- Identificação do tomador com EVIDÊNCIA ARQUIVADA e verificável por hash.
- RETENÇÃO de 5 anos garantida pelo banco (Lei 9.613/98, art. 10, III),
  contados do ENCERRAMENTO DA RELAÇÃO desde a migration 022 — não do
  arquivamento, que numa operação de 60 parcelas vencia cinco anos cedo
  demais. `retencao_ate` continua sendo gravado e continua imutável, mas
  virou o PISO; o prazo que vale é derivado e vem em `retencao_efetiva`.
- DETECÇÃO INTERNA de atipicidade sobre os dados que já existem.

O canal externo é ADAPTADOR: a ocorrência já nasce com os campos
`comunicado_em`/`comunicacao_ref`, que nada preenche hoje. Quando o parecer
sair, liga-se o envio sem tocar na detecção — e o histórico já acumulado
continua válido.

A ativação de operação de tomador sem identificação arquivada é bloqueada
pelo banco desde a migration 014 (OC019). `GET
/compliance/identificacao/pendencias` continua expondo quem está nessa
situação, com o capital exposto — deixou de ser lista informativa e passou a
ser a relação de tomadores com quem não se consegue mais operar.

OS BYTES SÃO LIDOS PELO SERVIDOR (migration 019). Até ela, este router
aceitava um campo `sha256` vindo do cliente, validado só por
`^[0-9a-f]{64}$`: sessenta e quatro caracteres digitados satisfaziam a
exigência de identificar o cliente e nenhum byte era lido. Agora o
arquivamento recebe o ARQUIVO, calcula o hash dos bytes recebidos, guarda os
bytes no storage e só então grava a linha. Sem storage configurado, arquivar
é RECUSADO — fail-closed, porque aceitar o hash sem guardar o arquivo é
justamente o defeito corrigido.
"""

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import Row, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import get_admin_user, get_current_user, get_operador_user
from app.core.storage import (
    TAMANHO_MAXIMO_BYTES,
    ObjetoNaoEncontrado,
    Storage,
    StorageError,
    StorageNaoConfigurado,
    get_storage,
    referencia_para,
)
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/compliance", tags=["compliance"])

# Lei 9.613/98, art. 10, III — guarda por no mínimo 5 anos.
RETENCAO_ANOS = 5

TipoDocumento = Literal[
    "contrato_social",
    "cartao_cnpj",
    "documento_socio",
    "comprovante_endereco",
    "procuracao",
    "outro",
]

# O nome do arquivo é o único dado do cliente que sobrevive ao arquivamento,
# e ele é RÓTULO, não endereço: o caminho do objeto no storage é derivado do
# hash do conteúdo (`referencia_para`), sem um caractere vindo de fora. Ainda
# assim ele é saneado, porque vai para tela e para relatório — um nome com
# separador de diretório ou caractere de controle é ou tentativa de confundir
# quem lê, ou lixo que veio junto do navegador.
_NOME_ARQUIVO_PROIBIDO = re.compile(r"[\x00-\x1f\x7f/\\]")


def storage_de_documentos() -> Storage:
    """Dependência: o storage configurado, ou 503.

    A tradução de `StorageNaoConfigurado` para HTTP mora aqui, e não dentro
    de `app/core/storage.py`, para o módulo de storage continuar sem saber
    que existe FastAPI — é o que permite testá-lo (e falsificá-lo) sem subir
    aplicação nenhuma.

    503 e não 500: a configuração ausente não é bug do servidor processando o
    pedido, é dependência indisponível. E não é 422: o operador não mandou
    nada de errado, não há o que ele corrija no formulário. A instrução útil
    é para quem opera a infraestrutura, e vai no `detail`.
    """
    try:
        return get_storage()
    except StorageNaoConfigurado as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class DocumentoOut(BaseModel):
    id: UUID
    tomador_id: UUID
    tipo: str
    nome_arquivo: str
    sha256: str
    arquivado_em: datetime
    # O PISO, não o prazo. Continua sendo a coluna `retencao_ate` gravada no
    # arquivamento (arquivamento + 5 anos, sob a regra vigente naquele dia), e
    # continua com o mesmo nome para não quebrar quem já o consome — o que a
    # migration 022 mudou é que ele deixou de ser a última palavra.
    retencao_ate: date
    # A última palavra: greatest(piso, encerramento da relação + 5 anos),
    # Lei 9.613/98 art. 10, III. NULO significa INDETERMINADA — a relação de
    # negócio com o tomador ainda não encerrou, então os cinco anos sequer
    # começaram a correr e não existe data em que apagar seja legítimo.
    retencao_efetiva: Optional[date]
    relacao_em_curso: bool
    encerramento_relacao: Optional[date]
    # Nulo só nas evidências anteriores à migration 019 — aquelas cujos bytes
    # nunca existiram. Exposto porque a diferença entre "identificação
    # arquivada" e "hash sem arquivo" é exatamente o que uma fiscalização
    # pergunta, e esconder o campo devolveria as duas coisas com a mesma cara.
    storage_objeto: Optional[str]


# A leitura de documento sai TODA de `v_documento_retencao` (migration 022), e
# não da tabela: o prazo efetivo é derivado, e derivá-lo de novo aqui em
# Python criaria uma segunda implementação da regra — a que a tela mostra —
# livre para divergir daquela que o trigger OC013 aplica. Sendo a view a única
# fonte, tela e banco respondem sempre a mesma coisa.
_SELECT_DOCUMENTO = """
select documento_id, tomador_id, tipo, nome_arquivo, sha256, arquivado_em,
       retencao_piso, retencao_efetiva, relacao_em_curso, encerramento_relacao,
       storage_objeto
from v_documento_retencao
"""


def _documento_out(r: Row[Any]) -> DocumentoOut:
    return DocumentoOut(
        id=r.documento_id,
        tomador_id=r.tomador_id,
        tipo=r.tipo,
        nome_arquivo=r.nome_arquivo,
        sha256=r.sha256,
        arquivado_em=r.arquivado_em,
        retencao_ate=r.retencao_piso,
        retencao_efetiva=r.retencao_efetiva,
        relacao_em_curso=r.relacao_em_curso,
        encerramento_relacao=r.encerramento_relacao,
        storage_objeto=r.storage_objeto,
    )


def _ler_upload(arquivo: UploadFile) -> bytes:
    """Lê o upload inteiro, com teto, e recusa o que não é evidência de nada.

    O teto é aplicado LENDO um byte a mais que o limite em vez de confiar em
    `arquivo.size` ou no `Content-Length`: os dois são declarações do cliente,
    e o ponto deste endpoint é parar de acreditar em declaração do cliente
    sobre o conteúdo.
    """
    conteudo = arquivo.file.read(TAMANHO_MAXIMO_BYTES + 1)
    if len(conteudo) > TAMANHO_MAXIMO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo excede o limite de {TAMANHO_MAXIMO_BYTES // (1024 * 1024)} MiB.",
        )
    if not conteudo:
        raise HTTPException(
            status_code=422,
            detail="Arquivo vazio não é evidência de identificação.",
        )
    return conteudo


def _nome_saneado(arquivo: UploadFile) -> str:
    """Nome de exibição do arquivo, sem separador de caminho nem controle."""
    bruto = (arquivo.filename or "").strip()
    limpo = _NOME_ARQUIVO_PROIBIDO.sub("_", bruto)[:255].strip()
    if not limpo:
        raise HTTPException(status_code=422, detail="Envie o arquivo com um nome.")
    return limpo


@router.get("/tomadores/{tomador_id}/documentos", response_model=List[DocumentoOut])
def get_documentos(
    tomador_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[DocumentoOut]:
    rows = db.execute(
        text(f"{_SELECT_DOCUMENTO} where tomador_id = :t order by arquivado_em desc"),
        {"t": str(tomador_id)},
    ).all()
    return [_documento_out(r) for r in rows]


@router.post("/tomadores/{tomador_id}/documentos", response_model=DocumentoOut, status_code=201)
def post_documento(
    tomador_id: UUID,
    tipo: TipoDocumento = Form(...),
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
    storage: Storage = Depends(storage_de_documentos),
) -> DocumentoOut:
    """Arquiva a evidência de identificação — com os BYTES.

    O QUE MUDOU NA MIGRATION 019, e por que era grave: este endpoint recebia
    um campo `sha256` do cliente e gravava a linha. Nenhum byte era lido, não
    havia storage, e o gate OC019 (ativar exige evidência arquivada, Lei
    9.613/98 art. 10, I) dava por cumprida a identificação de quem digitasse
    64 caracteres hexadecimais. Agora o hash é CALCULADO aqui, sobre o que
    chegou — não existe mais um caminho para o cliente afirmar o hash.

    A ORDEM É: guardar os bytes, depois gravar a linha. O inverso deixaria a
    janela em que o banco afirma ter evidência que o bucket não tem, que é o
    estado que esta migration existe para eliminar. Falhar na ordem escolhida
    deixa, no pior caso, um objeto no bucket sem linha no banco — desperdício
    de espaço, não falha de compliance. E nem isso, no caso comum: a
    referência é derivada do hash do conteúdo, então a retentativa regrava o
    mesmo objeto no mesmo lugar em vez de criar outro.

    `retencao_ate` é gravado agora, e não calculado na leitura: se o prazo
    legal mudar, os documentos já arquivados mantêm a regra vigente à época
    — que é o que se defende numa fiscalização.

    O QUE A MIGRATION 022 MUDOU AQUI: nada na escrita, tudo na leitura. A
    coluna continua sendo gravada com `current_date + 5 anos` e continua
    imutável; ela passou a ser o PISO da retenção. O prazo que vale é
    `retencao_efetiva` — greatest(piso, encerramento da relação + 5 anos) —,
    derivado a cada consulta porque o encerramento só se conhece depois, e
    porque a única alternativa seria reescrever esta linha anos depois, que é
    justamente o que OC013 recusa. Ele vem no corpo da resposta, ao lado do
    piso.
    """
    existe = db.execute(text("select 1 from tomador where id = :t"), {"t": str(tomador_id)}).first()
    if existe is None:
        raise HTTPException(status_code=404, detail=f"Tomador {tomador_id} não existe.")

    conteudo = _ler_upload(arquivo)
    nome_arquivo = _nome_saneado(arquivo)
    sha256 = hashlib.sha256(conteudo).hexdigest()
    referencia = referencia_para(str(tomador_id), sha256)

    try:
        storage.guardar(referencia, conteudo, arquivo.content_type or "application/octet-stream")
    except StorageError as exc:
        # 502 e não 500: quem falhou foi a dependência a jusante, e a
        # distinção importa para quem lê o log — 500 aqui mandaria procurar
        # bug no OrgCred por uma indisponibilidade do bucket.
        raise HTTPException(
            status_code=502, detail=f"Falha ao guardar o documento no storage: {exc}"
        ) from exc

    try:
        documento_id = db.execute(
            text("""
            insert into tomador_documento
                (tomador_id, tipo, nome_arquivo, sha256, retencao_ate, usuario_id,
                 storage_objeto)
            values (:t, :tipo, :nome, :sha, current_date + make_interval(years => :anos), :u,
                    :obj)
            returning id
            """),
            {
                "t": str(tomador_id),
                "tipo": tipo,
                "nome": nome_arquivo,
                "sha": sha256,
                "anos": RETENCAO_ANOS,
                "u": str(user.id),
                "obj": referencia,
            },
        ).scalar_one()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Este arquivo já está arquivado para este tomador (mesmo hash).",
        ) from exc

    # Releitura pela view em vez de `returning` com todas as colunas: o prazo
    # efetivo é derivado e não existe como coluna para o INSERT devolver. Sai
    # mais barato do que a alternativa — repetir a derivação aqui —, que
    # criaria a segunda implementação da regra que `_SELECT_DOCUMENTO` existe
    # para evitar.
    row = db.execute(
        text(f"{_SELECT_DOCUMENTO} where documento_id = :d"), {"d": str(documento_id)}
    ).one()
    return _documento_out(row)


def _documento(db: Session, documento_id: UUID) -> Row[Any]:
    """Linha da evidência, ou 404 — os dois endpoints de leitura começam igual."""
    row = db.execute(
        text("""
        select nome_arquivo, sha256, storage_objeto
        from tomador_documento where id = :d
    """),
        {"d": str(documento_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não existe.")
    return row


def _bytes_arquivados(storage: Storage, referencia: Optional[str]) -> bytes:
    """Recupera do storage os bytes de uma evidência, com os erros traduzidos.

    Documento anterior à 019 (`storage_objeto` nulo) devolve 409, e não 404:
    o documento EXISTE no sistema — o que não existe é o arquivo dele, e a
    resposta precisa dizer isso com todas as letras. Um 404 aqui faria o
    operador procurar um id errado por uma falha que é do sistema, não dele.
    """
    if referencia is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta evidência foi arquivada antes da migration 019: existe o hash, "
                "não existe o arquivo. Arquive o documento novamente para que os bytes "
                "passem a ser guardados."
            ),
        )
    try:
        return storage.recuperar(referencia)
    except ObjetoNaoEncontrado as exc:
        # 410 Gone: o banco afirma a existência da evidência e o bucket não a
        # tem. É incidente de retenção legal (Lei 9.613/98, art. 10, III),
        # não pedido malformado — alguém apagou o objeto por fora do sistema,
        # onde o OC013 não alcança.
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except StorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _content_disposition(nome_arquivo: str) -> str:
    """Monta o cabeçalho de download sem que o NOME do arquivo derrube a resposta.

    O nome é o único dado do cliente que sobrevive ao arquivamento, e ele vai
    para dentro de um cabeçalho HTTP. Cabeçalho HTTP é latin-1: o Starlette
    faz `valor.encode("latin-1")` ao montar a resposta, e um nome com
    caractere fora dessa tabela (cirílico, CJK, emoji — nada exótico num
    documento digitalizado que veio do celular de alguém) levantava
    `UnicodeEncodeError` DENTRO da montagem da resposta, virando 500.

    Por que isso era grave, e não cosmético: o arquivamento aceitava o nome
    (201, bytes gravados no bucket) e só o DOWNLOAD explodia. A linha é
    imutável por OC013 — não há UPDATE que conserte o nome — e rearquivar o
    mesmo arquivo bate na unique `(tomador_id, sha256)` da migration 010. Ou
    seja: a evidência ficava permanentemente impossível de apresentar, que é
    exatamente o estado que a migration 019 existe para eliminar. Guardar os
    bytes e não conseguir entregá-los numa fiscalização vale o mesmo que não
    tê-los guardado.

    A saída é o que a RFC 6266 já prevê, e por isso são DOIS campos:

    - `filename="..."` — o fallback, forçado a ASCII (`?` no lugar do que não
      couber) e com `"` e `\\` neutralizados, porque um deles fecharia a
      quoted-string antes da hora e o cabeçalho passaria a dizer outra coisa;
    - `filename*=UTF-8''...` — o nome de verdade, percent-encoded, que é o que
      qualquer navegador atual usa quando os dois estão presentes.

    Não há risco de quebra de resposta por CR/LF aqui: `_nome_saneado` já
    substituiu todo `\\x00-\\x1f`. Este helper cuida do que sobra.
    """
    ascii_fallback = nome_arquivo.encode("ascii", "replace").decode("ascii")
    ascii_fallback = ascii_fallback.replace("\\", "_").replace('"', "_").strip() or "documento"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(nome_arquivo)}"


@router.get("/documentos/{documento_id}/conteudo")
def get_conteudo_documento(
    documento_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    storage: Storage = Depends(storage_de_documentos),
) -> Response:
    """Devolve os bytes arquivados.

    É o outro lado do arquivamento: guardar sem conseguir apresentar teria o
    mesmo valor prático de não guardar. `Content-Disposition: attachment` com
    o nome registrado — a evidência é para ser baixada e anexada a um
    processo, não renderizada dentro da aplicação (o que, com HTML ou SVG
    enviados como "documento", seria script de terceiro rodando na origem do
    OrgCred).
    """
    doc = _documento(db, documento_id)
    conteudo = _bytes_arquivados(storage, doc.storage_objeto)
    return Response(
        content=conteudo,
        media_type="application/octet-stream",
        headers={"Content-Disposition": _content_disposition(doc.nome_arquivo)},
    )


class VerificacaoOut(BaseModel):
    sha256_calculado: str
    sha256_arquivado: str
    confere: bool
    # None quando a evidência é anterior à 019 (não há objeto para conferir).
    storage_integro: Optional[bool]


@router.post("/documentos/{documento_id}/verificar", response_model=VerificacaoOut)
def post_verificar_documento(
    documento_id: UUID,
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    storage: Storage = Depends(storage_de_documentos),
) -> VerificacaoOut:
    """Confere se um arquivo apresentado é bit a bit o que foi arquivado.

    DUAS PERGUNTAS DIFERENTES, e a segunda só passou a ser respondível com o
    storage:

    - `confere`: o arquivo que você acabou de mandar bate com o hash gravado
      no banco? É a conferência que dá sentido a guardar o hash.
    - `storage_integro`: os bytes guardados no bucket ainda batem com esse
      mesmo hash? Detecta adulteração DO ARQUIVO GUARDADO — o único ataque
      que o trigger OC013 não alcança, porque acontece do lado do storage,
      onde o Postgres não tem jurisdição. Vale `None` para evidência anterior
      à 019, que não tem objeto para conferir.

    As duas são calculadas contra o hash gravado, nunca uma contra a outra:
    se alguém trocar o objeto no bucket, `confere` continua respondendo sobre
    o documento verdadeiro e `storage_integro` acusa a troca. Comparar o
    upload direto com o objeto do bucket deixaria os dois errados juntos e
    concordando.
    """
    doc = _documento(db, documento_id)

    conteudo = _ler_upload(arquivo)
    calculado = hashlib.sha256(conteudo).hexdigest()

    integro: Optional[bool] = None
    if doc.storage_objeto is not None:
        guardado = _bytes_arquivados(storage, doc.storage_objeto)
        integro = hashlib.sha256(guardado).hexdigest() == doc.sha256

    return VerificacaoOut(
        sha256_calculado=calculado,
        sha256_arquivado=doc.sha256,
        confere=calculado == doc.sha256,
        storage_integro=integro,
    )


class RetencaoOut(BaseModel):
    documento_id: UUID
    tomador_id: UUID
    nome_arquivo: str
    arquivado_em: datetime
    referencia: date
    existia_na_referencia: bool
    retencao_piso: date
    relacao_em_curso: bool
    encerramento_relacao: Optional[date]
    # Nulo = indeterminada: a relação de negócio ainda não tinha encerrado na
    # data de referência.
    retencao_efetiva: Optional[date]
    podia_ser_apagado: bool


@router.get("/documentos/{documento_id}/retencao", response_model=RetencaoOut)
def get_retencao_documento(
    documento_id: UUID,
    em: Optional[date] = Query(
        default=None,
        description="Data de referência da consulta. Ausente = hoje.",
    ),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> RetencaoOut:
    """Responde "este documento podia ter sido apagado naquela data?".

    É a pergunta que uma fiscalização faz, e é o motivo de a migration 022 ter
    escolhido DERIVAR o prazo em vez de reescrever a coluna quando a relação
    encerra. Uma coluna sobrescrita só sabe dizer o valor de hoje: perguntar
    "e em março de 2029?" não teria resposta, porque não há versionamento de
    `retencao_ate` — e não vai haver, já que OC013 recusa UPDATE.

    A derivação responde porque tudo de que ela depende é imutável: o piso
    (OC013), a existência e a data de nascimento da operação, e os eventos de
    transição de status (`operacao_evento`, append-only por OC010). A conta é
    a MESMA função que o trigger consulta para decidir o DELETE de hoje —
    `fn_retencao_efetiva_em`, com a data de referência trocada —, então não há
    como a resposta da auditoria discordar do comportamento do banco.

    `existia_na_referencia` falso quando a data pedida é anterior ao
    arquivamento: aí `podia_ser_apagado` é falso por uma razão diferente de
    todas as outras — não havia o que apagar. Devolver `true` ali ("não estava
    protegido") seria responder à pergunta errada.
    """
    # A data de referência sai de um CTE em vez de repetir o `coalesce` em
    # cada chamada — e o cast é `cast(:em as date)`, não `:em::date`: o
    # `text()` do SQLAlchemy não reconhece o bind quando ele é seguido de
    # `::`, e o parâmetro chegava literal ao Postgres.
    row = db.execute(
        text("""
        with ref as (select coalesce(cast(:em as date), current_date) as em)
        select d.tomador_id, d.nome_arquivo, d.arquivado_em, d.retencao_ate,
               ref.em as referencia,
               fn_relacao_em_curso(d.tomador_id, ref.em) as relacao_em_curso,
               fn_encerramento_relacao(d.tomador_id, ref.em) as encerramento_relacao,
               nullif(
                   fn_retencao_efetiva_em(d.tomador_id, d.retencao_ate, ref.em),
                   'infinity'::date
               ) as retencao_efetiva
        from tomador_documento d, ref
        where d.id = :d
    """),
        {"d": str(documento_id), "em": em},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Documento {documento_id} não existe.")

    existia = row.arquivado_em.date() <= row.referencia
    # `retencao_efetiva` nula é retenção indeterminada, ou seja, protegido —
    # não o contrário. O `and` com `existia` vem depois porque a proteção só
    # faz sentido sobre documento que já existia.
    vencida = row.retencao_efetiva is not None and row.retencao_efetiva < row.referencia

    return RetencaoOut(
        documento_id=documento_id,
        tomador_id=row.tomador_id,
        nome_arquivo=row.nome_arquivo,
        arquivado_em=row.arquivado_em,
        referencia=row.referencia,
        existia_na_referencia=existia,
        retencao_piso=row.retencao_ate,
        relacao_em_curso=row.relacao_em_curso,
        encerramento_relacao=row.encerramento_relacao,
        retencao_efetiva=row.retencao_efetiva,
        podia_ser_apagado=existia and vencida,
    )


class PendenciaIdentificacaoOut(BaseModel):
    tomador_id: UUID
    cnpj: str
    razao_social: str
    capital_exposto: Decimal


@router.get("/identificacao/pendencias", response_model=List[PendenciaIdentificacaoOut])
def get_pendencias_identificacao(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[PendenciaIdentificacaoOut]:
    """Tomadores sem nenhuma evidência arquivada, com o capital exposto.

    Ordenado por exposição: é essa a lista que embasa a decisão de negócio
    sobre exigir identificação antes da ativação.
    """
    rows = db.execute(
        text("""
        select tomador_id, cnpj, razao_social, capital_exposto
        from v_tomadores_sem_identificacao
        order by capital_exposto desc, razao_social
    """)
    ).all()
    return [
        PendenciaIdentificacaoOut(
            tomador_id=r.tomador_id,
            cnpj=r.cnpj,
            razao_social=r.razao_social,
            capital_exposto=r.capital_exposto,
        )
        for r in rows
    ]


# ---------------------------------------------------------------------
# Detecção interna de atipicidade
# ---------------------------------------------------------------------


class OcorrenciaOut(BaseModel):
    id: UUID
    regra: str
    severidade: str
    tomador_id: Optional[UUID]
    tomador_razao_social: Optional[str]
    operacao_id: Optional[UUID]
    detalhe: str
    comunicado_em: Optional[datetime]
    created_at: datetime


@router.get("/atipicidades", response_model=List[OcorrenciaOut])
def get_atipicidades(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[OcorrenciaOut]:
    """Ocorrências detectadas, mais graves e mais recentes primeiro."""
    rows = db.execute(
        text("""
        select o.id, o.regra, o.severidade, o.tomador_id, t.razao_social as tomador_razao_social,
               o.operacao_id, o.detalhe, o.comunicado_em, o.created_at
        from ocorrencia_atipicidade o
        left join tomador t on t.id = o.tomador_id
        order by case o.severidade when 'alta' then 0 when 'media' then 1 else 2 end,
                 o.created_at desc
    """)
    ).all()
    return [
        OcorrenciaOut(
            id=r.id,
            regra=r.regra,
            severidade=r.severidade,
            tomador_id=r.tomador_id,
            tomador_razao_social=r.tomador_razao_social,
            operacao_id=r.operacao_id,
            detalhe=r.detalhe,
            comunicado_em=r.comunicado_em,
            created_at=r.created_at,
        )
        for r in rows
    ]


class DetectarIn(BaseModel):
    limiar: Decimal = Field(default=Decimal("10000"), gt=0)
    janela_dias: int = Field(default=30, ge=1, le=365)


class DetectarOut(BaseModel):
    novas_ocorrencias: int


@router.post("/atipicidades/detectar", response_model=DetectarOut)
def post_detectar(
    body: DetectarIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_admin_user),
) -> DetectarOut:
    """
    Roda a varredura de atipicidade sobre os dados existentes.

    Idempotente: a constraint `ocorrencia_unica` faz uma segunda passada no
    mesmo dia não duplicar nada. Sem isso o painel viraria ruído e o
    analista pararia de olhar — que é o pior resultado possível para um
    controle de PLD.
    """
    total = db.execute(
        text("select fn_detectar_atipicidades(:limiar, :janela)"),
        {"limiar": body.limiar, "janela": body.janela_dias},
    ).scalar_one()
    db.commit()
    return DetectarOut(novas_ocorrencias=int(total))
