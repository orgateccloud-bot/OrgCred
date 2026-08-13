-- OrgCred — o gate de liquidação: quitação prova pagamento, write-off não devolve capital
--
-- O FURO QUE ESTA MIGRATION FECHA — o mais grave do sistema, alcançável por
-- qualquer operador pela API, sem SQL direto e sem má-fé aparente:
--
--   `POST /operacoes/{id}/liquidar` fazia `ativa -> liquidada`
--   INCONDICIONALMENTE. A máquina de estados da 006 (recopiada até a 014)
--   autoriza a transição, e o bloco de SAÍDA do trigger do teto devolve
--   `new.valor_principal` inteiro ao capital disponível e grava o evento
--   'liquidacao' no capital_ledger — sem olhar UMA parcela. Uma operação de
--   R$ 30.000 com as doze parcelas em aberto, zero centavo comprovado no
--   extrato, virava R$ 30.000 de teto livre para emprestar de novo. De
--   quebra a operação saía de `v_aging_operacoes` (a view filtra
--   'ativa'/'inadimplente'), ou seja, a cobrança morria junto.
--
--   Era o caminho mais curto para furar o Art. 5º da LC 167/2019: emprestar
--   além do capital próprio sem que nada no banco recusasse. E a suíte
--   PROVAVA o furo — test_liquidar_devolve_capital_e_grava_no_ledger
--   liquidava com as doze parcelas abertas e afirmava `comprometido == 0`.
--
-- A POLÍTICA (decidida pelo dono em 2026-08-12, DECISOES_PENDENTES.md §6):
--
--   QUITAÇÃO  -> `liquidada`. Exige TODAS as parcelas pagas, cada uma com
--                lastro bancário (parcela.movimento_id não-nulo). DEVOLVE o
--                capital ao teto, porque o dinheiro voltou de verdade.
--   WRITE-OFF -> `baixada_prejuizo`. Perdão de dívida / baixa contábil.
--                Encerra a cobrança e NÃO devolve capital ao teto, porque o
--                dinheiro não voltou.
--
-- Os dois são estados TERMINAIS DISTINTOS, com EVENTOS DISTINTOS no
-- capital_ledger ('liquidacao' e 'baixa_prejuizo'), para que a auditoria
-- separe "foi pago" de "foi perdoado" sem inferir por valores. Um único
-- estado 'liquidada' com um campo `motivo` ao lado obrigaria todo consumidor
-- do ledger — apuração fiscal, relatório de carteira, laudo — a ler duas
-- colunas e acertar a interpretação; e o dia em que alguém lesse só o status
-- somaria perda com recebimento.
--
-- CONSEQUÊNCIA INTENCIONAL: o teto encolhe permanentemente a cada write-off.
-- Recuperar capacidade operacional exige APORTE de capital (novo evento
-- 'constituicao' em esc_capital_social), não uma baixa contábil. Liberar teto
-- por um empréstimo que nunca foi pago permitiria emprestar de novo o mesmo
-- dinheiro que já se perdeu — exatamente o que o teto existe para impedir.
--
-- ---------------------------------------------------------------------
-- POR QUE O NOME 'baixada_prejuizo'
-- ---------------------------------------------------------------------
-- É a expressão do regulador e do contador, não um neologismo do sistema: a
-- Res. CMN 2.682, art. 12, fala em "baixa do crédito como prejuízo" e é assim
-- que o lançamento aparece no razão. Quem receber um relatório com esse
-- status sabe o que aconteceu sem consultar glossário.
--
-- Segue a forma dos outros estados — todos particípios que concordam com
-- "operação": proposta, registrada, liquidada, renegociada, cancelada. Um
-- substantivo ('perda', 'prejuizo') destoaria da leitura "operação X".
--
-- NÃO se chama 'baixada' seco: a 016 acabou de REMOVER 'baixada' do domínio
-- de `parcela.status` justamente por ser um segundo nome indistinguível de
-- 'paga'. Reintroduzir a mesma palavra em outra tabela, com sentido oposto
-- (lá era "recebida", aqui é "perdida"), plantaria a confusão de novo.
--
-- ---------------------------------------------------------------------
-- A DECISÃO ESTRUTURAL: write-off ENTRA no conjunto que ocupa o teto
-- ---------------------------------------------------------------------
-- Esta é a parte que exige cuidado, e é onde uma implementação ingênua
-- reabre o furo pela porta dos fundos.
--
-- O comprometido é derivado, em tempo real, de
-- `sum(valor_principal) where status in (...)` — no trigger do teto, no gate
-- de redução de capital (OC005) e nas leituras do dashboard. O bloco de
-- SAÍDA de fn_check_teto_capital dispara exatamente quando o status DEIXA
-- esse conjunto; é ele que devolve o capital e grava o evento.
--
-- Logo, se 'baixada_prejuizo' ficasse FORA do conjunto, a transição
-- `ativa -> baixada_prejuizo` cairia no bloco de saída e devolveria o
-- capital — o furo de volta, agora com outro nome. A única forma de o
-- capital NÃO voltar é o estado continuar dentro do conjunto que ocupa o
-- teto. É o reflexo honesto do que a política diz em palavras: "o montante
-- foi consumido pela operação".
--
-- O efeito colateral que precisa ser resolvido junto — e é a razão de o
-- aging não ficar cobrando um crédito perdoado — é que os dois conjuntos
-- DEIXAM DE SER O MESMO:
--
--   ocupa o teto (Art. 5º)  = ativa, inadimplente, baixada_prejuizo
--   está em cobrança (008)  = ativa, inadimplente
--
-- `v_aging_operacoes` e `fn_processar_aging` filtram pelo segundo conjunto e
-- por isso NÃO precisam de uma linha sequer nesta migration: a operação sai
-- da régua de cobrança no instante em que muda de status, porque
-- 'baixada_prejuizo' simplesmente não está lá. Isso é registrado aqui, e não
-- deixado implícito, porque a próxima pessoa que acrescentar um status vai
-- ter que decidir explicitamente em qual dos dois conjuntos ele entra — a
-- resposta não é mais "nos dois".
--
-- Consequência de dado: as parcelas de uma operação baixada como prejuízo
-- continuam 'aberta' para sempre. É correto e é deliberado — elas são a prova
-- documental de quanto ficou por receber. Marcá-las como pagas seria mentir
-- (a 016 já recusa, OC011: sair de 'aberta' exige movimento bancário), e
-- apagá-las seria destruir a agenda (OC009). O que o sistema precisa é parar
-- de COBRAR, não parar de LEMBRAR.
--
-- ---------------------------------------------------------------------
-- NOVO SQLSTATE: OC022
-- ---------------------------------------------------------------------
-- Código próprio, pela mesma razão que levou a 014 a criar OC019 em vez de
-- reusar OC004 e a 015 a criar OC020/OC021: a instrução ao operador é
-- inédita. OC003 ("transição de status inválida") diria que o caminho
-- ativa->liquidada não existe — e ele existe, é o caminho certo assim que as
-- parcelas forem baixadas. A recusa aqui não é sobre o destino, é sobre a
-- PROVA que falta, e a UI precisa poder dizer as duas saídas: baixe as
-- parcelas contra o extrato, ou assuma o prejuízo.
--
-- Continua sem OC006 — reservado ao gate de IOF (DECISOES_PENDENTES.md §2);
-- ocupá-lo obrigaria a renumerar contrato público de erro na próxima
-- migration fiscal.

