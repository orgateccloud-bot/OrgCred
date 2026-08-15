-- OrgCred — a REGRA 2 de atipicidade passa a olhar a data do FATO
--
-- O DEFEITO. A migration 010 criou a REGRA 2 de `fn_detectar_atipicidades`
-- ("liquidação muito antecipada") com este filtro:
--
--     where a.primeiro_venc is not null and a.primeiro_venc > current_date
--
-- Ele compara o primeiro vencimento com HOJE — o dia em que alguém clicou em
-- "detectar" — e não com o dia em que a liquidação ACONTECEU. O fato que a
-- regra existe para enxergar ("a operação foi quitada antes de a primeira
-- parcela vencer") é imutável; o filtro não é. Uma operação liquidada no dia
-- 1, com primeiro vencimento no dia 30, é detectada enquanto a varredura
-- rodar até o dia 30 e deixa de ser detectada PARA SEMPRE a partir do dia 31,
-- embora nada sobre ela tenha mudado.
--
-- E a varredura só roda por clique manual (`POST
-- /compliance/atipicidades/detectar`, restrito a admin). Ou seja: o controle
-- tinha um prazo de validade que começava a correr na liquidação e vencia no
-- primeiro vencimento, e ninguém era avisado de que ele estava correndo. Na
-- prática a regra tende a nunca disparar — é o pior formato possível para um
-- controle de PLD, porque a tela fica vazia e o vazio é lido como "não há o
-- que ver".
--
-- ---------------------------------------------------------------------
-- DE ONDE SAI A DATA DO FATO, E POR QUE DESTA FONTE
-- ---------------------------------------------------------------------
-- Há duas trilhas append-only que testemunham uma liquidação:
--
--   (a) `capital_ledger`, com `evento_tipo = 'liquidacao'` (017). Desde a 020
--       seu `created_at` é ESCRITO PELO BANCO (`new.created_at := now()` em
--       fn_calcular_hash_ledger, que sobrescreve o que o INSERT tenha
--       passado) e entra no digest da hash-chain. É, dos dois carimbos, o
--       impossível de ditar: antedatá-lo exige forjar o hash.
--
--   (b) `operacao_evento`, com `status_novo = 'liquidada'` (008). O
--       `created_at` tem DEFAULT clock_timestamp(), mas é um default: um
--       INSERT pode informar outro valor. O append-only (OC010) recusa UPDATE
--       e DELETE, não recusa uma linha nova com carimbo escolhido.
--
-- ESCOLHIDA A (b), `operacao_evento`, por três razões nesta ordem:
--
--   1. É A TRILHA QUE RESPONDE À PERGUNTA. A separação foi decidida na 008 e
--      está escrita lá: `capital_ledger` registra MOVIMENTOS DE CAPITAL,
--      `operacao_evento` registra TRANSIÇÕES DE ESTADO. "Quando esta operação
--      virou liquidada" é pergunta de estado. O ledger responde outra coisa
--      — quanto de capital voltou ao teto — e responde por acidente, porque
--      hoje os dois atos coincidem no tempo.
--
--   2. FONTE ÚNICA COM A 022. A retenção ancorada já lê `operacao_evento`
--      para saber quando cada operação encerrou, e a 018 lê a mesma trilha
--      para achar o corte de competência. Usar uma terceira fonte para "a
--      mesma operação, a mesma data" seria garantir que um dia elas
--      discordem — e a discordância apareceria como uma atipicidade que a
--      tela de compliance mostra e o laudo fiscal nega.
--
--   3. O LEDGER NÃO COBRE O CASO NOVO. `baixada_prejuizo` (ver abaixo) grava
--      `evento_tipo = 'baixa_prejuizo'`, não 'liquidacao', e é um bloco
--      separado da 017; e a ideia de derivar a data de encerramento a partir
--      de qual bloco disparou reintroduz o acoplamento invisível que a 017
--      tomou o cuidado de evitar. A trilha de estado trata os dois
--      encerramentos com a mesma leitura.
--
-- O PREÇO DA ESCOLHA, DITO POR EXTENSO: quem puder inserir direto em
-- `operacao_evento` pode escolher a data que a regra vai ler. Ele é pequeno
-- na direção que importa — ver min() logo abaixo — e o carimbo do ledger
-- continua disponível para uma auditoria que queira confrontar as duas
-- trilhas. O que não se faz é usar as duas aqui e ter de decidir, em código
-- de detecção, qual delas mente.
--
-- min(), E NÃO max(). As três migrations que leem esta trilha escolhem lados
-- diferentes, e cada escolha é a que torna a fraude inútil no seu contexto:
--
--   - 018 usa min() porque o corte de competência mais cedo é o conservador;
--   - 022 usa max() porque uma data de encerramento antecipada ENCURTARIA o
--     prazo legal de guarda, e um evento forjado com carimbo retroativo
--     liberaria o expurgo antes da hora;
--   - aqui é min(), porque a detecção dispara quando o encerramento é
--     ANTERIOR ao primeiro vencimento. Quem quer escapar precisa que a data
--     lida seja TARDIA; com min(), um evento 'liquidada' inserido depois, com
--     carimbo posterior, é inócuo — o evento real continua sendo o menor. O
--     forjado que ANTECIPA a data continua possível e só produz uma
--     ocorrência a mais na tela do analista, que é o lado do erro que não faz
--     mal a ninguém.
--
-- SEM EVENTO NA TRILHA = DETECTA ASSIM MESMO, com o detalhe dizendo que a
-- data não está provada. Faltar o evento terminal só acontece se alguém
-- desligou o trigger da 008; nesse caso, silenciar a regra faria do
-- desligamento do trigger o jeito mais barato de apagar um alerta de PLD.
-- Fail-closed: na dúvida, o analista vê a linha.
--
-- ---------------------------------------------------------------------
-- O DETALHE MUDA, E A DUPLICAÇÃO É TRATADA NA ORIGEM
-- ---------------------------------------------------------------------
-- O índice `ocorrencia_unica` (010) deduplica por (regra, tomador_id,
-- operacao_id, DETALHE), e o detalhe da REGRA 2 embute o primeiro vencimento
-- via format(). Como `parcela.vencimento` é imutável (OC009) e a agenda é
-- emitida uma única vez pela ativação (007), esse texto é estável no tempo —
-- de modo que mexer nele é justamente o que quebra a deduplicação: toda
-- operação já marcada sob o texto antigo seria marcada DE NOVO sob o texto
-- novo, e a mesma atipicidade passaria a aparecer duas vezes na tela. Como a
-- ocorrência é append-only (OC014) e o TRUNCATE é recusado (016), a duplicata
-- seria permanente e sem conserto.
--
-- O texto MUDA mesmo assim, porque sem a data da liquidação a ocorrência é
-- inavaliável: "Liquidada antes do primeiro vencimento (2026-09-15)" não diz
-- se a antecipação foi de um dia ou de onze meses, e essa distância é
-- exatamente o que faz o analista abrir ou fechar o caso. A regra passa a
-- gravar as DUAS pontas.
--
-- E a duplicação é tratada na origem, não aceita: a REGRA 2 deixa de confiar
-- no texto para ser idempotente e passa a se guardar por (regra,
-- operacao_id), com um `not exists` explícito. É a chave natural do fato —
-- uma operação encerra UMA vez, e uma segunda ocorrência sobre o mesmo
-- encerramento nunca é informação nova. O `on conflict` continua onde estava,
-- como segunda linha de defesa e porque as REGRAS 1 e 3 seguem dependendo
-- dele.
--
-- EFEITO SOBRE BASES EXISTENTES, item por item:
--
--   - operação JÁ MARCADA sob o texto antigo: não ganha linha nova. A linha
--     histórica fica como está, com o texto da época — que é o que uma
--     trilha append-only deve fazer;
--   - operação que a regra antiga PERDEU (liquidada antes do vencimento, mas
--     varrida depois dele): passa a ser marcada, agora, pela primeira vez. A
--     correção é retroativa sobre toda a base, então a PRIMEIRA varredura
--     depois desta migration pode devolver um número alto de ocorrências
--     novas. Isso não é ruído: é o acúmulo que a janela de validade da 010
--     vinha descartando em silêncio;
--   - operação futura: uma linha só, com as duas datas.
--
-- ---------------------------------------------------------------------
-- WRITE-OFF ANTES DO PRIMEIRO VENCIMENTO É OUTRA REGRA
-- ---------------------------------------------------------------------
-- `baixada_prejuizo` antes de a primeira parcela vencer é um sinal DIFERENTE
-- e mais forte: significa que a ESC emprestou e, sem que um único pagamento
-- tivesse sequer vencido, declarou o valor irrecuperável. Não houve
-- oportunidade de inadimplência — não havia o que pagar ainda. O que sobra é
-- a forma de uma transferência disfarçada de empréstimo, com a baixa fazendo
-- o papel de encerrar a cobrança de dinheiro que nunca se esperou de volta.
--
-- REGRA NOVA, com nome próprio (`baixa_prejuizo_antecipada`, severidade
-- 'alta'), e não a mesma:
--
--   - o significado econômico é OPOSTO. Em 'liquidacao_antecipada' o dinheiro
--     VOLTOU cedo demais; aqui ele NÃO voltou. Empilhar os dois sob um rótulo
--     só obrigaria o analista a abrir cada linha para descobrir de qual dos
--     dois fatos ela fala — que é como um painel de PLD deixa de ser lido;
--   - a severidade é outra ('alta' contra 'media'), e severidade é o campo
--     pelo qual a tela ordena;
--   - a providência é outra: quitação antecipada se investiga olhando a
--     origem do recurso que quitou; write-off precoce se investiga olhando
--     quem autorizou a perda e contra que evidência de incobrabilidade.
--
-- Nome novo também significa ZERO ocorrência preexistente sob esse rótulo,
-- então não há questão de deduplicação com o histórico: a primeira varredura
-- depois desta migration marca todo write-off precoce que a base já tiver.
--
-- NENHUM SQLSTATE NOVO. Nada aqui levanta exceção: a varredura é uma função
-- de leitura e INSERT, e as travas que a protegem (OC014, e o TRUNCATE da
-- 016) continuam sendo as mesmas.

-- ---------------------------------------------------------------------
-- fn_detectar_atipicidades, ancorada
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função inteira: as REGRAS 1 e 3 abaixo estão
-- letra por letra como a 010 as deixou, inclusive os comentários. A única
-- coisa que muda é a REGRA 2 — e o que ela ganha (o write-off precoce) entra
-- na mesma varredura porque compartilha a mesma leitura de trilha, não porque
-- seja o mesmo sinal.
create or replace function fn_detectar_atipicidades(
    p_limiar        numeric default 10000,
    p_janela_dias   int default 30
) returns int as $$
declare
    v_total  int := 0;
    -- GET DIAGNOSTICS só ATRIBUI: `get diagnostics v_total = v_total +
    -- row_count` é erro de sintaxe. Daí a variável auxiliar por regra.
    v_linhas int;
begin
    -- REGRA 1 — Fracionamento (smurfing): várias operações pequenas do
    -- mesmo tomador numa janela curta, somando acima do limiar. É o padrão
    -- clássico de quem quer ficar abaixo do radar de cada operação isolada.
    with fracionadas as (
        select oc.tomador_id,
               count(*) as qtd,
               sum(oc.valor_principal) as soma
        from operacao_credito oc
        where oc.created_at >= current_date - make_interval(days => p_janela_dias)
          and oc.valor_principal < p_limiar
          and oc.status <> 'cancelada'
        group by oc.tomador_id
        having count(*) >= 3 and sum(oc.valor_principal) >= p_limiar
    )
    insert into ocorrencia_atipicidade (regra, severidade, tomador_id, detalhe)
    select 'fracionamento', 'alta', f.tomador_id,
           format('%s operações abaixo de %s em %s dias, somando %s',
                  f.qtd, p_limiar, p_janela_dias, f.soma)
    from fracionadas f
    on conflict (
        regra,
        coalesce(tomador_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(operacao_id, '00000000-0000-0000-0000-000000000000'::uuid),
        detalhe
    ) do nothing;
    get diagnostics v_linhas = row_count;
    v_total := v_total + v_linhas;

    -- REGRA 2 — Encerramento antes do primeiro vencimento, nas suas duas
    -- formas. A comparação é entre DUAS DATAS DO FATO — o encerramento lido
    -- de `operacao_evento` e o primeiro vencimento lido da agenda —, e
    -- `current_date` não aparece: é o que faz a resposta desta varredura ser
    -- a mesma hoje, amanhã e daqui a cinco anos.
    --
    --   'liquidada'         -> quitou antes de a primeira parcela vencer.
    --                          Não é ilegal, mas é o formato de quem usa a
    --                          operação para dar aparência lícita a recurso
    --                          que já tinha. Severidade 'media'.
    --   'baixada_prejuizo'  -> deu por perdido antes de haver o que cobrar.
    --                          Severidade 'alta' — ver o cabeçalho.
    --
    -- `encerrada_em` procura o evento cujo `status_novo` é o status ATUAL da
    -- operação: é o evento que a pôs onde ela está. min() pelo motivo do
    -- cabeçalho (o forjado que atrasa a data é o que interessaria a quem
    -- quer escapar, e min() o ignora). Nulo = evento ausente = trilha da 008
    -- desligada em algum momento: detecta assim mesmo, com o detalhe dizendo
    -- que a data não está provada.
    with encerradas as (
        select oc.id,
               oc.tomador_id,
               oc.status,
               (select min(p.vencimento)
                  from parcela p
                 where p.operacao_id = oc.id)          as primeiro_venc,
               (select min(e.created_at)::date
                  from operacao_evento e
                 where e.operacao_id = oc.id
                   and e.status_novo = oc.status)      as encerrada_em
        from operacao_credito oc
        where oc.status in ('liquidada', 'baixada_prejuizo')
    ),
    -- O rótulo é decidido uma vez, aqui, e reusado no INSERT e na guarda de
    -- idempotência. Repeti-lo em dois `case` idênticos seria o jeito de, na
    -- próxima alteração, mudar um e esquecer o outro — e a guarda passaria a
    -- comparar contra uma regra que ninguém grava, reinserindo a mesma
    -- ocorrência a cada varredura.
    antecipadas as (
        select a.*,
               case a.status
                   when 'liquidada' then 'liquidacao_antecipada'
                   else 'baixa_prejuizo_antecipada'
               end as regra
        from encerradas a
        where a.primeiro_venc is not null
          and (a.encerrada_em is null or a.encerrada_em < a.primeiro_venc)
    )
    insert into ocorrencia_atipicidade (regra, severidade, tomador_id, operacao_id, detalhe)
    select a.regra,
           case a.status when 'liquidada' then 'media' else 'alta' end,
           a.tomador_id, a.id,
           format('%s em %s, antes do primeiro vencimento (%s)',
                  case a.status
                      when 'liquidada' then 'Liquidada'
                      else 'Baixada como prejuízo'
                  end,
                  coalesce(a.encerrada_em::text,
                           'data não provada — sem evento na trilha de transições'),
                  a.primeiro_venc)
    from antecipadas a
    -- A idempotência desta regra é por FATO, não por texto: uma operação
    -- encerra uma vez só, então (regra, operacao_id) já é a chave. É o que
    -- permite mudar o texto do detalhe sem produzir uma segunda linha para
    -- as operações já marcadas sob o texto da 010 — ver o cabeçalho.
    where not exists (
        select 1 from ocorrencia_atipicidade o
         where o.operacao_id = a.id
           and o.regra = a.regra
    )
    on conflict (
        regra,
        coalesce(tomador_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(operacao_id, '00000000-0000-0000-0000-000000000000'::uuid),
        detalhe
    ) do nothing;
    get diagnostics v_linhas = row_count;
    v_total := v_total + v_linhas;

    -- REGRA 3 — Pagamento em excesso relevante. Um crédito muito acima do
    -- devido pode ser mora legítima; acima de 10% E de R$ 1.000 já merece
    -- um par de olhos, porque é o formato de injeção de recurso disfarçada
    -- de pagamento.
    insert into ocorrencia_atipicidade (regra, severidade, tomador_id, operacao_id, detalhe)
    select 'pagamento_em_excesso', 'baixa', oc.tomador_id, oc.id,
           format('Movimento %s para parcela %s de %s', m.documento, p.numero, p.valor_total)
    from parcela p
    join movimento_bancario m on m.id = p.movimento_id
    join operacao_credito oc on oc.id = p.operacao_id
    where m.valor - p.valor_total > 1000
      and m.valor > p.valor_total * 1.10
    on conflict (
        regra,
        coalesce(tomador_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(operacao_id, '00000000-0000-0000-0000-000000000000'::uuid),
        detalhe
    ) do nothing;
    get diagnostics v_linhas = row_count;
    v_total := v_total + v_linhas;

    return v_total;
end;
$$ language plpgsql;

comment on function fn_detectar_atipicidades(numeric, int) is
    'Varredura de atipicidade PLD/FT sobre os dados internos (migration 010, REGRA 2 corrigida na 023). Regras: fracionamento, encerramento antes do primeiro vencimento (liquidacao_antecipada e baixa_prejuizo_antecipada) e pagamento em excesso. Desde a 023 a REGRA 2 compara o primeiro vencimento com a DATA DO ENCERRAMENTO, lida de operacao_evento (008), e não com current_date — o fato é imutável, e a detecção passa a ser também: independe de quando a varredura roda. Idempotente por (regra, operacao_id), o que a torna imune a mudanças no texto do detalhe.';
