-- OrgCred — o gate de novação: renegociar não é pagar, e por isso não devolve teto
--
-- O FURO QUE ESTA MIGRATION FECHA, reproduzido ao vivo três vezes (duas
-- auditorias independentes e o operador humano), pelo caminho normal da API,
-- sem SQL direto e sem má-fé aparente:
--
--   capital social ............................. R$ 50.000,00
--   operação ATIVA de R$ 30.000, doze parcelas em aberto, zero centavo
--   comprovado no extrato ...................... comprometido R$ 30.000,00
--   fn_novar_operacao(op, 0.01, ...) ........... comprometido R$      0,00  <<<
--   cancelar a substituta ...................... comprometido R$      0,00
--   ativar nova operação de R$ 50.000 .......... comprometido R$ 50.000,00
--   -------------------------------------------------------------------
--   DINHEIRO NA RUA: R$ 80.000 sobre R$ 50.000 de capital próprio.
--
-- É a violação direta do Art. 5º da LC 167/2019 — emprestar além do capital
-- próprio — que o teto existe para impedir, e ela cabia em duas chamadas de
-- endpoint.
--
-- ---------------------------------------------------------------------
-- CAUSA: DUAS PORTAS, UM FURO SÓ
-- ---------------------------------------------------------------------
-- (1) O VALOR. `fn_novar_operacao` (006:224) aceitava `p_valor_principal`
--     arbitrário e não o confrontava com NADA: nem com o principal da
--     original, nem com o que foi efetivamente amortizado contra movimento
--     bancário. O `update ... set status='renegociada'` caía no bloco de
--     SAÍDA do trigger do teto e devolvia os R$ 30.000 INTEIROS ao capital
--     disponível, contra uma substituta de um centavo.
--
-- (2) A JANELA. A substituta nascia em 'registrada', que NÃO ocupa o teto,
--     enquanto a original saía do comprometido no MESMO comando — e nada
--     impunha prazo para ativar a substituta, nem impedia cancelá-la. Entre
--     os dois atos o teto ficava livre com o dinheiro na rua. Corrigir só o
--     valor deixaria essa janela aberta: bastaria novar por R$ 30.000 e
--     cancelar a substituta para liberar os mesmos R$ 30.000.
--
-- É EXATAMENTE O EFEITO QUE A 017 RECUSA NO PRÓPRIO CABEÇALHO — "liberar teto
-- por um empréstimo que nunca foi pago permitiria emprestar de novo o mesmo
-- dinheiro que já se perdeu". A 017 fechou a porta da frente (`liquidar`
-- deixou de devolver capital sem a agenda baixada, OC022) e deixou esta
-- aberta: aquele gate olha `new.status = 'liquidada'`, e 'renegociada' ficou
-- fora do conjunto que ocupa o teto. Mesma perda, mesma devolução indevida,
-- outro verbo.
--
-- ---------------------------------------------------------------------
-- A REGRA: O COMPROMETIDO NÃO PODE DIMINUIR NUMA NOVAÇÃO SEM LASTRO
-- ---------------------------------------------------------------------
-- Decorre da política de liquidação já adotada (DECISOES_PENDENTES.md §6):
-- write-off não devolve capital porque o dinheiro não voltou. A novação é a
-- mesma pergunta com outra roupa. Se o principal não foi amortizado contra
-- movimento bancário, o montante continua consumido pela operação, e a
-- substituta tem que COBRIR O SALDO DEVEDOR da original. Redução do
-- comprometido só é legítima na medida exata do que foi efetivamente pago.
--
-- Capitalizar juros (substituta MAIOR) continua livre: é o caso mais comum de
-- renegociação real, e o teto é conferido na ativação da substituta como em
-- qualquer outra ativação.
--
-- SALDO DEVEDOR, DEFINIDO COM PRECISÃO (fn_saldo_devedor_com_lastro):
--
--     valor_principal da operação
--   - soma de `parcela.valor_amortizacao` das parcelas 'paga' COM
--     `movimento_id` não-nulo
--
-- `valor_amortizacao` E NÃO `valor_total`, e a diferença não é sutil: a
-- agenda da 007 decompõe cada parcela em amortização de principal + juros do
-- período. Uma operação PRICE de R$ 30.000 em 12 parcelas a 2,5% a.m. paga
-- ~R$ 35.100 ao longo do contrato — usar o valor cheio da parcela creditaria
-- R$ 5.100 de JUROS como se fossem devolução de principal e afrouxaria o gate
-- justamente na direção do furo. Pior nas primeiras parcelas do PRICE, em que
-- o juro é a maior fatia: seis parcelas pagas de doze amortizam bem menos que
-- metade do principal, e o valor cheio diria que amortizaram mais da metade.
--
-- `movimento_id` não-nulo E NÃO só `status = 'paga'`: é a mesma disciplina do
-- gate de quitação da 017 — o que justifica reduzir o comprometido é o
-- dinheiro que ENTROU na conta, não o rótulo da linha. Desde a 016 as duas
-- condições são equivalentes (sair de 'aberta' exige lastro), e as duas são
-- escritas assim mesmo para que um status novo de parcela não herde
-- silenciosamente a permissão de liberar teto.
--
-- AGENDA VAZIA AQUI É O CASO MAIS ESTRITO, e é o oposto do que acontece na
-- 017: lá `not exists (parcela em aberto)` daria "quitada" por vacuidade e
-- por isso a agenda vazia teve de virar recusa explícita. Aqui a soma de
-- amortizações de um conjunto vazio é zero, o saldo devedor é o principal
-- inteiro e a exigência sobre a substituta fica no máximo. A vacuidade cai do
-- lado seguro sozinha.
--
-- ---------------------------------------------------------------------
-- A JANELA: A ORIGINAL SÓ SAI DO COMPROMETIDO QUANDO A SUBSTITUTA ENTRA
-- ---------------------------------------------------------------------
-- Havia dois desenhos possíveis, e a escolha muda o comportamento visível de
-- `POST /operacoes/{id}/renegociar`. Ficou o segundo:
--
--   (A) a substituta passa a ocupar o teto desde o nascimento, ainda em
--       'registrada';
--   (B) a original PERMANECE no seu status (e no comprometido) até a
--       substituta ser ATIVADA; a marca 'renegociada' deixa de ser efeito da
--       chamada de novação e passa a ser efeito da ativação da substituta,
--       na mesma transação e sob o mesmo advisory lock.
--
-- POR QUE (B), pelas três perguntas que importam:
--
--   O QUE ACONTECE SE A SUBSTITUTA NUNCA FOR ATIVADA. Em (B): nada. A
--   original continua 'ativa'/'inadimplente', continua ocupando o teto,
--   continua na régua de cobrança (`v_aging_operacoes`, 008) e continua com
--   agenda viva. A dívida velha permanece exigível, que é a verdade jurídica
--   enquanto o novo título não existe. Em (A) o resultado seria uma operação
--   'registrada' ocupando o teto sem estar em cobrança nenhuma — a original
--   já 'renegociada' saiu do aging e a substituta 'registrada' nunca entrou:
--   ninguém cobra os R$ 30.000, e o único jeito de destravar o teto seria
--   ativar a substituta. (A) exigiria ainda PROIBIR cancelar a substituta,
--   porque o cancelamento a tiraria do comprometido sem o dinheiro voltar —
--   uma restrição nova que prende o operador num estado do qual só se sai
--   para frente. Em (B) cancelar a substituta é inofensivo e não precisa de
--   regra alguma: a original nunca chegou a sair.
--
--   O QUE A AUDITORIA VÊ. Em (B) o capital_ledger conta a história certa: a
--   chamada de novação, que não move um centavo, não grava evento nenhum; a
--   ativação da substituta grava 'renegociacao' (a original saindo) e
--   'ativacao_operacao' (a substituta entrando), nesta ordem, na mesma
--   transação — os dois lados da troca, com o carimbo do instante em que ela
--   de fato ocorreu. Em (A) haveria dois eventos no ato da novação, quando
--   nada aconteceu, e a série temporal mostraria uma troca que ainda era só
--   uma intenção.
--
--   SE A ESCOLHA CRIA UM SEGUNDO FURO PELO OUTRO LADO. O risco de (B) é o
--   oposto do original: as duas contando ao mesmo tempo. Não ocorre, porque
--   a troca é atômica — a original é baixada DENTRO do gate de ativação da
--   substituta, antes de o comprometido ser somado, sob o mesmo
--   `pg_advisory_xact_lock`. O outro risco seria travar o teto para sempre;
--   também não ocorre: a original segue com todos os caminhos normais
--   (quitar com lastro, baixar como prejuízo, aging). E (B) tem a vantagem
--   de NÃO MEXER na definição de comprometido — `status in
--   ('ativa','inadimplente','baixada_prejuizo')` continua valendo palavra por
--   palavra no trigger do teto, no gate de redução (OC005), no congelamento
--   da 015 e nas leituras de `app/capital_engine.py`. Um furo de teto não se
--   fecha reescrevendo a definição de teto em sete lugares.
--
-- FUNDAMENTO LEGAL DE (B), e é o que resolve o desconforto de a original
-- continuar 'ativa' depois de o operador ter renegociado: pelo Art. 5º §3º da
-- LC 167/2019 a operação só existe legalmente com registro em entidade
-- registradora — é o gate OC004 que a 013 tornou exigência de registro
-- CONFIRMADO. Enquanto o novo título não está constituído, a novação não se
-- consumou e a obrigação antiga não se extinguiu. (B) é o reflexo disso no
-- banco: a substituta é uma proposta de troca até o instante em que passa
-- pelos gates de ativação.
--
-- O GATE DE VALOR É CONFERIDO DUAS VEZES, e não é redundância. Na novação,
-- para recusar cedo o que não pode dar certo (o operador descobre no ato, e
-- não depois de o contrato ter sido emitido). E de novo na ATIVAÇÃO da
-- substituta, que é a conferência autoritativa: entre uma coisa e outra o
-- `valor_principal` de uma operação 'registrada' pode ser alterado — a 015
-- só congela os campos econômicos enquanto a operação OCUPA o teto, e uma
-- substituta pendente não ocupa. Sem a segunda conferência, novar por
-- R$ 30.000 e depois `update ... set valor_principal = 0.01` na substituta
-- reabriria o furo inteiro por uma linha de SQL.
--
-- ---------------------------------------------------------------------
-- NOVO SQLSTATE: OC024
-- ---------------------------------------------------------------------
-- O próximo livre: OC023 é da 025 (trilha de execução de rotina) e OC006
-- segue reservado ao gate de IOF (DECISOES_PENDENTES.md §2).
--
-- Código próprio, pelo critério que a 017 fixou: a instrução ao operador é
-- inédita. OC003 ("transição inválida") diria que o caminho não existe — e
-- ele existe, é o caminho certo assim que a substituta cobrir o saldo
-- devedor. OC001 (teto) diria que falta capital — e não falta: o problema é
-- que esta operação está tentando LIBERAR capital sem prova de pagamento.
-- A recusa aqui é sobre o LASTRO que falta, e a UI precisa poder dizer as
-- saídas: aumentar a substituta até o saldo devedor, baixar parcelas contra o
-- extrato antes de renegociar, ou — se a intenção é encerrar sem pagamento —
-- usar a baixa como prejuízo, que não devolve capital.
--
-- TRÊS RAISES, UM CÓDIGO, seguindo o precedente do próprio OC022 (que tem
-- dois): substituta menor que o saldo devedor na novação, substituta menor
-- que o saldo devedor na ativação, e substituta órfã (a original não está
-- mais em condição de ser trocada, então ativá-la seria dinheiro novo saindo
-- com nome de novação). São três formas da mesma frase — "esta troca reduziria
-- o comprometido sem que o dinheiro tenha voltado" — e a mensagem carrega o
-- caso concreto.
--
-- A ÓRFÃ TEM DOIS SUBCASOS que a mensagem separa, porque a instrução ao
-- operador difere: se a original saiu do comprometido (liquidada, ou já
-- trocada por outra substituta), não há lugar a ceder; se ela foi baixada
-- como PREJUÍZO, ela continua ocupando o teto — 'baixada_prejuizo' está no
-- conjunto do comprometido desde a 017 — e o que se recusa é ressuscitar
-- como título novo uma dívida cuja perda já foi reconhecida.

