-- OrgCred — a identidade da conta, e a baixa só em cobrança
--
-- A 027 fechou três altos de cobrança e ABRIU UM CRÍTICO no mesmo commit. Esta
-- migration existe por causa disso, e o cabeçalho começa pelo erro porque ele é
-- mais instrutivo que o conserto.
--
-- ---------------------------------------------------------------------
-- (0) O QUE A 027 ERROU, e por que a verificação dela não viu
-- ---------------------------------------------------------------------
-- A 027 trocou `unique (documento)` por `unique nulls not distinct (documento,
-- conta_origem)` com o argumento — correto — de que o FITID é único DENTRO da
-- conta e não no universo. O erro está numa premissa que ela nunca enunciou:
-- que `conta_origem` IDENTIFICA a conta. Não identifica. É a GRAFIA que o
-- arquivo trouxe. `_formatar_conta` (app/ofx.py) devolve `BANKID/ACCTID`,
-- `ACCTID` ou `BANKID`, verbatim, sem normalizar nada:
--
--     mesmo extrato, mesma conta, mesmos FITIDs, duas exportações
--       com <BANKID>001  ->  conta_origem = '001/123456'
--       sem <BANKID>     ->  conta_origem = '123456'
--
--     dois espaços de nomes distintos -> as duas importações CRIAM
--     -> R$ 31.514,86 recebidos viram R$ 63.029,72 de lastro
--     -> as quatro parcelas ficam quitadas contra dinheiro que não entrou
--     -> `liquidar` é aceito (OC022 pede exatamente "todas as parcelas pagas")
--     -> o comprometido volta a ZERO com principal na rua
--
-- É o furo do teto do Art. 5º reaberto pela porta do extrato, sem má-fé: duas
-- exportações do mesmo mês em sessões diferentes do internet banking bastam. E
-- a aritmética do relatório de importação FECHA nas duas — a mesma propriedade
-- que a 027 dizia estar consertando.
--
-- POR QUE A VERIFICAÇÃO DA 027 NÃO PEGOU, que é a parte que interessa: ela
-- perguntou "mesmo FITID em contas DIFERENTES entra?" e comemorou o sim. Nunca
-- perguntou "e quando é a MESMA conta escrita de dois jeitos?". Uma guarda
-- verificada só na direção em que ela foi desenhada não foi verificada.
--
-- ---------------------------------------------------------------------
-- (1) A CHAVE PASSA A SER A IDENTIDADE, E A GRAFIA VIRA PROVENIÊNCIA
-- ---------------------------------------------------------------------
-- `conta_origem` FICA como está e continua sendo o que o arquivo disse — é
-- proveniência, é o que a tela mostra, e apagá-la destruiria a única pista de
-- qual exportação trouxe a linha. O que muda é que ela deixa de ser metade da
-- CHAVE. Entra `conta_chave`, coluna GERADA pelo banco a partir dela.
--
-- POR QUE GERADA, E NÃO ESCRITA PELA APLICAÇÃO: é a mesma disciplina do resto
-- do motor. Se Python calculasse a chave e a enviasse, a regra passaria a viver
-- em dois lugares e o banco aceitaria qualquer valor que o cliente mandasse —
-- inclusive um que separasse o que deveria unir. Gerada, a canonização é
-- função do dado gravado e nenhum cliente pode discordar dela.
--
-- A CANONIZAÇÃO DESCARTA O BANKID DA CHAVE, e esta é a decisão central:
--
--   - o caso que quebrou é a MESMA conta com o BANKID presente numa exportação
--     e ausente noutra. Enquanto o BANKID fizer parte da chave, as duas grafias
--     são espaços de nomes distintos e o lastro dobra. Não há canonização de
--     string que faça '001/123456' e '123456' coincidirem SEM descartar o
--     BANKID: a informação está presente num arquivo e ausente no outro;
--
--   - o número da conta, esse, quase nunca varia entre exportações do mesmo
--     banco. O que varia é pontuação e zero à esquerda ('12345-6' contra
--     '123456', '0123' contra '123'), e isso a canonização resolve;
--
--   - O CUSTO ASSUMIDO, escrito aqui para não ser descoberto por acidente:
--     dois bancos DIFERENTES com o mesmo número de conta E o mesmo FITID
--     voltam a colidir, e uma linha real seria pulada. É o furo que a 027
--     fechou, reaberto numa janela muito mais estreita — precisa de coincidência
--     em DOIS campos, não em um. E, diferente da 027, ele deixa de ser
--     silencioso: ver o item (2).
--
-- A DIREÇÃO DA DÚVIDA É DELIBERADA e é a mesma do `NULLS NOT DISTINCT` da 027:
-- quando o sistema não tem como saber se duas linhas são a mesma, a resposta
-- segura é tratá-las como a mesma. Duplicar lastro fabrica dinheiro e chega ao
-- teto; pular uma linha deixa um crédito de fora, o que o operador conserta com
-- um lançamento manual — desde que ENXERGUE. A 027 escolheu a direção certa
-- para o caso do NULL e a errada para todos os outros.
create or replace function fn_conta_chave(p_conta text)
returns text as $$
    -- split_part com índice NEGATIVO (PostgreSQL 14+) pega a última parte:
    -- 'BANKID/ACCTID' -> 'ACCTID'; 'ACCTID' -> 'ACCTID'. Depois some tudo que
    -- não é alfanumérico (o hífen do 'agência-dígito'), sobem as maiúsculas
    -- (conta com letra existe em conta de investimento) e caem os zeros à
    -- esquerda.
    --
    -- O `nullif` final não é higiene: uma conta que canoniza para string vazia
    -- (só zeros, só pontuação) não identifica coisa alguma, e devolvê-la como
    -- '' criaria um espaço de nomes fantasma compartilhado por contas que não
    -- têm nada em comum. NULL a joga no espaço dos sem-conta, que é o
    -- conservador — o mesmo destino do lançamento manual.
    select nullif(
        regexp_replace(
            upper(regexp_replace(split_part(p_conta, '/', -1), '[^0-9A-Za-z]', '', 'g')),
            '^0+',
            ''
        ),
        ''
    )
