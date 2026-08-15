-- OrgCred — a cadeia do capital_ledger passa a ser ancorada numa chave MONOTÔNICA
--
-- O QUE ESTAVA ERRADO. A hash-chain da migration 005 é encadeada e verificada
-- por `created_at`, cujo default é `now()` — e `now()` no Postgres é
-- `transaction_timestamp()`, fixado quando a transação ABRE, não quando a
-- linha é gravada:
--
--     005:53   select current_hash into v_prev_hash from capital_ledger
--              order by created_at desc, id desc limit 1;
--     005:107  lag(l.current_hash) over (order by l.created_at, l.id)
--
-- Enquanto a transação for curta o bastante para que abrir e gravar sejam "o
-- mesmo instante", os dois coincidem e ninguém percebe. Duas transações
-- SOBREPOSTAS desfazem a coincidência. T_A abre em t0 e ainda não escreve;
-- T_B abre em t0+5ms, grava no ledger e commita; só então T_A grava — e, em
-- READ COMMITTED, enxerga a linha de T_B e encadeia CERTO nela. Mas carimba
-- `created_at` = t0. A verificação reordena por `created_at`, coloca T_A
-- ANTES de T_B, e acusa AS DUAS linhas de adulteração.
--
-- E não é preciso corrida apertada nenhuma: basta uma transação que LEIA
-- antes de escrever — que é o formato de qualquer request que consulta o
-- capital disponível e então ativa a operação.
--
-- POR QUE ISSO É GRAVE, e não um alarme cosmético. A consequência é dupla, e
-- a segunda é pior que a primeira: (1) `GET /auditoria` reporta adulteração
-- INEXISTENTE, e quem recebe "linha possivelmente adulterada" de uma corrida
-- benigna aprende a ignorar o alerta; (2) a partir daí, uma adulteração REAL
-- fica indistinguível de uma corrida benigna — a cadeia de hash deixa de
-- separar os dois casos, que é a única coisa que ela existe para fazer. Um
-- detector que dispara sozinho não é um detector.
--
-- ---------------------------------------------------------------------
-- POR QUE UMA CHAVE NOVA, e não `clock_timestamp()` no `created_at`
-- ---------------------------------------------------------------------
-- A migration 008 trocou `now()` por `clock_timestamp()` exatamente onde a
-- ordem importa, e a tentação aqui é repetir a receita. Ela não serve: um
-- relógio melhor continua sendo um RELÓGIO, e o que a cadeia precisa é de
-- ORDEM. Relógio empata (duas linhas no mesmo microssegundo não têm ordem
-- definida entre si), relógio anda para trás (ajuste de NTP) e relógio não
-- promete nenhuma relação com a ordem em que as linhas foram encadeadas. Uma
-- sequência promete as três coisas de graça: é estritamente crescente, é
-- atribuída no momento da gravação, e nunca repete.
--
-- Dito de outro jeito: `created_at` responde QUANDO o evento aconteceu, e
-- essa pergunta continua valendo. `seq` responde EM QUE ORDEM as linhas
-- foram encadeadas — e é essa, e só essa, a pergunta que a verificação da
-- cadeia faz. Estavam sendo respondidas pelo mesmo campo, e o campo só sabia
-- responder a primeira.
--
-- ---------------------------------------------------------------------
-- POR QUE O ELO ANTERIOR É "A MAIOR CHAVE MENOR QUE A MINHA"
-- ---------------------------------------------------------------------
-- O valor do DEFAULT de uma coluna é avaliado ANTES de o trigger BEFORE
-- INSERT rodar. Ou seja: dentro de `fn_calcular_hash_ledger` a linha já sabe
-- o próprio `seq`, e isso permite trocar a pergunta "qual é a ÚLTIMA linha
-- da tabela?" por "qual é a linha IMEDIATAMENTE ANTERIOR A MIM?".
--
--     where seq < new.seq order by seq desc limit 1
--
-- A diferença é a que separa esta migration de um remendo. "A última linha"
-- é uma pergunta sobre o estado global da tabela, e a resposta pode não ser
-- o predecessor que a verificação vai atribuir a esta linha: se por qualquer
-- caminho existir uma linha commitada com `seq` MAIOR que o meu, encadear
-- nela reproduz o defeito da 005 numa roupagem nova — encadeio em quem a
-- `lag()` vai colocar DEPOIS de mim. "A maior chave menor que a minha" é a
-- definição do predecessor no mesmo vocabulário que a verificação usa
-- (`lag(...) over (order by seq)`), então as duas não têm como discordar.
--
-- Isso também absorve os BURACOS da sequência, que são inevitáveis:
-- `nextval` não volta atrás em rollback, então toda transação abortada
-- depois de tocar o ledger queima um número. Um buraco não quebra nem o
-- encadeamento nem a verificação — os dois falam em "anterior", não em
-- "menos um".
--
-- ---------------------------------------------------------------------
-- O ADVISORY LOCK CONTINUA SENDO PEÇA DA CORREÇÃO — não afrouxar
-- ---------------------------------------------------------------------
-- `seq` sozinho NÃO fecha a corrida; ele a fecha JUNTO com a serialização
-- que já existe. Quem escreve no ledger é uma função só —
-- `fn_check_teto_capital` (017), em três ramos —, e cada um dos três abre
-- com `pg_advisory_xact_lock(hashtext('orgcred_capital_gate'))` ANTES do
-- INSERT. O lock é de TRANSAÇÃO: só cai no commit. E como o `nextval` do
-- default de `seq` é avaliado dentro do INSERT, ou seja, já sob o lock, a
-- transação seguinte nem chega a tirar seu número antes de a anterior
-- commitar. Daí decorrem, nesta ordem: os `seq` saem na ordem dos commits;
-- quando uma transação lê o elo anterior, a linha de quem a precede JÁ ESTÁ
-- COMMITADA e portanto visível em READ COMMITTED; e o predecessor que ela
-- encadeia é exatamente o mesmo que a `lag()` vai lhe atribuir. (
-- `fn_novar_operacao` (006) e `fn_check_reducao_capital` (017) tomam o mesmo
-- lock sem inserir no ledger — a linha delas nasce do trigger, já dentro da
-- seção crítica.)
--
-- Tire o lock e a cadeia volta a acusar sozinha, por um caminho novo: T1
-- tira `seq` = 5 e não commita; T2 tira 6, não ENXERGA a linha 5 (READ
-- COMMITTED), encadeia em 4 e commita; T1 commita. A `lag()` põe 5 entre 4 e
-- 6, e a linha 6 é acusada de cadeia rompida sem ninguém ter tocado nela.
-- Isso foi medido, não deduzido: duas transações sobrepostas inserindo
-- direto em `capital_ledger`, fora do gate, produzem exatamente 1 acusação
-- falsa.
--
-- "A maior chave menor que a minha" reduz o estrago desse cenário pela
-- metade, e é por isso que ela está aqui em vez de "a última linha": se uma
-- linha commitada com `seq` MAIOR que o meu já existir quando eu leio,
-- encadear nela me faria apontar para quem a `lag()` vai colocar DEPOIS de
-- mim, e o resultado seriam 2 linhas acusadas em vez de 1 (também medido).
-- Reduzir não é eliminar: o que elimina é o lock. Quem for mexer na
-- serialização do gate está mexendo na hash-chain, e
-- `test_todo_insert_no_ledger_acontece_sob_o_advisory_lock` está lá para
-- dizer isso em voz alta.
--
-- ---------------------------------------------------------------------
-- O BACKFILL É A PARTE PERIGOSA — e o que ele NÃO faz
-- ---------------------------------------------------------------------
-- `created_at` ENTRA NO DIGEST (005:66), e os hashes já gravados foram
-- calculados sobre a ordem `(created_at, id)`. Um backfill que numerasse as
-- linhas em qualquer outra ordem faria a verificação percorrer a cadeia por
-- um caminho diferente daquele em que ela foi construída — ou seja,
-- "consertar" a cadeia INVALIDARIA a cadeia, o oposto exato do objetivo.
-- Daí o `row_number() over (order by created_at, id)`: não é uma ordem
-- razoável escolhida entre outras, é A ordem sobre a qual cada hash
-- histórico foi computado.
--
-- Havia uma alternativa mais esperta: percorrer a própria cadeia
-- (`prev_hash` -> `current_hash`) e numerar as linhas na ordem REAL de
-- inserção, o que faria até as linhas historicamente invertidas passarem a
-- verificar como íntegras. Ela foi recusada de propósito. Seguir a cadeia
-- para decidir a ordem significa deduzir a ordem A PARTIR dos hashes — e num
-- histórico genuinamente adulterado a cadeia não fecha, obrigando a migration
-- a adivinhar; pior, onde ela fechasse, o resultado seria uma cadeia que
-- passa a verificar limpa porque foi REORDENADA para isso. É indistinguível
-- de encobrir a adulteração.
--
-- Então o contrato desta migration é estreito e explícito: ela NÃO reescreve
-- o veredito do histórico — preserva-o, linha por linha, inclusive os falsos
-- positivos que porventura já existam nele. O que ela conserta é o FUTURO:
-- daqui em diante `seq` é atribuído na gravação e a inversão não tem por
-- onde acontecer. (Isso inclui o caso das duas linhas de ledger gravadas na
-- MESMA transação, que hoje empatam no `created_at` e têm a ordem relativa
-- decidida por um `id` uuid4 aleatório: com `seq`, passam a ter ordem.)
--
-- NENHUM HASH É RECALCULADO AQUI, e nenhum byte do digest muda: `seq` NÃO
-- entra no digest. Entrar seria invalidar a cadeia inteira de uma vez —
-- todos os hashes existentes foram calculados sem ele.
--
-- NENHUM SQLSTATE NOVO. As guardas append-only (OC007) continuam as mesmas.