-- ---------------------------------------------------------------------
-- 1. Saldo devedor com lastro — a medida do que ainda está na rua
-- ---------------------------------------------------------------------
-- Função própria, e não uma subquery repetida nos dois pontos de checagem:
-- esta é A definição de "quanto desta operação ainda não foi pago" e ela vai
-- ser consultada de novo (relatório de renegociação, tela de cobrança). Duas
-- cópias divergiriam no dia em que a agenda ganhar um campo.
--
-- VOLATILE (o padrão, deliberadamente não marcada STABLE): é chamada de
-- dentro de um trigger, depois de outras escritas da mesma transação, e
-- precisa enxergar o estado corrente — inclusive uma baixa de parcela feita
-- há dois comandos. Marcá-la STABLE amarraria a leitura ao snapshot do
-- comando externo, o que aqui não é otimização, é risco.
create or replace function fn_saldo_devedor_com_lastro(p_operacao_id uuid)
returns numeric as $$
declare
    v_principal   numeric(14,2);
    v_amortizado  numeric(14,2);
begin
    select valor_principal into v_principal
    from operacao_credito where id = p_operacao_id;

    if not found then
        raise exception 'Operação % não existe.', p_operacao_id using errcode = 'OC003';
    end if;

    -- Só principal, e só com lastro. Ver a justificativa longa no cabeçalho:
    -- `valor_total` incluiria os juros e afrouxaria o gate na direção do furo.
    select coalesce(sum(valor_amortizacao), 0) into v_amortizado
    from parcela
    where operacao_id = p_operacao_id
      and status = 'paga'
      and movimento_id is not null;

    -- A última parcela absorve o resíduo de arredondamento (007), então
    -- sum(valor_amortizacao) da agenda inteira é EXATAMENTE o principal e a
    -- diferença nunca fica negativa. O greatest existe para que uma agenda
    -- futura com outra regra de resíduo não produza saldo negativo — que
    -- viraria licença para novar por menos que zero.
    return greatest(v_principal - v_amortizado, 0);
