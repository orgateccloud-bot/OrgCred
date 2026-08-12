-- OrgCred — as bordas do teto do Art. 5º
--
-- A 003 fechou a race condition, a 006 fechou a saída por inadimplência e
-- renegociação, a 013/014 fecharam os gates de entrada. Todas elas vigiam a
-- TRANSIÇÃO. Nenhuma vigiava o que acontece com uma operação DEPOIS de ela já
-- estar comprometendo capital, nem o que acontece com a linha de capital
-- social depois de constituída. Sobraram três furos, todos alcançáveis por
-- SQL direto e nenhum deles deixando rastro no capital_ledger:
--
--   (a) UPDATE de operação JÁ ATIVA não passa por gate nenhum. O trigger da
--       014 avalia os gates na ENTRADA no estado comprometido ('if
--       v_compromete_agora and (tg_op = INSERT or not v_comprometia_antes)')
--       e na SAÍDA; um UPDATE ativa->ativa cai fora dos dois blocos, e a
--       máquina de estados também é pulada, porque está sob 'if tg_op =
--       UPDATE and new.status is distinct from old.status'. Com capital de
--       50.000 e uma operação ativa de 30.000, um
--       'update operacao_credito set valor_principal = 500000' deixa o
--       comprometido em 500.000 — dez vezes o teto — sem erro e sem evento.
--       O mesmo vale para tomador_id: mover a operação para outro tomador
--       depois de ativa contorna o gate geográfico (OC002) e o de
--       identificação (OC019), que só rodam na ativação.
--
--   (b) esc_capital_social só tinha trigger de INSERT (003, 'before insert on
--       esc_capital_social'). A 006 redefiniu a FUNÇÃO e nunca o trigger.
--       Como v_capital_atual soma a tabela em tempo real, apagar ou editar
--       uma linha de constituição derruba o teto na hora, com operações
--       ativas comprometidas, sem OC005 nenhum. Pior: apagar uma linha de
--       'reducao' INFLA o teto, e nenhuma checagem de "capital resultante vs.
--       comprometido" pegaria isso, porque o capital SOBE.
--
--   (c) Valor positivo era invariante só do Pydantic. Um INSERT de
--       (valor = -100000, tipo_evento = 'reducao') infla o teto: a view faz
--       'when reducao then -valor' e fn_check_reducao_capital calcula
--       'capital_atual - new.valor', que com valor negativo CRESCE — a
--       redução passa pelo OC005 justamente por ser um aporte disfarçado.
--
-- Dois SQLSTATEs novos. OC020 e OC021, e não OC006 (que está livre por
-- acidente histórico, mas aparece em DECISOES_PENDENTES.md como o código
-- previsto para o gate de IOF) — reaproveitar um número reservado faria a
-- próxima migration fiscal ter que renumerar contrato público de erro.
--   OC020 = campo econômico alterado em operação que já compromete capital
--   OC021 = histórico de capital social é append-only (UPDATE/DELETE)
--
-- Códigos próprios, e não OC005, pela mesma razão da 014 ao criar OC019 em
-- vez de reusar OC004: é outra regra e a instrução ao operador é outra. OC005
-- continua sendo exatamente o que sempre foi — "esta REDUÇÃO deixaria o
-- capital abaixo do comprometido" — e seu caminho (INSERT de 'reducao') não
-- é tocado aqui.

-- ---------------------------------------------------------------------
-- (a) Congelar os campos econômicos enquanto a operação ocupa o teto
-- ---------------------------------------------------------------------
-- Os quatro campos são os que definem quanto dinheiro saiu e para quem:
-- valor_principal (o que ocupa o teto e o que o ledger registrou), tomador_id
-- (de quem são os gates de município e identificação), taxa_juros_mensal e
-- numero_parcelas (a agenda que a 007 gerou na ativação e que a 009 baixa
-- contra movimento bancário). Alterar qualquer um deles depois de ativa é
-- reescrever o contrato sem passar por novação — e para isso existe
-- fn_novar_operacao, que baixa a original e cria a substituta sob o mesmo
-- lock, na mesma transação.
--
-- Os demais campos seguem editáveis de propósito: registro_entidade_ref é
-- referência informativa desde a 013 (quem destrava a ativação é o registro
-- confirmado em registro_operacao) e é corrigido em operação viva hoje.
--
-- 'ativa' E 'inadimplente': os dois comprometem capital desde a 006, então
-- os dois precisam do congelamento. Congelar só 'ativa' deixaria a porta
-- aberta pelo caminho ativa -> inadimplente -> edita -> ativa.
--
-- A checagem é sobre OLD.status, não NEW.status. Isso cobre de graça o caso
-- mais perigoso: ativa -> liquidada TROCANDO o valor no mesmo UPDATE, que
-- faria o bloco de SAÍDA do trigger do teto gravar no ledger um
-- new.valor_principal diferente do que entrou — liberando mais capital do
-- que foi comprometido, com a cadeia de hash intacta porque nada foi
-- adulterado depois do fato.
--
-- DELETE de operação comprometida não precisa de trigger: capital_ledger
-- referencia operacao_credito por FK sem ON DELETE, e toda operação que
-- chegou a comprometer capital tem pelo menos o evento 'ativacao_operacao'
-- apontando para ela — o próprio banco já recusa com 23503. Vale o mesmo
-- para parcela (007), operacao_evento (008), contrato_emprestimo e
-- registro_operacao (012), todas sem ON DELETE.
--
-- Isso é uma dependência de forma de schema, não de código, e por isso o
-- teste que a cobre (test_bloqueia_delete_de_operacao_comprometida) lê
-- pg_constraint além de provar o 23503: acrescentar ON DELETE CASCADE a
-- qualquer uma dessas FKs numa migration futura reabriria o furo — o DELETE
-- devolveria o valor ao teto e apagaria junto o evento de ledger que provava
-- a saída — e reabriria em silêncio, já que a recusa continuaria vindo das
-- outras FKs até a última cair.
create or replace function fn_bloquear_alteracao_operacao_comprometida()
returns trigger as $$
declare
    v_alterados text[] := array[]::text[];
begin
    if old.status not in ('ativa','inadimplente') then
        return new;
    end if;

    if new.valor_principal is distinct from old.valor_principal then
        v_alterados := v_alterados ||
            format('valor_principal (%s -> %s)', old.valor_principal, new.valor_principal);
    end if;

    if new.tomador_id is distinct from old.tomador_id then
        v_alterados := v_alterados ||
            format('tomador_id (%s -> %s)', old.tomador_id, new.tomador_id);
    end if;

    if new.taxa_juros_mensal is distinct from old.taxa_juros_mensal then
        v_alterados := v_alterados ||
            format('taxa_juros_mensal (%s -> %s)', old.taxa_juros_mensal, new.taxa_juros_mensal);
    end if;

    if new.numero_parcelas is distinct from old.numero_parcelas then
        v_alterados := v_alterados ||
            format('numero_parcelas (%s -> %s)', old.numero_parcelas, new.numero_parcelas);
    end if;

    if array_length(v_alterados, 1) is null then
        return new;
    end if;

    raise exception
        'Operação % está em % e compromete capital: % não pode ser alterado fora de novação (use fn_novar_operacao). Art. 5º, LC 167/2019.',
        old.id, old.status, array_to_string(v_alterados, ', ')
        using errcode = 'OC020';
end;
$$ language plpgsql;

-- O nome começa com 'bloquear' por ordenação, não por estilo: triggers BEFORE
-- de linha disparam em ordem alfabética do NOME, e 'trg_bloquear_...' vem
-- antes de 'trg_check_teto_capital' (001). Assim a recusa acontece antes de o
-- trigger do teto chegar a montar um evento de ledger a partir de um valor
-- adulterado. A transação abortaria de qualquer jeito; o que a ordem garante
-- é que o erro que chega na API seja OC020, e não outro qualquer levantado
-- no caminho.
--
-- `drop trigger if exists` antes de cada `create trigger`, como a 007..012
-- fazem e a 005 não fez: `create trigger` puro é 42710 na segunda aplicação,
-- e reaplicar a cadeia inteira de migrations sobre um banco existente é o
-- movimento normal para reconferir schema em incidente. Sem o drop, este
-- arquivo seria o único ponto do conjunto em que essa reconferência aborta —
-- e as quatro CHECK constraints logo abaixo já usam exatamente este padrão
-- (`drop constraint if exists` + `add constraint`), então a alternativa era
-- um arquivo idempotente pela metade.
drop trigger if exists trg_bloquear_alteracao_operacao_comprometida on operacao_credito;
create trigger trg_bloquear_alteracao_operacao_comprometida
    before update on operacao_credito
    for each row execute function fn_bloquear_alteracao_operacao_comprometida();

-- ---------------------------------------------------------------------
-- (b) esc_capital_social é append-only
-- ---------------------------------------------------------------------
-- Mesmo tratamento que a 005 deu ao capital_ledger, e pela mesma razão: um
-- histórico que pode ser editado em silêncio não é prova de conformidade com
-- o teto, é um log que parece confiável. O teto do Art. 5º é derivado desta
-- tabela pela view v_capital_atual; se a tabela é mutável, o teto é mutável.
--
-- Bloqueio seco, sem "só bloqueia se ficar abaixo do comprometido", porque
-- esse condicional não pegaria o ataque inverso — apagar uma linha de
-- 'reducao' aumenta o capital e passaria por qualquer checagem que só olhe
-- para baixo. E o caminho legítimo já existe e continua aberto: reduzir
-- capital é INSERIR um evento 'reducao', que passa pelo OC005.
create or replace function fn_bloquear_mutacao_capital_social()
returns trigger as $$
begin
    raise exception
        'esc_capital_social é append-only: % não é permitido (evento % de %). Para reduzir capital, insira um evento tipo_evento = ''reducao'' — que passa pelo gate do Art. 5º.',
        tg_op, old.id, old.valor
        using errcode = 'OC021';
end;
$$ language plpgsql;

--
-- LIMITE CONHECIDO DESTE "append-only": TRUNCATE não dispara trigger de
-- linha. `truncate table esc_capital_social` continua zerando o histórico e
-- derrubando o teto para 0 com operações comprometidas — conferido, não
-- suposto. Fica aberto de propósito, por dois motivos: o capital_ledger da
-- 005 tem exatamente a mesma abertura (fechar só aqui daria a impressão
-- falsa de que a outra tabela está coberta), e a limpeza entre corridas de
-- tests/test_concorrencia.py é justamente um `truncate` varrendo pg_tables —
-- um trigger BEFORE TRUNCATE aqui derrubaria aquela suíte. Fechar isso é
-- decisão única para as duas tabelas, com ajuste do fixture junto, e não
-- cabe nesta migration. Em produção a defesa é a de sempre para DDL/DML de
-- massa: o papel do banco (a role da aplicação não é dona da tabela).
drop trigger if exists trg_bloquear_update_capital_social on esc_capital_social;
create trigger trg_bloquear_update_capital_social
    before update on esc_capital_social
    for each row execute function fn_bloquear_mutacao_capital_social();

drop trigger if exists trg_bloquear_delete_capital_social on esc_capital_social;
create trigger trg_bloquear_delete_capital_social
    before delete on esc_capital_social
    for each row execute function fn_bloquear_mutacao_capital_social();

-- ---------------------------------------------------------------------
-- (c) Domínio e sinal: invariantes de dado, não de camada
-- ---------------------------------------------------------------------
-- app/routers/capital.py já declara valor: Decimal = Field(gt=0) e
-- tipo_evento: Literal["constituicao","reducao"], e operacoes.py já declara
-- valor_principal: Field(gt=0) / numero_parcelas: Field(gt=0). Isso protege o
-- endpoint — e só o endpoint. Um script de migração de dados, um job, um
-- psql aberto num incidente: nenhum passa por Pydantic. O princípio do
-- projeto é que o banco decide, e sinal de valor é decisão do banco.
--
-- O CHECK de tipo_evento fecha, de quebra, o 'else 0' da view v_capital_atual
-- (001): um tipo_evento desconhecido era contabilizado como zero, ou seja,
-- entrava na tabela e sumia do teto sem erro nenhum. Com o domínio fechado o
-- ramo vira inalcançável, que é o único estado em que ele é seguro.
--
-- ATENÇÃO PARA APLICAR EM BASE COM DADOS: ADD CONSTRAINT ... CHECK valida a
-- tabela inteira e falha com 23514 se existir uma linha violando. Nos bancos
-- de teste isto é vácuo (o conftest aplica as migrations em banco recém-criado,
-- antes de qualquer INSERT). Em produção, conferir antes:
--   select count(*) from esc_capital_social
--    where valor <= 0 or tipo_evento not in ('constituicao','reducao');
--   select count(*) from operacao_credito
--    where valor_principal <= 0 or numero_parcelas <= 0;
-- Se alguma retornar linha, ela é um dado que já está mentindo sobre o teto e
-- precisa de decisão humana antes — não de um NOT VALID que adia o problema.
alter table esc_capital_social
    drop constraint if exists esc_capital_social_valor_positivo;
alter table esc_capital_social
    add constraint esc_capital_social_valor_positivo
    check (valor > 0);

alter table esc_capital_social
    drop constraint if exists esc_capital_social_tipo_evento_valido;
alter table esc_capital_social
    add constraint esc_capital_social_tipo_evento_valido
    check (tipo_evento in ('constituicao','reducao'));

alter table operacao_credito
    drop constraint if exists operacao_credito_valor_principal_positivo;
alter table operacao_credito
    add constraint operacao_credito_valor_principal_positivo
    check (valor_principal > 0);

alter table operacao_credito
    drop constraint if exists operacao_credito_numero_parcelas_positivo;
alter table operacao_credito
    add constraint operacao_credito_numero_parcelas_positivo
    check (numero_parcelas > 0);

comment on function fn_bloquear_alteracao_operacao_comprometida() is
    'OC020 — congela valor_principal/tomador_id/taxa_juros_mensal/numero_parcelas enquanto a operação está em ativa ou inadimplente.';
comment on function fn_bloquear_mutacao_capital_social() is
    'OC021 — esc_capital_social é append-only; reduzir capital é INSERT de tipo_evento = reducao (gate OC005).';