-- ---------------------------------------------------------------------
-- 1. A coluna e a sequência que a alimenta
-- ---------------------------------------------------------------------
-- A coluna nasce NULA-ÁVEL e SEM default: precisa existir vazia para o
-- backfill do passo 2 poder preenchê-la na ordem histórica. Criá-la já com
-- `default nextval(...)` faria o Postgres reescrever a tabela atribuindo os
-- números na ordem FÍSICA do heap — que não tem relação nenhuma com
-- `(created_at, id)` e destruiria a cadeia em silêncio.
alter table capital_ledger
    add column if not exists seq bigint;

-- `owned by` amarra a sequência à coluna: se a coluna for derrubada (o
-- downgrade da 0020 faz isso), a sequência vai junto em vez de ficar órfã.
create sequence if not exists capital_ledger_seq_seq owned by capital_ledger.seq;

-- ---------------------------------------------------------------------
-- 2. Backfill na ordem sobre a qual os hashes vigentes foram calculados
-- ---------------------------------------------------------------------
-- Este UPDATE esbarra na guarda append-only da 005 (`trg_bloquear_update_ledger`,
-- OC007) — que é o comportamento correto dela: a guarda não sabe distinguir
-- "preencher uma coluna nova de metadado" de "reescrever um valor do ledger",
-- e não deveria mesmo saber. Desligá-la aqui é uma decisão consciente, e vem
-- com três limites:
--
--   - o desligamento é TRANSACIONAL (`alter table ... disable trigger` é
--     revertido pelo rollback), então uma falha no meio desta migration não
--     deixa o ledger destravado;
--   - é cirúrgico: só o trigger de UPDATE, não `disable trigger all` nem
--     `disable trigger user` — o de DELETE e o de TRUNCATE (016) seguem de pé;
--   - o UPDATE toca EXCLUSIVAMENTE a coluna `seq`. Nenhuma coluna do digest é
--     escrita, e por isso nenhum `current_hash` deixa de bater com o
--     recalculado depois daqui. O teste
--     `test_hashes_gravados_antes_da_020_continuam_identicos` compara o
--     antes e o depois hash a hash em vez de acreditar nesta frase.
alter table capital_ledger disable trigger trg_bloquear_update_ledger;