end;
$$ language plpgsql;

comment on function fn_saldo_devedor_com_lastro(uuid) is
    'Principal que ainda não voltou: valor_principal menos a soma de parcela.valor_amortizacao '
    'das parcelas pagas COM movimento bancário. É a medida que limita a redução do comprometido '
    'numa novação (OC024, migration 026). Usa valor_amortizacao e não valor_total porque juros '
    'não são devolução de principal.';

-- ---------------------------------------------------------------------
-- 2. fn_novar_operacao — o gate de valor e o fim da baixa antecipada
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função inteira: o corpo abaixo é o da 006 com
-- TRÊS mudanças, todas marcadas:
--
--   (i)   recusa uma segunda substituta pendente sobre a mesma original;
--   (ii)  o gate de valor (OC024) contra o saldo devedor com lastro;
--   (iii) o `update ... set status = 'renegociada'` SAI daqui — passou a ser
--         efeito da ativação da substituta (ver item 3).
create or replace function fn_novar_operacao(
    p_operacao_id           uuid,
    p_valor_principal       numeric,
    p_taxa_juros_mensal     numeric,
    p_sistema_amortizacao   text,
    p_numero_parcelas       int,
    p_registro_entidade_ref text default null
)
returns uuid as $$
declare
    v_original      operacao_credito%rowtype;
    v_saldo_devedor numeric(14,2);
    v_pendente      uuid;
    v_nova_id       uuid;
