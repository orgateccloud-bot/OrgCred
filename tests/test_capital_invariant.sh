#!/usr/bin/env bash
# Regressão do motor de capital — 7 cenários, todos validados contra Postgres real.
# Uso: ./tests/test_capital_invariant.sh [nome_do_banco_de_teste]
set -e
DB="${1:-orgcred_regression_test}"
fail() { echo "   FALHA — $1"; dropdb --if-exists "$DB"; exit 1; }

echo ">> Criando banco de teste: $DB"
dropdb --if-exists "$DB"; createdb "$DB"

echo ">> Aplicando migrations (001, 002, 003)"
for m in 001_initial_schema 002_usuarios_papeis 003_hardening_capital; do
  psql -d "$DB" -f "migrations/$m.sql" > /dev/null
done

echo ">> Cenário 1: capital 50.000, operação 30.000 registrada deve ATIVAR"
psql -d "$DB" -v ON_ERROR_STOP=1 -q <<SQL
insert into esc_capital_social (valor, tipo_evento) values (50000, 'constituicao');
insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
values ('12345678000199', 'Padaria Teste ME', 'ME', 'Formoso', 'GO', true);
insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
select id, 'emprestimo', 30000, 2.5, 'PRICE', 12, 'registrada', 'REG-001' from tomador where cnpj='12345678000199';
update operacao_credito set status='ativa' where valor_principal=30000;
SQL
echo "   OK"

echo ">> Cenário 2: operação 25.000 com só 20.000 disponíveis deve BLOQUEAR (OC001)"
psql -d "$DB" -q <<SQL 2>/tmp/e
insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
select id, 'emprestimo', 25000, 2.5, 'PRICE', 12, 'registrada', 'REG-002' from tomador where cnpj='12345678000199';
SQL
if psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "update operacao_credito set status='ativa' where valor_principal=25000;" 2>/tmp/e
then fail "deveria ter sido bloqueado"; else grep -q "Teto de capital excedido" /tmp/e && echo "   OK" || fail "erro inesperado: $(cat /tmp/e)"; fi

echo ">> Cenário 3: tomador fora do município deve BLOQUEAR (OC002)"
psql -d "$DB" -v ON_ERROR_STOP=1 -q <<SQL
insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
values ('98765432000188', 'Comércio Fora ME', 'ME', 'Goiânia', 'GO', false);
insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
select id, 'emprestimo', 5000, 2.5, 'PRICE', 12, 'registrada', 'REG-003' from tomador where cnpj='98765432000188';
SQL
if psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "update operacao_credito set status='ativa' where valor_principal=5000;" 2>/tmp/e
then fail "deveria ter sido bloqueado"; else grep -q "fora da área de atuação" /tmp/e && echo "   OK" || fail "erro inesperado: $(cat /tmp/e)"; fi

echo ">> Cenário 4: liquidar 30.000 deve liberar capital para a de 25.000"
psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "update operacao_credito set status='liquidada' where valor_principal=30000;"
psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "update operacao_credito set status='ativa' where valor_principal=25000;"
[ "$(psql -d "$DB" -t -c "select status from operacao_credito where valor_principal=25000;" | xargs)" = "ativa" ] && echo "   OK" || fail "status inesperado"

echo ">> Cenário 5: reduzir capital abaixo do comprometido deve BLOQUEAR (OC005)"
if psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "insert into esc_capital_social (valor, tipo_evento) values (40000,'reducao');" 2>/tmp/e
then fail "deveria ter sido bloqueado"; else grep -q "Redução de capital bloqueada" /tmp/e && echo "   OK" || fail "erro inesperado: $(cat /tmp/e)"; fi

echo ">> Cenário 6: transição proposta -> ativa deve BLOQUEAR (OC003)"
psql -d "$DB" -v ON_ERROR_STOP=1 -q <<SQL
insert into operacao_credito (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao, numero_parcelas, status)
select id, 'emprestimo', 1000, 2.5, 'PRICE', 6, 'proposta' from tomador where cnpj='12345678000199';
SQL
if psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "update operacao_credito set status='ativa' where valor_principal=1000;" 2>/tmp/e
then fail "deveria ter sido bloqueado"; else grep -q "Transição de status inválida" /tmp/e && echo "   OK" || fail "erro inesperado: $(cat /tmp/e)"; fi

echo ">> Cenário 7: ativar sem registro_entidade_ref deve BLOQUEAR (OC004)"
psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "update operacao_credito set status='registrada' where valor_principal=1000;"
if psql -d "$DB" -v ON_ERROR_STOP=1 -q -c "update operacao_credito set status='ativa' where valor_principal=1000;" 2>/tmp/e
then fail "deveria ter sido bloqueado"; else grep -q "sem registro na entidade registradora" /tmp/e && echo "   OK" || fail "erro inesperado: $(cat /tmp/e)"; fi

echo ""
echo ">> Todos os 7 cenários passaram."
dropdb "$DB"