update capital_ledger l
set seq = ordenado.n
from (
    select id, row_number() over (order by created_at, id) as n
    from capital_ledger
) ordenado
where ordenado.id = l.id
  and l.seq is distinct from ordenado.n;

alter table capital_ledger enable trigger trg_bloquear_update_ledger;

-- ---------------------------------------------------------------------
-- 3. A sequência assume daqui para a frente
-- ---------------------------------------------------------------------
-- `setval(..., max+1, false)` posiciona a sequência para que o PRÓXIMO
-- `nextval` devolva max+1 — ou seja, a primeira linha nova continua de onde
-- o histórico parou. O `coalesce(..., 0)` cobre o ledger vazio (base nova),
-- em que a primeira linha recebe 1.
select setval('capital_ledger_seq_seq', coalesce((select max(seq) from capital_ledger), 0) + 1, false);

alter table capital_ledger
    alter column seq set default nextval('capital_ledger_seq_seq');

-- `not null` só DEPOIS do backfill, e é o que impede a cadeia de nascer sem
-- âncora: um INSERT que passe `seq => null` explicitamente encontraria
-- `where seq < null` (nenhuma linha), gravaria `prev_hash` nulo no meio da
-- cadeia e a quebraria. Com a restrição, esse INSERT simplesmente não entra.
alter table capital_ledger
    alter column seq set not null;