begin
    perform pg_advisory_xact_lock(hashtext('orgcred_capital_gate'));

    select * into v_original from operacao_credito where id = p_operacao_id for update;
    if not found then
        raise exception 'Operação % não existe.', p_operacao_id using errcode = 'OC003';
    end if;

    if v_original.status not in ('ativa','inadimplente') then
        raise exception
            'Só operação ativa ou inadimplente pode ser renegociada (operação % está em %).',
            p_operacao_id, v_original.status
            using errcode = 'OC003';
    end if;

    -- (i) UMA SUBSTITUTA PENDENTE POR VEZ.
    --
    -- Com a original permanecendo comprometida até a troca, duas substitutas
    -- pendentes sobre o mesmo título seriam duas trocas concorrentes pelo
    -- mesmo lugar: ativada a primeira, a segunda viraria dinheiro NOVO saindo
    -- com nome de novação. O gate de ativação recusa a segunda de qualquer
    -- forma (OC024, substituta órfã), mas deixá-la nascer produziria um
    -- contrato emitido que já nasce impossível de ativar.
    --
    -- OC003 e não OC024: aqui não falta lastro, falta resolver um conflito de
    -- estado — e ele se resolve cancelando a substituta pendente, coisa que a
    -- 026 tornou inofensiva (a original nunca saiu do comprometido).
    select id into v_pendente
    from operacao_credito
    where substitui_operacao_id = p_operacao_id and status = 'registrada'
    limit 1;

    if found then
        raise exception
            'Operação % já tem a substituta % pendente de ativação. Ative-a ou cancele-a antes de renegociar de novo.',
            p_operacao_id, v_pendente
            using errcode = 'OC003';
    end if;

    -- (ii) O GATE DE VALOR — recusa cedo o que a ativação recusaria depois.
    v_saldo_devedor := fn_saldo_devedor_com_lastro(p_operacao_id);

    if p_valor_principal < v_saldo_devedor then
        raise exception
            'Novação bloqueada: a substituta de % não cobre o saldo devedor de % da operação % (principal % menos o que foi amortizado contra movimento bancário). Renegociar não é pagar: reduzir o comprometido sem lastro liberaria teto do Art. 5º (LC 167/2019) por dinheiro que continua na rua. Aumente a substituta até o saldo devedor, baixe as parcelas contra o extrato antes de renegociar, ou — para encerrar sem pagamento — use a baixa como prejuízo (status baixada_prejuizo), que NÃO devolve capital.',
            p_valor_principal, v_saldo_devedor, p_operacao_id, v_original.valor_principal
            using errcode = 'OC024';
    end if;

    -- Libera os gates de novação apenas dentro desta transação.
    perform set_config('app.novacao_em_curso', '1', true);

    -- (iii) A ORIGINAL NÃO É BAIXADA AQUI. Ela continua no status em que está
    -- — e portanto no comprometido, no aging e na cobrança — até a substituta
    -- passar pelos gates de ativação. Ver a justificativa longa de (B) no
    -- cabeçalho: enquanto o novo título não está registrado e ativo, a
    -- novação não se consumou e a dívida antiga não se extinguiu.
    insert into operacao_credito
        (id, tomador_id, tipo, valor_principal, taxa_juros_mensal,
         sistema_amortizacao, numero_parcelas, status, registro_entidade_ref,
         substitui_operacao_id)
    values
        (gen_random_uuid(), v_original.tomador_id, v_original.tipo, p_valor_principal,
         p_taxa_juros_mensal, p_sistema_amortizacao, p_numero_parcelas, 'registrada',
         p_registro_entidade_ref, p_operacao_id)
    returning id into v_nova_id;

    perform set_config('app.novacao_em_curso', '0', true);

    return v_nova_id;
