-- OrgCred — registro em entidade registradora não NASCE confirmado
--
-- O DEFEITO. `fn_registro_transicao` (012) é a máquina de estados do registro,
-- e o trigger que a chama é `before update or delete`. O INSERT ficou de fora.
-- A tabela aceita, hoje, num único comando:
--
--   insert into registro_operacao
--       (operacao_id, entidade, status, protocolo, confirmado_em)
--   values (<uuid da operação>, 'CRDC', 'confirmado', 'PROTO-000123',
--           clock_timestamp());
--
-- (O uuid vai escrito por extenso, e não como parâmetro nomeado no estilo
-- dois-pontos-mais-nome, porque este arquivo é lido e executado via `text()`
-- do SQLAlchemy pelo conftest — que procura esses parâmetros até DENTRO de
-- comentário e transforma o exemplo num bind que ninguém preenche. O erro
-- aparece na criação do banco de teste, longe daqui.)
--
-- ... e as duas CHECK constraints da 012 aplaudem, porque protocolo e
-- confirmado_em estão lá. A linha nasce no estado TERMINAL sem nunca ter
-- passado por 'pendente' — ou seja, sem que exista o par de eventos (envio à
-- entidade, confirmação com protocolo) que é a única coisa capaz de
-- distinguir "houve processo de registro" de "alguém digitou um número".
--
-- POR QUE ISSO ESVAZIA O GATE OC004. Desde a 013, `registrada -> ativa` exige
-- registro CONFIRMADO (Art. 5º §3º, LC 167/2019). A 013 aposentou o texto
-- livre de `registro_entidade_ref` com o argumento de que "escrever 'x' ali
-- passava". Com o INSERT descoberto, escrever a MESMA string na coluna
-- `protocolo` de uma linha recém-criada passa igual: mudou a tabela em que se
-- digita, não a natureza da prova. O gate provava que alguém digitou um
-- protocolo, não que houve registro — que é exatamente o defeito que a 013
-- dizia ter corrigido.
--
-- ---------------------------------------------------------------------
-- A DECISÃO: RECUSAR, não forçar em silêncio
-- ---------------------------------------------------------------------
-- As duas saídas eram forçar `new.status := 'pendente'` (o INSERT passa, com
-- a intenção corrigida sem alarde) ou recusar com SQLSTATE. Este projeto já
-- tem resposta para os dois lados, e ela não é ambígua:
--
--   (a) O ÚNICO caso em que um trigger daqui sobrescreve o que o escritor
--       mandou é campo DERIVADO — `updated_at` (001), `sha256` do contrato
--       (012), `prev_hash`/`current_hash`/`created_at` do ledger (005/020).
--       São valores que quem escreve não tem o que opinar a respeito, e a
--       020 diz o porquê em uma linha: "numa trilha append-only, o dado que
--       entra no digest não pode ser ditado por quem escreve". Nenhum deles
--       carrega intenção; são calculados a partir do resto da linha.
--
--   (b) Quando o campo carrega uma AFIRMAÇÃO sobre o mundo, o projeto recusa.
--       O precedente é literalmente da mesma forma que este: em
--       `fn_check_teto_capital` (006/013/014), `if tg_op = 'INSERT' and
--       new.status not in ('proposta','registrada') then raise ... OC003` —
--       uma operação de crédito não pode NASCER ativa, e o banco não a
--       rebaixa para 'proposta' fingindo que o pedido foi outro: recusa. A
--       015 faz o mesmo com valor de operação comprometida (OC020) e com o
--       histórico de capital (OC021), em vez de reverter o campo calado.
--
-- `status = 'confirmado'` é afirmação, não derivação: quem escreve isso está
-- dizendo que a entidade registradora confirmou. Forçar para 'pendente'
-- devolveria 201 com `status: pendente` para quem pediu 'confirmado' — o
-- escritor de boa-fé sai achando que registrou, o de má-fé sai sem rastro
-- nenhum, e a tentativa (o dado mais valioso que existe num invariante
-- antifraude) evapora. A recusa é a única das duas que preserva a intenção
-- de quem tentou, porque a transação aborta com o motivo escrito.
--
-- O CUSTO DE RECUSAR FOI MEDIDO, não estimado: o único caminho de INSERT da
-- aplicação é `POST /operacoes/{id}/registros` (app/routers/contratos.py),
-- que insere `(operacao_id, entidade, usuario_id)` e deixa `status` no
-- default da coluna. Ele não muda de comportamento. O único outro escritor no
-- repositório era o helper `confirmar_registro` de tests/conftest.py, que
-- inseria a linha já confirmada para montar cenário — e passa a abrir em
-- 'pendente' e confirmar por UPDATE, exercitando a máquina de estados de
-- verdade em vez de contorná-la.
--
-- ---------------------------------------------------------------------
-- O CÓDIGO: OC018 reaproveitado, sem código novo
-- ---------------------------------------------------------------------
-- OC018 já é "transição inválida de status de registro". O que esta migration
-- corrige não é uma regra nova: é a ARESTA INICIAL da mesma máquina de
-- estados, que ficou sem guarda. A instrução ao operador é palavra por
-- palavra a que o OC018 já dá — "abra o registro em pendente e confirme
-- depois, com o protocolo que a entidade devolver".
--
-- O critério é o que a 013 usou para reaproveitar OC004 ("é a MESMA regra
-- legal — só ganhou dentes") e o que a 015 usou para NÃO reaproveitar OC005
-- ("é outra regra e a instrução ao operador é outra"). Aqui é o primeiro
-- caso. Some-se que `RegistroTransicaoInvalida` já existe, já está em
-- PGCODE_MAP (app/core/db_errors.py) e já vira 409 com mensagem traduzida:
-- um OC023 exigiria exceção nova e entrada nova de mapa para um caminho que
-- a UI não tem como alcançar — precisamente o critério pelo qual aquele
-- arquivo justifica deixar OC020 e OC021 FORA do mapa.
--
-- ---------------------------------------------------------------------
-- Uma função só, porque a máquina de estados é uma só
-- ---------------------------------------------------------------------
-- O nascimento entra em `fn_registro_transicao` em vez de virar um segundo
-- trigger com função própria: quem for ler daqui a um ano o que pode
-- acontecer com um registro precisa achar as regras num lugar, não em dois
-- arquivos que só a ordem alfabética dos triggers relaciona.
--
-- CREATE OR REPLACE recopia a função inteira: o corpo abaixo é o da 012
-- (linhas 131-155) verbatim, mais o bloco de INSERT no topo.
create or replace function fn_registro_transicao()
returns trigger as $$
begin
    -- NASCIMENTO. Sai antes de qualquer leitura de `old`: em BEFORE INSERT de
    -- linha `old` é NULL, e tocar em `old.status` aqui seria erro de execução
    -- (o registro morreria com 'record "old" is not assigned yet', SQLSTATE
    -- 55000) em vez de recusa de regra — mesma transação abortada, motivo
    -- ilegível.
    if tg_op = 'INSERT' then
        if new.status <> 'pendente' then
            raise exception
                'Registro de operação nasce em ''pendente'', nunca em ''%'': confirmar ou rejeitar é UPDATE sobre um registro aberto, não INSERT (Art. 5º §3º, LC 167/2019).',
                new.status
                using errcode = 'OC018';
        end if;

        -- 'pendente' INTEIRO, não a palavra 'pendente' pendurada numa linha
        -- terminal. Os três campos são RESULTADO do envio à registradora:
        -- protocolo e confirmado_em são o que a entidade devolve, e
        -- motivo_rejeicao é o que ela alega ao recusar. Nascer com eles
        -- preenchidos deixaria a porta aberta pela variante silenciosa do
        -- mesmo ataque — inserir 'pendente' já com protocolo e
        -- `confirmado_em = <data escolhida>` e depois dar um
        -- `update set status='confirmado'` que não toca em nenhum dos dois:
        -- a CHECK `registro_confirmado_tem_protocolo` (012) fica satisfeita
        -- pelos valores pré-cozidos e o registro passa a exibir uma data de
        -- confirmação ANTERIOR à confirmação. O caminho legítimo não é
        -- afetado: os endpoints de confirmar e rejeitar escrevem esses
        -- campos no próprio UPDATE que muda o status.
        --
        -- Esta cláusula sozinha não bastaria: o mesmo pré-cozimento é
        -- alcançável por UPDATE sobre um registro aberto limpo. Ver a guarda
        -- gêmea no ramo de UPDATE, mais abaixo — as duas juntas é que fazem
        -- 'pendente' significar 'pendente'.
        if new.protocolo is not null
           or new.confirmado_em is not null
           or new.motivo_rejeicao is not null then
            raise exception
                'Registro nasce sem protocolo, sem data de confirmação e sem motivo de rejeição: esses campos são o RESULTADO do envio à entidade registradora e só podem ser gravados no UPDATE que confirma ou rejeita.'
                using errcode = 'OC018';
        end if;

        return new;
    end if;

    if tg_op = 'DELETE' then
        raise exception 'Registro de operação não pode ser apagado.'
            using errcode = 'OC018';
    end if;

    if old.status <> 'pendente' then
        raise exception
            'Registro já está % — é estado terminal.', old.status
            using errcode = 'OC018';
    end if;

    if new.operacao_id is distinct from old.operacao_id
       or new.entidade is distinct from old.entidade
       or new.enviado_em is distinct from old.enviado_em then
        raise exception
            'Operação, entidade e data de envio do registro são imutáveis.'
            using errcode = 'OC018';
    end if;

    -- 'pendente' INTEIRO TAMBÉM NO UPDATE, e não só no nascimento. Fechar o
    -- pré-cozimento apenas no INSERT custaria ao atacante um comando a mais e
    -- nada além disso: abrir o registro limpo (passa), `update set protocolo,
    -- confirmado_em = <data escolhida>` sem mexer no status (old.status é
    -- 'pendente', a CHECK `registro_confirmado_tem_protocolo` nem se aplica a
    -- linha pendente), e então `update set status = 'confirmado'`, que
    -- encontra os campos já preenchidos e satisfaz a CHECK sem ter escrito
    -- nada. O resultado é bit a bit o mesmo que a guarda de nascimento
    -- recusa. Medido nesta base antes de escrever esta cláusula: a linha
    -- terminava 'confirmado', com protocolo à escolha e confirmado_em de
    -- 2020-01-01 sobre enviado_em de 2026-08-15.
    --
    -- Nenhum caminho legítimo faz UPDATE que deixe a linha em 'pendente':
    -- confirmar e rejeitar (app/routers/contratos.py) mudam o status no
    -- mesmo comando em que gravam protocolo/confirmado_em/motivo_rejeicao.
    if new.status = 'pendente'
       and (new.protocolo is not null
            or new.confirmado_em is not null
            or new.motivo_rejeicao is not null) then
        raise exception
            'Registro pendente não carrega protocolo, data de confirmação nem motivo de rejeição: esses campos são gravados no MESMO update que muda o status para confirmado ou rejeitado.'
            using errcode = 'OC018';
    end if;

    -- E a confirmação não antecede o envio. É a última forma de produzir o
    -- mesmo defeito num único comando de forma legítima — `update set
    -- status='confirmado', protocolo=..., confirmado_em='2020-01-01'` —, e é
    -- impossível por construção: a entidade registradora não confirma o que
    -- ainda não recebeu. Note que isto NÃO é a decisão pendente sobre
    -- `enviado_em` (que segue aceitando valor no INSERT, e portanto ainda
    -- permite antedatar a ABERTURA): é só a ordem entre os dois carimbos, que
    -- vale qualquer que seja a origem do primeiro.
    if new.confirmado_em is not null and new.confirmado_em < new.enviado_em then
        raise exception
            'Data de confirmação (%) é anterior ao envio à entidade registradora (%): a registradora não confirma o que ainda não recebeu.',
            new.confirmado_em, new.enviado_em
            using errcode = 'OC018';
    end if;

    return new;
end;
$$ language plpgsql;

-- O trigger da 012 é `before update or delete`; recriá-lo com `insert` junto é
-- a única mudança de forma desta migration. `drop trigger if exists` antes,
-- como a 007..015 fazem, para que reaplicar a cadeia inteira sobre um banco
-- existente (o movimento normal de reconferência de schema em incidente) não
-- aborte com 42710.
drop trigger if exists trg_registro_transicao on registro_operacao;
create trigger trg_registro_transicao
    before insert or update or delete on registro_operacao
    for each row execute function fn_registro_transicao();

comment on function fn_registro_transicao() is
    'OC018 — máquina de estados de registro_operacao: nasce em pendente e SEGUE pendente sem protocolo/confirmado_em/motivo_rejeicao, transita uma única vez para confirmado ou rejeitado (gravando esses campos no mesmo comando, com confirmação nunca anterior ao envio), e não é apagado.';
