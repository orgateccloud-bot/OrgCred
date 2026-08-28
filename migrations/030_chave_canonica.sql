-- OrgCred — a canonização vai para os campos que FORMAM a identidade
--
-- QUARTA MIGRATION SEGUIDA SOBRE A MESMA CHAVE. A lista, porque a forma do erro
-- é a informação:
--
--   009  (documento)                  -> perdia o crédito do 2º banco
--   027  (documento, conta_origem)    -> DOBRAVA (grafia da conta)
--   028  (documento, conta_chave)     -> DOBRAVA (metade do ACCTID)
--   029  (documento, valor, data)     -> DOBRAVA (grafia do FITID, fuso da data)
--   030  (documento_chave, valor, data canônica)
--
-- A 029 acertou o diagnóstico e aplicou-o a UM dos três campos. Ela escreveu
-- que "exportações diferentes da mesma conta escrevem coisas diferentes",
-- concluiu que a conta não podia estar na identidade, e não fez a mesma
-- pergunta aos dois campos que ficaram.
--
-- O RESULTADO É UMA IRONIA VERIFICÁVEL: `fn_conta_chave` — a única canonização
-- do sistema — está aplicada a `conta_origem`, que a 029 REMOVEU da identidade;
-- enquanto `documento` é comparado byte a byte e `data_movimento` sai de um
-- parser que DESCARTA o fuso declarado. A canonização ficou no campo que não é
-- mais identidade; a identidade ficou sem canonização.
--
-- Medido, com a mesma travessia de sempre até o teto do Art. 5º:
--
--   FITID 'TED1' contra 'ted1'    -> duas linhas, lastro dobrado
--   FITID 'TED1' contra '0TED1'   -> duas linhas, lastro dobrado
--   FITID 'TED1' contra 'TED 1'   -> duas linhas, lastro dobrado
--   DTPOSTED '20260810220000[-3:BRT]' contra '20260811010000[0:GMT]'
--     — o MESMO INSTANTE — -> 2026-08-10 contra 2026-08-11, lastro dobrado
--
-- ---------------------------------------------------------------------
-- A REGRA, ENUNCIADA UMA VEZ E APLICADA A TODOS OS CAMPOS DA IDENTIDADE
-- ---------------------------------------------------------------------
-- TODO campo que participa da identidade é CANÔNICO; o verbatim fica ao lado,
-- como proveniência. Não é uma correção a mais na lista: é o que faltava para a
-- regra da 029 ser aplicável sem que alguém precise LEMBRAR de aplicá-la a cada
-- campo novo.
--
-- `fn_chave_texto` é a normalização, extraída para uma função só — antes ela
-- estava embutida em `fn_conta_chave` e por isso não podia ser reusada. Regra:
-- some o que não é alfanumérico, sobem as maiúsculas, caem os zeros à esquerda
-- (preservando ao menos um caractere, para que '000' e '0' sejam a mesma coisa
-- em vez de um deles virar vazio).
create or replace function fn_chave_texto(p_texto text)
returns text as $$
    select nullif(
        regexp_replace(
            upper(regexp_replace(p_texto, '[^0-9A-Za-z]', '', 'g')),
            '^0+(.)',
            '\1'
        ),
        ''
    )
$$ language sql immutable strict;

comment on function fn_chave_texto(text) is
    'A normalização de representação, num lugar só: sem pontuação, maiúsculas, sem zeros à esquerda (guardando um caractere). Todo campo que forma identidade passa por ela — foi não fazer isso que deixou o FITID comparado byte a byte enquanto a conta, já fora da identidade, era a única canonizada.';

-- `fn_conta_chave` passa a ser um caso da regra geral, e não a regra.
create or replace function fn_conta_chave(p_conta text)
returns text as $$
    select fn_chave_texto(split_part(p_conta, '/', -1))
$$ language sql immutable strict;

-- ---------------------------------------------------------------------
-- O DOCUMENTO GANHA CHAVE, COMO A CONTA JÁ TINHA
-- ---------------------------------------------------------------------
-- `documento` fica verbatim: é o que o banco escreveu, é o que a tela mostra e
-- é por ele que o operador procura a linha no extrato de papel. `coalesce` com
-- o verbatim em maiúsculas porque `documento` é NOT NULL e precisa continuar
-- identificando: um FITID que canonize para vazio (só pontuação) não pode
-- virar NULL, ou duas linhas sem nada em comum passariam a colidir.
-- UMA função para a coluna gerada E para a consulta da importação. Sem ela, a
-- expressão do `generated always as` teria que ser repetida em SQL solto na
-- aplicação — e duas cópias de uma regra de identidade é exatamente como o
-- FITID acabou comparado byte a byte de um lado e canonizado de nenhum.
create or replace function fn_documento_chave(p_documento text)
returns text as $$
    select coalesce(fn_chave_texto(p_documento), upper(p_documento))
$$ language sql immutable strict;

comment on function fn_documento_chave(text) is
    'A identidade do identificador do extrato. É esta função que a coluna gerada movimento_bancario.documento_chave calcula, e é a MESMA que a importação usa para procurar o que já está gravado.';

alter table movimento_bancario
    drop column if exists documento_chave;

alter table movimento_bancario
    add column documento_chave text
    generated always as (fn_documento_chave(documento)) stored;

comment on column movimento_bancario.documento is
    'O identificador COMO O BANCO ESCREVEU (FITID). Proveniência e busca — não é identidade: exportadores diferentes escrevem o mesmo identificador com caixa, espaço e zeros à esquerda diferentes. A identidade é documento_chave.';
comment on column movimento_bancario.documento_chave is
    'O identificador canônico, gerado pelo banco. Forma a identidade do crédito junto com valor e data.';

alter table movimento_bancario
    drop constraint if exists movimento_credito_unico;

alter table movimento_bancario
    add constraint movimento_credito_unico
    unique (documento_chave, valor, data_movimento);

comment on constraint movimento_credito_unico on movimento_bancario is
    'A identidade de um crédito: identificador CANÔNICO, valor e data. Todos os três campos normalizados — foi ter deixado dois deles verbatim que fez a 029 duplicar lastro por caixa do FITID e por fuso do DTPOSTED.';

-- A chave por conta acompanha, pelo mesmo motivo: ela também comparava o
-- documento byte a byte, então 'TED1' e 'ted1' na MESMA conta passavam por
-- identificadores diferentes — e essa é a chave que existe justamente para
-- impedir o mesmo FITID de se repetir dentro de uma conta.
alter table movimento_bancario
    drop constraint if exists movimento_documento_por_conta;

alter table movimento_bancario
    add constraint movimento_documento_por_conta
    unique nulls not distinct (documento_chave, conta_chave);

comment on constraint movimento_documento_por_conta on movimento_bancario is
    'O mesmo identificador não se repete DENTRO da conta (especificação OFX), comparado pela forma CANÔNICA. Barra o extrato reemitido com o mesmo identificador e valor corrigido.';
