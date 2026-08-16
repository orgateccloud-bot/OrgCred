"""
Semeia um cenário de demonstração no banco de DESENVOLVIMENTO.

Existe para que alguém abra a aplicação e veja o sistema funcionando em vez de
seis telas vazias — e, principalmente, para que os gates legais sejam
exercitados de verdade ao navegar.

PRINCÍPIO: o cenário é montado pelos CAMINHOS REAIS. `ativar_operacao` de
`app.capital_engine`, `fn_baixar_parcela`, `fn_processar_aging`, registro
aberto em 'pendente' e confirmado depois. Nada de escrever estado final direto
no banco.

Isso não é preciosismo. Um seed que dá `update operacao_credito set
status='ativa'` contorna o teto do Art. 5º (OC001), o gate geográfico (OC002),
o de registro confirmado (OC004) e o de identificação (OC019) — e produz uma
tela bonita que prova exatamente nada. Pior: esconde justamente as regressões
que esses gates existem para pegar, porque o dado semeado nunca passou por
eles. Quando este script quebra depois de uma migration nova, ele está fazendo
o trabalho dele.

USO:
    docker compose up -d postgres api
    python scripts/semear_dev.py

    python scripts/semear_dev.py --limpar   # apaga o cenário antes de semear

O script é idempotente: rodar de novo não duplica nada.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.capital_engine import ativar_operacao, processar_aging  # noqa: E402


# CNPJs do cenário. O prefixo é o que o `--limpar` usa para achar o que apagar,
# e é o que impede o script de encostar em dado que não foi ele que criou.
PREFIXO_DEMO = "1122233"
EMAIL_DEMO = "admin@orgcred.local"

TOMADORES = [
    # cnpj, razão social, porte, município, uf, autorizado, identificação arquivada
    ("11222330000181", "Padaria do Bairro ME", "ME", "Formoso", "GO", True, True),
    ("11222331000172", "Mercearia Central EPP", "EPP", "Formoso", "GO", True, True),
    # Fora da área de atuação: existe para o gate geográfico (OC002) ter o que
    # recusar quando alguém tentar ativar pela tela.
    ("11222332000163", "Oficina Norte ME", "ME", "Campinas", "SP", False, True),
    # Sem identificação arquivada: existe para o gate OC019 ter o que recusar,
    # e para a tela de Compliance ter uma pendência de verdade.
    ("11222333000154", "Transportes Sul ME", "ME", "Formoso", "GO", True, False),
]


def _url_do_banco() -> str:
    return os.environ.get(
        "ORGCRED_DATABASE_URL",
        "postgresql+psycopg://orgcred:orgcred_dev_password@127.0.0.1:5433/orgcred_dev",
    )


def _recusar_fora_de_desenvolvimento(url: str) -> None:
    """Três checagens independentes, porque uma só falha aberto.

    A URL de produção aponta para `postgres.railway.internal`, que não casa com
    nenhum host local — mas depender só disso deixaria o script rodar contra
    qualquer banco remoto que alguém apontasse por engano. E `ORGCRED_ENVIRONMENT`
    sozinha não basta porque ela pode simplesmente não estar setada no shell de
    quem executa.
    """
    if os.environ.get("ORGCRED_ENVIRONMENT", "development").strip().lower() == "production":
        sys.exit("RECUSADO: ORGCRED_ENVIRONMENT=production. Este script é só de desenvolvimento.")

    hospedeiro_local = any(h in url for h in ("127.0.0.1", "localhost", "[::1]", "@postgres:"))
    if not hospedeiro_local:
        sys.exit(
            "RECUSADO: a URL do banco não aponta para um host local.\n"
            f"  {url}\n"
            "Este script cria dados fictícios e não deve tocar em banco remoto."
        )

    if "railway" in url or "supabase" in url:
        sys.exit(f"RECUSADO: a URL menciona um provedor gerenciado:\n  {url}")


def _limpar(db: Session) -> None:
    """Apaga só o que este script cria, achando pelo prefixo de CNPJ.

    As trilhas append-only exigem desligar as guardas com nome e sobrenome —
    ter que fazer isso é a prova de que, pela aplicação, não há caminho para
    destruí-las.
    """
    ops = (
        db.execute(
            text("""
        select id from operacao_credito
         where tomador_id in (select id from tomador where cnpj like :p)
        """),
            {"p": f"{PREFIXO_DEMO}%"},
        )
        .scalars()
        .all()
    )

    # A lista foi levantada consultando `pg_trigger` por gatilhos que bloqueiam
    # DELETE, e não escrita de memória — são OITO, em oito tabelas diferentes.
    # Que seja preciso desligar oito guardas nominalmente para apagar um
    # cenário de brinquedo é a medida de quanta destruição o sistema recusa
    # pelos caminhos normais. Se uma migration futura acrescentar a nona, este
    # script quebra com o nome dela na mensagem — e é assim que se descobre.
    GUARDAS = [
        ("parcela", "trg_parcela_imutavel"),  # OC009: agenda emitida não muda
        ("contrato_emprestimo", "trg_contrato_imutavel"),  # OC017
        ("registro_operacao", "trg_registro_transicao"),  # OC018
        ("operacao_evento", "trg_operacao_evento_append_only"),  # OC010
        ("capital_ledger", "trg_bloquear_delete_ledger"),  # OC007
        ("ocorrencia_atipicidade", "trg_ocorrencia_append_only"),  # OC014
        ("tomador_documento", "trg_documento_retencao"),  # OC013
        # OC012: extrato é fato de fora — não se edita nem se apaga.
        ("movimento_bancario", "trg_movimento_imutavel"),
    ]
    for tabela, gatilho in GUARDAS:
        db.execute(text(f"alter table {tabela} disable trigger {gatilho}"))

    # A ORDEM ABAIXO VEM DO GRAFO DE CHAVES ESTRANGEIRAS, e foi lida do banco,
    # não deduzida: NENHUMA delas tem `on delete cascade` — são todas
    # `NO ACTION`. Apagar o tomador esperando que o resto caia junto falha com
    # violação de FK, e falha DEPOIS de as guardas terem sido desligadas.
    #
    # Estritamente de baixo para cima:
    #   parcela          -> filha de operacao_credito E de movimento_bancario
    #   contrato/registro/evento/ledger/ocorrencia -> filhas de operacao_credito
    #   operacao_credito -> referencia a SI MESMA (novação: substituta aponta
    #                       para a original), por isso sai num único DELETE
    #                       sobre o conjunto inteiro
    #   documento/ocorrencia -> filhas de tomador
    #   movimento_bancario   -> só depois que nenhuma parcela o referencia
    ids = [str(o) for o in ops]
    if ids:
        for tabela in (
            "parcela",
            "contrato_emprestimo",
            "registro_operacao",
            "operacao_evento",
            "capital_ledger",
            "ocorrencia_atipicidade",
        ):
            db.execute(text(f"delete from {tabela} where operacao_id = any(:i)"), {"i": ids})
        db.execute(text("delete from operacao_credito where id = any(:i)"), {"i": ids})

    for tabela in ("tomador_documento", "ocorrencia_atipicidade"):
        db.execute(
            text(f"""
            delete from {tabela}
             where tomador_id in (select id from tomador where cnpj like :p)
            """),
            {"p": f"{PREFIXO_DEMO}%"},
        )
    db.execute(text("delete from tomador where cnpj like :p"), {"p": f"{PREFIXO_DEMO}%"})
    db.execute(text("delete from movimento_bancario where documento like 'FITID-DEMO-%'"))

    for tabela, gatilho in GUARDAS:
        db.execute(text(f"alter table {tabela} enable trigger {gatilho}"))
    db.commit()
    print(f"limpo: {len(ops)} operação(ões) e os tomadores do prefixo {PREFIXO_DEMO}")


def _usuario_demo(db: Session) -> str:
    """O usuário do painel. Sem linha em `usuario`, um token válido é recusado
    com PERMISSAO_NEGADA — o papel vem do banco a cada request, nunca do JWT."""
    existente = db.execute(
        text("select id::text from usuario where email = :e"), {"e": EMAIL_DEMO}
    ).scalar_one_or_none()
    if existente:
        return str(existente)
    uid = uuid.uuid4()
    db.execute(
        text("""
        insert into usuario (id, email, nome, papel, ativo)
        values (:i, :e, 'Admin Local', 'admin', true)
        """),
        {"i": str(uid), "e": EMAIL_DEMO},
    )
    db.commit()
    return str(uid)


def _confirmar_registro(db: Session, op_id: Any, entidade: str = "CRDC") -> None:
    """Abre em 'pendente' e confirma — DOIS comandos, como os endpoints emitem.

    Desde a migration 021 a máquina de estados guarda também o INSERT: nascer
    já 'confirmado' é recusado com OC018.
    """
    rid = db.execute(
        text("insert into registro_operacao (operacao_id, entidade) values (:o, :e) returning id"),
        {"o": str(op_id), "e": entidade},
    ).scalar_one()
    db.execute(
        text("""
        update registro_operacao
           set status = 'confirmado', protocolo = :p, confirmado_em = clock_timestamp()
         where id = :id
        """),
        {"id": str(rid), "p": f"{entidade.upper()[:4]}-{str(op_id)[:8].upper()}"},
    )
    db.commit()


def _criar_proposta(
    db: Session,
    tomador_id: Any,
    valor: str,
    parcelas: int,
    taxa: str = "2.5",
    sistema: str = "PRICE",
) -> Any:
    op = db.execute(
        text("""
        insert into operacao_credito
            (tomador_id, tipo, valor_principal, taxa_juros_mensal,
             sistema_amortizacao, numero_parcelas, status)
        values (:t, 'emprestimo', :v, :j, :s, :n, 'proposta')
        returning id
        """),
        {
            "t": str(tomador_id),
            "v": Decimal(valor),
            "j": Decimal(taxa),
            "s": sistema,
            "n": parcelas,
        },
    ).scalar_one()
    db.commit()
    return op


def _promover_a_registrada(db: Session, op_id: Any) -> None:
    db.execute(
        text("update operacao_credito set status = 'registrada' where id = :i"), {"i": str(op_id)}
    )
    db.commit()


def semear(db: Session) -> None:
    usuario_id = _usuario_demo(db)

    if db.execute(text("select capital_atual from v_capital_atual")).scalar_one() == 0:
        db.execute(
            text(
                "insert into esc_capital_social (valor, tipo_evento) "
                "values (500000, 'constituicao')"
            )
        )
        db.commit()

    ids: dict[str, Any] = {}
    for cnpj, razao, porte, municipio, uf, autorizado, identificado in TOMADORES:
        existente = db.execute(
            text("select id from tomador where cnpj = :c"), {"c": cnpj}
        ).scalar_one_or_none()
        if existente is not None:
            ids[razao] = existente
            continue
        tid = db.execute(
            text("""
            insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
            values (:c, :r, :p, :m, :u, :a) returning id
            """),
            {"c": cnpj, "r": razao, "p": porte, "m": municipio, "u": uf, "a": autorizado},
        ).scalar_one()
        db.commit()
        ids[razao] = tid
        if identificado:
            db.execute(
                text("""
                insert into tomador_documento (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
                values (:t, 'contrato_social', :n, encode(digest(:s, 'sha256'), 'hex'),
                        current_date + interval '5 years')
                """),
                {"t": str(tid), "n": f"contrato-social-{cnpj[:8]}.pdf", "s": f"demo:{cnpj}"},
            )
            db.commit()

    if db.execute(text("select count(*) from operacao_credito")).scalar_one() > 0:
        print("já há operações no banco — nada a semear (use --limpar para recomeçar)")
        return

    padaria = ids["Padaria do Bairro ME"]
    mercearia = ids["Mercearia Central EPP"]
    oficina = ids["Oficina Norte ME"]
    transportes = ids["Transportes Sul ME"]

    # Proposta crua: o começo do funil.
    _criar_proposta(db, padaria, "12000", 12)

    # Registrada e confirmada: pronta para o operador ativar pela tela e ver o
    # capital sair do disponível.
    op_pronta = _criar_proposta(db, mercearia, "30000", 18, taxa="2.2", sistema="SAC")
    _promover_a_registrada(db, op_pronta)
    _confirmar_registro(db, op_pronta, "SPC Grafeno")

    # Ativa, com agenda emitida pelo próprio banco na transição.
    op_ativa = _criar_proposta(db, padaria, "60000", 24)
    _promover_a_registrada(db, op_ativa)
    _confirmar_registro(db, op_ativa)
    ativar_operacao(db, op_ativa, usuario_id=usuario_id)

    # Ativa e vencida: a régua declara a inadimplência abaixo.
    op_atrasada = _criar_proposta(db, mercearia, "18000", 6)
    _promover_a_registrada(db, op_atrasada)
    _confirmar_registro(db, op_atrasada)
    ativar_operacao(db, op_atrasada, usuario_id=usuario_id)
    # Vencimento é imutável (OC009): fabricar atraso exige desligar a guarda,
    # o que é impossível pela aplicação — e é essa a garantia.
    db.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    db.execute(
        text("""
        update parcela set vencimento = current_date - cast(:d as int)
         where operacao_id = :i and numero <= 2
        """),
        {"d": 100, "i": str(op_atrasada)},
    )
    db.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db.commit()

    # Propostas que os gates devem recusar quando alguém tentar ativar:
    # a da oficina por município (OC002), a da transportadora por falta de
    # identificação arquivada (OC019).
    _criar_proposta(db, oficina, "8000", 6)
    _criar_proposta(db, transportes, "9000", 6)

    # Baixa real da primeira parcela, com lastro bancário.
    parcela = db.execute(
        text("select id, valor_total from parcela where operacao_id = :i and numero = 1"),
        {"i": str(op_ativa)},
    ).one()
    movimento = db.execute(
        text("""
        insert into movimento_bancario (data_movimento, valor, documento, descricao, origem)
        values (current_date, :v, 'FITID-DEMO-0001', 'TED recebida — parcela 1', 'manual')
        returning id
        """),
        {"v": parcela.valor_total},
    ).scalar_one()
    db.commit()
    db.execute(text("select set_config('app.user_id', :u, true)"), {"u": usuario_id})
    db.execute(
        text("select fn_baixar_parcela(:p, :m)"), {"p": str(parcela.id), "m": str(movimento)}
    )
    db.commit()

    # Movimento sem destino: dá o que conciliar na tela de Cobrança.
    db.execute(
        text("""
        insert into movimento_bancario (data_movimento, valor, documento, descricao, origem)
        values (current_date, 2500.00, 'FITID-DEMO-0002', 'TED recebida — a conciliar', 'manual')
        """)
    )
    db.commit()

    declaradas = processar_aging(db, limite_dias=90)
    print(f"régua de aging: {declaradas} operação(ões) declarada(s) inadimplente(s)")


def relatorio(db: Session) -> None:
    print("\noperações por status:")
    for status, quantidade, soma in db.execute(
        text("""
        select status, count(*), sum(valor_principal)
          from operacao_credito group by status order by status
        """)
    ).all():
        print(f"  {status:18} {quantidade:2}   R$ {soma:>12,.2f}")

    linha = db.execute(
        text("""
        select (select capital_atual from v_capital_atual) as total,
               coalesce((select sum(valor_principal) from operacao_credito
                          where status in ('ativa', 'inadimplente', 'baixada_prejuizo')), 0)
                 as comprometido
        """)
    ).one()
    disponivel = linha.total - linha.comprometido
    print(
        f"\nteto R$ {linha.total:,.2f}"
        f" | comprometido R$ {linha.comprometido:,.2f}"
        f" | disponível R$ {disponivel:,.2f}"
    )
    print(f"\nentre em {EMAIL_DEMO} — o painel sobe em http://localhost:5173")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limpar",
        action="store_true",
        help="Apaga o cenário (tomadores do prefixo de demonstração) antes de semear.",
    )
    args = parser.parse_args()

    url = _url_do_banco()
    _recusar_fora_de_desenvolvimento(url)

    with Session(create_engine(url)) as db:
        if args.limpar:
            _limpar(db)
        semear(db)
        relatorio(db)


if __name__ == "__main__":
    main()
