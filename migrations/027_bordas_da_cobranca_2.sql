-- OrgCred — as bordas da cobrança, segunda volta
--
-- A 016 fechou as bordas do que acontece com a PARCELA depois de emitida e com
-- as trilhas append-only depois de gravadas. Uma auditoria adversarial
-- independente voltou ao mesmo módulo e achou três furos que a 016 não olhou,
-- porque os três estão FORA do caminho que ela percorreu: um na identidade do
-- movimento bancário, um no INSERT da parcela (a 016 só reescreveu o UPDATE) e
-- um na porta de trás da baixa. Todos alcançáveis sem má-fé, dois deles sem
-- SQL direto:
--
--   (1) FITID COLIDINDO ENTRE CONTAS DESCARTA CRÉDITO REAL (009:39).
--       `movimento_bancario.documento` é UNIQUE GLOBAL desde a 009. Mas FITID
--       é único DENTRO DA CONTA do banco, não no universo: a especificação OFX
--       o define por conta, e bancos brasileiros emitem sequências curtas
--       ('1', '000123', o número do documento) que colidem entre instituições
--       com facilidade banal. Uma ESC que recebe em dois bancos — ou em duas
--       contas do mesmo banco — importa o extrato do segundo e vê o crédito
--       ser contado como "ja_registrados": a linha existe na tabela, mas é a
--       do OUTRO banco, com outro valor e outra data.
--
--       É o pior formato de defeito que este sistema pode ter, e não é força
--       de expressão: a aritmética do relatório de importação FECHA
--       (lidas = criados + ja_registrados + repetidos_no_arquivo +
--       debitos_ignorados), então a tela afirma, com números conferidos, que
--       nada faltou — enquanto um recebimento real ficou de fora do lastro. O
--       operador não tem como descobrir, e a parcela correspondente segue no
--       aging (008) como inadimplente de um tomador que pagou.
--
--   (2) INSERT EM `parcela` SEM GUARDA (007:75).
--       `fn_parcela_imutavel` é `before update or delete` desde a 007, e a 016
--       — que reescreveu a função inteira — manteve o gatilho como estava. O
--       INSERT nunca teve dono. A agenda que o banco emite na ativação aceita
--       APÊNDICE: `insert into parcela (operacao_id, numero, vencimento, ...)`
--       numa operação ATIVA acrescenta uma décima terceira parcela a um
--       contrato de doze, e ela entra no aging (008, que soma toda parcela
--       'aberta' vencida) e na apuração fiscal (011, que no regime caixa soma
--       toda parcela 'paga'). Inventar receita e inventar inadimplência pelo
--       mesmo comando.
--
--   (3) UPDATE DIRETO BAIXA PARCELA SEM COBERTURA DE VALOR (016:204).
--       A regra "o movimento tem que cobrir a parcela" vive DENTRO de
--       `fn_baixar_parcela`. O trigger de imutabilidade exige `movimento_id`
--       não nulo para sair de 'aberta' (009/016), mas não pergunta QUANTO o
--       movimento vale: `update parcela set status='paga', movimento_id=<uma
--       tarifa de R$ 0,01>` passa por todas as guardas de linha e pela
--       constraint `parcela_lastro_obrigatorio`, que também só checa a
--       presença. A carteira fica quitada contra centavos — e como a
--       liquidação da 017 (OC022) pede exatamente "todas as parcelas pagas",
--       essa quitação de mentira devolve o capital inteiro ao teto do Art. 5º.
--
-- (4) A BAIXA NÃO TINHA AUTOR PELA API, quarto achado da mesma auditoria, é
--     correção de APLICAÇÃO e não aparece aqui: a coluna
--     `parcela.baixado_por`, o `nullif(current_setting('app.user_id'))` de
--     `fn_baixar_parcela` e a guarda contra reescrita existem desde a 016 — só
--     o router não passava o usuário. Registrado nesta lista para que quem
--     leia a migration não procure no banco o que estava em
--     `app/routers/cobranca.py`.
--
-- ---------------------------------------------------------------------
-- UM SQLSTATE NOVO, E SÓ UM: OC025
-- ---------------------------------------------------------------------
-- Pelo critério que a 016 fixou — código novo só quando a INSTRUÇÃO AO
-- OPERADOR é nova, porque um código que significa duas situações não produz
-- mensagem correta para nenhuma das duas:
--
--   (1) não é bloqueio nenhum: é uma chave única sendo CORRIGIDA (de mais
--       restritiva para a que o formato de fato garante). Nada novo a recusar,
--       nada novo a explicar.
--
--   (2) OC025 = a agenda emitida não recebe parcela por fora. É regra nova e
--       instrução nova. OC009 ("parcela já emitida não pode ser alterada nem
--       apagada") seria o vizinho óbvio, e é o errado: a mensagem que a UI
--       associa a ele manda o operador "fazer a baixa da parcela contra o
--       movimento bancário" — exatamente o que quem tenta acrescentar uma
--       parcela NÃO deve fazer. Instrução diferente, código diferente.
--
--   (3) OC011, reusado sem hesitação. A recusa é literalmente a mesma que
--       `fn_baixar_parcela` já dá ("Movimento de X não cobre a parcela Y"), o
--       dicionário do frontend já a descreve ("...ou tem valor menor que a
--       parcela"), e o operador que esbarrar nela pela porta da frente ou pela
--       de trás precisa conferir a mesma coisa: o extrato.

-- ---------------------------------------------------------------------
-- (1) O documento do extrato é único DENTRO DA CONTA
-- ---------------------------------------------------------------------
-- A chave passa a ser (documento, conta_origem), a coluna de conta que a 024
-- criou e que a importação de OFX já preenche com o BANKID/ACCTID declarado no
-- arquivo.
--
-- `NULLS NOT DISTINCT` É O CORAÇÃO DESTE BLOCO, e escrevê-lo sem entender o
-- que ele faz reabriria o furo do outro lado. Em SQL, NULL nunca é igual a
-- NULL: uma UNIQUE comum sobre (documento, conta_origem) NÃO impediria dois
-- lançamentos manuais com o mesmo `documento` — porque `conta_origem` é NULL
-- nos dois por decisão da 024 (manual não pode ter proveniência) e dois NULLs
-- contam como valores distintos. A idempotência que a 009 entrega para o
-- lançamento digitado desapareceria em silêncio, trocando um furo por outro
-- pior: hoje o crédito repetido é RECUSADO (MOVIMENTO_DUPLICADO, 409), e sem
-- esta cláusula ele seria ACEITO e poderia baixar uma segunda parcela.
--
-- Com `NULLS NOT DISTINCT` (PostgreSQL 15+; a imagem deste projeto é a 16),
-- todas as linhas SEM conta declarada — os lançamentos manuais e as
-- importações de OFX que não declaram conta (extrato de cartão capado, ver o
-- comentário de `conta_origem` na 024) — dividem UM ÚNICO espaço de nomes,
-- exatamente o que valia antes desta migration para a tabela inteira. Só se
-- separa o que o ARQUIVO DECLARA separado. É a leitura conservadora de
-- propósito: sem conta, o banco não tem como saber se dois FITIDs iguais são a
-- mesma linha ou duas, e nesse caso a resposta segura é a de hoje (tratar como
-- a mesma e recusar/pular), não a de inventar uma distinção que ninguém
-- declarou.
--
-- APLICAR EM BASE COM DADOS É SEGURO, e a razão é estrutural, não empírica: a
-- chave nova é ESTRITAMENTE MAIS FRACA que a antiga. Se `documento` era único
-- no universo, o par (documento, conta_origem) também é — nenhuma linha
-- existente pode violá-la, e a validação do ADD CONSTRAINT não tem como
-- falhar. O DROP vem antes do ADD na mesma transação: se o ADD falhasse, a
-- transação inteira volta e a tabela continua com a chave antiga.
--
-- O QUE MUDA NO COMPORTAMENTO, para ninguém tratar como incidente: passa a ser
-- possível existir duas linhas com o mesmo `documento` desde que de contas
-- diferentes. Isso é o conserto. A tela de movimentos mostra `conta_origem` ao
-- lado desde a 024, e é ela que distingue as duas.
alter table movimento_bancario
    drop constraint if exists movimento_documento_unico;

alter table movimento_bancario
    drop constraint if exists movimento_documento_por_conta;
alter table movimento_bancario
    add constraint movimento_documento_por_conta
    unique nulls not distinct (documento, conta_origem);

comment on constraint movimento_documento_por_conta on movimento_bancario is
    'FITID é único DENTRO da conta, não no universo: a chave é (documento, conta_origem). NULLS NOT DISTINCT mantém manual e OFX sem conta declarada num único espaço de nomes — sem ela, dois lançamentos manuais com o mesmo documento passariam.';

-- ---------------------------------------------------------------------
-- (2) A agenda não recebe apêndice
-- ---------------------------------------------------------------------
-- A GUARDA TINHA QUE DEIXAR PASSAR `fn_gerar_parcelas` (007), que insere a
-- agenda legítima de dentro da própria ativação, e barrar todo o resto. Três
-- desenhos foram considerados; o escolhido é o terceiro:
--
--   (i) UMA GUC DE SESSÃO ('app.gerando_agenda'), setada por fn_gerar_parcelas
--       e exigida pelo trigger. Rejeitada: uma GUC é um `select
--       set_config(...)` de uma linha para quem tem SQL direto — que é
--       precisamente o atacante deste furo. Seria uma guarda que só barra quem
--       não sabe que ela existe, com aparência de proteção;
--
--  (ii) `pg_trigger_depth() >= 2`, aproveitando que a agenda legítima nasce
--       dentro do trigger de ativação (profundidade 1) e portanto o trigger da
--       parcela roda em profundidade 2, enquanto um INSERT solto roda em 1.
--       Rejeitada por ser CONTEXTUAL e frágil: a permissão passaria a depender
--       de por onde o comando entrou, não do que ele diz. Qualquer trigger novo
--       em qualquer tabela que viesse a inserir parcela ganharia passe livre
--       sem que ninguém decidisse isso, e um `select fn_gerar_parcelas(op)`
--       chamado direto — hoje ninguém o faz, mas nada o proíbe — quebraria;
--
-- (iii) A CONDIÇÃO SOBRE O DADO, escolhida. A agenda só está sendo emitida
--       quando as duas coisas são verdade ao mesmo tempo: a operação está
--       'ativa' (a ativação já foi aceita — o trigger da 007 é AFTER, o status
--       já mudou) E ela ainda não tem a agenda completa. Fora dessa janela não
--       existe INSERT legítimo, e a janela não é forjável de fora:
--
--         - operação que NÃO está 'ativa' não emite agenda nenhuma;
--         - operação 'ativa' JÁ COMMITADA sempre tem a agenda completa —
--           `fn_gerar_parcelas` insere `numero_parcelas` linhas na mesma
--           transação da ativação, e parcela não se apaga: DELETE é recusado
--           linha a linha (OC009) e TRUNCATE, que não visita linhas e por isso
--           atravessava aquela recusa, passa a ser recusado logo abaixo. Logo
--           `count(*) = numero_parcelas` e o INSERT é recusado;
--         - a única janela em que uma operação 'ativa' tem agenda INCOMPLETA é
--           o interior da transação de ativação, que nenhuma outra sessão
--           enxerga (para ela a operação ainda está 'registrada');
--         - `numero_parcelas` não muda depois: a 015 congela os campos
--           econômicos de operação que compromete capital (OC020).
--
--       Vale sobre o que está escrito na linha e na tabela, não sobre o
--       caminho por onde o comando chegou. É a mesma disciplina do resto do
--       motor.
--
-- A QUARTA CONDIÇÃO — parcela NASCE EM ABERTO, sem lastro, sem data de
-- pagamento e sem autor — não é decoração. É o que fecha a porta lateral do
-- furo (3): sem ela, alguém poderia INSERIR uma parcela já 'paga' apontando
-- para uma tarifa de um centavo, e a checagem de cobertura acrescentada abaixo
-- não a veria, porque ela vive no UPDATE. Com as duas juntas, o enunciado fica
-- inteiro e verificável numa frase: toda parcela nasce em aberto, e o único
-- jeito de sair de aberta é um UPDATE — que agora confere o valor.
--
-- TODAS AS QUATRO RECUSAS SAEM COMO OC025, e não uma como OC025 e outra como
-- OC011: para quem está do lado de fora elas são a mesma frase — "a agenda é
-- emitida pelo banco na ativação e nada se insere nela por fora". Separar os
-- códigos dentro de uma guarda só faria a UI explicar o mesmo ato de duas
-- maneiras, que é o defeito que a 016 nomeou.
create or replace function fn_parcela_insercao_valida()
returns trigger as $$
declare
    v_op       operacao_credito%rowtype;
    v_emitidas int;
begin
    select * into v_op from operacao_credito where id = new.operacao_id;
    if not found then
        -- Alcançável antes da FK, que é AFTER: dizer "operação não existe" é
        -- mais útil que o 23503 que viria depois.
        raise exception
            'Operação % não existe: não há agenda a emitir.', new.operacao_id
            using errcode = 'OC025';
    end if;

    if v_op.status <> 'ativa' then
        raise exception
            'A agenda da operação % é emitida na ATIVAÇÃO (situação atual: %) e não recebe parcela avulsa.',
            new.operacao_id, v_op.status
            using errcode = 'OC025';
    end if;

    select count(*) into v_emitidas from parcela where operacao_id = new.operacao_id;
    if v_emitidas >= v_op.numero_parcelas then
        raise exception
            'A agenda da operação % já foi emitida por inteiro (% parcelas): ela não recebe apêndice.',
            new.operacao_id, v_op.numero_parcelas
            using errcode = 'OC025';
    end if;

    if new.numero > v_op.numero_parcelas then
        raise exception
            'Parcela % não cabe na agenda da operação %, contratada em % parcelas.',
            new.numero, new.operacao_id, v_op.numero_parcelas
            using errcode = 'OC025';
    end if;

    if new.status <> 'aberta'
       or new.movimento_id is not null
       or new.pago_em is not null
       or new.baixado_por is not null then
        raise exception
            'Parcela % da operação % nasce EM ABERTO e sem lastro: pagamento se registra pela baixa contra movimento bancário, nunca na emissão da agenda.',
            new.numero, new.operacao_id
            using errcode = 'OC025';
    end if;

    return new;
end;
$$ language plpgsql;

-- Trigger SEPARADO de `trg_parcela_imutavel`, e função separada, em vez de
-- transformar aquele em `before insert or update or delete`. Duas razões, e a
-- segunda é a que decide:
--
--   - em trigger de INSERT o registro OLD não é atribuído, e o corpo de
--     `fn_parcela_imutavel` referencia `old.*` em quase toda linha. Unificar
--     exigiria um desvio no topo isolando o caso INSERT — ou seja, as duas
--     funções que temos aqui, dentro de uma;
--
--   - os testes deste projeto desligam `trg_parcela_imutavel` por nome para
--     fabricar cenários de atraso (`alter table parcela disable trigger
--     trg_parcela_imutavel`, ver tests/test_baixa_recebimento.py e
--     tests/test_router_cobranca.py). Se a guarda de INSERT morasse no mesmo
--     trigger, ela cairia junto — e uma proteção que some quando um teste
--     antedata um vencimento não protege nada.
drop trigger if exists trg_parcela_insercao on parcela;
create trigger trg_parcela_insercao
    before insert on parcela
    for each row execute function fn_parcela_insercao_valida();

-- ---------------------------------------------------------------------
-- (2b) E a agenda não some, para que "agenda completa" queira dizer algo
-- ---------------------------------------------------------------------
-- SEM ESTE PASSO A GUARDA ACIMA TEM UMA PORTA, e ela foi medida antes de ser
-- escrita: `truncate parcela` era aceito até aqui, e depois dele uma operação
-- continua 'ativa' com ZERO parcelas — exatamente a janela que a condição de
-- agenda incompleta declara inforjável. Um INSERT na sequência entra sem
-- recusa nenhuma, e a parcela forjada (vencida, do valor que o autor quiser)
-- cai no aging da 008 e na apuração da 011. O ataque que a guarda existe para
-- barrar volta inteiro, em dois comandos.
--
-- A CAUSA É A DE SEMPRE E JÁ ESTÁ NOMEADA NA 016: TRUNCATE não visita linhas,
-- então nenhum trigger de LINHA o vê — a recusa de DELETE (OC009) o deixa
-- passar do mesmo jeito que a de `capital_ledger` deixava. A 016 instalou
-- BEFORE TRUNCATE de statement em capital_ledger, operacao_evento,
-- tomador_documento, ocorrencia_atipicidade e esc_capital_social; `parcela`
-- ficou de fora porque, até esta migration, nada dependia de a tabela estar
-- CHEIA — a imutabilidade da 009/016 é sobre cada linha, e apagar todas
-- destruía a agenda sem habilitar nada. Agora a contagem de parcelas é uma
-- PERMISSÃO, e a tabela vazia deixou de ser só perda: virou chave.
--
-- REUSA `fn_bloquear_truncate_append_only` (016) COM OC009, e as duas escolhas
-- têm motivo:
--
--   - a função já recebe o SQLSTATE por TG_ARGV justamente para servir a
--     tabelas com invariantes diferentes, e escrever uma segunda igual seria
--     o CASE sobre TG_TABLE_NAME que a 016 rejeitou. O texto dela fala em
--     "append-only", que para `parcela` é frouxo de um lado (a baixa ALTERA a
--     linha) e exato do outro, que é o que importa aqui: linha gravada não
--     some. A segunda metade da frase — "TRUNCATE apagaria o histórico inteiro
--     sem passar por nenhuma das guardas de linha" — é literalmente o defeito;
--
--   - OC009 é o mesmo código que o DELETE linha a linha já devolve, e TRUNCATE
--     é DELETE no atacado. Um código novo obrigaria a UI a explicar de duas
--     maneiras o mesmo ato ("a agenda emitida não se apaga"), que é o defeito
--     que a 016 nomeou ao fixar o critério. Nenhum endpoint trunca, então esta
--     mensagem não chega a operador nenhum pela tela — o que chega é a de
--     DELETE, e é a mesma.
--
-- FECHA `movimento_bancario` DE TABELA, sem trigger próprio: a FK
-- `parcela.movimento_id` faz o Postgres recusar `truncate movimento_bancario`
-- sozinho, e `truncate movimento_bancario cascade` arrasta `parcela` para o
-- mesmo comando — onde este trigger dispara e aborta os dois.
--
-- LIMITE QUE PERMANECE, o mesmo da 016: quem é DONO da tabela desliga o
-- trigger antes (`alter table parcela disable trigger`) e nada em trigger
-- fecha isso. O que fecha é a role da aplicação não ser dona. O que este passo
-- fecha é o resto — o script de limpeza copiado de outro ambiente, a aplicação
-- comprometida e, principalmente, o caminho de dois comandos que reabria a
-- guarda de INSERT sem tocar em trigger nenhum.
drop trigger if exists trg_bloquear_truncate_parcela on parcela;
create trigger trg_bloquear_truncate_parcela
    before truncate on parcela
    for each statement execute function fn_bloquear_truncate_append_only('OC009');

-- ---------------------------------------------------------------------
-- (3) A cobertura de valor sai de dentro da função de baixa
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função INTEIRA: o corpo abaixo é o da 016
-- (DELETE recusado, sete campos congelados, domínio fechado em aberta/paga,
-- baixa terminal, sair de 'aberta' exige movimento, lastro e autoria não se
-- reescrevem) mais UM bloco novo — a cobertura.
--
-- POR QUE NO TRIGGER E NÃO SÓ NA FUNÇÃO, que é a pergunta que este passo
-- responde: `fn_baixar_parcela` é o único caminho de baixa PELA APLICAÇÃO, não
-- o único caminho pelo banco. Um `update parcela set status='paga',
-- movimento_id=X` atravessa a função inteira e chega direto às guardas de
-- linha, que até aqui perguntavam se existe um movimento apontado e nunca
-- quanto ele vale. A regra de negócio "o crédito tem que cobrir a dívida"
-- morava, sozinha, do lado de fora da tabela que ela protege.
--
-- A CHECAGEM DA FUNÇÃO CONTINUA ONDE ESTÁ, e não é redundância inútil: ela
-- roda ANTES do UPDATE, com o número da parcela e o valor devido à mão, e é
-- ela que dá a mensagem que o operador lê no caminho normal. O trigger é a
-- rede embaixo — mesma regra, mesmo OC011, alcançada por qualquer porta.
--
-- O GATILHO É A TRANSIÇÃO `movimento_id` NULL -> NÃO NULL, e não `status =
-- 'paga'`: é o apontamento do lastro que precisa ser coberto, aconteça ele
-- junto com a mudança de status ou sozinho. Apontar um movimento sem mudar o
-- status ('aberta' com movimento_id) tira o crédito de
-- `v_movimentos_disponiveis` e o tranca — e trancá-lo com um valor que nem
-- cobriria a parcela é o pior dos dois mundos.
--
-- O CAMINHO INVERSO NÃO PRECISA DE BLOCO: sair de um movimento já apontado
-- (repontar ou soltar) continua recusado logo abaixo, então `old.movimento_id
-- is null` cobre todas as transições em que um lastro NOVO aparece.
--
-- LIMITE QUE PERMANECE, escrito porque a 016 escreveu o dela: esta guarda é de
-- TRIGGER e some com `alter table parcela disable trigger`. Diferente do
-- domínio de status e da exigência de lastro, ela NÃO pode virar CHECK
-- constraint — a regra compara duas tabelas (`parcela.valor_total` com
-- `movimento_bancario.valor`), e CHECK só enxerga a própria linha. A defesa
-- complementar é a de sempre: a role da aplicação não é dona desta tabela.
create or replace function fn_parcela_imutavel()
returns trigger as $$
declare
    v_valor_movimento numeric(14,2);
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

    -- (016 a) Domínio fechado, verificado no trigger ANTES do CHECK homônimo.
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

    -- O coração da 009, sobre a NEGAÇÃO de 'aberta': quem acrescentar um
    -- status novo ao domínio herda a exigência de lastro por construção.
    if new.status <> 'aberta' and new.movimento_id is null then
        raise exception
            'Parcela % não pode sair de aberta (para %) sem movimento bancário correspondente.',
            new.numero, new.status
            using errcode = 'OC011';
    end if;

    -- (027) O lastro tem que COBRIR a parcela, e não apenas existir.
    if old.movimento_id is null and new.movimento_id is not null then
        select valor into v_valor_movimento
          from movimento_bancario
         where id = new.movimento_id;

        -- A FK de `parcela.movimento_id` é verificada DEPOIS deste BEFORE ROW
        -- (restrições de chave estrangeira são triggers AFTER), então aqui o
        -- movimento pode legitimamente não existir ainda. Recusar com OC011 dá
        -- ao operador a mesma instrução de `fn_baixar_parcela`, em vez do
        -- 23503 que viria adiante e chegaria à API como 500.
        if not found then
            raise exception
                'Movimento bancário % não existe: a parcela % não tem contra o que ser baixada.',
                new.movimento_id, new.numero
                using errcode = 'OC011';
        end if;

        -- `>=` e não `=`, pela mesma razão da 009: juros de mora fazem o
        -- tomador pagar MAIS que o valor original, e exigir igualdade
        -- recusaria a baixa de todo pagamento atrasado — justamente os que
        -- mais importam para a régua de cobrança.
        if v_valor_movimento < new.valor_total then
            raise exception
                'Movimento de % não cobre a parcela % (valor devido: %).',
                v_valor_movimento, new.numero, new.valor_total
                using errcode = 'OC011';
        end if;
    end if;

    -- (016 b) O lastro não se repõe nem se solta. O índice único garante que
    -- um movimento está em no máximo uma parcela AGORA; sem isto, zerar
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

    -- (016 d) Mesma disciplina para o autor: registrado uma vez, não se
    -- reescreve. Trilha de autoria editável não é trilha, é um campo de texto.
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

comment on function fn_parcela_insercao_valida() is
    'OC025 — parcela só entra na agenda durante a emissão (operação ativa, agenda incompleta), dentro do número contratado, e sempre em aberto e sem lastro.';
comment on function fn_parcela_imutavel() is
    'OC009/OC011 — agenda emitida não muda; status limitado a aberta/paga; sair de aberta exige movimento que COBRE a parcela; lastro e autoria da baixa não se reescrevem.';