-- ---------------------------------------------------------------------
-- 1. O domínio de status de operacao_credito, agora declarado no schema
-- ---------------------------------------------------------------------
-- Até aqui o domínio existia só como COMENTÁRIO na coluna (001, linha 131) e
-- como as duplas da máquina de estados dentro do trigger. Um
-- `update operacao_credito set status = 'quitada'` — uma palavra errada num
-- script — passava pela máquina de estados? Não: o `if not (...)` recusa
-- qualquer par desconhecido com OC003. Mas o INSERT não: a única checagem de
-- INSERT é `status not in ('proposta','registrada')`, então nascer em
-- 'proposta' e depois... também é recusado. O domínio, na prática, já estava
-- fechado pelo trigger.
--
-- O CHECK entra pelo motivo que a 016 escreveu por extenso: a própria suíte
-- deste projeto desliga triggers para montar cenário
-- (tests/test_baixa_recebimento.py:93, `alter table ... disable trigger`), o
-- que prova que uma guarda que vive só em trigger é desligável por uma linha
-- de SQL. CHECK constraint não se desliga sem DDL nomeado, que aparece no
-- diff do schema. E, com o domínio escrito no schema, acrescentar um estado
-- passa a ser um ato explícito — que é justamente o que esta migration quer
-- forçar, já que cada estado novo agora precisa responder "ocupa o teto?" e
-- "está em cobrança?" separadamente.
--
-- ATENÇÃO PARA APLICAR EM BASE COM DADOS: ADD CONSTRAINT ... CHECK valida a
-- tabela inteira e falha com 23514 se existir linha violando. Conferir antes:
--   select distinct status from operacao_credito;
alter table operacao_credito
    drop constraint if exists operacao_credito_status_valido;
