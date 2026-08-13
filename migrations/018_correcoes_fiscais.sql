-- OrgCred — quatro erros de CONTEÚDO tributário na apuração fiscal
--
-- A ARQUITETURA DA 011 ESTÁ CERTA E NADA AQUI A MEXE: o cálculo continua
-- dentro de fn_apurar_trimestre (o banco decide), a apuração continua imutável
-- por OC016 com retificação criando versão nova, os parâmetros continuam
-- COPIADOS para dentro da linha, e apurar sem parâmetro continua sendo recusa
-- com OC015 em vez de um número plausível. O que estava errado era o CONTEÚDO:
-- QUAIS linhas entram na base e QUAL parâmetro se aplica. Nenhum dos quatro
-- pontos tinha teste — todos passavam verdes porque a suíte só exercitava um
-- cenário limpo (uma operação, um parâmetro, tudo no mesmo trimestre).
--
-- O agravante comum aos quatro: o snapshot de parâmetros, que existe para
-- tornar a apuração REPRODUZÍVEL, transforma cada um deles em prova
-- documental do erro. Uma apuração errada e imutável, assinada com as
-- alíquotas "congeladas", é pior que uma planilha errada — ela se apresenta
-- como a versão auditada do fato.
--
-- NENHUM SQLSTATE NOVO. Não há regra nova aqui: OC015 continua sendo "não dá
-- para apurar sem parâmetro", só que agora a pergunta é feita sobre o período
-- CERTO. Inventar um código para "sem parâmetro no período" faria a UI
-- explicar de dois jeitos a mesma providência — cadastrar o parâmetro. E
-- continua sem OC006, reservado ao gate de IOF (DECISOES_PENDENTES.md §2).
--
-- ---------------------------------------------------------------------
-- (a) O PARÂMETRO ERA O DE HOJE, NÃO O DO PERÍODO APURADO
-- ---------------------------------------------------------------------
-- `select * into v_par from v_parametro_fiscal_vigente` (011, linha 158). A
-- view é `where vigencia_inicio <= current_date order by vigencia_inicio desc
-- limit 1` — ancorada em HOJE, sempre. Apurar 2021/T1 depois de a alíquota ter
-- mudado em 2024 aplicava a alíquota de 2024 a uma receita de 2021.
--
-- Isso destrói exatamente o que a 011 queria construir. O comentário dela diz,
-- com todas as letras, que a vigência existe porque "uma apuração de 2026 tem
-- que continuar reproduzível com os números de 2026" — e a função escolhia o
-- parâmetro pelo relógio de quem apura. O caso real que quebra é o mais comum
-- de todos: RETIFICAÇÃO. Retifica-se um trimestre meses ou anos depois, que é
-- quando a alíquota já mudou; a versão 2 da apuração sairia diferente da
-- versão 1 sem que um único centavo de receita tivesse mudado, e o snapshot
-- gravaria as alíquotas novas como se fossem as do período.
--
-- A ÂNCORA É O ENCERRAMENTO DO TRIMESTRE, não o início. No Lucro Presumido o
-- fato gerador do IRPJ/CSLL se completa em 31/03, 30/06, 30/09 e 31/12 (Lei
-- 9.430/96, art. 1º): é a data em que o período de apuração se encerra que
-- define a lei aplicável ao trimestre inteiro. Ancorar no INÍCIO daria o
-- resultado oposto ao da lei numa alíquota que entra em vigor no meio do
-- trimestre — e essa é a única situação em que as duas âncoras discordam, ou
-- seja, exatamente a que precisa estar certa.
--
-- CONSEQUÊNCIA DELIBERADA: apurar um trimestre ANTERIOR à vigência mais antiga
-- cadastrada passa a ser recusado com OC015. Antes "funcionava", aplicando o
-- parâmetro de hoje a um período que nenhum parâmetro cobre — que é o bug, não
-- um recurso. A recusa é a mesma resposta honesta que a 011 já dava para a
-- ausência total de parâmetro, e a providência é a mesma: cadastrar a vigência
-- que cobre o período.
--
-- A VIEW v_parametro_fiscal_vigente CONTINUA EXISTINDO E ANCORADA EM HOJE, de
-- propósito. Ela responde a outra pergunta — "qual parâmetro está valendo
-- agora", que é o que `GET /fiscal/parametros/vigente` mostra na tela de
-- configuração. O erro nunca foi a view; foi a apuração ter usado a resposta
-- de uma pergunta pela resposta de outra.
--
-- ---------------------------------------------------------------------
-- (b) A COMPETÊNCIA SOMAVA AS DUAS AGENDAS DE UMA NOVAÇÃO
-- ---------------------------------------------------------------------
-- `select sum(valor_juros) from parcela where vencimento >= ... < ...` (011,
-- linha 174) — sem UMA palavra sobre a operação dona da parcela. A agenda é
-- imutável desde a 007 (OC009) e NÃO é apagada quando a operação é renegociada:
-- fn_novar_operacao (006) põe a original em 'renegociada' e cria a substituta
-- com agenda PRÓPRIA, e as duas continuam no banco lado a lado.
--
-- Resultado: a partir da primeira novação, TODO trimestre soma os juros da
-- agenda morta com os da agenda viva. Numa carteira que renegocia — e uma ESC
-- de microcrédito renegocia — a base infla cumulativamente. Pagam-se IRPJ,
-- CSLL, PIS e COFINS sobre receita que não vai existir, e o dinheiro não volta:
-- restituição de tributo pago a maior sobre base inventada é pedido que se
-- instrui com o quê?
--
-- O CORTE NÃO É POR STATUS, É POR STATUS **E DATA**. Um filtro simples
-- `status in ('ativa','inadimplente','liquidada')` conserta a dupla contagem e
-- cria um erro novo, do lado perigoso: apagaria retroativamente os juros que a
-- agenda original ACUMULOU enquanto estava viva. Se a operação venceu quatro
-- parcelas em 2025 e foi renegociada em 2026, aqueles quatro trimestres de
-- 2025 foram declarados com aquela receita — e uma retificação de 2025 feita
-- depois da novação passaria a mostrar receita MENOR que a declaração
-- original. Isso é subdeclaração autoinfligida, o lado que gera multa de
-- ofício.
--
-- Por isso o critério é: a agenda de uma operação gera receita de competência
-- até o dia em que a operação deixa de gerá-la, e nem um dia depois. A data
-- desse corte não precisou ser inventada nem armazenada: `operacao_evento`
-- (008) registra TODA transição de status por trigger, com `created_at`. O
-- corte é o `min(created_at)` do evento que levou ao status terminal.
--
-- Os quatro grupos, e por que cada um está onde está:
--
--   ativa, inadimplente ...... gera receita, a agenda está viva. Inadimplente
--                              inclusive: no regime de COMPETÊNCIA o atraso
--                              não suspende o reconhecimento — a receita foi
--                              auferida, o que falta é o caixa. (Quem quiser
--                              tributar só o recebido escolhe o regime caixa,
--                              que é a outra metade desta função.)
--   liquidada ................ gera receita da agenda inteira: desde a 017,
--                              liquidar exige TODAS as parcelas pagas com
--                              lastro. Não há parcela futura para inflar nada.
--   renegociada .............. gera até a data da novação. Depois dela, quem
--                              gera é a substituta.
--   baixada_prejuizo ......... gera até a data do write-off. O crédito foi
--                              declarado perdido e a cobrança encerrada (017);
--                              continuar acumulando receita sobre parcelas de
--                              uma agenda morta — que ficam 'aberta' PARA
--                              SEMPRE, por decisão explícita da 017 — faria a
--                              base crescer indefinidamente sobre dinheiro que
--                              o próprio sistema já registrou como perdido.
--                              O que veio ANTES do write-off fica: foi receita
--                              auferida de verdade, e no Lucro Presumido não
--                              há dedução de perda que a desfaça.
--   proposta, registrada ..... não têm agenda (a 007 só a gera na ativação).
--   cancelada ................ idem: a máquina de estados só cancela a partir
--                              de 'proposta' ou de 'registrada'.
--
--                              Os dois últimos grupos não contribuiriam nada
--                              mesmo se ficassem de fora do filtro; estão
--                              nomeados aqui porque a lista precisa ser
--                              exaustiva sobre o domínio declarado pela 017 —
--                              é a próxima pessoa que acrescentar um estado
--                              que tem de encontrar a pergunta feita por
--                              escrito: "esta agenda gera receita, e até
--                              quando?".
--
-- COALESCE PARA 'infinity' quando o evento não é encontrado: o único jeito de
-- faltar o evento é alguém ter desligado o trigger da 008 (a própria suíte faz
-- isso para montar cenário). Nesse caso a escolha é entre incluir tudo
-- (declarar a mais) e excluir tudo (declarar a menos). Inclui-se: erro de
-- apuração para cima custa dinheiro, para baixo custa multa de ofício.
--
-- O REGIME DE CAIXA NÃO LEVA ESSE FILTRO, e é importante que não leve: lá a
-- pergunta é "o dinheiro entrou?", e dinheiro que entrou é receita ainda que a
-- operação tenha sido renegociada, quitada ou baixada depois. Filtrar por
-- status no caixa apagaria recebimentos comprovados por extrato.
--
-- ---------------------------------------------------------------------
-- (c) O CAIXA ANCORAVA NA CONCILIAÇÃO, NÃO NO CRÉDITO EM CONTA
-- ---------------------------------------------------------------------
-- `where status = 'paga' and pago_em >= v_inicio and pago_em < v_fim` (011,
-- linha 170). `parcela.pago_em` é `clock_timestamp()` no instante em que
-- fn_baixar_parcela roda (009/016) — é a data em que ALGUÉM CONCILIOU no
-- sistema, não a data em que o dinheiro caiu na conta. As duas coincidem só
-- quando a conciliação é feita no mesmo dia.
--
-- O crédito de 30/06 conciliado em 02/07 — atraso rotineiro, um feriado, um
-- fim de semana, uma volta de férias — sai do 2º trimestre e entra no 3º. Nos
-- dois trimestres o número fica errado: um a menos, outro a mais, e ambos
-- assinados. E o erro é INDUZIDO PELO OPERADOR: conciliar mais tarde muda o
-- imposto do trimestre, o que também significa que a data de reconhecimento da
-- receita fica ao alcance de quem quiser escolhê-la.
--
-- A âncora certa é `movimento_bancario.data_movimento` — a data do extrato,
-- que é fato de fora, imutável desde a 009 (OC012) e não escolhível por
-- ninguém de dentro. `parcela.pago_em` continua na tabela e continua útil:
-- é a trilha de QUANDO se conciliou, ao lado de `baixado_por` (016), que é
-- QUEM conciliou. Deixou de ser fato fiscal, não deixou de ser fato.
--
-- O JOIN é seguro por construção: desde a 016 o CHECK
-- `parcela_lastro_obrigatorio` garante que toda parcela fora de 'aberta' tem
-- `movimento_id` não-nulo, então o INNER JOIN não perde nenhuma linha 'paga'.
--
-- ---------------------------------------------------------------------
-- (d) MORA E MULTA RECEBIDAS SUMIAM DA BASE
-- ---------------------------------------------------------------------
-- A apuração só somava `parcela.valor_juros` — o juro CONTRATUAL da agenda,
-- calculado na ativação e congelado pela 007. Quando o movimento cobre MAIS
-- que a parcela, a diferença é receita e não era registrada em lugar nenhum.
--
-- E o excedente não é acidente: fn_baixar_parcela aceita `valor >= valor_total`
-- desde a 009 justamente porque "juros de mora fazem o tomador pagar MAIS que
-- o valor original, e recusar isso impediria a baixa de todo pagamento
-- atrasado". Ou seja: o sistema foi construído para receber mora — e depois
-- jogava a mora fora na hora de apurar. Numa carteira de microcrédito, os
-- pagamentos atrasados não são a exceção.
--
-- Isso é SUBDECLARAÇÃO: base menor que a real, imposto a menos, multa de
-- ofício de 75% (Lei 9.430/96, art. 44, I) sobre a diferença — o lado caro do
-- erro. O outro item deste arquivo, (b), errava para cima; este errava para
-- baixo, e os dois juntos produziam um número sem relação com nada.
--
-- MORA É RECONHECIDA PELO RECEBIMENTO NOS DOIS REGIMES, e a razão está no
-- próprio dado: antes do pagamento não existe mora apurada em lugar nenhum do
-- sistema. Ela não está na agenda (a 007 congela amortização, juros e total no
-- momento da ativação e a 016 recusa alterá-los), não tem data de vencimento
-- própria e seu valor só é conhecido no instante do crédito bancário, porque é
-- ele que revela quanto o tomador de fato pagou a mais. Não há competência a
-- que ancorar: o único fato observável é o extrato. Por isso a linha de demais
-- receitas usa `data_movimento` mesmo quando o regime configurado é
-- competência.
--
-- POR QUE UMA COLUNA NOVA EM VEZ DE SOMAR EM `receita_juros`: os dois números
-- têm naturezas diferentes (rendimento do contrato vs. penalidade por atraso),
-- vão para linhas diferentes da escrituração e contam histórias diferentes
-- sobre a carteira — uma mora que cresce é um indicador de inadimplência, e
-- diluída dentro de "receita de juros" ela fica invisível. Além disso
-- `receita_juros` é o campo que a 011 documentou como "só o JURO, nunca a
-- amortização"; passar a somar outra coisa nele desmentiria o comentário e a
-- tela sem que nada avisasse.
--
-- `receita_total` é coluna GERADA (stored), não calculada na função: uma soma
-- que o Postgres mantém não pode divergir das parcelas dela num INSERT futuro
-- que esqueça de atualizá-la. E ser stored — e não uma conta feita na leitura —
-- é o que a mantém coerente com o resto da tabela, cujas colunas de tributo
-- também são derivadas e guardadas: a apuração é um DOCUMENTO, tem de ser
-- legível sem aritmética por quem a recebe.
--
-- BACKFILL DAS APURAÇÕES ANTIGAS SEM UPDATE: `receita_demais` entra com
-- `default 0` (apurações anteriores a esta migration realmente não tinham
-- linha de mora) e `receita_total` é gerada, então o Postgres a calcula para
-- todas as linhas existentes durante o próprio ADD COLUMN. Isso importa porque
-- apuracao_fiscal é imutável por OC016: um `update ... set receita_total =
-- receita_juros` para preencher o histórico seria RECUSADO pelo trigger, e
-- contorná-lo desligando o trigger dentro de uma migration é exatamente o
-- gênero de coisa que a 016 documentou como perigosa. DDL não dispara trigger
-- de linha, e aqui isso é usado para NÃO precisar mexer em nenhuma linha.

