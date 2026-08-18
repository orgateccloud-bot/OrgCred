-- OrgCred — o sistema passa a SABER quando as próprias rotinas rodaram
--
-- O QUE ESTAVA ERRADO, em uma frase: as quatro rotinas (aging, atipicidades,
-- backup, restore_test) rodam num serviço de cron e não deixavam UM ÚNICO
-- registro no banco. O app não sabia quando a última tinha rodado.
--
-- A consequência não é "falta um canal de alerta". É que a detecção de
-- incidente ficava terceirizada para fora do sistema: só descobria que o cron
-- parou quem abrisse o painel do Railway. E o modo de falha mais perigoso
-- destas rotinas nem chega a produzir uma execução vermelha lá — é a ausência
-- de execução. Um serviço de cron que deixa de ser agendado, uma imagem que
-- sobe sem o comando, um deploy que renomeia o serviço: nada disso FALHA.
-- Simplesmente para de acontecer, e um painel de execuções não tem como
-- mostrar a execução que não houve.
--
-- Por isso a régua de 90 dias podia parar de declarar inadimplência, a
-- varredura de PLD podia parar de detectar e o backup podia parar de ser
-- feito, os três em silêncio, com o app inteiro verde ao lado.
--
-- O QUE ESTA MIGRATION FAZ: cria a trilha em que cada execução se registra, e
-- com isso troca a pergunta "houve uma falha?" (que ninguém consegue fazer
-- sobre o que não aconteceu) pela pergunta "HÁ QUANTO TEMPO?" — que tem
-- resposta mesmo quando não houve execução nenhuma, porque a ausência de linha
-- É a resposta. Sabendo o próprio estado, o sistema o mostra sozinho; um canal
-- externo (e-mail, Slack) passa a ser incremento, não pré-requisito.
--
-- ---------------------------------------------------------------------
-- QUAL CARIMBO DE TEMPO — a lição da 020, aplicada aqui
-- ---------------------------------------------------------------------
-- A 020 escreveu duas coisas que valem inteiras nesta tabela:
--
--   (1) `now()` É `transaction_timestamp()` — o instante em que a transação
--       ABRIU, não aquele em que a linha foi gravada. Numa trilha de rotinas
--       isso não é sutileza: se as quatro execuções do plano do dia fossem
--       gravadas numa transação só, as quatro receberiam o MESMO carimbo, e
--       ele seria o do começo de tudo. Um backup de 28 minutos apareceria
--       como registrado 28 minutos antes de ter terminado — e é exatamente a
--       distância entre carimbos que esta tabela existe para medir. Daí
--       `clock_timestamp()`: o instante real da gravação, linha a linha.
--
--   (2) QUEM ESCREVE NÃO DITA O CARIMBO. Um DEFAULT é só um default: o INSERT
--       pode passar outro valor e a guarda append-only não recusa — ela recusa
--       UPDATE e DELETE, não uma linha nova com data escolhida. Numa trilha
--       cuja única pergunta é "há quanto tempo?", um carimbo ditado por quem
--       escreve é o mesmo que carimbo nenhum: bastaria o cron (ou qualquer
--       coisa com INSERT) gravar uma execução com data de hoje para a tela
--       dizer que o backup está em dia sem que backup nenhum tenha havido.
--       Daí `fn_execucao_rotina_carimbo()`, BEFORE INSERT, que SOBRESCREVE o
--       que o INSERT tenha passado — o mesmo `new.created_at := now()` que a
--       020 instalou no ledger, pelo mesmo motivo e com o relógio certo.
--
-- E O INÍCIO DA EXECUÇÃO? Ele NÃO é uma coluna, e isso é decisão, não
-- esquecimento. O início é um fato que só a aplicação conhece (a rotina rodou
-- 28 minutos antes de haver o que gravar), então o banco não tem como carimbá-
-- lo — e uma coluna `iniciada_em` escrita pela aplicação seria justamente o
-- carimbo ditado que o parágrafo acima recusa. O início é DERIVADO na leitura:
--
--     iniciada_em = registrada_em - duracao_s
--
-- `registrada_em` é do banco e `duracao_s` é medida em relógio MONOTÔNICO pelo
-- executor (`time.monotonic`, app/rotinas.py) — imune a ajuste de NTP e a
-- fuso. O que sobra ao alcance de quem escreve é mentir na duração, e essa
-- mentira só desloca o INÍCIO; a âncora de frescor continua sendo
-- `registrada_em`. Como em 023 (min() e não max()), o lado do erro que
-- permanece possível é o inofensivo: uma duração inflada faz a execução
-- parecer ter começado antes, nunca faz uma rotina parada parecer recente.
--
-- ---------------------------------------------------------------------
-- TRÊS RESULTADOS, E NÃO UM BOOLEANO
-- ---------------------------------------------------------------------
-- 'sucesso' | 'falha' | 'dispensada'.
--
-- A terceira existe por causa do restore-test, e sem ela a trilha mentiria
-- todo dia. O restore-test é MENSAL: em ~30 dos 31 dias o executor olha para
-- ele, vê que a competência já está coberta e devolve `executado: False` —
-- uma execução que terminou bem e não fez nada. Registrada como 'sucesso',
-- ela renovaria o relógio de frescor diariamente, e a tela diria "restore-test
-- em dia" sobre um teste de restauração que pode não acontecer há meses. Seria
-- a mesma cobertura de fachada que esta migration existe para acabar, só que
-- agora com um registro no banco para sustentá-la.
--
-- Registrada como 'dispensada', ela conta a verdade em duas partes: o cron
-- ESTEVE aqui hoje (e isso se lê na trilha) e o teste NÃO foi feito hoje (e o
-- relógio do restore-test continua correndo desde a última restauração de
-- verdade). Quem pergunta "há quanto tempo?" ignora as dispensadas — é o que
-- `app/routers/auditoria.py` faz.
--
-- `erro` é NOT NULL exatamente quando `resultado = 'falha'`, por CHECK. Uma
-- falha sem texto é uma linha vermelha que não diz o que houve — e o operador
-- que a encontrar às 3h precisa da mensagem, não do fato. O outro lado da
-- disjunção proíbe erro em execução bem-sucedida, que só poderia ser lixo de
-- retentativa colado na linha errada.
--
-- ---------------------------------------------------------------------
-- NOVO SQLSTATE: OC023 = execução de rotina é append-only
-- ---------------------------------------------------------------------
-- É o próximo livre. OC022 (017) é o último atribuído; OC023 chegou a ser
-- cogitado na 021 e recusado lá ("exigiria exceção nova e entrada nova de mapa
-- para um caminho que a UI não tem"), sem nunca ter sido gravado no banco.
--
-- ELE NÃO ENTRA EM `app/core/db_errors.py`, e isso é a aplicação do critério
-- que o próprio arquivo escreve, não um esquecimento. O mapa é o contrato de
-- erro do que o OPERADOR alcança pela tela; OC020 e OC021 ficam de fora de
-- propósito porque só são alcançáveis por SQL direto. OC023 é igual: nenhum
-- endpoint altera ou apaga execução de rotina, e nem vai — a trilha é escrita
-- por um processo e lida por outro. Mapeá-lo criaria uma mensagem de UI para
-- um caminho que a UI não tem.
--
-- A guarda existe mesmo assim, e não é decoração: uma trilha que pode ser
-- editada não é trilha. Se `registrada_em` pudesse ser reescrito, o único dado
-- que esta tabela guarda — a distância até agora — passaria a ser opinião.

-- ---------------------------------------------------------------------
-- A tabela
-- ---------------------------------------------------------------------
create table if not exists execucao_rotina (
    id            uuid primary key default uuid_generate_v4(),

    -- O nome tal como o executor o conhece (app/rotinas.py: ROTINAS_CONHECIDAS).
    -- SEM check de domínio, de propósito: uma lista fechada aqui faria a
    -- inclusão de uma quinta rotina depender de migration, e o modo de falha
    -- dessa dependência é o pior possível — o cron rodaria a rotina nova, o
    -- INSERT seria recusado, e a rotina passaria a existir sem NUNCA aparecer
    -- na tela de estado. Quem decide o que é rotina conhecida é o executor; o
    -- que chega aqui com nome estranho aparece como rotina desconhecida na
    -- leitura, que é ruído visível — e ruído visível é melhor que uma trilha
    -- que recusa o que deveria testemunhar.
    rotina        text        not null,

    resultado     text        not null,

    -- Duração medida em relógio monotônico pelo executor. `numeric` e não
    -- `interval` porque é o que o Python já produz (segundos com 3 casas) e o
    -- que a tela compara com o teto de tempo das rotinas (TIMEOUT_BACKUP_S).
    duracao_s     numeric(12, 3) not null,

    -- O QUE a rotina fez: `{"transicionadas": 3, "limite_dias": 90}`,
    -- `{"novas_ocorrencias": 7, ...}`, `{"executado": false, "motivo": ...}`.
    -- jsonb porque o conteúdo é diferente por rotina e não há forma que sirva
    -- às quatro; é o MESMO dicionário que já ia para o log estruturado, agora
    -- num lugar que sobrevive à rotação de log.
    detalhe       jsonb       not null default '{}'::jsonb,

    -- Só em 'falha' — ver o CHECK abaixo.
    erro          text,

    -- ESCRITO PELO BANCO (trg_execucao_rotina_carimbo). O default está aqui
    -- para o NOT NULL não depender do trigger, mas não é ele que decide o
    -- valor: quem decide é o trigger, que sobrescreve inclusive o que o INSERT
    -- passar explicitamente.
    registrada_em timestamptz not null default clock_timestamp(),

    constraint execucao_rotina_resultado_valido
        check (resultado in ('sucesso', 'falha', 'dispensada')),

    -- `is not null` explícito antes do texto, e a disjunção fechando os dois
    -- lados: é a mesma forma da 024 (movimento_proveniencia_coerente), pelo
    -- mesmo motivo — em SQL um CHECK que resulta NULL PASSA.
    constraint execucao_rotina_erro_coerente
        check (
            (resultado =  'falha' and erro is not null and erro <> '')
            or
            (resultado <> 'falha' and erro is null)
        ),

    -- Duração negativa não é dado ruim, é relógio andando para trás — e uma
    -- negativa faz `iniciada_em` derivado cair DEPOIS de `registrada_em`.
    constraint execucao_rotina_duracao_nao_negativa
        check (duracao_s >= 0)
);

comment on table execucao_rotina is
    'Trilha append-only (OC023) de execuções das rotinas periódicas (app/rotinas.py). Uma linha por rotina por execução, gravada DEPOIS do fato. É a fonte da resposta "há quanto tempo a rotina X rodou pela última vez?" — a pergunta que detecta a rotina que PAROU DE RODAR, que nenhum painel de execuções consegue mostrar porque a execução ausente não produz linha em lugar nenhum.';

comment on column execucao_rotina.registrada_em is
    'Instante em que a linha foi GRAVADA (clock_timestamp), escrito pelo BANCO: fn_execucao_rotina_carimbo sobrescreve o que o INSERT passar. É a âncora do cálculo de atraso — ditá-la pela aplicação faria "rotina em dia" ser auto-declaração, exatamente como o carimbo do capital_ledger antes da migration 020.';

comment on column execucao_rotina.resultado is
    'sucesso | falha | dispensada. "dispensada" é a execução que terminou bem sem fazer o trabalho — o restore-test nos ~30 dias do mês em que a competência já está coberta. Ela NÃO renova o relógio de frescor: contá-la como sucesso faria a tela dizer "restore-test em dia" sobre um teste de restauração que pode não acontecer há meses.';

comment on column execucao_rotina.duracao_s is
    'Segundos medidos em relógio MONOTÔNICO pelo executor (time.monotonic) — imune a ajuste de NTP e a fuso. O início da execução é derivado dela na leitura (registrada_em - duracao_s) em vez de ser uma coluna: início é fato que só a aplicação conhece, e coluna escrita pela aplicação seria o carimbo ditado que esta trilha recusa.';

-- A consulta desta tabela é sempre a mesma e sempre por rotina: "a última
-- linha de cada uma". O índice a serve inteira — o planner desce pelo lado
-- direito de cada `rotina` e para na primeira linha.
create index if not exists idx_execucao_rotina_recente
    on execucao_rotina (rotina, registrada_em desc);

-- ---------------------------------------------------------------------
-- O carimbo é do banco
-- ---------------------------------------------------------------------
create or replace function fn_execucao_rotina_carimbo()
returns trigger as $$
begin
    new.registrada_em := clock_timestamp();
    return new;
end;
$$ language plpgsql;

comment on function fn_execucao_rotina_carimbo() is
    'BEFORE INSERT em execucao_rotina: registrada_em passa a ser clock_timestamp() do banco, sobrescrevendo o que a aplicação tenha passado. clock_timestamp e não now(): now() é o instante de ABERTURA da transação e daria o mesmo carimbo às quatro rotinas do plano se elas compartilhassem transação.';

drop trigger if exists trg_execucao_rotina_carimbo on execucao_rotina;
create trigger trg_execucao_rotina_carimbo
    before insert on execucao_rotina
    for each row execute function fn_execucao_rotina_carimbo();

-- ---------------------------------------------------------------------
-- Append-only (OC023)
-- ---------------------------------------------------------------------
create or replace function fn_execucao_rotina_append_only()
returns trigger as $$
begin
    raise exception 'execucao_rotina é append-only: % não é permitido.', tg_op
        using errcode = 'OC023';
end;
$$ language plpgsql;

comment on function fn_execucao_rotina_append_only() is
    'OC023 — a trilha de execução de rotina não se edita nem se apaga. Reescrever registrada_em transformaria a única informação que a tabela guarda (a distância até agora) em opinião de quem escreve.';

drop trigger if exists trg_execucao_rotina_append_only on execucao_rotina;
create trigger trg_execucao_rotina_append_only
    before update or delete on execucao_rotina
    for each row execute function fn_execucao_rotina_append_only();

-- TRUNCATE não visita linhas e por isso atravessa a guarda acima — mesma
-- limitação que a 016 fechou para as outras cinco trilhas, e a função dela é
-- reusada aqui com o SQLSTATE desta tabela em TG_ARGV. Sem esta linha, `delete
-- from execucao_rotina` seria recusado com OC023 e `truncate table
-- execucao_rotina` apagaria a mesma coisa em silêncio — devolvendo o sistema
-- ao estado exato de antes desta migration, com a tela dizendo "nunca
-- executou" e ninguém sabendo por quê.
drop trigger if exists trg_bloquear_truncate_execucao_rotina on execucao_rotina;
create trigger trg_bloquear_truncate_execucao_rotina
    before truncate on execucao_rotina
    for each statement execute function fn_bloquear_truncate_append_only('OC023');
