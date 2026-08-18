"""Router: trilha de auditoria do capital_ledger (hash-chain, migration 005) e
estado das rotinas periódicas (trilha `execucao_rotina`, migration 025).

POR QUE O ESTADO DAS ROTINAS MORA AQUI, e não num router próprio. Este é o
router em que o sistema responde SOBRE SI MESMO: `GET /auditoria` não fala de
uma operação nem de um tomador — fala da integridade da própria trilha de
capital, e o dashboard já o consome exatamente para isso (o banner "cadeia de
auditoria quebrada" nasce dessa resposta). "As minhas rotinas rodaram?" é a
mesma classe de pergunta, feita pelo mesmo painel, e a resposta serve ao mesmo
fim: decidir se dá para confiar nos números da tela. Um router novo separaria
duas metades da mesma auto-inspeção — e o painel teria de perguntar em dois
lugares para saber se está olhando para um sistema saudável.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db import get_db
from app.models import Usuario
from app.rotinas import LIMITE_ATRASO_HORAS, RESULTADO_FALHA, ROTINAS_CONHECIDAS


router = APIRouter(prefix="/auditoria", tags=["auditoria"])

# O ledger é append-only e cresce para sempre: uma linha por ativação, baixa,
# novação e movimento de capital, sem nenhum expurgo possível (a migration 005
# bloqueia UPDATE/DELETE e a 016 bloqueia TRUNCATE — é assim de propósito, é a
# prova documental do teto do Art. 5º). Sem página, este endpoint devolvia a
# tabela inteira a cada abertura da tela de auditoria e a cada polling do
# dashboard; num ano de operação isso é um JSON de dezenas de MB montado
# inteiro em memória, no servidor e no navegador.
#
# 100 é o padrão porque é o que o painel consegue exibir e usar: a tela de
# auditoria lista eventos recentes e o card de evolução de saldo plota os
# últimos pontos. 500 é o teto porque acima disso o custo de serialização já
# supera o de uma segunda requisição.
TAMANHO_PAGINA_PADRAO = 100
TAMANHO_PAGINA_MAX = 500

# Teto do NÚMERO da página, e não só do tamanho dela. `pagina` entrava com
# piso (`ge=1`, para não virar OFFSET negativo) e sem teto: como o Pydantic
# aceita inteiro de precisão arbitrária, `?pagina=10000000000000000000` virava
# um OFFSET maior que o bigint do Postgres, o driver estourava e o endpoint
# respondia 500 — um 500 que qualquer usuário autenticado dispara de propósito
# só mudando a query string, poluindo log e métrica de erro. Com o teto o
# mesmo pedido vira 422, que é o que ele sempre foi: parâmetro inválido.
#
# 1.000.000 de páginas × 500 eventos = 500 milhões de eventos endereçáveis,
# ordens de grandeza acima de qualquer ledger real desta ESC, e o maior
# deslocamento possível (5×10⁸) cabe folgado no bigint.
PAGINA_MAX = 1_000_000


class LedgerEventoOut(BaseModel):
    id: UUID
    evento_tipo: str
    valor: Decimal
    operacao_id: Optional[UUID]
    saldo_disponivel_pos: Decimal
    usuario_nome: Optional[str]
    created_at: datetime
    prev_hash: Optional[str]
    current_hash: Optional[str]


class QuebraCadeia(BaseModel):
    id: UUID
    motivo: str


class AuditoriaOut(BaseModel):
    integro: bool
    quebras: List[QuebraCadeia]
    eventos: List[LedgerEventoOut]
    # Campos ADITIVOS (passo 14): `integro`, `quebras` e `eventos` continuam
    # com o mesmo nome e o mesmo formato, então o painel atual segue lendo o
    # que sempre leu. O que mudou é que `eventos` agora traz uma página, e não
    # a tabela toda — daí `total` existir: sem ele o cliente não teria como
    # distinguir "são só estes" de "há mais lá atrás".
    total: int
    pagina: int
    tamanho_pagina: int


@router.get("", response_model=AuditoriaOut)
def get_auditoria(
    pagina: int = Query(
        1,
        ge=1,
        le=PAGINA_MAX,
        description="Página (1-based), ordenada do mais recente",
    ),
    tamanho: int = Query(
        TAMANHO_PAGINA_PADRAO,
        ge=1,
        le=TAMANHO_PAGINA_MAX,
        description=f"Eventos por página (máximo {TAMANHO_PAGINA_MAX})",
    ),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AuditoriaOut:
    """
    Trilha de auditoria em duas camadas: eventos legíveis (com nome do
    usuário quando disponível) e o resultado da verificação da cadeia de
    hash (`fn_verificar_cadeia_ledger()`, migration 005) — 0 quebras
    significa cadeia íntegra.

    `eventos` é paginado; `quebras` NÃO é, de propósito. A verificação da
    cadeia é uma afirmação sobre o ledger inteiro: paginar as quebras faria
    `integro` significar "esta página está íntegra", que é exatamente a
    mentira que a cadeia de hash existe para impedir. Na operação normal a
    lista vem vazia; se vier grande, o tamanho dela é a notícia.
    """
    quebras_rows = db.execute(text("select id, motivo from fn_verificar_cadeia_ledger()")).all()
    quebras = [QuebraCadeia(id=row.id, motivo=row.motivo) for row in quebras_rows]

    total = db.execute(text("select count(*) from capital_ledger")).scalar_one()

    eventos_rows = db.execute(
        text("""
        select
            l.id, l.evento_tipo, l.valor, l.operacao_id, l.saldo_disponivel_pos,
            u.nome as usuario_nome, l.created_at, l.prev_hash, l.current_hash
        from capital_ledger l
        left join usuario u on u.id::text = l.usuario_id
        order by l.created_at desc, l.id desc
        limit :limite offset :deslocamento
    """),
        {"limite": tamanho, "deslocamento": (pagina - 1) * tamanho},
    ).all()
    eventos = [
        LedgerEventoOut(
            id=row.id,
            evento_tipo=row.evento_tipo,
            valor=row.valor,
            operacao_id=row.operacao_id,
            saldo_disponivel_pos=row.saldo_disponivel_pos,
            usuario_nome=row.usuario_nome,
            created_at=row.created_at,
            prev_hash=row.prev_hash,
            current_hash=row.current_hash,
        )
        for row in eventos_rows
    ]

    return AuditoriaOut(
        integro=len(quebras) == 0,
        quebras=quebras,
        eventos=eventos,
        total=int(total),
        pagina=pagina,
        tamanho_pagina=tamanho,
    )


# ---------------------------------------------------------------------
# Estado das rotinas periódicas (migration 025)
# ---------------------------------------------------------------------


class EstadoRotinaOut(BaseModel):
    rotina: str
    # A ÚLTIMA VEZ QUE O CRON OLHOU PARA ESTA ROTINA — inclui as execuções
    # 'dispensada'. Existe por causa do restore-test, e é o campo que separa
    # "o cron parou" de "o cron passou por aqui e não era a vez": sem ele, uma
    # rotina mensal em dia e um serviço de cron morto têm a mesma aparência.
    ultima_tentativa: Optional[datetime]
    # A última execução que FEZ o trabalho (sucesso ou falha). É esta que o
    # operador quer ver, e é dela que saem `resultado`, `erro` e `detalhe`.
    ultima_execucao: Optional[datetime]
    # Derivado (registrada_em - duracao_s), não uma coluna — ver o cabeçalho da
    # migration 025: início é fato que só a aplicação conhece, e coluna escrita
    # pela aplicação seria o carimbo ditado por quem escreve.
    iniciada_em: Optional[datetime]
    duracao_s: Optional[Decimal]
    resultado: Optional[str]
    erro: Optional[str]
    detalhe: Dict[str, Any]
    ultimo_sucesso: Optional[datetime]
    # O NÚMERO QUE IMPORTA. Nulo = nunca houve sucesso, que é o caso mais grave
    # e não o mais brando: não há distância a medir porque não há marco.
    horas_desde_ultimo_sucesso: Optional[float]
    # Nulo só para rotina que a trilha conhece e o executor não — ver o
    # endpoint. Rotina sem limiar declarado nunca é dada como atrasada.
    limite_horas: Optional[int]
    atrasada: bool
    falhou: bool
    nunca_executou: bool


class EstadoRotinasOut(BaseModel):
    verificado_em: datetime
    # Falso se QUALQUER rotina conhecida está atrasada ou falhou na última
    # execução. É o único campo que o banner do dashboard precisa ler para
    # decidir se aparece.
    saudavel: bool
    rotinas: List[EstadoRotinaOut]


# A leitura é uma consulta só, com três recortes da mesma trilha. Separá-los é
# o ponto, não economia de linhas:
#
#   `tentativa` — TUDO, inclusive 'dispensada'. Prova que o cron esteve aqui.
#   `ultima`    — a execução efetiva mais recente. De onde saem resultado e erro.
#   `sucesso`   — o marco a partir do qual o relógio de atraso corre.
#
# O FROM é dirigido por `tentativa` porque uma rotina pode ter SÓ linhas
# 'dispensada' (restore-test cuja competência já estava marcada no volume
# quando o banco era novo) e precisa aparecer assim mesmo, com o relógio
# correndo desde nunca.
#
# `clock_timestamp()` e não `now()` na conta das horas: é o mesmo relógio com
# que a migration 025 grava. Usar dois relógios diferentes nas duas pontas do
# mesmo cálculo é como se introduz uma diferença que ninguém explica depois.
_SELECT_ESTADO_ROTINAS = """
with tentativa as (
    select rotina, max(registrada_em) as em
      from execucao_rotina
     group by rotina
),
efetivas as (
    select * from execucao_rotina where resultado <> 'dispensada'
),
ultima as (
    select distinct on (rotina)
           rotina, registrada_em, resultado, erro, duracao_s, detalhe
      from efetivas
     order by rotina, registrada_em desc
),
sucesso as (
    select rotina, max(registrada_em) as em
      from efetivas
     where resultado = 'sucesso'
     group by rotina
)
select t.rotina,
       t.em            as ultima_tentativa,
       u.registrada_em as ultima_execucao,
       u.registrada_em - make_interval(secs => cast(u.duracao_s as double precision))
                       as iniciada_em,
       u.duracao_s,
       u.resultado,
       u.erro,
       u.detalhe,
       s.em            as ultimo_sucesso,
       extract(epoch from (clock_timestamp() - s.em)) / 3600.0
                       as horas_desde_ultimo_sucesso
  from tentativa t
  left join ultima  u on u.rotina = t.rotina
  left join sucesso s on s.rotina = t.rotina
