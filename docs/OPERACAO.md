# Operação — as rotinas automáticas do OrgCred

Este documento é para quem foi acordado às 3h da manhã porque uma execução ficou
vermelha. Ele começa pelo que fazer e só depois explica por quê.

---

## Em uma linha

Um serviço de cron no Railway, uma agenda diária, um comando:

```
python -m app.rotinas
```

Esse comando roda **quatro rotinas**, sempre na mesma ordem, sempre todas — e
sai com código **0 se todas passaram** e **1 se qualquer uma falhou**. É esse
número que o Railway lê para marcar a execução como falha.

---

## O que rodou, e o que significa cada uma falhar

| Rotina | Frequência | O que faz | O que significa falhar | Urgência |
|---|---|---|---|---|
| `aging` | todo dia | Passa para `inadimplente` toda operação `ativa` com atraso ≥ 90 dias | Nenhuma inadimplência foi declarada hoje. A cada dia parado, a data de declaração de alguém atrasa mais um dia — e essa data tem efeito jurídico e reputacional para o tomador | **Alta** — resolver no mesmo dia útil |
| `atipicidades` | todo dia | Varredura interna de PLD (fracionamento, encerramento precoce, pagamento em excesso) | O controle de PLD não rodou hoje. A tela de ocorrências continua mostrando o resultado de ontem, e uma tela que não mudou é lida como "não há o que ver" | **Alta** — resolver no mesmo dia útil |
| `backup` | todo dia | `pg_dump` comprimido no diretório de backups + rotação de 30 dias | **Não existe cópia do dia de hoje.** Se o banco cair agora, o ponto de recuperação é o backup de ontem | **Crítica** — resolver agora |
| `restore_test` | 1× por mês | Restaura o backup mais recente num banco temporário e confere que o ledger responde | O backup existe mas **não se sabe se restaura**. É a diferença entre ter backup e ter um arquivo | **Alta** — resolver em 24h |

A ordem não é arbitrária: régua → varredura → backup → teste de restauração. A
varredura lê o estado que a régua acabou de mudar; o backup captura o dia já
processado, não o dia pela metade; e o teste valida o dump que acabou de ser
feito.

---

## Como ler o log

Toda linha é um JSON em stdout (é dali que o Railway agrega). Os eventos são:

| `event` | Quando | Campos que importam |
|---|---|---|
| `plano_montado` | uma vez, no início | `data`, `rotinas` |
| `rotina_iniciada` | antes de cada rotina | `rotina` |
| `rotina_concluida` | rotina passou | `rotina`, `duracao_s`, `detalhe` |
| `rotina_falhou` | rotina falhou | `rotina`, `duracao_s`, `erro`, `exception` (traceback completo) |
| `rotinas_concluidas` | no fim, tudo verde | `total`, `falhas: []`, `duracao_total_s` |
| `rotinas_concluidas_com_falha` | no fim, algo falhou | `falhas` — **a lista de nomes que você precisa** |

**Comece pela última linha.** Ela nomeia exatamente o que falhou. Depois procure
o `rotina_falhou` daquele nome: o campo `exception` tem o traceback inteiro.

Um exemplo de fim de execução ruim:

```json
{"event":"rotinas_concluidas_com_falha","data":"2027-03-09","total":4,"falhas":["backup"],"duracao_total_s":41.2,"level":"error"}
```

Leitura: a régua rodou, a varredura rodou, o teste de restauração rodou. Só o
backup falhou. Isso é de propósito — ver "Por que uma falha não derruba as
outras".

---

## Runbook: o que fazer em cada falha

Antes de tudo, você pode rodar **só a rotina que falhou**, sem repetir as que
passaram:

```
python -m app.rotinas --apenas backup
```

`--apenas` aceita `aging`, `atipicidades`, `backup`, `restore_test`, e pode ser
repetido. Rodar de novo é seguro: as quatro rotinas são idempotentes (ver
"Rodar duas vezes é seguro").

### `backup` falhou

