-- OrgCred — a proveniência do extrato: de qual ARQUIVO o movimento veio
--
-- O PROBLEMA, em uma frase: até aqui o único produtor de `movimento_bancario`
-- era um formulário, e o lastro bancário da carteira inteira era AUTO-DECLARADO.
--
-- A migration 009 fechou o furo ESTRUTURAL — não existe parcela 'paga' sem uma
-- linha de extrato apontada (OC011) — e a 016 fechou o de reescrita (o lastro
-- de uma baixa não se reaponta). Nenhuma das duas toca no furo PROBATÓRIO: a
-- linha de extrato que elas exigem nasce de `POST /cobranca/movimentos`, com
-- data, valor e `documento` DIGITADOS. Um operador que quisesse fazer uma
-- carteira podre parecer saudável não precisava contornar invariante nenhum;
-- bastava digitar um FITID inventado e usar o movimento resultante na baixa. O
-- sistema provava "existe um registro apontado", nunca "o dinheiro entrou".
--
-- Para uma ESC (LC 167/2019), cuja defesa em fiscalização é a rastreabilidade
-- do fluxo financeiro — e cujo capital é próprio, o que torna o extrato a
-- única testemunha externa da operação —, essa é a diferença entre ter e não
-- ter prova.
--
-- O QUE ESTA MIGRATION FAZ: dá ao movimento importado um vínculo com o ARQUIVO
-- que o originou (o SHA-256 dos bytes recebidos) e com a CONTA declarada nele
-- (BANKID/ACCTID), e torna esse vínculo OBRIGATÓRIO para quem se diz importado.
--
-- POR QUE `origem` SOZINHA NÃO BASTAVA — a pergunta que este passo tinha que
-- responder. A coluna `origem` já existe desde a 009 e o CHECK dela já admite
-- 'ofx'; junto com `usuario_id`, ela responde literalmente ao "quem importou e
-- que não foi digitado". Mas responde do mesmo jeito que a carteira respondia
-- antes: por auto-declaração. `insert into movimento_bancario (..., origem)
-- values (..., 'ofx')` é uma palavra a mais na digitação, e produziria um
-- movimento com o CARIMBO de importado e nenhum arquivo atrás — trocando o
-- lastro auto-declarado por um selo auto-declarado, que é pior, porque agora
-- mente com aparência de prova.
--
-- Com a constraint abaixo, 'ofx' passa a EXIGIR um hash de 64 hexadecimais.
-- Isso não impede alguém de calcular o SHA-256 de um arquivo qualquer e
-- digitá-lo — nada em trigger impede quem tem SQL direto —, mas muda a natureza
-- do ato: deixa de ser digitar um número e passa a ser produzir um arquivo cujo
-- hash bate com o gravado, que é exatamente o que a fiscalização pede e o que
-- a ESC guarda. E fecha, de vez, o caminho barato: pelo formulário manual, que
-- não coleta hash nenhum, 'ofx' é agora inalcançável.
--
-- NENHUM SQLSTATE NOVO, pelo mesmo critério da 016: não há regra de negócio
-- nova a explicar ao operador. Quem esbarrar nesta constraint está inserindo
-- por SQL direto (a aplicação preenche as duas colunas juntas, sempre), e a
-- recusa 23514 é a resposta certa para uso indevido do schema — não para um
-- ato de operação. Inventar um OC0xx aqui criaria uma mensagem de UI para um
-- caminho que a UI não tem.
--
-- AS COLUNAS SÃO WRITE-ONCE POR CONSTRUÇÃO, sem precisar de guarda nova:
-- `movimento_bancario` é imutável desde a 009 (OC012 recusa UPDATE e DELETE de
-- linha). Não há back-fill possível para movimentos manuais antigos, e é o que
-- se quer: um movimento digitado em março não vira "importado" em agosto.
--
-- ATENÇÃO PARA APLICAR EM BASE COM DADOS: ADD CONSTRAINT ... CHECK valida a
-- tabela inteira. Conferir antes que nenhuma linha já se diz importada:
--   select count(*) from movimento_bancario where origem = 'ofx';
-- Zero é o esperado (nenhum caminho de produção jamais gravou 'ofx' — o
-- formulário grava sempre 'manual'). Diferente de zero significa que alguém
-- carimbou movimentos à mão, e essas linhas precisam ser reconciliadas contra
-- o extrato de verdade ANTES desta migration — não é caso de relaxar o CHECK.

-- ---------------------------------------------------------------------
-- As duas colunas de proveniência
-- ---------------------------------------------------------------------
alter table movimento_bancario
    add column if not exists arquivo_sha256 text,
    add column if not exists conta_origem   text;

-- SHA-256 do ARQUIVO recebido, e não do conteúdo interpretado: o que a ESC
-- arquiva e o que o fiscal pede é o extrato como o banco o emitiu. Hash de uma
-- normalização nossa só provaria concordância com a nossa própria leitura.
comment on column movimento_bancario.arquivo_sha256 is
    'SHA-256 (hex minúsculo) dos bytes do OFX que originou este movimento. NULL para lançamento manual. Obrigatório quando origem = ''ofx''.';

-- Nullable mesmo para 'ofx': OFX de cartão traz só ACCTID, e exportação capada
-- pode não trazer conta nenhuma. Exigir o que o arquivo pode legitimamente não
-- ter transformaria extrato válido em erro de importação.
comment on column movimento_bancario.conta_origem is
    'Conta declarada no OFX, no formato BANKID/ACCTID (ou só ACCTID em extrato de cartão). NULL quando o arquivo não a declara.';

-- ---------------------------------------------------------------------
-- Coerência: quem se diz importado tem que apontar para um arquivo
-- ---------------------------------------------------------------------
-- Escrita com `is not null` EXPLÍCITO antes do regex, e não só
-- `arquivo_sha256 ~ '...'`: em SQL, um CHECK cujo resultado é NULL PASSA. Com
-- o regex sozinho, `origem = 'ofx'` com hash nulo produziria NULL e seria
-- aceito — a constraint existiria e não guardaria nada, que é a forma mais
-- silenciosa possível de um invariante falhar.
--
-- O outro lado da disjunção proíbe o manual de ter proveniência. Não é
-- simetria decorativa: um `conta_origem` digitado num lançamento manual seria
-- de novo a auto-declaração, agora num campo que a tela apresentaria como se
-- viesse do banco.
alter table movimento_bancario
    drop constraint if exists movimento_proveniencia_coerente;
alter table movimento_bancario
    add constraint movimento_proveniencia_coerente
    check (
        (origem = 'ofx'
         and arquivo_sha256 is not null
         and arquivo_sha256 ~ '^[0-9a-f]{64}$')
        or
        (origem <> 'ofx'
         and arquivo_sha256 is null
         and conta_origem is null)
    );

-- Parcial porque só os importados têm hash, e a pergunta que este índice serve
-- é sempre a mesma e sempre sobre eles: "mostre tudo que entrou por este
-- arquivo" — a consulta que reconstrói uma importação inteira diante do fiscal,
-- e a que responde se um extrato já foi importado antes de reimportá-lo.
create index if not exists idx_movimento_arquivo
    on movimento_bancario(arquivo_sha256)
    where arquivo_sha256 is not null;

comment on constraint movimento_proveniencia_coerente on movimento_bancario is
    'origem = ''ofx'' exige SHA-256 do arquivo de origem; origem manual não pode ter proveniência de arquivo.';