"""


@router.get("/rotinas", response_model=EstadoRotinasOut)
def get_estado_rotinas(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> EstadoRotinasOut:
    """Responde "as rotinas periódicas estão rodando?" — com HÁ QUANTO TEMPO.

    O TEMPO É O CAMPO, e não a falha. Uma rotina que nunca falhou mas parou de
    rodar há nove dias é o caso perigoso justamente porque não há falha para
    ver: nenhuma execução vermelha existe, nenhum painel de execuções mostra a
    execução que não houve, e a régua de aging passa nove dias declarando
    inadimplência com atraso enquanto tudo parece bem.
    `horas_desde_ultimo_sucesso` é a única leitura que enxerga esse estado,
    porque ela cresce sozinha, sem depender de nada acontecer.

    NUNCA EXECUTOU CONTA COMO ATRASADA — fail-closed, pelo mesmo critério da
    migration 023 ("sem evento na trilha = detecta assim mesmo"). O contrário
    seria o pior default possível aqui: um serviço de cron que jamais foi
    implantado ficaria verde para sempre, que é literalmente o estado que esta
    trilha existe para acabar. O preço é conhecido e aceito: nas primeiras
    horas depois de a migration 025 subir, a tabela está vazia e o painel avisa
    até a primeira execução do cron. O aviso está certo — o sistema realmente
    não tem evidência nenhuma.

    O ATRASO É MEDIDO DO ÚLTIMO SUCESSO, não da última tentativa. Uma rotina
    que falha todo dia tem tentativa recente e não fez o trabalho nenhuma vez;
    medir dali diria que ela está em dia. Ela aparece nas duas leituras: por
    `falhou` (a última execução deu errado) e por `atrasada`, assim que o
    último sucesso envelhecer além do limiar.

    OS LIMIARES SÃO DO EXECUTOR (`app.rotinas.LIMITE_ATRASO_HORAS`), não deste
    módulo. Quem muda a agenda do cron muda o arquivo que define as rotinas; se
    a régua de pontualidade morasse aqui, a tela continuaria cobrando uma
    periodicidade que ninguém mais pratica e o número seguiria bonito.
    """
    linhas = {row.rotina: row for row in db.execute(text(_SELECT_ESTADO_ROTINAS)).all()}

    # A união, e não só ROTINAS_CONHECIDAS: uma rotina conhecida SEM nenhuma
    # linha precisa aparecer (é o caso "nunca executou", o mais importante de
    # todos), e um nome que está na trilha e não no executor também — a
    # migration 025 recusa de propósito um CHECK de domínio na coluna `rotina`,
    # e a contrapartida de aceitar qualquer nome é mostrá-lo. Sem limiar
    # declarado ele nunca é dado como atrasado: seria inventar uma
    # periodicidade que ninguém prometeu.
    nomes = list(ROTINAS_CONHECIDAS) + sorted(set(linhas) - set(ROTINAS_CONHECIDAS))

    rotinas: List[EstadoRotinaOut] = []
    for nome in nomes:
        linha = linhas.get(nome)
        limite = LIMITE_ATRASO_HORAS.get(nome)
        horas: Optional[float] = None
        if linha is not None and linha.horas_desde_ultimo_sucesso is not None:
            horas = float(linha.horas_desde_ultimo_sucesso)
        atrasada = limite is not None and (horas is None or horas > limite)

        rotinas.append(
            EstadoRotinaOut(
                rotina=nome,
                ultima_tentativa=None if linha is None else linha.ultima_tentativa,
                ultima_execucao=None if linha is None else linha.ultima_execucao,
                iniciada_em=None if linha is None else linha.iniciada_em,
                duracao_s=None if linha is None else linha.duracao_s,
                resultado=None if linha is None else linha.resultado,
                erro=None if linha is None else linha.erro,
                detalhe={} if linha is None or linha.detalhe is None else dict(linha.detalhe),
                ultimo_sucesso=None if linha is None else linha.ultimo_sucesso,
                horas_desde_ultimo_sucesso=horas,
                limite_horas=limite,
                atrasada=atrasada,
                falhou=linha is not None and linha.resultado == RESULTADO_FALHA,
                nunca_executou=linha is None or linha.ultima_execucao is None,
            )
        )

    return EstadoRotinasOut(
        # Do BANCO, não do relógio do processo web: é o mesmo relógio contra o
        # qual as horas acima foram medidas. Dois relógios produziriam uma
        # resposta em que o "agora" do cabeçalho não fecha com a aritmética das
        # linhas — e alguém gastaria uma tarde para descobrir por quê.
        verificado_em=db.execute(text("select clock_timestamp()")).scalar_one(),
        saudavel=not any(r.atrasada or r.falhou for r in rotinas),
        rotinas=rotinas,
    )