end;
$$ language plpgsql;

comment on function fn_novar_operacao(uuid, numeric, numeric, text, int, text) is
    'Cria a substituta de uma novação, amarrada à original por substitui_operacao_id. Desde a '
    '026 NÃO baixa mais a original: a troca (original -> renegociada) acontece na ativação da '
    'substituta, dentro de fn_check_teto_capital, sob o mesmo advisory lock. Recusa substituta '
    'menor que o saldo devedor com lastro (OC024) e segunda substituta pendente (OC003).';

-- ---------------------------------------------------------------------
-- 3. fn_check_teto_capital — a troca da novação dentro do gate de ativação
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função inteira: o corpo abaixo é o da 017
-- (máquina de estados, novação atômica, gate de quitação OC022, gate de
-- registro confirmado, gate de identificação, gate geográfico, teto, entrada
-- e saída do comprometido, evento de write-off) com UMA mudança, marcada no
-- corpo como (v): o bloco da TROCA, dentro da entrada no comprometido.
--
-- ONDE ELE FICA IMPORTA. Vem depois dos gates de ativação (registro,
-- identificação, município) e ANTES da soma do comprometido:
--
--   - depois dos gates, porque não faz sentido baixar a original para
--     descobrir em seguida que a substituta não podia ser ativada. Como tudo
--     roda numa transação só, uma recusa posterior desfaria a baixa de
--     qualquer forma; a ordem é por clareza da leitura, não por correção;
--   - antes da soma, porque é dela que depende a aritmética: a original
--     precisa já estar fora do comprometido quando `v_comprometido_outras`
--     for calculado. Fosse depois, uma novação de R$ 30.000 por R$ 30.000
--     veria comprometido = 30.000 e pediria mais 30.000 de teto para trocar
--     um título pelo mesmo valor — recusa espúria que quebraria o caminho
--     feliz mais comum da renegociação.
--
-- A RECURSÃO É DELIBERADA: o `update` da original dispara este mesmo trigger
-- para ela, que cai no bloco de SAÍDA e grava 'renegociacao' no ledger com o
-- carimbo do instante da troca. Escrever o evento à mão aqui duplicaria a
-- regra de saída em dois lugares. O advisory lock é de transação e reentrante,
-- então retomá-lo no aninhamento não trava.
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
    v_original              operacao_credito%rowtype;
    v_saldo_devedor         numeric(14,2);
