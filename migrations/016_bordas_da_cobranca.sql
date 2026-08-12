-- OrgCred — as bordas da cobrança e do compliance
--
-- A 015 fechou as bordas do TETO (o que acontece com uma operação e com o
-- capital social depois de constituídos). Sobraram as bordas do outro lado do
-- ciclo: o que acontece com a PARCELA depois de emitida e com as trilhas
-- append-only depois de gravadas. Três furos de dado, um de autoria e um de
-- tradução de erro — todos alcançáveis por SQL direto, nenhum deixando rastro:
--
--   (a) 'baixada' é um status ACEITO pelo CHECK da 007 e escrito por NINGUÉM.
--       Nenhuma função, nenhum endpoint, nenhum teste o produz — e ele
--       atravessa todas as guardas de fn_parcela_imutavel, porque as três
--       regras da 009 falam de 'paga' ('paga' não volta para aberta; 'paga'
--       exige movimento). Um `update parcela set status = 'baixada'` de uma
--       palavra tira a parcela do atraso (fn_dias_atraso, 008, só olha
--       status = 'aberta') E da receita tributável (fn_apurar_trimestre, 011,
--       no regime caixa só soma status = 'paga') sem lastro bancário, sem
--       evento e sem erro. É a única forma conhecida de fazer uma carteira
--       podre parecer saudável e ainda por cima reduzir o IRPJ apurado.
--
--   (b) movimento_id pode ser REPONTADO. Ele não está na lista de campos
--       congelados da 009, e o índice único `idx_parcela_movimento_unico` só
--       garante que um movimento pertence a UMA parcela por vez — não que
--       pertence para sempre à mesma. `update parcela set movimento_id = null
--       where id = <ja_baixada>` libera o crédito para baixar outra parcela,
--       deixando a primeira 'paga' sem lastro nenhum; e um UPDATE que apenas
--       troca o movimento reescreve, depois do fato, contra qual dinheiro a
--       dívida foi quitada.
--
--   (c) TRUNCATE não dispara trigger de LINHA. As proteções append-only do
--       capital_ledger (005, OC007), do operacao_evento (008, OC010), do
--       tomador_documento (010, OC013), da ocorrencia_atipicidade (010,
--       OC014) e do esc_capital_social (015, OC021) são todas BEFORE
--       INSERT/UPDATE/DELETE FOR EACH ROW: um `truncate table capital_ledger`
--       apaga a cadeia de hash inteira sem levantar um único erro. Era
--       limitação CONHECIDA e documentada na 015, deixada aberta lá porque
--       fechá-la é decisão única para TODAS as trilhas e exigia ajustar o
--       fixture `banco_zerado` de tests/test_concorrencia.py junto. É o que
--       esta migration faz.
--
--       O CRITÉRIO DAS CINCO, escrito para não virar lista arbitrária: são
--       exatamente as tabelas que o próprio schema declara append-only (as
--       quatro que dizem a palavra em 005, 008, 010 e 015) mais o
--       tomador_documento, cuja guarda é de retenção legal — a mesma coisa
--       com outro nome. Ficam DE FORA, e de propósito, as tabelas cuja
--       guarda de linha protege um DOCUMENTO e não uma TRILHA
--       (movimento_bancario/OC012, apuracao_fiscal/OC016,
--       contrato_emprestimo/OC017, registro_operacao/OC018, parcela/OC009):
--       limpar uma importação inteira delas é operação administrativa
--       existente, e proibi-la aqui seria trocar um furo por uma regressão.
--
--   (d) A BAIXA NÃO TEM AUTOR. É o único ato irreversível do ciclo sem nome
--       de gente: ativação, liquidação, cancelamento e novação gravam
--       `usuario_id` no capital_ledger via `current_setting('app.user_id')`
--       (padrão da 004), e a baixa — que não tem estorno definido (009) —
--       não gravava nada. Uma conciliação errada é permanente e ninguém
--       responde por ela.
--
--   (e) Baixa CONCORRENTE devolvia 23505 cru. O `if exists (...)` de
--       fn_baixar_parcela roda em READ COMMITTED: duas transações
--       simultâneas com o mesmo movimento passam as duas pela checagem, e a
--       perdedora morre no índice único com um SQLSTATE que o
--       PGCODE_MAP não conhece — HTTP 500 ("erro interno") para uma
--       situação de negócio perfeitamente normal e cuja instrução ao
--       operador é clara ("este crédito já baixou outra parcela").
--
-- NENHUM SQLSTATE NOVO. Diferente da 015, aqui não há regra nova: cada furo
-- é um caminho que contorna um invariante JÁ declarado, e o operador que
-- esbarra nele precisa receber a mesma instrução que receberia pelo caminho
-- de frente. Inventar OC022 para "status inválido de parcela" faria a UI
-- explicar de duas maneiras diferentes a mesma coisa — que baixa exige
-- lastro. Os códigos reusados, e por quê:
--   OC009 = a agenda emitida não muda (valores, datas, número)
--   OC011 = a baixa não se inventa nem se reescreve (lastro e autoria)
--   OC007/OC010/OC013/OC014/OC021 = a trilha append-only correspondente,
--                                   agora também contra TRUNCATE

