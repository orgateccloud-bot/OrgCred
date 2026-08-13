-- OrgCred — a evidência de identificação passa a ter BYTES
--
-- O QUE ESTAVA ERRADO. A migration 010 criou `tomador_documento` guardando
-- o SHA-256 do documento e escreveu, no próprio comentário, que "o binário
-- vive no storage". Storage nenhum foi construído. A 014 então ligou o gate
-- OC019 — ativar operação exige ao menos uma evidência arquivada (Lei
-- 9.613/98, art. 10, I) — em cima dessa evidência oca. O resultado prático:
-- `POST /compliance/tomadores/{id}/documentos` aceitava um campo `sha256`
-- vindo do CLIENTE, validado só por `^[0-9a-f]{64}$`. Sessenta e quatro
-- caracteres digitados à mão satisfaziam a exigência legal de identificar o
-- cliente, e nenhum byte de documento algum era lido pelo servidor.
--
-- Numa fiscalização isso é pior do que não ter controle: o sistema afirma
-- que a identificação foi arquivada e não existe nada para apresentar. O
-- hash sem o arquivo não prova nada — ele só serve para provar que um
-- arquivo APRESENTADO DEPOIS é bit a bit o mesmo de antes, e sem o arquivo
-- guardado não há "o mesmo de antes" para comparar com coisa nenhuma.
--
-- O QUE ESTA MIGRATION FAZ. Dá à evidência o campo que faltava: a
-- REFERÊNCIA DO OBJETO no storage (Supabase Storage — decisão do dono em
-- 2026-08-12). A partir daqui o servidor recebe o arquivo, calcula o hash
-- dos bytes recebidos, guarda os bytes e só então grava a linha; o hash
-- informado pelo cliente deixa de existir como entrada.
--
-- POR QUE A COLUNA É NULA-ÁVEL, e não `not null`. Existem linhas arquivadas
-- ANTES desta migration, cujos bytes nunca chegaram a existir em lugar
-- nenhum. Um `not null` exigiria backfill, e o único backfill possível seria
-- inventar uma referência que não aponta para nada — trocar uma lacuna
-- visível por uma mentira invisível, que é exatamente o defeito que esta
-- migration existe para corrigir. `storage_objeto is null` significa, com
-- precisão, "evidência da era sem storage: só o hash foi registrado".
--
-- POR QUE O BANCO AINDA NÃO EXIGE BYTES NAS LINHAS NOVAS. Seria a amarra com
-- dentes (um BEFORE INSERT recusando `storage_objeto is null`), e é o passo
-- seguinte natural. Não entra aqui porque exigir bytes no INSERT invalida
-- todo INSERT direto em `tomador_documento` feito fora do endpoint — e há
-- fixtures e testes de outras suítes que montam cenário assim. Ligar a
-- amarra é uma mudança coordenada, não um efeito colateral desta. O que esta
-- migration garante é que, quando ela for ligada, a coluna que ela vai
-- exigir já existe, já é única e já é imutável.
--
-- A REFERÊNCIA GUARDA O BUCKET JUNTO ('<bucket>/<caminho>'), e não só o
-- caminho. O prazo de retenção é de 5 anos; o nome do bucket é configuração,
-- e configuração muda. Uma referência que dependesse do bucket configurado
-- HOJE para localizar um objeto gravado há quatro anos seria uma referência
-- que apodrece sozinha. Guardando os dois, a linha continua apontando para o
-- objeto certo mesmo depois de a configuração mudar.
--
-- NENHUM SQLSTATE NOVO. A imutabilidade da coluna já é dada pelo trigger da
-- 010 (OC013) — ver o bloco no fim deste arquivo.

-- ---------------------------------------------------------------------
-- 1. A coluna
-- ---------------------------------------------------------------------
alter table tomador_documento
    add column if not exists storage_objeto text;

-- A restrição não é cosmética: `storage_objeto` é interpolado num caminho de
-- URL na hora de recuperar o objeto, e o valor gravado é imutável (OC013) —
-- ou seja, um valor ruim que entre aqui não tem como ser corrigido depois,
-- só substituído por uma linha nova. Daí a validação ser da própria coluna,
-- e não confiança em quem escreve nela:
--
--   - tem bucket E caminho, nessa ordem, separados por '/' (o '/' não pode
--     ser o primeiro caractere, senão o bucket seria vazio);
--   - não termina em '/' (caminho vazio);
--   - não contém '..' (travessia de diretório);
--   - não tem espaço nas pontas (o caractere invisível que faz duas
--     referências parecerem iguais e apontarem para objetos diferentes).
alter table tomador_documento
    drop constraint if exists tomador_documento_storage_objeto_valido;
alter table tomador_documento
    add constraint tomador_documento_storage_objeto_valido check (
        storage_objeto is null
        or (
            length(storage_objeto) between 3 and 512
            and position('/' in storage_objeto) > 1
            and right(storage_objeto, 1) <> '/'
            and position('..' in storage_objeto) = 0
            and storage_objeto = btrim(storage_objeto)
        )
    );

-- Duas linhas apontando para o MESMO objeto seriam uma armadilha de
-- expurgo: vencido o prazo de retenção de uma delas, apagar o objeto
-- destruiria a evidência da outra, que ainda está em retenção legal. O
-- índice é parcial porque `null` aqui é "documento da era sem storage", e
-- todos eles são igualmente sem objeto — não conflitam entre si.
create unique index if not exists tomador_documento_storage_objeto_unico
    on tomador_documento (storage_objeto)
    where storage_objeto is not null;

comment on column tomador_documento.storage_objeto is
    'Referência ''<bucket>/<caminho>'' do objeto no storage, ou NULL para evidências anteriores à migration 019 (só hash). O bucket vai junto de propósito: a retenção é de 5 anos e o bucket configurado muda.';

-- ---------------------------------------------------------------------
-- 2. A coluna nova nasce congelada — verificado, não presumido
-- ---------------------------------------------------------------------
-- `fn_documento_retencao()` (migration 010) recusa QUALQUER update em
-- `tomador_documento` com OC013, sem lista de colunas permitidas: o único
-- caminho para trocar o conteúdo de uma evidência é arquivar uma nova. Isso
-- significa que `storage_objeto` já entra imutável, sem precisar recriar o
-- trigger — e o comentário abaixo existe para que a próxima pessoa que
-- pensar em abrir uma exceção ("só para corrigir o caminho do objeto")
-- encontre escrito por que não se abre.
--
-- Se a exceção fosse aberta, apontar a linha para outro objeto seria
-- indistinguível de trocar o documento arquivado: o hash continuaria o
-- mesmo, a data de arquivamento também, e a única coisa que mudaria é QUAL
-- arquivo será apresentado numa fiscalização. É a troca do documento, feita
-- pela porta dos fundos.
comment on function fn_documento_retencao() is
    'OC013 — evidência de identificação: DELETE só depois de vencida a retenção (Lei 9.613/98, art. 10, III) e UPDATE nunca, em coluna nenhuma. Isso inclui storage_objeto (migration 019): repontar a linha para outro objeto seria trocar o documento arquivado sem trocar o hash.';
