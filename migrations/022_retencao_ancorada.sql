-- OrgCred — a retenção de documento passa a contar do ENCERRAMENTO da relação
--
-- O DEFEITO. A migration 010 criou `tomador_documento.retencao_ate` e a
-- materializou no ato do arquivamento, como `current_date + 5 anos` (é o que
-- `POST /compliance/tomadores/{id}/documentos` grava até hoje). A Lei
-- 9.613/98, art. 10, III manda conservar os cadastros e registros por no
-- mínimo cinco anos CONTADOS DO ENCERRAMENTO DA RELAÇÃO DE NEGÓCIO — não do
-- dia em que alguém subiu o PDF.
--
-- A diferença não é de detalhe. Uma operação de 60 parcelas dura cinco anos:
-- o `retencao_ate` gravado na abertura vence no mês em que o contrato acaba,
-- ou seja, cerca de CINCO ANOS ANTES do que a lei exige. O sistema recusava
-- o DELETE (OC013) com a firmeza toda até o dia errado, e no dia errado
-- passava a autorizá-lo. Pior do que não ter o controle: ter um controle que
-- diz "pode apagar" com a autoridade do banco.
--
-- ---------------------------------------------------------------------
-- A TENSÃO: `retencao_ate` É IMUTÁVEL, E A DATA CERTA SÓ SE SABE DEPOIS
-- ---------------------------------------------------------------------
-- `fn_documento_retencao` (010) recusa QUALQUER update em
-- `tomador_documento` — a 019 reforçou por escrito que isso inclui
-- `storage_objeto`, porque repontar a linha para outro objeto seria trocar o
-- documento arquivado mantendo o hash. Ancorar no encerramento significa que
-- a data correta só é conhecida anos depois do arquivamento, e a
-- imutabilidade impede simplesmente atualizá-la.
--
-- Três saídas foram consideradas:
--
--   (a) PERMITIR EXTENSÃO PARA FRENTE — um UPDATE que só aumenta a data,
--       mantendo a recusa de encurtar. RECUSADA, por três razões:
--
--       1. Volta a depender de alguém lembrar. Alguma rotina teria de rodar
--          no encerramento de cada operação e reescrever a data em cada
--          documento do tomador. Se não rodar — job caído, transação que
--          falhou, operação encerrada por SQL direto — o documento fica
--          apagável exatamente no dia em que a lei mais o protege. O
--          comentário da 010 já dizia por que isso não serve: "a obrigação
--          de guardar não pode depender de ninguém lembrar dela".
--       2. Abre a porta que a 019 documentou como fechada. O trigger
--          deixaria de ser "UPDATE nunca" e passaria a ser "UPDATE só nesta
--          coluna, só nesta direção" — a forma que apodrece, porque a
--          próxima exceção ("só para corrigir o caminho do objeto") já
--          encontra o precedente aberto.
--       3. Destrói a resposta de auditoria. A pergunta que uma fiscalização
--          faz é "este documento PODIA ter sido apagado naquela data?", e
--          uma coluna sobrescrita só sabe dizer o valor de hoje. Não há
--          versionamento de `retencao_ate` e não vai haver.
--
--   (b) PARAR DE MATERIALIZAR e derivar tudo na leitura. RECUSADA porque
--       joga fora uma propriedade que a 010 escolheu de propósito: a data
--       materializada CONGELA A REGRA VIGENTE À ÉPOCA do arquivamento. Se o
--       prazo legal mudar de 5 para 3 anos, uma derivação pura recalcularia
--       os documentos antigos sob a regra nova e os tornaria apagáveis
--       retroativamente. Encurtar retroativamente prazo de guarda é o erro
--       caro; alongar não é erro nenhum.
--
--   (c) A COLUNA VIRA PISO E A DERIVAÇÃO ENTRA POR CIMA. ESCOLHIDA.
--
-- ---------------------------------------------------------------------
-- O DESENHO ESCOLHIDO
-- ---------------------------------------------------------------------
-- `retencao_ate` continua exatamente o que sempre foi — a data materializada
-- no arquivamento, sob a regra vigente naquele dia — e passa a se chamar, na
-- leitura, PISO. Sobre ela entra a âncora:
--
--     retenção efetiva = greatest(piso, último encerramento + 5 anos)
--
-- e, enquanto a relação NÃO encerrou, a retenção efetiva é `infinity`: o
-- prazo de cinco anos ainda não começou a correr, então não há data em que
-- apagar seja legítimo. `infinity` é `date` de verdade no Postgres, o que
-- deixa a comparação do trigger ser um `>=` comum em vez de um caso
-- especial.
--
-- O QUE ISSO PRESERVA, item por item:
--
--   - o trigger OC013 continua sendo a única autoridade sobre apagar, e
--     continua recusando UPDATE em coluna nenhuma. A única linha que muda
--     nele é a que decide a data-limite: em vez de ler a coluna, pergunta à
--     função. Não há caminho novo de escrita em `tomador_documento`;
--   - a UI que hoje exibe `retencao_ate` continua funcionando e continua
--     recebendo o mesmo campo. Ela ganha, ao lado, o prazo efetivo e o
--     motivo — ver `v_documento_retencao`;
--   - a auditoria ganha o que nenhuma das outras saídas dava:
--     `fn_retencao_efetiva_em(tomador, piso, DATA)` responde qual era o prazo
--     efetivo em QUALQUER data passada, porque tudo de que ela depende é
--     imutável (o piso, por OC013; os eventos de transição, por OC010).
--
-- ---------------------------------------------------------------------
-- "ENCERRAMENTO DA RELAÇÃO" NÃO É O ENCERRAMENTO DE UMA OPERAÇÃO
-- ---------------------------------------------------------------------
-- Um tomador tem várias operações, e a relação de negócio é com o TOMADOR.
-- Daí duas regras, as duas implementadas em `fn_relacao_em_curso` e
-- `fn_encerramento_relacao`:
--
--   1. Havendo UMA operação viva, a relação está viva — não importa quantas
--      já encerraram. Retenção efetiva = `infinity`.
--   2. Encerradas todas, a âncora é a MAIS RECENTE. Não a primeira, não a
--      maior: a última a encerrar é a que marca o fim da relação.
--
-- E O RELÓGIO REINICIA. Se o tomador voltar a tomar crédito, a operação nova
-- é uma operação viva e a regra 1 volta a valer sozinha — a retenção volta a
-- ser indeterminada e, quando essa operação encerrar, a regra 2 usará a data
-- dela. Nada precisa ser recalculado nem regravado, porque nada foi gravado:
-- é essa a vantagem de derivar em vez de materializar. Documento cujo prazo
-- JÁ TINHA VENCIDO e que ainda não foi expurgado volta a ficar protegido —
-- correto: a relação de negócio é uma só, e ela recomeçou.
--
-- 'proposta' e 'registrada' CONTAM COMO RELAÇÃO VIVA. Uma proposta em
-- análise é transação não concluída (é o termo do art. 10, III), e é
-- justamente quando a identificação do cliente importa. O efeito colateral é
-- conhecido e aceito: uma proposta esquecida segura o expurgo dos documentos
-- daquele tomador para sempre. Isso é o lado seguro do erro, é visível em
-- `v_documento_retencao.motivo`, e tem conserto de um comando — a máquina de
-- estados da 017 cancela proposta a qualquer momento.
--
-- ---------------------------------------------------------------------
-- DE ONDE SAI A DATA DE ENCERRAMENTO DE CADA OPERAÇÃO
-- ---------------------------------------------------------------------
-- De `operacao_evento` (008): a trilha append-only (OC010) de TODA transição
-- de status, gravada por trigger, com `created_at`. É a mesma fonte que a
-- 018 usa para achar o corte de competência de uma operação encerrada — e
-- usar duas fontes diferentes para "quando esta operação acabou" seria
-- garantir que um dia elas discordem.
--
-- NÃO se usa `operacao_credito.updated_at`: ele é reescrito a cada UPDATE
-- (`new.updated_at := now()`, 017), inclusive por alterações que não são
-- transição. Uma retenção ancorada nele mudaria de resposta ao sabor de
-- edições posteriores — e, pior, mudaria a resposta sobre o PASSADO, que é
-- exatamente o que esta migration existe para tornar responsável.
--
-- max(), E NÃO min() COMO NA 018. As duas migrations leem a mesma trilha
-- procurando coisas opostas. A 018 quer o corte MAIS CEDO, porque declarar
-- receita a mais custa dinheiro e a menos custa multa de ofício. Aqui, uma
-- data de encerramento antecipada ENCURTA prazo legal de guarda: se alguém
-- inserir à mão um evento de encerramento com `created_at` retroativo — a
-- tabela é append-only, mas nada impede INSERT —, com min() esse evento
-- forjado venceria e liberaria o expurgo antes da hora; com max() ele é
-- inócuo. O forjado que ALONGA a retenção continua possível, e é o lado do
-- erro que não faz mal a ninguém.
--
-- STATUS TERMINAL SEM EVENTO DE TRANSIÇÃO = `infinity`, ou seja, segue
-- protegido. É o mesmo `coalesce(..., 'infinity')` da 018, pela razão de lá
-- ("o único jeito de faltar o evento é alguém ter desligado o trigger da
-- 008") e por uma daqui: encerramento não provado não autoriza apagar prova.
-- O preço é não conseguir expurgar os documentos desse tomador — perda de
-- minimização de dados, nunca de conformidade.
--
-- NENHUM SQLSTATE NOVO. O bloqueio continua sendo OC013; o que muda é a data
-- até a qual ele vale, e a mensagem, que agora diz qual âncora está segurando.

-- ---------------------------------------------------------------------
-- 1. Encerramento por operação
-- ---------------------------------------------------------------------
-- `encerrada_em` nulo = operação viva hoje. `'infinity'` = operação em status
-- terminal sem evento que prove QUANDO chegou lá. Os dois significam "não
-- encerrada até a data de referência" e são tratados pela mesma comparação
-- lá embaixo — a distinção existe para a view de diagnóstico, não para a
-- lógica.
--
-- `aberta_em` sai de `operacao_credito.created_at`, e não do primeiro evento:
-- é a data de nascimento da linha, não muda, e é o que permite responder
-- "esta operação já existia naquela data?" ao avaliar uma data passada.
create or replace view v_operacao_encerramento as
select o.id                as operacao_id,
       o.tomador_id,
       o.status,
       o.created_at::date  as aberta_em,
       case
           when o.status in ('proposta', 'registrada', 'ativa', 'inadimplente')
               then null::date
           else coalesce(
               (select max(e.created_at)::date
                  from operacao_evento e
                 where e.operacao_id = o.id
                   and e.status_novo in ('liquidada', 'renegociada', 'cancelada',
                                         'baixada_prejuizo')),
               'infinity'::date)
       end                 as encerrada_em
from operacao_credito o;

comment on view v_operacao_encerramento is
    'Data de encerramento de cada operação (migration 022), lida de operacao_evento (008). NULL = viva hoje; infinity = status terminal sem evento que prove quando encerrou (segue contando como não encerrada, fail-closed).';

-- ---------------------------------------------------------------------
-- 2. A relação, no nível do TOMADOR
-- ---------------------------------------------------------------------
-- As duas funções recebem a DATA DE REFERÊNCIA em vez de olharem para
-- `current_date` por dentro. É o que torna a auditoria possível: a mesma
-- lógica que o trigger aplica hoje responde sobre qualquer dia do passado,
-- sem uma segunda implementação para divergir da primeira.
--
-- `stable` e não `volatile`: dependem só do conteúdo do banco dentro da
-- transação. Isso permite ao planejador reusar o resultado dentro de um mesmo
-- comando — relevante porque `v_documento_retencao` as chama uma vez por
-- linha.
create or replace function fn_relacao_em_curso(
    p_tomador_id  uuid,
    p_referencia  date
) returns boolean as $$
begin
    if p_tomador_id is null then
        return false;
    end if;

    return exists (
        select 1
        from v_operacao_encerramento e
        where e.tomador_id = p_tomador_id
          and e.aberta_em <= p_referencia
          and (e.encerrada_em is null or e.encerrada_em > p_referencia)
    );
end;
$$ language plpgsql stable;

-- Data em que a relação encerrou, olhando da data de referência. NULL quando
-- nunca houve operação encerrada até lá — o que inclui o tomador que só tem
-- cadastro e nenhuma operação, e o que só tem operação viva. Quem chama
-- decide o que fazer com o nulo; `fn_retencao_efetiva_em` faz as duas coisas
-- diferentes, porque os dois casos são diferentes.
create or replace function fn_encerramento_relacao(
    p_tomador_id  uuid,
    p_referencia  date
) returns date as $$
declare
    v_ultimo date;
begin
    if p_tomador_id is null then
        return null;
    end if;

    select max(e.encerrada_em) into v_ultimo
    from v_operacao_encerramento e
    where e.tomador_id = p_tomador_id
      and e.encerrada_em <= p_referencia;

    return v_ultimo;
end;
$$ language plpgsql stable;

-- ---------------------------------------------------------------------
-- 3. A retenção efetiva
-- ---------------------------------------------------------------------
-- O núcleo. Três casos, nesta ordem, e a ordem importa:
--
--   1. relação viva  -> `infinity`. O prazo não começou a correr. Este caso
--      vem PRIMEIRO porque um tomador pode ter, ao mesmo tempo, operações
--      encerradas há anos e uma operação nova; o encerramento antigo não
--      pode responder por uma relação que recomeçou.
--   2. nenhuma operação encerrada até a referência, e nenhuma viva -> vale o
--      PISO. É o tomador que só tem cadastro: não há relação de negócio a
--      encerrar, e a regra da 010 (arquivamento + 5 anos) segue sendo a
--      melhor leitura disponível.
--   3. relação encerrada -> greatest(piso, encerramento + 5 anos).
--      `greatest`, e não substituição: o piso é PISO. Um documento arquivado
--      ontem para um tomador que encerrou tudo há seis anos continua guardado
--      cinco anos a contar de ontem — porque foi ontem que ele passou a
--      existir, e um prazo de guarda não retroage sobre o que ainda não
--      estava guardado.
--
-- Os 5 anos estão escritos aqui e em `app/routers/compliance.py`
-- (RETENCAO_ANOS), que é quem grava o piso. São o mesmo número em dois
-- lugares de propósito: o piso é congelado na regra da época do
-- arquivamento, então mudar o prazo legal amanhã deve mudar só ESTE, e
-- deixar os pisos já gravados como estão.
create or replace function fn_retencao_efetiva_em(
    p_tomador_id  uuid,
    p_piso        date,
    p_referencia  date
) returns date as $$
declare
    v_encerramento date;
begin
    if fn_relacao_em_curso(p_tomador_id, p_referencia) then
        return 'infinity'::date;
    end if;

    v_encerramento := fn_encerramento_relacao(p_tomador_id, p_referencia);

    if v_encerramento is null then
        return p_piso;
    end if;

    -- Lei 9.613/98, art. 10, III — cinco anos do encerramento da relação.
    return greatest(p_piso, (v_encerramento + make_interval(years => 5))::date);
end;
$$ language plpgsql stable;

-- Atalho para "hoje", que é o que o trigger pergunta. Existe para que o
-- trigger não repita `current_date` e para que ninguém seja tentado a
-- escrever uma segunda versão da regra "sem data de referência".
create or replace function fn_retencao_efetiva(
    p_tomador_id  uuid,
    p_piso        date
) returns date as $$
begin
    return fn_retencao_efetiva_em(p_tomador_id, p_piso, current_date);
end;
$$ language plpgsql stable;

comment on function fn_retencao_efetiva_em(uuid, date, date) is
    'Retenção efetiva de um documento na DATA DE REFERÊNCIA: infinity se a relação com o tomador estava viva, greatest(piso, último encerramento + 5 anos) se já havia encerrado, e o próprio piso se o tomador nunca teve operação. Responde à pergunta de auditoria "este documento podia ter sido apagado naquela data?" (Lei 9.613/98, art. 10, III).';
comment on function fn_retencao_efetiva(uuid, date) is
    'fn_retencao_efetiva_em com referência em current_date — é a forma que o trigger OC013 consulta.';

-- ---------------------------------------------------------------------
-- 4. O trigger OC013, ancorado
-- ---------------------------------------------------------------------
-- CREATE OR REPLACE recopia a função inteira: abaixo está a versão da 010
-- com UMA diferença de comportamento — a data-limite do DELETE deixa de ser
-- `old.retencao_ate` e passa a ser `fn_retencao_efetiva(...)`. O ramo do
-- UPDATE fica letra por letra como estava, e isso é a metade do desenho: a
-- saída (a) do cabeçalho é recusada AQUI, no lugar onde ela teria de ser
-- aberta.
--
-- A MENSAGEM PASSA A DIZER QUAL ÂNCORA SEGURA. Sem isso, um operador
-- olhando um documento de seis anos recusado pelo banco não teria como
-- distinguir "a relação ainda está viva" de "encerrou há pouco" de "o piso
-- é que ainda não venceu" — e as três têm providências diferentes.
create or replace function fn_documento_retencao()
returns trigger as $$
declare
    v_efetiva      date;
    v_encerramento date;
begin
    if tg_op = 'DELETE' then
        v_efetiva := fn_retencao_efetiva(old.tomador_id, old.retencao_ate);

        if v_efetiva >= current_date then
            if fn_relacao_em_curso(old.tomador_id, current_date) then
                raise exception
                    'Documento % do tomador % não pode ser apagado: a relação de negócio ainda não encerrou, e o prazo de 5 anos conta do encerramento (Lei 9.613/98, art. 10, III). Piso do arquivamento: %.',
                    old.nome_arquivo, old.tomador_id, old.retencao_ate
                    using errcode = 'OC013';
            end if;

            v_encerramento := fn_encerramento_relacao(old.tomador_id, current_date);

            raise exception
                'Documento % do tomador % está em retenção legal até % (Lei 9.613/98, art. 10, III). Piso do arquivamento: %; encerramento da relação: %.',
                old.nome_arquivo, old.tomador_id, v_efetiva, old.retencao_ate,
                coalesce(v_encerramento::text, 'nenhuma operação encerrada')
                using errcode = 'OC013';
        end if;

        return old;
    end if;

    raise exception 'Evidência de identificação não pode ser alterada, apenas substituída por nova.'
        using errcode = 'OC013';
end;
$$ language plpgsql;

comment on function fn_documento_retencao() is
    'OC013 — evidência de identificação: DELETE só depois de vencida a retenção EFETIVA (migration 022: greatest do piso gravado e do encerramento da relação + 5 anos, Lei 9.613/98 art. 10, III) e UPDATE nunca, em coluna nenhuma. Isso inclui storage_objeto (migration 019) e o próprio retencao_ate: o prazo se estende por derivação, não por reescrita.';

-- ---------------------------------------------------------------------
-- 5. A leitura: o que a tela e a auditoria consultam
-- ---------------------------------------------------------------------
-- `retencao_efetiva` sai NULO quando a função devolve `infinity`. É uma
-- tradução deliberada na fronteira: 'infinity' é o valor certo para a
-- comparação do trigger e o valor errado para uma tela, onde "31/12/9999"
-- seria lido como bug. Nulo aqui significa, com precisão, "indeterminada —
-- a relação ainda não encerrou", e vem acompanhado do `motivo` para que
-- ninguém precise adivinhar.
--
-- `retencao_piso` mantém o nome da coluna à mostra (`retencao_ate`) no
-- campo `retencao_ate` da API: o que a 022 muda é o SIGNIFICADO do número,
-- não o contrato de quem já o consome.
create or replace view v_documento_retencao as
select d.id            as documento_id,
       d.tomador_id,
       d.tipo,
       d.nome_arquivo,
       d.sha256,
       d.arquivado_em,
       d.storage_objeto,
       d.retencao_ate  as retencao_piso,
       fn_relacao_em_curso(d.tomador_id, current_date)      as relacao_em_curso,
       fn_encerramento_relacao(d.tomador_id, current_date)  as encerramento_relacao,
       nullif(fn_retencao_efetiva(d.tomador_id, d.retencao_ate), 'infinity'::date)
                                                            as retencao_efetiva,
       case
           when fn_relacao_em_curso(d.tomador_id, current_date)
               then 'relação de negócio em curso: o prazo de 5 anos ainda não começou a correr'
           when fn_encerramento_relacao(d.tomador_id, current_date) is null
               then 'tomador sem operação encerrada: vale o piso do arquivamento'
           when fn_retencao_efetiva(d.tomador_id, d.retencao_ate) = d.retencao_ate
               then 'piso do arquivamento é posterior ao encerramento + 5 anos'
           else 'ancorado no encerramento da relação + 5 anos'
       end                                                  as motivo
from tomador_documento d;

comment on view v_documento_retencao is
    'Retenção de cada evidência com o prazo EFETIVO ao lado do piso gravado (migration 022). retencao_efetiva nula = indeterminada, porque a relação de negócio com o tomador ainda não encerrou.';