-- ---------------------------------------------------------------------
-- (a) O domínio de status da parcela
-- ---------------------------------------------------------------------
-- DECISÃO: as DUAS coisas — remover 'baixada' do domínio E exigir lastro em
-- qualquer status que não seja 'aberta'. O enunciado do problema oferecia
-- uma ou outra; cada uma sozinha deixa metade do furo:
--
--   - só remover 'baixada' conserta o caso de hoje e não o de amanhã: a
--     próxima migration que precisar de um status ('renegociada',
--     'protestada', 'perdida') o acrescenta ao CHECK e reabre exatamente
--     este buraco, porque a regra de lastro continuaria escrita como
--     "se status = 'paga'". O furo voltaria em silêncio, num arquivo que
--     nem estaria falando de lastro.
--
--   - só exigir movimento_id conserta o caso de amanhã e deixa 'baixada'
--     de pé como um SEGUNDO NOME para 'paga' — indistinguível dela para
--     quem lê, e invisível para a régua de atraso (008) e para a receita
--     tributável (011), que perguntam por 'aberta' e por 'paga' pelo nome.
--     Uma parcela 'baixada' com movimento seria um pagamento que não conta
--     como receita: erro fiscal por digitação, sem nada recusando.
--
-- Com as duas, o domínio fica fechado em ('aberta','paga') e a regra de
-- lastro passa a ser sobre a NEGAÇÃO de 'aberta' — de modo que um status
-- novo nasce obrigatoriamente com lastro, e quem o acrescentar tem que
-- decidir explicitamente o que fazer com aging e apuração.
--
-- CHECK e não só trigger: a própria suíte deste projeto demonstra por que.
-- tests/test_baixa_recebimento.py:93 faz `alter table parcela disable
-- trigger trg_parcela_imutavel` para conseguir antedatar um vencimento —
-- um caminho legítimo, mas que prova que uma guarda que vive só em trigger
-- é desligável por uma linha de SQL. CHECK constraint não se desliga sem
-- ALTER TABLE ... DROP CONSTRAINT, que é DDL nomeado e aparece no diff do
-- schema. A guarda de trigger continua existindo (é ela que devolve OC011
-- em vez de 23514, porque BEFORE ROW roda ANTES da avaliação das
-- constraints); o CHECK é o que sobra quando alguém a desliga.
--
-- ATENÇÃO PARA APLICAR EM BASE COM DADOS: ADD CONSTRAINT ... CHECK valida a
-- tabela inteira e falha com 23514 se existir linha violando. Conferir antes:
--   select count(*) from parcela where status not in ('aberta','paga');
--   select count(*) from parcela where status <> 'aberta' and movimento_id is null;
-- A primeira retornando linha significa que alguém JÁ usou o furo (a) — não
-- é caso de relaxar a constraint, é caso de reconciliar aquelas parcelas
-- contra o extrato antes de subir esta migration.
alter table parcela
    drop constraint if exists parcela_status_valido;
alter table parcela
    add constraint parcela_status_valido
    check (status in ('aberta','paga'));

alter table parcela
    drop constraint if exists parcela_lastro_obrigatorio;
alter table parcela
    add constraint parcela_lastro_obrigatorio
    check (status = 'aberta' or movimento_id is not null);