-- Unicidade não é decoração: dois `seq` iguais dariam DOIS predecessores
-- possíveis para a mesma linha, e a `lag()` escolheria um deles de forma não
-- determinística — a verificação passaria a devolver resultados diferentes
-- para o mesmo ledger.
create unique index if not exists capital_ledger_seq_unico
    on capital_ledger (seq);

comment on column capital_ledger.seq is
    'Ordem de GRAVAÇÃO da linha na hash-chain (migration 020). É por ela que a cadeia é encadeada e verificada — não por created_at, que é o instante de ABERTURA da transação (now() = transaction_timestamp) e pode inverter entre transações sobrepostas. Buracos são normais: nextval não volta atrás em rollback.';

-- ---------------------------------------------------------------------
-- 4. O encadeamento passa a olhar para `seq`
-- ---------------------------------------------------------------------
-- Cópia integral da versão vigente (005:46-72) com DUAS mudanças: a busca do
-- elo anterior, e a autoria de `created_at` (logo abaixo). O digest é
-- reproduzido caractere a caractere, `created_at` inclusive — qualquer
-- alteração aqui invalidaria todos os hashes já gravados, porque o
-- `fn_verificar_cadeia_ledger` recalcula os antigos com a fórmula nova.
--
-- QUEM ESCREVE `created_at` É O BANCO — e isto NÃO é zelo cosmético, é o
-- fechamento de um buraco que a própria 020 abriria. Até a 019 a cadeia era
-- percorrida por `created_at`, e isso, por acidente, AMARRAVA o carimbo à
-- posição: uma linha nova gravada com `created_at` retroativo encadeava no
-- hash da última linha mas era reordenada para o passado pela verificação,
-- que acusava a quebra. Ancorar a cadeia em `seq` desfaz esse amarrio —
-- `seq` diz onde a linha está, e nada mais confere o que ela DIZ sobre
-- quando aconteceu. Sem esta linha, quem tivesse apenas privilégio de
-- INSERT (nenhum `disable trigger`, nenhum UPDATE, nenhum DELETE) poderia
-- acrescentar um lançamento forjado carimbado com qualquer data do passado,
-- e a cadeia o declararia ÍNTEGRO — o trigger calcularia o digest sobre o
-- `created_at` que o próprio atacante forneceu. Numa tabela que é prova
-- documental de conformidade com o teto do Art. 5º da LC 167/2019, um
-- lançamento antedatado que passa na verificação é exatamente o artefato
-- que a verificação existe para tornar impossível.
--
-- `now()` aqui é o MESMO valor que o default da coluna já produzia (é o
-- default desde a 001), então nenhum caminho legítimo muda de comportamento:
-- os nove `insert into capital_ledger` das migrations 001-017 omitem
-- `created_at` justamente porque o default basta. O que muda é que passar a
-- coluna explicitamente deixa de ter efeito — `created_at` passa a ser
-- escrito pelo banco pelo mesmo motivo que `prev_hash`, `current_hash` e
-- `seq` são: numa trilha append-only, o dado que entra no digest não pode
-- ser ditado por quem escreve.
--
-- (Quem um dia precisar IMPORTAR histórico com datas próprias continua
-- podendo: importação de lastro é migration, e migration desliga trigger —
-- o que a torna um ato explícito e auditável, em vez de um INSERT comum.)
create or replace function fn_calcular_hash_ledger()
returns trigger as $$
declare
    v_prev_hash varchar(64);
