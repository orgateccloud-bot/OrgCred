#!/usr/bin/env python3
"""
Teste de concorrência do teto de capital (F1 da revisão de 2026-07-11).

Reproduz o ataque que quebrou a versão 001 do trigger: duas transações
ativando operações simultaneamente, cada uma cabendo sozinha no capital,
mas violando o teto juntas. Com a migration 003 (advisory lock), exatamente
uma deve ativar e a outra deve ser bloqueada com SQLSTATE OC001.

Uso: python3 tests/test_concorrencia.py [dbname]
Requer: psycopg2, acesso ao Postgres via PGHOST/PGUSER/PGPASSWORD (variáveis
padrão do libpq). Sem PGHOST definido, cai no comportamento padrão do
psycopg2/libpq — socket Unix local (peer auth), útil em dev Linux; em CI
(GitHub Actions, container de serviço Postgres) defina PGHOST=localhost.
"""

import os
import sys
import threading

import psycopg2


def _dsn(dbname: str) -> str:
    """Monta a DSN a partir de variáveis de ambiente padrão do libpq.

    Não hardcoda host: se PGHOST não estiver definida, o psycopg2 usa o
    comportamento padrão da libpq (socket Unix local) — isso é o que
    quebrava silenciosamente antes, pois o host vinha fixo no código e
    ignorava qualquer PGHOST setada pelo CI.
    """
    parts = [f"dbname={dbname}", f"user={os.environ.get('PGUSER', 'postgres')}"]
    host = os.environ.get("PGHOST")
    if host:
        parts.append(f"host={host}")
    password = os.environ.get("PGPASSWORD")
    if password:
        parts.append(f"password={password}")
    return " ".join(parts)


DB = sys.argv[1] if len(sys.argv) > 1 else "orgcred_conc_test"
ADMIN_DSN = _dsn("postgres")
DSN = _dsn(DB)


def run_sql(dsn, sql, autocommit=True):
    conn = psycopg2.connect(dsn)
    conn.autocommit = autocommit
    cur = conn.cursor()
    cur.execute(sql)
    conn.close()


# setup
admin = psycopg2.connect(ADMIN_DSN)
admin.autocommit = True
ac = admin.cursor()
ac.execute(f'drop database if exists "{DB}"')
ac.execute(f'create database "{DB}"')
admin.close()

for mig in ("001_initial_schema", "002_usuarios_papeis", "003_hardening_capital"):
    with open(f"migrations/{mig}.sql") as f:
        run_sql(DSN, f.read())

run_sql(
    DSN,
    """
    insert into esc_capital_social (valor, tipo_evento) values (50000,'constituicao');
    insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
    values ('11111111000111','Alvo A ME','ME','Formoso','GO',true),
           ('22222222000122','Alvo B ME','ME','Formoso','GO',true);
    insert into operacao_credito (tomador_id,tipo,valor_principal,taxa_juros_mensal,
                                  sistema_amortizacao,numero_parcelas,status,registro_entidade_ref)
    select id,'emprestimo',30000,2.5,'PRICE',12,'registrada','REG-CONC' from tomador;
""",
)

barrier = threading.Barrier(2)
results = {}


def ativar(cnpj, key):
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    c = conn.cursor()
    try:
        barrier.wait(timeout=10)
        c.execute(
            "update operacao_credito set status='ativa' "
            "where tomador_id=(select id from tomador where cnpj=%s)",
            (cnpj,),
        )
        conn.commit()
        results[key] = ("ATIVADA", None)
    except Exception as e:
        conn.rollback()
        results[key] = ("BLOQUEADA", getattr(e, "pgcode", None))
    finally:
        conn.close()


t1 = threading.Thread(target=ativar, args=("11111111000111", "A"))
t2 = threading.Thread(target=ativar, args=("22222222000122", "B"))
t1.start()
t2.start()
t1.join()
t2.join()

check = psycopg2.connect(DSN)
c = check.cursor()
c.execute("select coalesce(sum(valor_principal),0) from operacao_credito where status='ativa'")
total = c.fetchone()[0]
c.execute("select capital_atual from v_capital_atual")
cap = c.fetchone()[0]
check.close()

statuses = sorted(v[0] for v in results.values())
codes = [v[1] for v in results.values() if v[1]]

print(f"resultados: {results}")
print(f"total ativo: {total} | capital: {cap}")

ok = total <= cap and statuses == ["ATIVADA", "BLOQUEADA"] and codes == ["OC001"]
if ok:
    print("PASS — exatamente uma ativou; a outra foi bloqueada com OC001; teto respeitado.")
else:
    print("FAIL — comportamento concorrente incorreto.")
    sys.exit(1)

admin = psycopg2.connect(ADMIN_DSN)
admin.autocommit = True
admin.cursor().execute(f'drop database "{DB}"')
admin.close()