alter table operacao_credito
    add constraint operacao_credito_status_valido
    check (status in (
        'proposta', 'registrada', 'ativa', 'inadimplente',
        'liquidada', 'renegociada', 'cancelada', 'baixada_prejuizo'
    ));

comment on column operacao_credito.status is
    'Estados: proposta, registrada, ativa, inadimplente, renegociada, cancelada, '
    'e os dois terminais de encerramento — liquidada (quitação: todas as parcelas '
    'pagas com lastro, DEVOLVE capital ao teto) e baixada_prejuizo (write-off: '
    'encerra a cobrança, NÃO devolve capital). Ocupam o teto do Art. 5º: ativa, '
    'inadimplente e baixada_prejuizo. Entram no aging: ativa e inadimplente.';

-- ---------------------------------------------------------------------
-- 2. fn_check_teto_capital — o gate de quitação e o evento de write-off
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função inteira: o corpo abaixo é o da 014
-- (máquina de estados, novação atômica, gate de registro confirmado, gate de
-- identificação, gate geográfico, teto, entrada e saída do comprometido)
-- com QUATRO mudanças, todas marcadas no corpo:
--
--   (i)   'baixada_prejuizo' entra em v_comprometia_antes/v_compromete_agora
--         e nos dois `sum(valor_principal)` de comprometido;
--   (ii)  a máquina de estados ganha ativa -> baixada_prejuizo e
--         inadimplente -> baixada_prejuizo (e nada sai de lá: terminal);
--   (iii) o gate de quitação (OC022) antes de qualquer coisa mexer em
--         capital;
--   (iv)  um bloco novo, de evento SEM movimento de capital, para gravar o
--         write-off no ledger — porque ele não cai nem na entrada nem na
--         saída, exatamente por o estado continuar ocupando o teto.
create or replace function fn_check_teto_capital()
returns trigger as $$
declare
    v_capital_atual         numeric(14,2);
    v_comprometido_outras   numeric(14,2);
    v_disponivel            numeric(14,2);
    v_municipio_ok          boolean;
    v_usuario_id            text;
    v_comprometia_antes     boolean;
    v_compromete_agora      boolean;
    v_parcelas_totais       bigint;
    v_parcelas_sem_lastro   bigint;