-- ---------------------------------------------------------------------
-- (d) Autoria da baixa
-- ---------------------------------------------------------------------
-- Coluna na própria parcela, e não uma linha no capital_ledger: a baixa não
-- movimenta o teto do Art. 5º (o capital continua comprometido — quem o
-- devolve é a liquidação da operação), então um evento de ledger para ela
-- seria uma linha de valor zero poluindo a cadeia de hash que existe para
-- provar o teto. O que se quer aqui é mais simples e mais direto: a parcela
-- diz quem a conciliou.
--
-- text e não uuid, igual a capital_ledger.usuario_id e movimento_bancario
-- .usuario_id: o autor vem do JWT via `current_setting('app.user_id')`, que
-- é texto, e nem todo caminho que baixa parcela é uma pessoa autenticada
-- (importação de OFX, script de correção). Um uuid com FK obrigaria a
-- inventar um usuário-robô antes de a decisão sobre isso existir.
alter table parcela
    add column if not exists baixado_por text;

comment on column parcela.baixado_por is
    'Autor da baixa (app.user_id no momento da conciliação). NULL = baixa por caminho que não propaga usuário.';

-- ---------------------------------------------------------------------
-- (a) + (b) + (d): fn_parcela_imutavel
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função inteira: o corpo abaixo mantém tudo o
-- que a 009 tinha (DELETE recusado, sete campos congelados, baixa terminal,
-- 'paga' exige movimento) e acrescenta o domínio fechado, o congelamento de
-- movimento_id/baixado_por e a generalização da regra de lastro.
create or replace function fn_parcela_imutavel()
returns trigger as $$
begin
    if tg_op = 'DELETE' then
        raise exception
            'Parcela % da operação % não pode ser apagada: a agenda é imutável.',
            old.numero, old.operacao_id
            using errcode = 'OC009';
    end if;

    if new.operacao_id is distinct from old.operacao_id
       or new.numero is distinct from old.numero
       or new.vencimento is distinct from old.vencimento
       or new.valor_amortizacao is distinct from old.valor_amortizacao
       or new.valor_juros is distinct from old.valor_juros
       or new.valor_total is distinct from old.valor_total
       or new.saldo_devedor_pos is distinct from old.saldo_devedor_pos then
        raise exception
            'Parcela % da operação % é imutável: só a baixa pode alterá-la.',
            old.numero, old.operacao_id
            using errcode = 'OC009';
    end if;

    -- (a) Domínio fechado, verificado no trigger ANTES do CHECK homônimo.
    -- A ordem importa para o contrato de erro, não para a segurança: o CHECK
    -- recusaria de qualquer jeito, mas com 23514, que a API devolve como 500.
    -- Aqui a recusa sai como OC011 e a UI sabe o que dizer ao operador.
    if new.status not in ('aberta','paga') then
        raise exception
            'Status % não existe para parcela: uma parcela está em aberto ou foi paga contra movimento bancário.',
            new.status
            using errcode = 'OC011';
    end if;

    -- Baixa é terminal (ver nota sobre estorno no topo da 009).
    if old.status = 'paga' and new.status is distinct from 'paga' then
        raise exception
            'Parcela % já baixada não pode voltar a aberta: não há estorno definido.',
            old.numero
            using errcode = 'OC011';
    end if;

    -- O coração da 009, agora sobre a NEGAÇÃO de 'aberta': quem acrescentar
    -- um status novo ao domínio herda a exigência de lastro por construção.
    if new.status <> 'aberta' and new.movimento_id is null then
        raise exception
            'Parcela % não pode sair de aberta (para %) sem movimento bancário correspondente.',
            new.numero, new.status
            using errcode = 'OC011';
    end if;

    -- (b) O lastro não se repõe nem se solta. O índice único garante que um
    -- movimento está em no máximo uma parcela AGORA; sem isto, zerar
    -- movimento_id de uma parcela já paga devolve o crédito ao pool de
    -- disponíveis (v_movimentos_disponiveis) e deixa a parcela 'paga'
    -- pendurada em nada — que é precisamente o estado que a 009 existe para
    -- tornar inalcançável.
    if old.movimento_id is not null
       and new.movimento_id is distinct from old.movimento_id then
        raise exception
            'Parcela % já está conciliada contra o movimento %: o lastro de uma baixa não é reapontado (correção se faz no extrato).',
            old.numero, old.movimento_id
            using errcode = 'OC011';
    end if;

    -- (d) Mesma disciplina para o autor: registrado uma vez, não se reescreve.
    -- Trilha de autoria editável não é trilha, é um campo de texto.
    if old.baixado_por is not null
       and new.baixado_por is distinct from old.baixado_por then
        raise exception
            'A autoria da baixa da parcela % já está registrada (%) e não pode ser reescrita.',
            old.numero, old.baixado_por
            using errcode = 'OC011';
    end if;

    return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- (d) + (e): fn_baixar_parcela