-- ---------------------------------------------------------------------
-- 1. As duas linhas novas de receita
-- ---------------------------------------------------------------------
alter table apuracao_fiscal
    add column if not exists receita_demais numeric(14,2) not null default 0;

alter table apuracao_fiscal
    add column if not exists receita_total numeric(14,2)
    generated always as (receita_juros + receita_demais) stored;

comment on column apuracao_fiscal.receita_juros is
    'Juro CONTRATUAL da agenda de parcelas (007). Nunca amortização, que é devolução de principal.';
comment on column apuracao_fiscal.receita_demais is
    'Mora e multa efetivamente recebidas: excedente do crédito bancário sobre o valor da parcela, '
    'sempre pela data do extrato (não existe antes do recebimento, nos dois regimes).';
comment on column apuracao_fiscal.receita_total is
    'Base efetivamente tributada = receita_juros + receita_demais. Coluna gerada: não pode divergir das parcelas.';

-- A view foi criada com `select *`, que o Postgres expandiu para a lista de
-- colunas de então — ela NÃO enxerga as duas colunas novas sozinha. CREATE OR
-- REPLACE VIEW aceita ACRESCENTAR colunas ao fim da lista (o que proíbe é
-- remover ou trocar o tipo das existentes), e é exatamente o caso: as novas
-- entraram no fim da tabela.
create or replace view v_apuracao_vigente as
select distinct on (ano, trimestre) *
from apuracao_fiscal
order by ano desc, trimestre desc, versao desc;