begin
    v_usuario_id := nullif(current_setting('app.user_id', true), '');

    -- (i) Fonte única da verdade sobre o que ocupa o teto. 'inadimplente'
    -- entra desde a 006: o título saiu de 'ativa', mas o dinheiro continua
    -- fora. 'baixada_prejuizo' entra pela MESMA razão, levada ao limite — o
    -- dinheiro não só continua fora como não vai voltar. Tirá-lo daqui faria
    -- o bloco de SAÍDA lá embaixo devolver o capital de um empréstimo
    -- perdoado, que é o furo que esta migration existe para fechar.
    v_comprometia_antes := tg_op = 'UPDATE'
        and old.status in ('ativa','inadimplente','baixada_prejuizo');
    v_compromete_agora  := new.status in ('ativa','inadimplente','baixada_prejuizo');

    if tg_op = 'UPDATE' and new.status is distinct from old.status then
        -- (ii) Write-off sai de 'ativa' e de 'inadimplente' — na prática o
        -- caminho comum é o segundo, porque se declara perda depois de a
        -- cobrança falhar. Nenhuma dupla tem 'baixada_prejuizo' à ESQUERDA:
        -- é terminal como 'liquidada' e 'cancelada'. Um write-off que
        -- pudesse voltar a 'ativa' seria um crédito ressuscitado sem
        -- contrato, e um que pudesse virar 'liquidada' devolveria ao teto,
        -- em dois passos, o capital que esta migration recusa devolver em um.
        if not (
            (old.status = 'proposta'     and new.status in ('registrada','cancelada')) or
            (old.status = 'registrada'   and new.status in ('ativa','cancelada')) or
            (old.status = 'ativa'        and new.status in ('liquidada','inadimplente','renegociada','baixada_prejuizo')) or
            (old.status = 'inadimplente' and new.status in ('ativa','renegociada','liquidada','baixada_prejuizo'))
        ) then
            raise exception
                'Transição de status inválida: % -> % (operação %).',
                old.status, new.status, new.id
                using errcode = 'OC003';
        end if;

        -- Renegociar só dentro de fn_novar_operacao, que faz a baixa e a
        -- criação da substituta na MESMA transação e sob o mesmo lock. Fora
        -- dela, a original sairia do comprometido sem substituta amarrada —
        -- e nada impediria criar a substituta depois, contando o capital
        -- duas vezes em janelas diferentes.
        if new.status = 'renegociada'
           and coalesce(current_setting('app.novacao_em_curso', true), '') <> '1' then
            raise exception
                'Renegociação exige novação atômica: use fn_novar_operacao (operação %).',
                new.id
                using errcode = 'OC008';
        end if;

        -- (iii) BLOCO NOVO NESTA MIGRATION — O GATE DE QUITAÇÃO.
        --
        -- Vem AQUI, junto da máquina de estados e antes de qualquer bloco
        -- que toque em capital ou ledger, e não lá embaixo dentro da saída:
        -- o que se recusa é o ATO, não o efeito. Se a checagem morasse no
        -- bloco de saída, ela dependeria de o estado de destino estar fora
        -- do conjunto comprometido — um acoplamento invisível que a próxima
        -- migration quebraria sem perceber.
        --
        -- A CONDIÇÃO É SOBRE LASTRO, NÃO SOBRE STATUS. Hoje as duas coisas
        -- são equivalentes: desde a 016 o domínio da parcela é
        -- ('aberta','paga') e sair de 'aberta' exige movimento_id não-nulo,
        -- então "todas pagas" implica "todas com lastro". A checagem
        -- explicita as duas metades assim mesmo porque é o lastro — o
        -- dinheiro que entrou na conta — que justifica devolver capital ao
        -- teto; se um status novo de parcela aparecer amanhã, esta condição
        -- continua exigindo a prova em vez de herdar um domínio que mudou.
        --
        -- AGENDA VAZIA É RECUSA, não aprovação por vacuidade. `not exists
        -- (parcela em aberto)` sozinho daria "verdadeiro" para uma operação
        -- sem parcela nenhuma — e liquidar sem uma linha de agenda é
        -- precisamente o furo, com zero parcelas em vez de doze. Na prática
        -- toda operação ativa tem agenda (a 007 a gera na ativação), o que
        -- torna este ramo inalcançável pelo caminho normal; ele existe para
        -- que continue inalcançável se aquele gatilho um dia mudar.
        if new.status = 'liquidada' then
            select count(*) into v_parcelas_totais
            from parcela where operacao_id = new.id;

            select count(*) into v_parcelas_sem_lastro
            from parcela
            where operacao_id = new.id
              and (status <> 'paga' or movimento_id is null);

            if v_parcelas_totais = 0 then
                raise exception
                    'Liquidação bloqueada: operação % não tem agenda de parcelas emitida — não há o que comprovar como quitado.',
                    new.id
                    using errcode = 'OC022';
            end if;

            if v_parcelas_sem_lastro > 0 then
                raise exception
                    'Liquidação bloqueada: operação % tem % de % parcelas sem baixa com lastro bancário. Quitação devolve capital ao teto (Art. 5º, LC 167/2019) e por isso exige todas as parcelas pagas contra movimento bancário; para encerrar a cobrança sem pagamento, use a baixa como prejuízo (status baixada_prejuizo), que NÃO devolve capital.',
                    new.id, v_parcelas_sem_lastro, v_parcelas_totais
                    using errcode = 'OC022';
            end if;
        end if;
    end if;

    if tg_op = 'INSERT' and new.status not in ('proposta','registrada') then
        raise exception
            'Operação não pode ser criada já no status % (operação %).',
            new.status, new.id
            using errcode = 'OC003';
    end if;

    -- Substituta de novação também só nasce dentro da função atômica.
    if tg_op = 'INSERT' and new.substitui_operacao_id is not null
       and coalesce(current_setting('app.novacao_em_curso', true), '') <> '1' then
        raise exception
            'Operação substituta só pode ser criada por fn_novar_operacao (operação %).',
            new.id
            using errcode = 'OC008';
    end if;

    -- ENTRADA no comprometido: só quando a operação passa a ocupar o teto
    -- vindo de um estado que NÃO ocupava. Com 'baixada_prejuizo' dentro do
    -- conjunto, `ativa -> baixada_prejuizo` tem v_comprometia_antes
    -- verdadeiro e não cai aqui — nenhum gate de ativação é reavaliado ao
    -- declarar prejuízo, o que é correto: é ato sobre operação que JÁ
    -- comprometia capital (mesma disciplina das 013/014 para a reativação
    -- de inadimplente).
    if v_compromete_agora and (tg_op = 'INSERT' or not v_comprometia_antes) then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        -- Registro em entidade registradora (migration 013).
        if not exists (
            select 1 from registro_operacao r
            where r.operacao_id = new.id and r.status = 'confirmado'
        ) then
            raise exception
                'Ativação bloqueada: operação % sem registro CONFIRMADO em entidade registradora (Art. 5º §3º, LC 167/2019).',
                new.id
                using errcode = 'OC004';
        end if;

        -- Identificação do tomador com evidência arquivada (migration 014).
        -- Vem ANTES do gate geográfico de propósito: não saber quem é o
        -- tomador é falha mais grave do que ele estar fora da área, e a
        -- mensagem mais útil é a da falha mais grave.
        if not exists (
            select 1 from tomador_documento d where d.tomador_id = new.tomador_id
        ) then
            raise exception
                'Ativação bloqueada: tomador % sem evidência de identificação arquivada (Lei 9.613/98, art. 10, I). Operação %.',
                new.tomador_id, new.id
                using errcode = 'OC019';
        end if;

        select municipio_autorizado into v_municipio_ok
        from tomador where id = new.tomador_id;

        if not v_municipio_ok then
            raise exception
                'Tomador fora da área de atuação autorizada (Art. 1º, LC 167/2019). Operação % bloqueada.',
                new.id
                using errcode = 'OC002';
        end if;

        select capital_atual into v_capital_atual from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido_outras
        from operacao_credito
        where status in ('ativa','inadimplente','baixada_prejuizo') and id <> new.id;

        v_disponivel := v_capital_atual - v_comprometido_outras;

        if new.valor_principal > v_disponivel then
            raise exception
                'Teto de capital excedido (Art. 5º, LC 167/2019). Capital disponível: %, valor solicitado: %. Operação % bloqueada.',
                v_disponivel, new.valor_principal, new.id
                using errcode = 'OC001';
        end if;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values ('ativacao_operacao', new.valor_principal, new.id, v_disponivel - new.valor_principal, v_usuario_id);
    end if;

    -- SAÍDA do comprometido: qualquer transição que deixa de ocupar o teto
    -- vindo de um estado que ocupava. Cobre liquidada E renegociada, e
    -- também a partir de 'inadimplente'.
    --
    -- ativa -> inadimplente NÃO cai aqui de propósito: os dois estados
    -- comprometem, então não há movimento de capital para registrar. Desde
    -- esta migration, ativa/inadimplente -> baixada_prejuizo tampouco cai —
    -- e é toda a diferença entre quitar e perdoar.
    if tg_op = 'UPDATE' and v_comprometia_antes and not v_compromete_agora then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual into v_capital_atual from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido_outras
        from operacao_credito
        where status in ('ativa','inadimplente','baixada_prejuizo') and id <> new.id;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values (
            case when new.status = 'renegociada' then 'renegociacao' else 'liquidacao' end,
            new.valor_principal, new.id,
            v_capital_atual - v_comprometido_outras, v_usuario_id
        );
    end if;

    -- (iv) BLOCO NOVO NESTA MIGRATION — O EVENTO DE WRITE-OFF.
    --
    -- Existe porque a baixa como prejuízo é o único ato do ciclo que encerra
    -- uma operação SEM mover capital: não entra (já comprometia) e não sai
    -- (continua comprometendo). Sem este bloco, o ato mais grave que um
    -- gestor pratica — reconhecer que R$ X não voltam — seria o único a não
    -- deixar linha no capital_ledger, e a auditoria teria de deduzi-lo pela
    -- ausência de uma 'liquidacao' que nunca chegou.
    --
    -- `valor` é o principal, igual aos demais eventos: o ledger registra o
    -- montante de que se está falando, não a variação do saldo. E
    -- `saldo_disponivel_pos` é calculado COM a operação ainda dentro do
    -- comprometido — é o número que qualquer consulta de teto vai devolver
    -- depois deste commit, e é o ponto todo do write-off: o disponível não
    -- se move. Uma linha com o saldo "corrigido para cima" aqui seria uma
    -- promessa de capital que o gate de ativação recusaria em seguida.
    --
    -- O advisory lock é o mesmo dos outros blocos, pela mesma razão: sem ele
    -- o saldo gravado poderia ser lido no meio de uma ativação concorrente
    -- ainda não commitada, e a cadeia de hash guardaria um número que nunca
    -- foi verdade.
    if tg_op = 'UPDATE' and new.status = 'baixada_prejuizo'
       and old.status is distinct from 'baixada_prejuizo' then
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual into v_capital_atual from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido_outras
        from operacao_credito
        where status in ('ativa','inadimplente','baixada_prejuizo') and id <> new.id;

        insert into capital_ledger (evento_tipo, valor, operacao_id, saldo_disponivel_pos, usuario_id)
        values (
            'baixa_prejuizo', new.valor_principal, new.id,
            v_capital_atual - v_comprometido_outras - new.valor_principal, v_usuario_id
        );
    end if;

    new.updated_at := now();
    return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- 3. fn_check_reducao_capital — o gate do Art. 5º pelo outro lado