1. Leia o `erro` na linha `rotina_falhou`. As causas, em ordem de frequência:
   - **`No space left on device`** — o volume de backups encheu. A rotação
     guarda 30 dias; se o banco cresceu, 30 dias não cabem mais. Aumente o
     volume ou reduza `RETENTION_DAYS` em `scripts/backup.sh`.
   - **`connection to server ... failed`** — o banco está fora, ou
     `ORGCRED_DATABASE_URL` do serviço de cron está errada.
   - **`script não encontrado`** — a imagem do serviço de cron não tem o
     diretório `scripts/`. Ver "Pré-requisitos" abaixo.
   - **`bash não encontrado no PATH`** ou **`pg_dump: command not found`** — a
     imagem não tem shell ou não tem o cliente Postgres. Idem.
2. Corrija e rode `python -m app.rotinas --apenas backup`.
3. Confirme que apareceu um arquivo novo no diretório de backups.

**Não existe backup parcial.** Se o `pg_dump` morre no meio, o `.gz` truncado é
apagado antes de o script sair. Isso é deliberado: o teste de restauração
escolhe o backup **mais recente**, e um arquivo truncado do dia de hoje seria
justamente o escolhido — com `ls` mostrando um backup fresco como se estivesse
tudo bem.

### `restore_test` falhou

Esta é a que dá mais susto e a que mais compensa investigar com calma.

1. **`nenhum backup encontrado`** — não é problema do teste; é problema do
   backup. Resolva o backup primeiro.
2. **`syntax error` / erro de restauração** — o dump não é restaurável. Não
   presuma corrupção de disco antes de checar o óbvio: uma migration nova que
   usa uma extensão que o papel de restauração não pode criar produz o mesmo
   sintoma. Reproduza à mão com o dump em questão.
3. **`view v_capital_atual não retornou valor`** — o dump restaurou mas o motor
   de capital não responde. Trate como incidente de integridade, não como falha
   de infraestrutura.

Enquanto ele falha, ele **é retentado todo dia**, automaticamente: a competência
só é marcada como coberta depois de um sucesso. Um backup que não restaura é o
tipo de problema que deve insistir.

Para forçar uma execução fora da vez (depois de corrigir, por exemplo):

```
python -m app.rotinas --apenas restore_test --forcar-restore-test
```

### O log não tem linha nenhuma (nem `plano_montado`)

Não é uma rotina que falhou — é o processo que não chegou a existir. A execução
morreu no `import`, antes do executor, e a saída é um traceback Python em vez de
JSON. A causa mais comum é ambiente incompleto no serviço de cron
(`ConfigError: ORGCRED_SUPABASE_JWT_SECRET ...`); ver "Pré-requisitos do serviço
de cron". Enquanto isso durar, **nenhuma** das quatro rotinas está rodando.

### `aging` ou `atipicidades` falharam

Quase sempre é o banco: fora do ar, credencial errada, ou um SQLSTATE da classe
`OC` no meio do caminho. O `exception` no log traz o erro do Postgres literal.

Depois de corrigir, `python -m app.rotinas --apenas aging` (ou
`--apenas atipicidades`). Rodar de novo não duplica nada.

---

## Por que uma falha não derruba as outras

O executor roda **todas** as rotinas, coleta os erros, e só no fim decide o
código de saída.

Isso não é tolerância a falha por gosto: um backup que falha por disco cheio e
uma régua de inadimplência que precisa rodar são problemas **independentes**.
Abortar o plano no primeiro erro transformaria um incidente de armazenamento em
inadimplência declarada com atraso — dois incidentes pelo preço de um.

O que **não** é tolerado é o silêncio. Qualquer falha:

- vira uma linha `rotina_falhou` com traceback,
- aparece nomeada no resumo final,
- e faz o processo sair com código 1.

---

## Rodar duas vezes é seguro

As quatro rotinas são idempotentes, e isso foi conferido lendo o código, não
presumido:

- **`aging`** — `fn_processar_aging` (migration 008) só toca operações em
  `ativa`. Na segunda passada elas já saíram desse status; nada é transicionado
  e nenhum evento é gravado.