begin
    new.created_at := now();

    -- O elo anterior é "a maior chave MENOR que a minha", e não "a última
    -- linha da tabela": é a mesma definição de predecessor que a
    -- `lag(...) over (order by seq)` da verificação usa, então as duas não
    -- têm como discordar. `new.seq` já está disponível porque o default da
    -- coluna é avaliado antes deste trigger.
    select current_hash into v_prev_hash
    from capital_ledger
    where seq < new.seq
    order by seq desc
    limit 1;

    new.prev_hash := v_prev_hash;
    new.current_hash := encode(
        digest(
            coalesce(v_prev_hash, '') || '|' ||
            new.evento_tipo || '|' ||
            new.valor::text || '|' ||
            coalesce(new.operacao_id::text, '') || '|' ||
            new.saldo_disponivel_pos::text || '|' ||
            coalesce(new.usuario_id, '') || '|' ||
            new.created_at::text,
            'sha256'
        ),
        'hex'
    );
    return new;
end;
$$ language plpgsql;

-- ---------------------------------------------------------------------
-- 5. A verificação passa a percorrer a cadeia por `seq`
-- ---------------------------------------------------------------------
-- Cópia integral da versão vigente (005:92-146) com UMA mudança: a janela da
-- `lag()` ordena por `seq` em vez de `(created_at, id)`. O digest recalculado
-- segue idêntico ao do trigger acima — as duas fórmulas são a mesma prova
-- escrita duas vezes, e divergir uma da outra faria a verificação acusar o
-- ledger inteiro.
--
-- O que NÃO mudou, e é o ponto: os dois motivos continuam existindo e
-- continuam significando o que significavam. `prev_hash` que não bate com o
-- predecessor segue sendo cadeia rompida; `current_hash` que não bate com o
-- recalculado segue sendo linha reescrita. O que a 020 tira de circulação é
-- só o falso positivo — cadeia intacta acusada por causa da ORDEM em que a
-- verificação a percorria.
create or replace function fn_verificar_cadeia_ledger()
returns table(id uuid, motivo text) as $$
begin
    return query
    with ordenado as (
        select
            l.id,
            l.evento_tipo,
            l.valor,
            l.operacao_id,
            l.saldo_disponivel_pos,
            l.usuario_id,
            l.created_at,
            l.prev_hash,
            l.current_hash,
            lag(l.current_hash) over (order by l.seq) as hash_anterior_esperado
        from capital_ledger l
    )
    select
        o.id,
        case
            when o.prev_hash is distinct from o.hash_anterior_esperado
                then 'prev_hash não corresponde ao current_hash da linha anterior'
            when o.current_hash is distinct from encode(
                digest(
                    coalesce(o.prev_hash, '') || '|' ||
                    o.evento_tipo || '|' ||
                    o.valor::text || '|' ||
                    coalesce(o.operacao_id::text, '') || '|' ||
                    o.saldo_disponivel_pos::text || '|' ||
                    coalesce(o.usuario_id, '') || '|' ||
                    o.created_at::text,
                    'sha256'
                ),
                'hex'
            ) then 'current_hash não bate com o recalculado — linha possivelmente adulterada'
            else null
        end as motivo
    from ordenado o
    where o.prev_hash is distinct from o.hash_anterior_esperado
       or o.current_hash is distinct from encode(
            digest(
                coalesce(o.prev_hash, '') || '|' ||
                o.evento_tipo || '|' ||
                o.valor::text || '|' ||
                coalesce(o.operacao_id::text, '') || '|' ||
                o.saldo_disponivel_pos::text || '|' ||
                coalesce(o.usuario_id, '') || '|' ||
                o.created_at::text,
                'sha256'
            ),
            'hex'
        );