-- ---------------------------------------------------------------------
-- Recopiada da 006 com uma única mudança: 'baixada_prejuizo' no conjunto do
-- comprometido. Sem isso o furo volta invertido e mais barato: bastaria
-- baixar como prejuízo uma operação de R$ 30.000 e, em seguida, INSERIR uma
-- 'reducao' de R$ 30.000 no capital social — a checagem veria o comprometido
-- ter caído e autorizaria. O resultado seria o teto encolhido no papel E o
-- prejuízo apagado da conta, deixando o disponível igual ao de antes de tudo:
-- o capital perdido reaparecendo como capacidade de emprestar.
--
-- Reduzir capital social depois de um write-off é uma decisão societária
-- legítima (é assim que se reconhece a perda no patrimônio), mas ela tem que
-- passar por este gate como qualquer outra redução, medida contra o
-- comprometido REAL — que inclui o que foi perdido.
create or replace function fn_check_reducao_capital()
returns trigger as $$
declare
    v_capital_pos_reducao numeric(14,2);
    v_comprometido        numeric(14,2);
begin
    if new.tipo_evento = 'reducao' then
        -- mesmo lock das ativações: uma redução não pode correr em paralelo
        -- com uma ativação que ainda não commitou
        perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

        select capital_atual - new.valor into v_capital_pos_reducao from v_capital_atual;

        select coalesce(sum(valor_principal), 0) into v_comprometido
        from operacao_credito
        where status in ('ativa','inadimplente','baixada_prejuizo');

        if v_capital_pos_reducao < v_comprometido then
            raise exception
                'Redução de capital bloqueada: capital resultante (%) ficaria abaixo do total de operações ativas (%). Art. 5º, LC 167/2019.',
                v_capital_pos_reducao, v_comprometido
                using errcode = 'OC005';
        end if;
    end if;
    return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- 4. fn_bloquear_alteracao_operacao_comprometida — congelar também o write-off
