-- OrgCred — a identidade do crédito não depende da conta
--
-- TERCEIRA MIGRATION SEGUIDA SOBRE A MESMA CHAVE, e o cabeçalho começa por isso
-- porque a repetição é o achado:
--
--   009  chave = (documento)                 -> perdia o crédito do 2º banco
--   027  chave = (documento, conta_origem)   -> DOBRAVA o lastro (grafia ≠ conta)
--   028  chave = (documento, conta_chave)    -> DOBRAVA do outro lado (ACCTID)
--
-- A 028 canonizou a grafia para neutralizar a ausência do `<BANKID>`. Foi
-- verificada nos dois sentidos e commitada. Horas depois, sete lentes acharam a
-- METADE SIMÉTRICA: quando falta o `<ACCTID>`, `_formatar_conta` devolve o
-- código do banco — ou None — e a mesma conta ocupa outro espaço de nomes.
-- Medido: R$ 6.000 recebidos viram R$ 12.000 de lastro, as parcelas ficam
-- quitadas contra dinheiro que não entrou, `liquidar` é aceito e o comprometido
-- volta a zero. O crítico da 027, inteiro, pela porta do ACCTID.
--
-- ---------------------------------------------------------------------
-- A PREMISSA ERRADA, e é ela que esta migration corrige
-- ---------------------------------------------------------------------
-- As três chaves acima compartilham uma suposição que nunca foi enunciada: que
-- o arquivo DIZ de qual conta a linha é. Ele não diz — ele diz o que o
-- exportador resolveu escrever, e exportações diferentes da MESMA conta
-- escrevem coisas diferentes: com BANKID e sem, com ACCTID e sem, com o bloco
-- `<BANKACCTFROM>` e sem ele.
--
-- CANONIZAÇÃO NORMALIZA FORMATO; NÃO RECUPERA INFORMAÇÃO AUSENTE. Enquanto a
-- conta fizer parte da identidade, sempre haverá um par de exportações da mesma
-- conta em que uma declara menos que a outra — e duas declarações diferentes
-- viram dois espaços de nomes, e dois espaços de nomes duplicam o lastro. Não é
-- uma canonização incompleta: é a forma da solução que está errada. Foi por
-- isso que consertar a metade BANKID não fechou nada.
--
-- A IDENTIDADE DE UM CRÉDITO É O CRÉDITO: quem o identificou (o FITID), quanto
-- é e quando entrou. A conta é PROVENIÊNCIA — diz de onde a linha veio, serve
-- para o operador conferir e para a tela mostrar, e não decide se duas linhas
-- são a mesma. `conta_origem` e `conta_chave` continuam gravadas e continuam
-- na tela; saem apenas da resposta à pergunta "isto já está aqui?".
--
-- ---------------------------------------------------------------------
-- DUAS CHAVES, PORQUE SÃO DUAS PERGUNTAS DIFERENTES
-- ---------------------------------------------------------------------
-- (A) `(documento, conta_chave)`, que a 028 criou, FICA. Ela responde "o mesmo
--     FITID pode aparecer duas vezes NESTA conta?" — não pode, é a regra da
--     especificação OFX. É ela que barra o extrato reemitido com o mesmo FITID
--     e valor CORRIGIDO: mesma conta, mesmo identificador, valor diferente.
--     Sozinha ela não impede a duplicação por grafia, mas removê-la abriria
--     esse outro caminho.
--
-- (B) `(documento, valor, data_movimento)`, NOVA, responde "este crédito já
--     está aqui, tenha vindo de onde tiver vindo?". É a que fecha a classe
--     inteira: nenhuma grafia, nenhum bloco ausente, nenhuma diferença entre
--     lançamento manual e OFX cria espaço de nomes novo, porque a conta não
--     aparece nela.
--
-- AS DUAS JUNTAS, e o INSERT usa `on conflict do nothing` SEM alvo — a forma
-- que ignora conflito com QUALQUER restrição, e não só com a que se nomeou.
-- Nomear um alvo aqui seria escolher qual metade da proteção vale.
--
-- ---------------------------------------------------------------------
-- O CUSTO, medido e assumido — e por que este é o lado certo de errar
-- ---------------------------------------------------------------------
-- Dois bancos diferentes que emitam o MESMO FITID com o MESMO valor no MESMO
-- dia passam a colidir: a segunda linha é pulada, e um crédito real fica de
-- fora do lastro. É mais estreito que o custo da 028 (que exigia coincidência
-- no número da conta) e continua sendo uma perda.
--
-- É O LADO CERTO DE ERRAR, e a assimetria não é opinião:
--
--   - DUPLICAR fabrica lastro. Lastro fabricado quita parcela que ninguém
--     pagou, `liquidar` é aceito (OC022 pede "todas as parcelas pagas") e o
--     capital volta ao teto do Art. 5º — a ESC passa a poder emprestar de novo
--     dinheiro que não voltou. É o invariante que este sistema existe para não
--     violar, e o erro é INVISÍVEL e IRREVERSÍVEL (movimento é imutável por
--     OC012, baixa não tem estorno).
--
--   - PULAR deixa um crédito de fora. O tomador que pagou aparece em atraso, o
--     operador confere o extrato e lança o movimento à mão. Recuperável em um
--     minuto — DESDE QUE ELE VEJA, e é por isso que a visibilidade abaixo não é
--     acessório.
--
-- ---------------------------------------------------------------------
-- O QUE FOI PULADO PRECISA SER VISÍVEL, e desta vez de verdade
-- ---------------------------------------------------------------------
-- A 028 já dizia isso e não entregava. Duas razões, as duas medidas:
--
--   1. a comparação rodava só contra o que chegou ao banco, então a linha
--      descartada pela deduplicação EM MEMÓRIA saía como
--      `repetidos_no_arquivo` — cuja explicação na tela manda o operador
--      auditar o BANCO por "anomalia do arquivo", quando o arquivo estava
--      perfeito e quem fundiu as linhas foi a nossa chave;
--
--   2. `ja_registrados` era DERIVADO por subtração (`len(unicas) - criados -
--      conflitos`), o que torna a soma dos destinos uma identidade algébrica: o
--      selo "Nenhuma linha do extrato se perdeu" não podia falhar nem com o
--      motor quebrado. Um selo que não pode falhar não é conferência, é
--      decoração com aparência de prova.
--
-- Ambos são conserto de aplicação (app/capital_engine.py) e não de schema; esta
-- migration entra na conta porque a regra que os dois implementam é a daqui.
-- A view abaixo é o que a aplicação consulta para separar "já está aqui igual"
-- de "já está aqui diferente".
create or replace view v_credito_por_identidade as
    select id, documento, valor, data_movimento, conta_chave, conta_origem, origem
      from movimento_bancario;