$$ language sql immutable strict;

comment on function fn_conta_chave(text) is
    'Identidade da conta a partir da grafia que o arquivo trouxe: última parte, só alfanumérico, sem zeros à esquerda, maiúsculas. Descarta o BANKID de propósito — ele está presente numa exportação e ausente noutra da MESMA conta, e enquanto estiver na chave o lastro dobra.';

alter table movimento_bancario
    drop column if exists conta_chave;

alter table movimento_bancario
    add column conta_chave text
    generated always as (fn_conta_chave(conta_origem)) stored;

comment on column movimento_bancario.conta_origem is
    'A GRAFIA que o arquivo trouxe (BANKID/ACCTID, ACCTID ou BANKID), verbatim. Proveniência e exibição — NÃO é identidade: a mesma conta aparece escrita de mais de um jeito entre exportações. A identidade é conta_chave.';
comment on column movimento_bancario.conta_chave is
    'Identidade da conta, gerada pelo banco a partir de conta_origem (fn_conta_chave). É esta, e não a grafia, que forma a chave do extrato junto com o documento.';

-- A troca da chave. Mesma cláusula `NULLS NOT DISTINCT` da 027, e pela mesma
-- razão: sem conta declarada — lançamento manual e OFX capado — tudo divide um
-- espaço de nomes só, porque não há como saber se dois FITIDs iguais são a
-- mesma linha ou duas.
--
-- ESTA MIGRATION PODE FALHAR EM BASE COM DADOS, ao contrário da 027, e a falha
-- é o comportamento correto. A chave nova é mais FORTE que a da 027 (une o que
-- ela separava), então linhas que só existiam por causa do defeito violam-na.
-- Falhar é o único jeito honesto de dizer "esta base tem lastro duplicado, e
-- qual das linhas é a real não é decisão de migration". A consulta que mostra
-- os pares está no docstring do upgrade() da revisão 0028.
alter table movimento_bancario
    drop constraint if exists movimento_documento_por_conta;

alter table movimento_bancario
    add constraint movimento_documento_por_conta
    unique nulls not distinct (documento, conta_chave);

comment on constraint movimento_documento_por_conta on movimento_bancario is
    'FITID é único DENTRO da conta — e a conta é a IDENTIDADE (conta_chave), nunca a grafia. Com a grafia na chave, a mesma conta exportada com e sem BANKID dobrava o lastro, e o lastro dobrado quitava a carteira e devolvia o capital ao teto do Art. 5º.';