-- ---------------------------------------------------------------------
-- Recopiada inteira da 009 (parcela em aberto, movimento existente, movimento
-- ainda não usado, valor >= devido — inclusive a razão do >=: juros de mora
-- fazem o tomador pagar MAIS, e exigir igualdade recusaria a baixa de todo
-- pagamento atrasado), com duas adições:
--
--   - grava o autor lido de `app.user_id`, no padrão da 004: nullif(...,'')
--     porque uma GUC customizada, uma vez setada numa conexão física de pool,
--     volta a '' e não a NULL — sem o nullif, baixas sem usuário autenticado
--     gravariam string vazia dependendo de qual conexão o pool entregou;
--
--   - traduz a colisão do índice único. O `if exists` acima é uma checagem em
--     READ COMMITTED: ele NÃO enxerga a baixa que outra transação já fez e
--     ainda não commitou. As duas passam, a segunda bloqueia no índice único
--     e acorda com 23505 quando a primeira commita. O bloco EXCEPTION
--     converte isso no mesmo OC011 que a checagem otimista daria — mesma
--     situação, mesma instrução ao operador, e nunca um 500.
--     A checagem otimista FICA: ela responde imediatamente no caso comum
--     (movimento já conciliado há dias) sem pagar por um bloqueio de índice.
create or replace function fn_baixar_parcela(
    p_parcela_id   uuid,
    p_movimento_id uuid
) returns void as $$
declare
    v_parcela    parcela%rowtype;
    v_movimento  movimento_bancario%rowtype;
    v_usuario_id text;
begin
    v_usuario_id := nullif(current_setting('app.user_id', true), '');

    select * into v_parcela from parcela where id = p_parcela_id for update;
    if not found then
        raise exception 'Parcela % não existe.', p_parcela_id using errcode = 'OC011';
    end if;
    if v_parcela.status <> 'aberta' then
        raise exception 'Parcela % não está em aberto (situação: %).',
            v_parcela.numero, v_parcela.status using errcode = 'OC011';
    end if;

    select * into v_movimento from movimento_bancario where id = p_movimento_id;
    if not found then
        raise exception 'Movimento bancário % não existe.', p_movimento_id
            using errcode = 'OC011';
    end if;

    if exists (select 1 from parcela where movimento_id = p_movimento_id) then
        raise exception
            'Movimento bancário % já foi usado para baixar outra parcela.', p_movimento_id
            using errcode = 'OC011';
    end if;

    if v_movimento.valor < v_parcela.valor_total then
        raise exception
            'Movimento de % não cobre a parcela % (valor devido: %).',
            v_movimento.valor, v_parcela.numero, v_parcela.valor_total
            using errcode = 'OC011';
    end if;

    begin
        update parcela
           set status = 'paga',
               pago_em = clock_timestamp(),
               movimento_id = p_movimento_id,
               baixado_por = v_usuario_id
         where id = p_parcela_id;
    exception
        when unique_violation then
            raise exception
                'Movimento bancário % foi usado para baixar outra parcela por uma transação concorrente.',
                p_movimento_id
                using errcode = 'OC011';
    end;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- (c) TRUNCATE nas trilhas append-only
