#!/usr/bin/env bash
# Regressão do motor de capital direto no psql, sem Python no caminho.
#
# LEIA ISTO ANTES DE INVESTIR TEMPO AQUI ------------------------------------
# Este script é HOJE uma duplicata de tests/test_capital_engine.py, que porta
# os mesmos cenários (o docstring de lá diz isso desde que foi escrito) e
# ainda prova a camada de tradução SQLSTATE -> exceção -> HTTP, que aqui não
# existe. A única coisa que ele acrescenta é não depender de SQLAlchemy nem
# do driver — e nenhum invariante deste projeto mora no driver.
#
# Ele continua no repositório por um motivo operacional, não técnico: o job
# `integration` de .circleci/config.yml o invoca por caminho fixo
# (`./tests/test_capital_invariant.sh orgcred_regression`). Apagá-lo agora
# quebraria a CI num commit que não fala de CI. A recomendação é retirar os
# dois juntos — script e job — num passo próprio, e é a razão de este aviso
# estar no topo do arquivo em vez de num relatório que ninguém relê.
#
# O QUE FOI CORRIGIDO (2026-08-12) ------------------------------------------
# 1. Aplicava SOMENTE as migrations 001, 002 e 003. `fn_check_teto_capital`
#    foi redefinida inteira por 003, 004, 006, 013 e 014; parando na 003, os
#    sete cenários exercitavam um trigger que não existe mais em lugar nenhum.
#    Agora aplica migrations/*.sql inteiro, em ordem — sem lista para
#    desatualizar (a contiguidade da numeração é garantida por
#    tests/test_migrations_sincronizadas.py).
# 2. Afirmava por SUBSTRING da mensagem de erro (`grep "sem registro na
#    entidade registradora"`), texto que a migration 013 já havia trocado —
#    e casar mensagem é a prática que este projeto proscreve, porque quebra
#    em silêncio. Agora afirma por SQLSTATE, via a função tst_sqlstate()
#    criada abaixo, que devolve o CÓDIGO do erro em vez de deixá-lo escapar.
#
# Uso: ./tests/test_capital_invariant.sh [nome_do_banco_de_teste]
# Requer: psql/createdb/dropdb e as variáveis padrão do libpq (PGHOST etc).
set -euo pipefail

DB="${1:-orgcred_regression_test}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

falhar() {
  echo "   FALHA — $1"
  dropdb --if-exists "$DB" >/dev/null 2>&1 || true
  exit 1
}

# Afirma o SQLSTATE de um comando. 'SEM_ERRO' é o caminho feliz.
#
# O comando roda DENTRO de tst_sqlstate: o bloco de exceção do PL/pgSQL
# captura o erro e devolve o código, então o psql sai 0 e o que se compara é
# o SQLSTATE, nunca o texto. O efeito colateral é o desejado: o comando que
# falhou é desfeito (subtransação implícita), o que passou permanece.
esperar() {
  local esperado="$1" descricao="$2" sql="$3" obtido
  obtido="$(psql -d "$DB" -tA -v ON_ERROR_STOP=1 -c "select tst_sqlstate(\$q\$${sql}\$q\$)")"
  if [ "$obtido" = "$esperado" ]; then
    echo "   OK — $descricao [$obtido]"
  else
    falhar "$descricao — esperado $esperado, obtido $obtido"
  fi
}

echo ">> Criando banco de teste: $DB"
dropdb --if-exists "$DB"
createdb "$DB"