-- ---------------------------------------------------------------------
-- (2) O QUE FOR PULADO PRECISA SER VISÍVEL
-- ---------------------------------------------------------------------
-- O achado da 027 não era "uma linha se perdeu": era "uma linha se perdeu E A
-- ARITMÉTICA FECHOU". O item (1) estreita a janela da colisão residual, mas não
-- a fecha — e uma janela estreita e silenciosa continua sendo silenciosa.
--
-- Esta view é o que a importação consulta DEPOIS de inserir para separar dois
-- fatos que o `on conflict do nothing` funde num número só: a linha que já
-- estava lá porque é a mesma (reimportação, rotina) e a linha que já estava lá
-- com OUTRO valor ou OUTRA data (colisão de identidade, anomalia). Sem esta
-- separação, `ja_registrados` volta a significar duas coisas — que é
-- exatamente o defeito que este projeto nomeia desde a 016.
--
-- Fica como view e não como lógica em Python porque a comparação é sobre o
-- dado gravado, e quem responde sobre o dado gravado é o banco.
create or replace view v_movimento_por_identidade as
    select id, documento, conta_chave, conta_origem, valor, data_movimento, origem
      from movimento_bancario;

comment on view v_movimento_por_identidade is
    'Movimentos pela identidade (documento, conta_chave), para a importação distinguir reimportação de colisão: mesma chave com valor ou data diferentes é anomalia, não rotina.';

-- ---------------------------------------------------------------------
-- (3) OC026 — A BAIXA EXIGE OPERAÇÃO EM COBRANÇA
-- ---------------------------------------------------------------------
-- `fn_baixar_parcela` (016) pergunta pelo status da PARCELA e nunca pelo da
-- OPERAÇÃO — zero ocorrências de `operacao_credito` no corpo dela. Consequência
-- medida pela porta de produção: consumada uma novação, a agenda do título
-- EXTINTO continua 'aberta', o endpoint devolve 204, o crédito real do tomador
-- é consumido contra uma dívida que já migrou, e a parcela VIVA da substituta
-- passa a ser recusada com OC011 ("movimento já usado"). Não há estorno: o
-- lastro fica preso na parcela errada para sempre.
--
-- O CONJUNTO QUE ACEITA BAIXA É 'ativa' + 'inadimplente', e não é conjunto
-- novo: é "em cobrança", que a 008 já definiu ao montar `v_aging_operacoes` e
-- que o cabeçalho de app/capital_engine.py descreve como o segundo dos DOIS
-- CONJUNTOS QUE DEIXARAM DE SER O MESMO. Reusá-lo aqui é o que mantém uma só
-- resposta para "esta dívida ainda está sendo cobrada?".
--
-- 'baixada_prejuizo' FICA DE FORA, e é a escolha que merece explicação: o
-- write-off encerra a cobrança (017), então receber depois é RECUPERAÇÃO — um
-- fato que este sistema não modela. Aceitar a baixa ali daria a parcela por
-- paga sem devolver capital nenhum ao teto (OC003 não tem saída de
-- 'baixada_prejuizo'), prendendo o dinheiro em silêncio. Recusar deixa o
-- assunto onde ele está: uma decisão de negócio pendente, não um efeito
-- colateral.
--
-- SQLSTATE NOVO pelo critério da 016 — código novo quando a INSTRUÇÃO ao
-- operador é nova. OC011 diria "a baixa não tem lastro bancário válido" a quem
-- tem um lastro perfeitamente válido e está apontando para a dívida errada, e
-- mandaria conferir o extrato, que é o lugar errado. A instrução aqui é outra:
-- a dívida viva é a da operação substituta.
create or replace function fn_operacao_em_cobranca(p_operacao_id uuid)
returns text as $$
declare
    v_status text;
begin
    select status into v_status from operacao_credito where id = p_operacao_id;
    if not found then
        return 'inexistente';
    end if;
    return v_status;
end;
$$ language plpgsql stable;

comment on function fn_operacao_em_cobranca(uuid) is
    'Status da operação de uma parcela, para o gate OC026. Devolve ''inexistente'' em vez de NULL para que quem chama não confunda "não achei" com "achei sem status".';

create or replace function fn_baixar_parcela(
    p_parcela_id   uuid,
    p_movimento_id uuid
) returns void as $$
declare
    v_parcela    parcela%rowtype;
    v_movimento  movimento_bancario%rowtype;
    v_status_op  text;
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

    -- (028) A dívida ainda precisa estar sendo cobrada.
    v_status_op := fn_operacao_em_cobranca(v_parcela.operacao_id);
    if v_status_op not in ('ativa', 'inadimplente') then
        raise exception
            'A operação da parcela % está em % e não está mais em cobrança: esta agenda não recebe baixa.',
            v_parcela.numero, v_status_op
            using errcode = 'OC026';
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

