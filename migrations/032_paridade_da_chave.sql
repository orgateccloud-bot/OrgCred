-- OrgCred — o espelho da chave concorda em todo o Unicode
--
-- A 030 pôs a identidade do crédito atrás de uma função canônica e escreveu que
-- a cópia em Python (`app.ofx`) e a do banco (`fn_*`) têm que concordar SEMPRE,
-- porque uma divergência silenciosa entre as duas é a classe de defeito que
-- quatro migrations existiram para matar. Um mapeamento independente encontrou
-- a exceção que o teste da 030 não cobria: ela enumerava 13 casos ASCII, e a
-- divergência mora fora do ASCII.
--
-- ONDE: no FALLBACK de `fn_documento_chave`. `documento` é NOT NULL, então
-- quando a forma canônica esvazia (um FITID só de pontuação ou de caracteres
-- não-ASCII) a função cai no verbatim para não devolver NULL. A 030 escreveu
-- esse fallback como `upper(p_documento)` — e `upper()` é o único ponto em que
-- Python e Postgres discordam:
--
--   documento_chave('ß')  -> Python 'SS'   (str.upper EXPANDE)
--   documento_chave('ß')  -> Postgres 'ß'  (upper() NÃO expande)
--
-- O EFEITO é o de sempre, do lado seguro mas real: a chave gravada usa a versão
-- do banco ('ß'), e a deduplicação em memória usa a do Python ('SS'). Uma linha
-- recém-criada deixa de casar com o próprio RETURNING e é recontada de `criados`
-- para `ja_registrados` — o selo "nenhuma linha se perdeu" quebra. Não dobra
-- lastro (a UNIQUE do banco é consistente consigo mesma), mas é a paridade que
-- a 030 prometeu, furada.
--
-- O CONSERTO É TIRAR O `upper()` DO FALLBACK, e não é perda: o fallback só é
-- alcançado quando NENHUM alfanumérico ASCII sobreviveu à limpeza — logo não há
-- letra ASCII a maiuscularizar, e a única coisa que `upper()` faz ali é tocar
-- exatamente os caracteres onde as duas linguagens divergem. Verbatim puro
-- concorda por construção, e a canonização de verdade (a que casa 'ted1' com
-- 'TED1') continua inteira no caminho principal, `fn_chave_texto`, que não muda.
create or replace function fn_documento_chave(p_documento text)
returns text as $$
    select coalesce(fn_chave_texto(p_documento), p_documento)
$$ language sql immutable strict;

comment on function fn_documento_chave(text) is
    'A identidade do identificador do extrato. Fallback é o verbatim SEM upper() (030 usava upper e divergia do str.upper do Python fora do ASCII): o fallback só é alcançado quando não há alfanumérico ASCII, então não há o que maiuscularizar e o upper só criava divergência.';