end;
$$ language plpgsql stable;

comment on function fn_verificar_cadeia_ledger() is
    'Recalcula e valida a cadeia de hash do capital_ledger, percorrendo-a por capital_ledger.seq (migration 020 — antes era por created_at, que é o instante de abertura da transação e invertia entre transações sobrepostas, acusando adulteração inexistente). SELECT * FROM fn_verificar_cadeia_ledger() — 0 linhas = íntegro.';

-- ---------------------------------------------------------------------
-- 6. `created_at` CONTINUA com default `now()` — decisão, não esquecimento
-- ---------------------------------------------------------------------
-- Trocar por `clock_timestamp()` melhoraria a fidelidade do horário
-- registrado, e o argumento a favor é real: hoje dois eventos gravados na
-- mesma transação recebem carimbos IDÊNTICOS. Ainda assim, não se troca
-- aqui, por três razões que se somam.
--
-- PRIMEIRA: o problema que a troca resolveria já está resolvido por esta
-- migration, e melhor. Quem lê a trilha e precisa ordenar dois eventos do
-- mesmo instante agora tem `seq`, que é a ordem REAL de gravação. O
-- `clock_timestamp()` daria uma ordem apenas CORRELACIONADA com ela, e com
-- precisão limitada pelo relógio.
--
-- SEGUNDA: `created_at` está DENTRO do digest, e a coluna passaria a ter
-- dois significados no mesmo ledger — "instante em que a transação abriu"
-- nas linhas anteriores à 020, "instante em que a linha foi gravada" nas
-- posteriores — sem nada na linha dizendo qual dos dois ela guarda. Numa
-- tabela cuja função é ser prova documental, uma coluna com dois significados
-- indistinguíveis é um passivo, não uma melhoria. (Os hashes continuariam
-- válidos nos dois casos — o digest usa o valor gravado, seja ele qual for.
-- O custo é de interpretação, não de integridade.)
--
-- TERCEIRA, e a mais concreta: a troca DESTRUIRIA o cenário que prova esta
-- correção. `TestOrdemDaCadeiaSobTransacoesSobrepostas`, em
-- tests/test_ledger_integrity.py, produz a inversão exatamente porque
-- `created_at` é o `transaction_timestamp()`. Com `clock_timestamp()` os
-- carimbos sairiam em ordem, o cenário evaporaria, e a suíte deixaria de ter
-- como demonstrar que a cadeia sobrevive a uma gravação fora de ordem —
-- inclusive contra um refactor futuro que voltasse a ordená-la por tempo.
-- Manter `now()` é o que mantém o defeito REPRODUZÍVEL, e um defeito
-- reproduzível é a única forma de garantir que ele não volta.
comment on column capital_ledger.created_at is
    'Instante de ABERTURA da transação que gravou a linha (now() = transaction_timestamp). Escrito pelo BANCO: fn_calcular_hash_ledger sobrescreve o que o INSERT tenha passado (migration 020) — a cadeia é percorrida por seq, então nada mais amarraria o carimbo à posição, e um INSERT antedatado passaria na verificação. Deliberadamente NÃO é clock_timestamp: a ordem da hash-chain é dada por capital_ledger.seq, e manter now() aqui é o que mantém reproduzível, em teste, a gravação fora de ordem que a 020 corrigiu.';