comment on view v_credito_por_identidade is
    'A identidade de um crédito: (documento, valor, data_movimento). A conta viaja junto como PROVENIÊNCIA — ela diz de onde a linha veio, não decide se duas linhas são a mesma.';

alter table movimento_bancario
    drop constraint if exists movimento_credito_unico;

alter table movimento_bancario
    add constraint movimento_credito_unico
    unique (documento, valor, data_movimento);

comment on constraint movimento_credito_unico on movimento_bancario is
    'O mesmo crédito não entra duas vezes, tenha vindo por qual grafia de conta for. Fecha a classe inteira que derrubou a 027 e a 028: enquanto a conta participava da identidade, sempre havia um par de exportações da MESMA conta em que uma declarava menos que a outra.';

-- A chave da 028 fica, e o comentário passa a dizer o que ela cobre DE FATO,
-- para ninguém voltar a tratá-la como a defesa contra duplicação.
comment on constraint movimento_documento_por_conta on movimento_bancario is
    'O mesmo FITID não se repete DENTRO da conta (especificação OFX) — é esta que barra o extrato reemitido com o mesmo identificador e valor corrigido. NÃO é a defesa contra duplicação por grafia: essa é movimento_credito_unico, porque a conta não pode participar da identidade.';

-- ---------------------------------------------------------------------
-- OC026 DEIXA DE SER UM GATE SEM TRAVA
-- ---------------------------------------------------------------------
-- `fn_operacao_em_cobranca` lia o status SEM LOCK e era `stable`. Medido: duas
-- sessões, uma baixando a parcela e outra renegociando a operação, atravessam
-- as duas guardas e deixam no banco exatamente o estado que a 028 declara
-- impossível — parcela 'paga' com lastro na agenda de um título extinto, com o
-- movimento queimado para sempre.
--
-- `for share` e não `for update`: a baixa não altera a operação, só precisa que
-- ela não SAIA de cobrança até o commit. `for share` deixa outras baixas
-- correrem em paralelo (elas não conflitam entre si) e bloqueia a transição de
-- status, que é exatamente a corrida a fechar. A função vira `volatile`, porque
-- uma função que adquire lock não é `stable`.
--
-- A ORDEM DE LOCK É A MESMA nos dois caminhos que a tomam — primeiro a parcela
-- (`fn_baixar_parcela` já fazia `for update`), depois a operação —, e é isso
-- que impede que a trava vire deadlock.
create or replace function fn_operacao_em_cobranca(p_operacao_id uuid)
returns text as $$
declare
    v_status text;
begin
    select status into v_status
      from operacao_credito
     where id = p_operacao_id
       for share;
    if not found then
        return 'inexistente';
    end if;
    return v_status;
end;
$$ language plpgsql volatile;

comment on function fn_operacao_em_cobranca(uuid) is
    'Status da operação de uma parcela, para o gate OC026, COM `for share`: sem o lock o gate valia só na direção sequencial em que foi desenhado, e uma renegociação concorrente atravessava as duas guardas. Devolve ''inexistente'' em vez de NULL para não confundir "não achei" com "achei sem status".';