begin
    v_usuario_id := nullif(current_setting('app.user_id', true), '');

    -- (i) Fonte única da verdade sobre o que ocupa o teto. 'inadimplente'
    -- entra desde a 006: o título saiu de 'ativa', mas o dinheiro continua
    -- fora. 'baixada_prejuizo' entra pela MESMA razão, levada ao limite — o
    -- dinheiro não só continua fora como não vai voltar. Tirá-lo daqui faria
    -- o bloco de SAÍDA lá embaixo devolver o capital de um empréstimo
    -- perdoado, que é o furo que a 017 existe para fechar.
    --
    -- A 026 NÃO MEXE NESTE CONJUNTO, e isso é resultado do desenho escolhido
    -- para a janela da novação: a original continua 'ativa'/'inadimplente'
    -- até a substituta entrar, então nenhum status novo precisou ser
    -- admitido no comprometido.
    v_comprometia_antes := tg_op = 'UPDATE'
        and old.status in ('ativa','inadimplente','baixada_prejuizo');
    v_compromete_agora  := new.status in ('ativa','inadimplente','baixada_prejuizo');

    if tg_op = 'UPDATE' and new.status is distinct from old.status then
        -- (ii) Write-off sai de 'ativa' e de 'inadimplente' — na prática o
        -- caminho comum é o segundo, porque se declara perda depois de a
        -- cobrança falhar. Nenhuma dupla tem 'baixada_prejuizo' à ESQUERDA:
        -- é terminal como 'liquidada' e 'cancelada'.
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

        -- Renegociar só dentro da novação atômica. Desde a 026 quem escreve
        -- 'renegociada' é o bloco (v) lá embaixo, no instante em que a
        -- substituta ativa e ocupa o lugar da original no comprometido. Fora
        -- dali, a original sairia do comprometido sem nada entrando — que é o
        -- furo inteiro desta migration, agora recusado com OC008.
        if new.status = 'renegociada'
           and coalesce(current_setting('app.novacao_em_curso', true), '') <> '1' then
            raise exception
                'Renegociação exige novação atômica: use fn_novar_operacao (operação %).',
                new.id
                using errcode = 'OC008';
        end if;

        -- (iii) O GATE DE QUITAÇÃO (017).
        --
        -- Vem AQUI, junto da máquina de estados e antes de qualquer bloco
        -- que toque em capital ou ledger: o que se recusa é o ATO, não o
        -- efeito.
        --
        -- A CONDIÇÃO É SOBRE LASTRO, NÃO SOBRE STATUS — é o dinheiro que
        -- entrou na conta que justifica devolver capital ao teto. É a mesma
        -- bússola que a 026 usa para medir o saldo devedor da novação.
        --
        -- AGENDA VAZIA É RECUSA, não aprovação por vacuidade: `not exists
        -- (parcela em aberto)` sozinho daria "verdadeiro" para uma operação
        -- sem parcela nenhuma.
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
    -- declarar prejuízo. Pela mesma razão, reativar uma inadimplente
    -- (inadimplente -> ativa) não repassa por aqui e não repete a troca da
    -- novação: quem já ocupava o teto não entra nele de novo.
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

        -- (v) BLOCO NOVO NESTA MIGRATION — A TROCA DA NOVAÇÃO.
        --
        -- Ativar uma substituta não é emprestar dinheiro novo: é trocar o
        -- título que já consome o teto por outro. A troca acontece AQUI,
        -- dentro do gate de ativação e antes da soma do comprometido, e é o
        -- único lugar do sistema que escreve 'renegociada'.
        --
        -- As duas recusas são a razão de existir da 026, medidas no instante
        -- em que o capital de fato se move — e não no instante em que o
        -- contrato foi redigido, quando o valor da substituta ainda podia ser
        -- alterado por estar em 'registrada' (a 015 só congela quem ocupa o
        -- teto).
        if new.substitui_operacao_id is not null then
            select * into v_original
            from operacao_credito
            where id = new.substitui_operacao_id
            for update;

            -- SUBSTITUTA ÓRFÃ: a original não está mais em condição de ser
            -- trocada, e ativar esta aqui seria dinheiro NOVO saindo com nome
            -- de novação, contornando a conta que o teto faz. O caminho, se o
            -- crédito novo é mesmo desejado, é cancelar a substituta e abrir
            -- uma operação comum, que passa pelo teto como qualquer outra.
            --
            -- SÃO DOIS CASOS DIFERENTES, e a mensagem não pode confundi-los:
            --
            --   - 'liquidada', 'renegociada' (já trocada por outra substituta)
            --     e as demais: a original saiu do comprometido, não há lugar
            --     a ceder e a substituta somaria por fora;
            --   - 'baixada_prejuizo': a original CONTINUA no comprometido —
            --     ela está no conjunto de (i) lá em cima, e é a 017 inteira
            --     que depende disso. Aqui o problema não é lugar nenhum
            --     vazio, é o contrário: o prejuízo já foi reconhecido, o
            --     valor continua consumindo o teto e nunca vai voltar, e
            --     ressuscitar a dívida como título novo somaria o mesmo
            --     dinheiro duas vezes. Dizer a este operador que a original
            --     "já não ocupa o teto" seria mentir sobre o motivo da
            --     recusa, e mandá-lo procurar o erro no lugar errado.
            --
            -- `is null` no mesmo teste, e não um `if not found` separado: a FK
            -- de substitui_operacao_id garante que a linha existe, então o
            -- ramo seria código morto — mas `null not in (...)` é NULL, e um
            -- `if` com NULL não dispara. Escrito assim, a única forma de
            -- seguir adiante é a original estar comprovadamente ocupando o
            -- teto, sem depender de a FK continuar existindo amanhã.
            if v_original.status is null
               or v_original.status not in ('ativa','inadimplente') then
                raise exception
                    'Ativação bloqueada: a operação original % está em % e não pode mais ser trocada por novação, então a substituta % não tem o que substituir. Ativá-la seria crédito NOVO com nome de novação (Art. 5º, LC 167/2019). Se a original foi baixada como prejuízo, o valor continua consumindo o teto e não vai voltar — a dívida não ressuscita como título novo; nos demais casos ela já saiu do comprometido por outro caminho e não há lugar a ceder. Cancele a substituta e, se o crédito novo é mesmo desejado, abra uma operação comum, que passa pelo teto pela porta da frente.',
                    new.substitui_operacao_id, coalesce(v_original.status, 'inexistente'), new.id
                    using errcode = 'OC024';
            end if;

            -- O GATE DE VALOR, agora sobre o número que vale: o saldo devedor
            -- NESTE instante (parcelas podem ter sido baixadas depois da
            -- novação, e cada baixa com lastro reduz legitimamente a
            -- exigência) contra o valor_principal com que a substituta está
            -- entrando.
            v_saldo_devedor := fn_saldo_devedor_com_lastro(v_original.id);

            if new.valor_principal < v_saldo_devedor then
                raise exception
                    'Ativação bloqueada: a substituta % de % não cobre o saldo devedor de % da operação original %. Trocar um título por outro menor devolveria % ao teto do Art. 5º (LC 167/2019) sem que o dinheiro tenha voltado. A redução só é legítima na medida do que foi amortizado contra movimento bancário.',
                    new.id, new.valor_principal, v_saldo_devedor, v_original.id,
                    v_saldo_devedor - new.valor_principal
                    using errcode = 'OC024';
            end if;

            -- A baixa da original, sob o mesmo lock e na mesma transação. O
            -- trigger reentra para ela, cai no bloco de SAÍDA e grava
            -- 'renegociacao' no ledger; o 'ativacao_operacao' da substituta é
            -- gravado logo abaixo. Os dois eventos contam os dois lados da
            -- troca, na ordem em que ela aconteceu (`capital_ledger.seq`,
            -- migration 020 — `created_at` empata dentro da transação).
            perform set_config('app.novacao_em_curso', '1', true);
            update operacao_credito set status = 'renegociada' where id = v_original.id;
            perform set_config('app.novacao_em_curso', '0', true);
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
    -- comprometem, então não há movimento de capital para registrar. Desde a
    -- 017, ativa/inadimplente -> baixada_prejuizo tampouco cai — e é toda a
    -- diferença entre quitar e perdoar. Desde a 026, a passagem por aqui com
    -- 'renegociada' é sempre a metade de uma troca: a outra metade é a
    -- ativação da substituta, no mesmo commit.
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

    -- (iv) O EVENTO DE WRITE-OFF (017).
    --
    -- Existe porque a baixa como prejuízo é o único ato do ciclo que encerra
    -- uma operação SEM mover capital: não entra (já comprometia) e não sai
    -- (continua comprometendo). Sem este bloco, o ato mais grave que um
    -- gestor pratica — reconhecer que R$ X não voltam — seria o único a não
    -- deixar linha no capital_ledger.
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

comment on column operacao_credito.substitui_operacao_id is
    'Operação original que esta substituta veio trocar (novação). Desde a migration 026 a '
    'original só é marcada como renegociada quando a substituta é ATIVADA — enquanto a '
    'substituta estiver em ''registrada'', é a original que ocupa o teto e está em cobrança. '
    'A substituta não pode entrar por valor menor que o saldo devedor com lastro da original '
    '(OC024).';