echo ">> Aplicando TODAS as migrations de migrations/, em ordem numérica"
for arquivo in "$RAIZ"/migrations/*.sql; do
  echo "   $(basename "$arquivo")"
  psql -d "$DB" -v ON_ERROR_STOP=1 -q -f "$arquivo" > /dev/null
done

echo ">> Instalando a sonda de SQLSTATE"
psql -d "$DB" -v ON_ERROR_STOP=1 -q <<'SQL'
create or replace function tst_sqlstate(p_sql text) returns text as $$
begin
    execute p_sql;
    return 'SEM_ERRO';
exception when others then
    return sqlstate;
end;
$$ language plpgsql;
SQL

echo ">> Preparando capital, tomadores e evidências de identificação"
psql -d "$DB" -v ON_ERROR_STOP=1 -q <<'SQL'
insert into esc_capital_social (valor, tipo_evento) values (50000, 'constituicao');

insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
values ('12345678000199', 'Padaria Teste ME',  'ME', 'Formoso', 'GO', true),
       ('98765432000188', 'Comércio Fora ME',  'ME', 'Goiânia', 'GO', false),
       ('11122233000144', 'Mercearia Sem Papel ME', 'ME', 'Formoso', 'GO', true);

-- Identificação arquivada (Lei 9.613/98, art. 10, I — gate da migration 014)
-- para os dois primeiros. O terceiro fica SEM de propósito: é o cenário 9.
insert into tomador_documento (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
select id, 'contrato_social', 'contrato.pdf',
       encode(sha256(cnpj::bytea), 'hex'), current_date + interval '5 years'
from tomador where cnpj in ('12345678000199', '98765432000188');

-- Operações. `registro_entidade_ref` continua preenchido porque a coluna
-- existe, mas desde a 013 quem libera a ativação é registro_operacao com
-- status 'confirmado' — e é isso que o cenário 8 explora.
insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                              sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
select id, 'emprestimo', v.valor, 2.5, 'PRICE', 12, 'registrada', 'REG-' || v.valor
from tomador, (values (30000), (25000)) as v(valor)
where cnpj = '12345678000199';

insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                              sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
select id, 'emprestimo', 5000, 2.5, 'PRICE', 12, 'registrada', 'REG-5000'
from tomador where cnpj = '98765432000188';

insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                              sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
select id, 'emprestimo', 2000, 2.5, 'PRICE', 12, 'registrada', 'REG-2000'
from tomador where cnpj = '11122233000144';

-- Registro CONFIRMADO para todas, menos a de 1000 (cenário 8), que nem existe
-- ainda. Em DOIS comandos, e não num INSERT já confirmado: desde a 021 o
-- registro nasce obrigatoriamente em 'pendente' e sem protocolo (OC018), e a
-- confirmação é o UPDATE — que é onde o CHECK da 012 passa a exigir protocolo
-- e data. Montar o cenário pelo caminho de produção é o ponto: um seed que
-- contorna a máquina de estados provaria o gate sobre um estado que a
-- aplicação não consegue produzir.
insert into registro_operacao (operacao_id, entidade)
select id, 'CRDC' from operacao_credito;

update registro_operacao r
   set status = 'confirmado',
       protocolo = 'PROTO-' || o.valor_principal,
       confirmado_em = clock_timestamp()
  from operacao_credito o
 where o.id = r.operacao_id;
SQL

echo ">> Cenário 1: 30.000 sobre capital de 50.000 deve ATIVAR"
esperar SEM_ERRO "ativação dentro do teto" \
  "update operacao_credito set status='ativa' where valor_principal=30000"

echo ">> Cenário 2: 25.000 com só 20.000 disponíveis deve BLOQUEAR (OC001)"
esperar OC001 "teto de capital (Art. 5º)" \
  "update operacao_credito set status='ativa' where valor_principal=25000"

echo ">> Cenário 3: tomador fora do município deve BLOQUEAR (OC002)"
esperar OC002 "área de atuação (Art. 1º)" \
  "update operacao_credito set status='ativa' where valor_principal=5000"

echo ">> Cenário 4: liquidar 30.000 deve liberar capital para a de 25.000"
esperar SEM_ERRO "liquidação" \
  "update operacao_credito set status='liquidada' where valor_principal=30000"
esperar SEM_ERRO "ativação com o capital devolvido" \
  "update operacao_credito set status='ativa' where valor_principal=25000"

echo ">> Cenário 5: reduzir capital abaixo do comprometido deve BLOQUEAR (OC005)"
esperar OC005 "redução abaixo do comprometido" \
  "insert into esc_capital_social (valor, tipo_evento) values (40000,'reducao')"

echo ">> Cenário 6: redução dentro da folga deve PASSAR (a amarra não é um muro)"
esperar SEM_ERRO "redução legítima" \
  "insert into esc_capital_social (valor, tipo_evento) values (20000,'reducao')"

echo ">> Cenário 7: transição proposta -> ativa deve BLOQUEAR (OC003)"
psql -d "$DB" -v ON_ERROR_STOP=1 -q <<'SQL'
insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                              sistema_amortizacao, numero_parcelas, status)
select id, 'emprestimo', 1000, 2.5, 'PRICE', 6, 'proposta'
from tomador where cnpj = '12345678000199';
SQL
esperar OC003 "máquina de estados" \
  "update operacao_credito set status='ativa' where valor_principal=1000"

echo ">> Cenário 8: ativar sem registro CONFIRMADO deve BLOQUEAR (OC004)"
esperar SEM_ERRO "proposta -> registrada" \
  "update operacao_credito set status='registrada' where valor_principal=1000"
esperar OC004 "gate de registro (Art. 5º §3º)" \
  "update operacao_credito set status='ativa' where valor_principal=1000"

echo ">> Cenário 9: ativar tomador sem identificação arquivada deve BLOQUEAR (OC019)"
esperar OC019 "gate de identificação (Lei 9.613/98, art. 10, I)" \
  "update operacao_credito set status='ativa' where valor_principal=2000"

echo ">> Cenário 10: com a evidência arquivada, a mesma operação ATIVA"
psql -d "$DB" -v ON_ERROR_STOP=1 -q <<'SQL'
insert into tomador_documento (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
select id, 'contrato_social', 'contrato.pdf',
       encode(sha256(cnpj::bytea), 'hex'), current_date + interval '5 years'
from tomador where cnpj = '11122233000144';
SQL
esperar SEM_ERRO "ativação após arquivar a identificação" \
  "update operacao_credito set status='ativa' where valor_principal=2000"

echo ">> Conferência final: comprometido não pode passar do capital"
INVARIANTE="$(psql -d "$DB" -tA -v ON_ERROR_STOP=1 -c "
  select case when (select coalesce(sum(valor_principal),0) from operacao_credito
                    where status in ('ativa','inadimplente'))
              <= (select capital_atual from v_capital_atual)
         then 'OK' else 'VIOLADO' end")"
[ "$INVARIANTE" = "OK" ] || falhar "teto violado ao fim da bateria"
echo "   OK — comprometido <= capital"

echo ""
echo ">> Todos os 10 cenários passaram."
dropdb "$DB"