-- E no TRIGGER também, pela razão que a 027 já usou para a cobertura de valor:
-- `fn_baixar_parcela` é o único caminho de baixa PELA APLICAÇÃO, não o único
-- caminho pelo banco. Um `update parcela set status='paga', movimento_id=X`
-- direto atravessa a função inteira. O corpo abaixo é o da 027 recopiado (o
-- `create or replace` troca a função inteira) mais UM bloco.
create or replace function fn_parcela_imutavel()
returns trigger as $$
declare
    v_valor_movimento numeric(14,2);
    v_status_op       text;
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

    if new.status not in ('aberta','paga') then
        raise exception
            'Status % não existe para parcela: uma parcela está em aberto ou foi paga contra movimento bancário.',
            new.status
            using errcode = 'OC011';
    end if;

    if old.status = 'paga' and new.status is distinct from 'paga' then
        raise exception
            'Parcela % já baixada não pode voltar a aberta: não há estorno definido.',
            old.numero
            using errcode = 'OC011';
    end if;

    if new.status <> 'aberta' and new.movimento_id is null then
        raise exception
            'Parcela % não pode sair de aberta (para %) sem movimento bancário correspondente.',
            new.numero, new.status
            using errcode = 'OC011';
    end if;

    if old.movimento_id is null and new.movimento_id is not null then
        -- (028) A dívida ainda precisa estar sendo cobrada. Vem ANTES da
        -- cobertura de propósito: apontar lastro na agenda de um título extinto
        -- é erro de ENDEREÇO, e dizer "o movimento não cobre" a quem escolheu a
        -- operação errada mandaria conferir o extrato — que está certo.
        v_status_op := fn_operacao_em_cobranca(new.operacao_id);
        if v_status_op not in ('ativa', 'inadimplente') then
            raise exception
                'A operação da parcela % está em % e não está mais em cobrança: esta agenda não recebe baixa.',
                new.numero, v_status_op
                using errcode = 'OC026';
        end if;

        select valor into v_valor_movimento
          from movimento_bancario
         where id = new.movimento_id;

        if not found then
            raise exception
                'Movimento bancário % não existe: a parcela % não tem contra o que ser baixada.',
                new.movimento_id, new.numero
                using errcode = 'OC011';
        end if;

        if v_valor_movimento < new.valor_total then
            raise exception
                'Movimento de % não cobre a parcela % (valor devido: %).',
                v_valor_movimento, new.numero, new.valor_total
                using errcode = 'OC011';
        end if;
    end if;

    if old.movimento_id is not null
       and new.movimento_id is distinct from old.movimento_id then
        raise exception
            'Parcela % já está conciliada contra o movimento %: o lastro de uma baixa não é reapontado (correção se faz no extrato).',
            old.numero, old.movimento_id
            using errcode = 'OC011';
    end if;

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

comment on function fn_parcela_imutavel() is
    'OC009/OC011/OC026 — agenda emitida não muda; status limitado a aberta/paga; sair de aberta exige operação EM COBRANÇA e movimento que COBRE a parcela; lastro e autoria da baixa não se reescrevem.';

-- ---------------------------------------------------------------------
-- (4) AS TRÊS TABELAS APPEND-ONLY QUE FICARAM DE FORA DO TRUNCATE
-- ---------------------------------------------------------------------
-- A 016 instalou `fn_bloquear_truncate_append_only` em cinco tabelas e a 027
-- acrescentou `parcela`. Sobraram três que o próprio schema declara imutáveis
-- por trigger de linha e que TRUNCATE atravessa pelo motivo de sempre: ele não
-- visita linhas, então nenhum trigger de LINHA o vê.
--
--   contrato_emprestimo  (OC017) — o instrumento de que o tomador tem via
--   registro_operacao    (OC018) — a prova do registro do Art. 5º §3º
--   apuracao_fiscal      (OC016) — a série de apurações, que não se retifica
--                                  apagando e sim gerando nova versão
--
-- Cada uma leva o SQLSTATE que a sua própria imutabilidade de linha já usa:
-- TRUNCATE é DELETE no atacado, e um código novo obrigaria a UI a explicar de
-- duas maneiras o mesmo ato.
drop trigger if exists trg_bloquear_truncate_contrato on contrato_emprestimo;
create trigger trg_bloquear_truncate_contrato
    before truncate on contrato_emprestimo
    for each statement execute function fn_bloquear_truncate_append_only('OC017');

drop trigger if exists trg_bloquear_truncate_registro on registro_operacao;
create trigger trg_bloquear_truncate_registro
    before truncate on registro_operacao
    for each statement execute function fn_bloquear_truncate_append_only('OC018');

drop trigger if exists trg_bloquear_truncate_apuracao on apuracao_fiscal;
create trigger trg_bloquear_truncate_apuracao
    before truncate on apuracao_fiscal
    for each statement execute function fn_bloquear_truncate_append_only('OC016');