-- ---------------------------------------------------------------------
-- 2. fn_apurar_trimestre — recopiada da 011 com as quatro correções
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função inteira: o corpo abaixo é o da 011
-- (validação do trimestre, recusa OC015 sem parâmetro, janela do trimestre,
-- presunção, adicional acima do limite trimestral, PIS/COFINS sobre a receita
-- e não sobre a base presumida, versionamento da retificação e snapshot dos
-- parâmetros) com as quatro mudanças marcadas no corpo como (a), (b), (c) e
-- (d).
create or replace function fn_apurar_trimestre(
    p_ano       int,
    p_trimestre int,
    p_usuario   text default null
) returns uuid as $$
declare
    v_par           parametro_fiscal%rowtype;
    v_inicio        date;
    v_fim           date;
    v_encerramento  date;
    v_juros         numeric(14,2);
    v_demais        numeric(14,2);
    v_receita       numeric(14,2);
    v_base_irpj     numeric(14,2);
    v_base_csll     numeric(14,2);
    v_irpj          numeric(14,2);
    v_adicional     numeric(14,2);
    v_csll          numeric(14,2);
    v_pis           numeric(14,2);
    v_cofins        numeric(14,2);
    v_versao        int;
    v_id            uuid;
begin
    if p_trimestre not between 1 and 4 then
        raise exception 'Trimestre inválido: %.', p_trimestre using errcode = 'OC015';
    end if;

    -- A janela do trimestre passou a ser calculada ANTES da busca do
    -- parâmetro, porque agora é ela que define qual parâmetro se aplica.
    v_inicio       := make_date(p_ano, (p_trimestre - 1) * 3 + 1, 1);
    v_fim          := (v_inicio + interval '3 months')::date;
    -- Último dia do trimestre: 31/03, 30/06, 30/09, 31/12. É a data em que o
    -- período de apuração se encerra e, com ele, o fato gerador do trimestre.
    v_encerramento := v_fim - 1;

    -- (a) O PARÂMETRO É O VIGENTE NO ENCERRAMENTO DO TRIMESTRE APURADO, e não
    -- o de hoje. Mesma regra da view v_parametro_fiscal_vigente (a mais
    -- recente que já entrou em vigor), só que ancorada na data do PERÍODO em
    -- vez de em current_date — é o que faz a retificação de um trimestre
    -- antigo reproduzir o número daquele trimestre.
    select * into v_par
    from parametro_fiscal
    where vigencia_inicio <= v_encerramento
    order by vigencia_inicio desc
    limit 1;

    if not found then
        raise exception
            'Não há parâmetro fiscal vigente em % (encerramento do %ºT%): configure a presunção e as alíquotas que valiam no período antes de apurá-lo.',
            v_encerramento, p_trimestre, p_ano
            using errcode = 'OC015';
    end if;

    if v_par.regime_reconhecimento = 'caixa' then
        -- (c) CAIXA ANCORADO NO EXTRATO. `movimento_bancario.data_movimento` é
        -- a data em que o dinheiro caiu na conta; `parcela.pago_em` é a data em
        -- que alguém conciliou. Só a primeira é fato de fora, e só ela não se
        -- desloca com o calendário de quem opera o sistema.
        --
        -- Sem filtro de status de OPERAÇÃO, de propósito: no caixa a pergunta é
        -- se o dinheiro entrou, e ele entrou mesmo que a operação tenha sido
        -- renegociada, quitada ou baixada depois.
        select coalesce(sum(p.valor_juros), 0) into v_juros
        from parcela p
        join movimento_bancario m on m.id = p.movimento_id
        where p.status = 'paga'
          and m.data_movimento >= v_inicio
          and m.data_movimento < v_fim;
    else
        -- (b) COMPETÊNCIA COM CORTE POR OPERAÇÃO E POR DATA DO CORTE. A agenda
        -- de uma operação gera receita até o dia em que a operação para de
        -- gerá-la (novação ou write-off) — nem antes de menos, nem depois de
        -- mais. Ver a tabela dos quatro grupos no topo deste arquivo.
        --
        -- O CORTE É INCLUSIVO (`<=`), e não `<`: uma parcela que vence NO DIA
        -- da novação ou do write-off teve seu juro auferido — o rendimento
        -- corre até o vencimento, e o ato praticado mais tarde naquele mesmo
        -- dia não desfaz competência já completada. Excluí-la seria declarar a
        -- MENOS no dia do corte, contra a mesma bússola que manda o coalesce
        -- abaixo cair em 'infinity': erro para cima custa dinheiro, para baixo
        -- custa multa de ofício (Lei 9.430/96, art. 44, I). E é a única
        -- leitura compatível com a regra escrita no topo deste arquivo — "até
        -- o dia em que a operação deixa de gerá-la", que em português inclui
        -- esse dia. Renegociar no vencimento da parcela é rotina, não borda
        -- exótica: é justamente quando o tomador procura o credor.
        select coalesce(sum(p.valor_juros), 0) into v_juros
        from parcela p
        join operacao_credito o on o.id = p.operacao_id
        where p.vencimento >= v_inicio
          and p.vencimento < v_fim
          and (
                o.status in ('ativa', 'inadimplente', 'liquidada')
                or (
                    o.status in ('renegociada', 'baixada_prejuizo')
                    and p.vencimento <= coalesce(
                        (
                            select min(e.created_at)::date
                            from operacao_evento e
                            where e.operacao_id = o.id
                              and e.status_novo = o.status
                        ),
                        'infinity'::date
                    )
                )
          );
    end if;

    -- (d) MORA E MULTA RECEBIDAS. O excedente do crédito bancário sobre o valor
    -- da parcela, sempre pela data do extrato — inclusive no regime de
    -- competência, porque mora não existe na agenda: ela só é conhecida no
    -- instante em que o tomador paga a mais. Não há dupla contagem com o bloco
    -- acima: lá soma-se `valor_juros` (o juro contratual), aqui só o que passou
    -- de `valor_total`.
    select coalesce(sum(m.valor - p.valor_total), 0) into v_demais
    from parcela p
    join movimento_bancario m on m.id = p.movimento_id
    where p.status = 'paga'
      and m.valor > p.valor_total
      and m.data_movimento >= v_inicio
      and m.data_movimento < v_fim;

    -- A base tributável é a receita TOTAL. A amortização continua fora: é
    -- devolução de principal e não é resultado.
    v_receita := v_juros + v_demais;

    v_base_irpj := round(v_receita * v_par.percentual_presuncao_irpj, 2);
    v_base_csll := round(v_receita * v_par.percentual_presuncao_csll, 2);

    v_irpj      := round(v_base_irpj * v_par.aliquota_irpj, 2);
    -- Adicional incide só sobre o que excede o limite do TRIMESTRE.
    v_adicional := round(
        greatest(v_base_irpj - v_par.adicional_irpj_limite, 0) * v_par.adicional_irpj_aliquota, 2
    );
    v_csll      := round(v_base_csll * v_par.aliquota_csll, 2);
    -- PIS/COFINS cumulativos incidem sobre a RECEITA, não sobre a base
    -- presumida — presunção é conceito de IRPJ/CSLL.
    v_pis       := round(v_receita * v_par.aliquota_pis, 2);
    v_cofins    := round(v_receita * v_par.aliquota_cofins, 2);

    select coalesce(max(versao), 0) + 1 into v_versao
    from apuracao_fiscal where ano = p_ano and trimestre = p_trimestre;

    -- `receita_total` NÃO aparece no INSERT: é coluna gerada, e listá-la seria
    -- erro de sintaxe. O Postgres a calcula a partir das duas linhas de receita.
    insert into apuracao_fiscal (
        ano, trimestre, versao, receita_juros, receita_demais,
        base_irpj, irpj, adicional_irpj, base_csll, csll, pis, cofins, total_tributos,
        percentual_presuncao_irpj, percentual_presuncao_csll,
        aliquota_irpj, aliquota_csll, adicional_irpj_aliquota, adicional_irpj_limite,
        aliquota_pis, aliquota_cofins, regime_reconhecimento, usuario_id
    ) values (
        p_ano, p_trimestre, v_versao, v_juros, v_demais,
        v_base_irpj, v_irpj, v_adicional, v_base_csll, v_csll, v_pis, v_cofins,
        v_irpj + v_adicional + v_csll + v_pis + v_cofins,
        v_par.percentual_presuncao_irpj, v_par.percentual_presuncao_csll,
        v_par.aliquota_irpj, v_par.aliquota_csll,
        v_par.adicional_irpj_aliquota, v_par.adicional_irpj_limite,
        v_par.aliquota_pis, v_par.aliquota_cofins, v_par.regime_reconhecimento, p_usuario
    ) returning id into v_id;

    return v_id;
end;
$$ language plpgsql;

comment on function fn_apurar_trimestre(int, int, text) is
    'OC015 — apura o trimestre com o parâmetro vigente no ENCERRAMENTO do período (não o de hoje). '
    'Competência: juros da agenda, por operação, até a data da novação ou do write-off. '
    'Caixa: juros das parcelas baixadas, pela data do extrato (não pela data da conciliação). '
    'Nos dois regimes soma mora e multa recebidas (excedente do crédito sobre o valor da parcela).';