- **`atipicidades`** — `fn_detectar_atipicidades` (migrations 010/023) grava com
  `on conflict ... do nothing` contra o índice único `ocorrencia_unica`, nas três
  regras. E desde a 023 nenhuma regra compara nada com `current_date`: a mesma
  varredura devolve o mesmo conjunto hoje e daqui a cinco anos.
- **`backup`** — cada execução grava um arquivo com timestamp próprio. Duas
  execuções no mesmo dia produzem dois arquivos, não um corrompido.
- **`restore_test`** — só roda se a competência do mês ainda não foi coberta.

---

## A regra mensal do `restore_test`, e por que ela não tem dia fixo

O critério **não é** "roda no dia 1" nem "roda no dia 15". É:

> **Esta competência (`AAAA-MM`) já teve seu teste de restauração?**

A resposta fica num arquivo-marcador ao lado dos backups
(`.ultimo_restore_test`), com o conteúdo `2027-03`. O teste roda na **primeira
execução de cada mês** — seja ela dia 1, dia 9 ou dia 23.

Qualquer critério de dia fixo tem dois modos de falha, e **nenhum dos dois
avisa**:

1. **O dia que não existe.** `dia == 31` pula fevereiro, abril, junho, setembro
   e novembro — cinco dos doze meses do ano ficam sem teste, e o painel não
   mostra falha nenhuma, porque não houve execução para falhar. Ausência de
   linha vermelha lida como saúde.
2. **O dia perdido.** Qualquer dia fixo é pulado de vez se o cron não rodar
   naquela data — deploy em andamento, serviço reiniciando, incidente. O mês
   inteiro fica descoberto e a próxima chance é daqui a 30 dias.

O critério por competência não depende de dia nenhum, então nenhum dia pode ser
pulado. E o marcador **só é escrito depois do sucesso**: um teste que falha não
marca o mês como coberto e volta a ser tentado no dia seguinte, todo dia, até
passar.

Se o marcador sumir (volume recriado, por exemplo), o teste roda de novo. É o
lado seguro do erro: o custo é um teste de restauração a mais, e o custo do
outro lado é descobrir na hora do desastre que o backup nunca foi testado.

---

## Pré-requisitos do serviço de cron

> **Estado atual: o `Dockerfile` da aplicação NÃO satisfaz estes requisitos.** A
> imagem de runtime (`python:3.12-slim`) copia apenas `app/`, `migrations/`,
> `alembic/` e o frontend — não copia `scripts/` — e não instala o cliente
> Postgres. Rodar `python -m app.rotinas` nessa imagem hoje faz `aging` e
> `atipicidades` passarem e `backup` e `restore_test` falharem com
> `script não encontrado`. **Isso é falha explícita e ruidosa, de propósito** —
> mas é falha. O serviço de cron precisa de uma imagem que atenda ao que segue.

O serviço de cron precisa de:

| Requisito | Por quê |
|---|---|
| `COPY scripts/ ./scripts/` na imagem | é onde `backup.sh` e `restore_test.sh` vivem |
| `postgresql-client` instalado (`pg_dump`, `psql`) | o backup e a restauração são feitos por eles, não por Python |
| `bash` | os dois scripts são bash (o Debian slim já traz) |
| **O MESMO conjunto de variáveis do serviço da API** — não só a URL do banco | ver o aviso logo abaixo: com menos que isso o comando morre no `import`, antes da primeira rotina |
| `ORGCRED_DATABASE_URL` | a mesma da aplicação; os scripts traduzem o dialeto SQLAlchemy para libpq sozinhos |
| `ORGCRED_SUPABASE_JWT_SECRET` | exigida em `production` por `app/core/config.py`, mesmo aqui, onde nenhuma rotina autentica ninguém |
| **Volume persistente** montado no diretório de backups | num diretório efêmero o backup é escrito, o contêiner morre, e o log diz que o backup concluiu — porque concluiu mesmo |
| Papel do banco com permissão de `CREATE DATABASE` | o `restore_test` cria e derruba um banco temporário |