-- ---------------------------------------------------------------------
-- Trigger de STATEMENT, não de linha: TRUNCATE não visita linhas — é essa a
-- razão de ele atravessar as guardas existentes, e é por isso que o BEFORE
-- TRUNCATE é a única forma de alcançá-lo de dentro do banco.
--
-- Uma função para as cinco tabelas, com o SQLSTATE vindo de TG_ARGV: cada
-- tabela precisa devolver o código do SEU invariante (OC007 fala de trilha de
-- capital, OC013 de retenção legal de documento — instruções diferentes ao
-- operador), mas o texto e a lógica são idênticos. A alternativa, um CASE
-- sobre TG_TABLE_NAME dentro da função, esconderia o mapeamento tabela ->
-- código longe do CREATE TRIGGER que o estabelece; com TG_ARGV o par está
-- escrito na mesma linha.
--
-- OLD/NEW não são referenciados de propósito: em trigger de statement eles
-- não são atribuídos, e citá-los levantaria "record old is not assigned yet"
-- — um erro de runtime em vez do bloqueio pretendido. É a razão de esta ser
-- uma função nova em vez de reuso de fn_bloquear_mutacao_ledger() (005) ou
-- fn_bloquear_mutacao_capital_social() (015), que formatam old.id.
--
-- O ESCOPO INCLUI esc_capital_social, que o mapeamento deste passo não
-- listava: a 015 registrou explicitamente que a abertura dela e a do
-- capital_ledger são a MESMA decisão, e fechar uma sem a outra deixaria de
-- pé o furo mais barato de todos — zerar o teto do Art. 5º com operações
-- comprometidas — enquanto a nota da 015 passaria a descrever um estado que
-- não existe mais.
--
-- LIMITE QUE PERMANECE: TRUNCATE é DDL-like e o DONO da tabela pode desligar
-- o trigger (`alter table ... disable trigger`) antes. Isto não fecha o
-- ataque de quem é dono do schema — nada em trigger fecha. Fecha o acidente,
-- o script de limpeza copiado de outro ambiente e o caminho de uma
-- aplicação comprometida, que é o que está ao alcance do banco. Em produção
-- a defesa complementar é a de sempre: a role da aplicação não é dona destas
-- tabelas.
create or replace function fn_bloquear_truncate_append_only()
returns trigger as $$
begin
    raise exception
        'Tabela % é append-only: TRUNCATE apagaria o histórico inteiro sem passar por nenhuma das guardas de linha.',
        tg_table_name
        using errcode = tg_argv[0];
end;
$$ language plpgsql;

drop trigger if exists trg_bloquear_truncate_ledger on capital_ledger;
create trigger trg_bloquear_truncate_ledger
    before truncate on capital_ledger
    for each statement execute function fn_bloquear_truncate_append_only('OC007');

-- operacao_evento é a trilha de QUEM fez O QUÊ com cada operação (ativou,
-- liquidou, renegociou, e o atraso de cada transição). A 008 a declara
-- "append-only, como o capital_ledger" e a defende com trigger de linha —
-- que TRUNCATE atravessa igual. Sem esta linha, o `delete from
-- operacao_evento` é recusado com OC010 e o `truncate table operacao_evento`
-- apaga a mesma coisa em silêncio: a trilha de responsabilidade some e as
-- operações ficam sem histórico de ato nenhum, com o ledger (protegido)
-- intacto ao lado, dando a impressão de que a auditoria está inteira.
drop trigger if exists trg_bloquear_truncate_evento on operacao_evento;
create trigger trg_bloquear_truncate_evento
    before truncate on operacao_evento
    for each statement execute function fn_bloquear_truncate_append_only('OC010');

drop trigger if exists trg_bloquear_truncate_documento on tomador_documento;
create trigger trg_bloquear_truncate_documento
    before truncate on tomador_documento
    for each statement execute function fn_bloquear_truncate_append_only('OC013');

drop trigger if exists trg_bloquear_truncate_ocorrencia on ocorrencia_atipicidade;
create trigger trg_bloquear_truncate_ocorrencia
    before truncate on ocorrencia_atipicidade
    for each statement execute function fn_bloquear_truncate_append_only('OC014');

drop trigger if exists trg_bloquear_truncate_capital_social on esc_capital_social;
create trigger trg_bloquear_truncate_capital_social
    before truncate on esc_capital_social
    for each statement execute function fn_bloquear_truncate_append_only('OC021');

comment on function fn_bloquear_truncate_append_only() is
    'Recusa TRUNCATE em tabela append-only com o SQLSTATE passado em TG_ARGV[0] (OC007 ledger, OC010 evento de operação, OC013 documento, OC014 ocorrência, OC021 capital social).';
comment on function fn_parcela_imutavel() is
    'OC009/OC011 — agenda emitida não muda; status limitado a aberta/paga; sair de aberta exige movimento; lastro e autoria da baixa não se reescrevem.';
comment on function fn_baixar_parcela(uuid, uuid) is
    'Único caminho de baixa: valida lastro, grava autor de app.user_id e traduz colisão concorrente do índice único em OC011.';