-- ---------------------------------------------------------------------
-- Recopiada da 015 com uma única mudança: 'baixada_prejuizo' na guarda de
-- entrada. A 015 congela valor_principal/tomador_id/taxa_juros_mensal/
-- numero_parcelas enquanto a operação ocupa o teto, e o motivo vale
-- integralmente aqui: uma operação baixada como prejuízo CONTINUA ocupando o
-- teto, então `update operacao_credito set valor_principal = 1` sobre ela
-- devolveria capital ao disponível sem passar por transição nenhuma — sem
-- evento de ledger, sem OC022, sem rastro. Seria o furo desta migration
-- reaberto pelo caminho que a 015 já sabia ser perigoso.
--
-- Deixar o valor congelado tem também o efeito documental certo: o montante
-- da perda fica escrito onde a auditoria o procura, e não pode ser
-- "arredondado" depois.
create or replace function fn_bloquear_alteracao_operacao_comprometida()
returns trigger as $$
declare
    v_alterados text[] := array[]::text[];
begin
    if old.status not in ('ativa','inadimplente','baixada_prejuizo') then
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

-- ---------------------------------------------------------------------
-- 5. v_tomadores_sem_identificacao — exposição também conta o que se perdeu
-- ---------------------------------------------------------------------
-- Recopiada da 010 com 'baixada_prejuizo' no filtro do `capital_exposto`.
-- A view responde "quanto dinheiro está na rua com gente de quem não temos
-- identificação arquivada" — pergunta de PLD (Lei 9.613/98), não de teto. Um
-- empréstimo perdoado para um tomador não identificado não deixa de ser
-- dinheiro que saiu; ao contrário, é o caso que mais interessa a uma
-- fiscalização. Sem esta linha, declarar prejuízo zeraria a exposição do
-- tomador na tela de compliance — o único lugar do sistema onde ela aparece.
create or replace view v_tomadores_sem_identificacao as
select t.id as tomador_id, t.cnpj, t.razao_social,
       coalesce(sum(oc.valor_principal) filter (
           where oc.status in ('ativa', 'inadimplente', 'baixada_prejuizo')), 0) as capital_exposto
from tomador t
left join operacao_credito oc on oc.tomador_id = t.id
where not exists (select 1 from tomador_documento d where d.tomador_id = t.id)
group by t.id, t.cnpj, t.razao_social;

comment on function fn_check_teto_capital() is
    'OC001/OC002/OC003/OC004/OC008/OC019/OC022 — gates de ativação, máquina de estados, '
    'gate de quitação (liquidar exige todas as parcelas com lastro) e o evento '
    'baixa_prejuizo, que encerra a cobrança sem devolver capital ao teto.';
comment on function fn_check_reducao_capital() is
    'OC005 — redução de capital medida contra o comprometido real, que inclui o que foi baixado como prejuízo.';
comment on function fn_bloquear_alteracao_operacao_comprometida() is
    'OC020 — congela valor_principal/tomador_id/taxa_juros_mensal/numero_parcelas enquanto a operação está em ativa, inadimplente ou baixada_prejuizo.';