> **O serviço de cron precisa do ambiente COMPLETO da aplicação, não só do
> banco.** `app/rotinas.py` importa `ProcessarAgingIn` e `DetectarIn` dos
> routers — de propósito, para que o botão e o cron usem os mesmos parâmetros
> de negócio — e esse import puxa `app.core.config`, que em `environment =
> production` recusa iniciar sem `ORGCRED_SUPABASE_JWT_SECRET` (e sem uma
> `ORGCRED_DATABASE_URL` explícita, que não aponte para `localhost`).
>
> Um serviço de cron provisionado só com a URL do banco falha assim, na
> primeira execução:
>
> ```
> app.core.config.ConfigError: ORGCRED_SUPABASE_JWT_SECRET não configurada
> para produção — recusando iniciar com valor default de desenvolvimento.
> ```
>
> A execução sai com código 1, **nenhuma das quatro rotinas roda**, e o log não
> tem uma linha `rotinas_concluidas_com_falha` para ler — a falha é anterior ao
> executor. O sintoma (um segredo de JWT) não tem relação nenhuma com a causa
> aparente (a régua de aging não rodou), e é o tipo de pista que consome uma
> madrugada. Copie o bloco de variáveis do serviço da API.

Duas variáveis opcionais ajustam caminhos quando o layout da imagem difere do
repositório:

- `ORGCRED_BACKUP_DIR` — onde gravar os dumps. Default: `./backups`.
- `ORGCRED_SCRIPTS_DIR` — onde estão os `.sh`. Default: `scripts/` ao lado de
  `app/`.

### Sobre o banco temporário do `restore_test`

Ele é criado **no mesmo servidor Postgres de produção**, restaurado, validado e
derrubado. Duas consequências que valem saber antes de a conta chegar:

- Ele ocupa, por alguns minutos, espaço equivalente ao banco inteiro.
- Ele contém uma cópia íntegra dos dados de produção enquanto existe.

Ele é derrubado por um `trap` de saída — inclusive quando a restauração falha no
meio. Se algum dia sobrar um `orgcred_restore_test_*` no servidor, é sinal de que
o processo foi morto de fora (OOM, timeout do contêiner), e ele pode ser
derrubado à mão com segurança.

---

## Rodando à mão

O mesmo comando que o cron roda, de qualquer lugar com as variáveis de ambiente
certas:

```
# plano completo do dia
python -m app.rotinas

# só uma rotina
python -m app.rotinas --apenas aging

# simular outra data (afeta só a decisão mensal do restore_test)
python -m app.rotinas --data 2027-03-01

# forçar o teste de restauração fora da vez
python -m app.rotinas --apenas restore_test --forcar-restore-test

# ajuda
python -m app.rotinas --help
```

Os scripts também continuam chamáveis diretamente — é o mesmo caminho que o
executor usa, de propósito: um script que só o cron sabe invocar é um script que
ninguém consegue testar quando ele falha às 3h da manhã.

```
ORGCRED_DATABASE_URL=... bash scripts/backup.sh /var/backups
ORGCRED_DATABASE_URL=... bash scripts/restore_test.sh /var/backups
```

---

## O que este arranjo substituiu

Quatro rotinas, nenhuma agendada. `backup.sh` e `restore_test.sh` existiam no
repositório sem que nada os chamasse. A régua de aging e a varredura de
atipicidade só rodavam por clique em `POST /cobranca/aging/processar` e
`POST /compliance/atipicidades/detectar`.

Na prática: a data em que uma inadimplência era declarada dependia de alguém
lembrar, e a detecção de PLD acontecia quando desse na telha.

A decisão foi **um** serviço, **uma** agenda diária, **um** comando — com o "o
que roda em cada dia" decidido no código (`app/rotinas.py`, coberto por
`tests/test_rotinas.py`) e não em quatro agendas de painel que ninguém revisa e
que divergem em silêncio do repositório.

O botão continua existindo. Um operador ainda pode disparar a régua ou a
varredura pela tela quando quiser — o cron não substitui a decisão humana, ele
garante o piso.
