# OrgCred — Relatório de execução e auditoria

**Período: 12 a 27 de agosto de 2026.** Trinta e cinco commits, ~16.000 linhas.

> Este relatório tem duas metades que precisam ser lidas juntas: o que foi
> construído, e o que uma auditoria independente encontrou depois. A segunda
> corrige afirmações da primeira.

---

## 1. Veredito

**Não dá para entrar em produção com dinheiro real.** Não há crítico aberto,
mas há altos — e uma frase anterior desta mesma seção ("o que impede deixou de
ser código") durou uma hora antes de ser derrubada por medição. Ela fica
registrada porque o padrão que ela repete é o assunto da seção 5.

1. ~~**Um defeito de código crítico e aberto.**~~ **Fechado pela migration 028**,
   doze horas depois de ter sido criado pela 027. O que era: a migration 027 trocou a
   chave global `unique (documento)` por `(documento, conta_origem)` — mas
   `conta_origem` é a **grafia que o arquivo trouxe**, não a identidade da
   conta: `_formatar_conta` ([ofx.py:289](app/ofx.py:289)) devolve
   `BANKID/ACCTID`, `ACCTID` ou `BANKID`, verbatim, sem normalizar. O mesmo
   extrato da mesma conta, exportado com e sem `<BANKID>`, importa **duas
   vezes** — com a aritmética do relatório fechando nas duas. Reproduzido de
   ponta a ponta pelo parser e pelo serviço do próprio projeto: R$ 31.514,86
   recebidos viram R$ 63.029,72 de lastro, as quatro parcelas ficam quitadas,
   `liquidar` é aceito e o comprometido volta a zero com R$ 28.485,14 de
   principal na rua. É o efeito da seção 4 deste relatório reaberto pela porta
   do extrato.

   A 028 move a chave da GRAFIA para a IDENTIDADE: `conta_chave` é uma coluna
   **gerada pelo banco** a partir de `conta_origem`, descartando o BANKID (que
   está presente numa exportação e ausente noutra) e normalizando pontuação e
   zeros. Verificado com o mesmo script que provou o furo: `criados=2` virou
   `ja_registrados=2`, e o lastro fabricado caiu de R$ 31.514,86 para **zero**.
   A colisão residual que sobra — dois bancos com o mesmo número de conta E o
   mesmo FITID — deixou de ser silenciosa: virou um contador próprio no
   relatório, separado de `ja_registrados`, porque o achado nunca foi "uma linha
   se perdeu" e sim "uma linha se perdeu **e a aritmética fechou**".

   Fechados junto: a agenda do título já renegociado, que aceitava baixa pela
   porta de produção e consumia o crédito real do tomador para sempre (OC026); o
   `TRUNCATE` nas três tabelas append-only que a 016 e a 027 tinham deixado de
   fora; e a linha ausente na revisão 0006 que fazia `alembic downgrade base`
   morrer com `DuplicateObject` — o job `alembic` da CI era **vermelho por
   construção desde o primeiro commit dela**, de modo que a prova de que o
   schema reverte nunca tinha existido.

   **Produção nunca esteve exposta: ela roda o schema 0026.**
2. **Uma credencial ausente.** Sem a `service_role` key do Supabase, arquivar
   identificação responde 503; como o gate OC019 exige evidência arquivada para
   ativar, nenhum tomador novo recebe crédito.
3. **Dados de negócio que faltam** — capital social e parâmetros fiscais. Essa
   recusa é deliberada, testada e correta, e não conta contra ninguém.

---

## 2. O que foi construído

**Ponto de partida:** o sistema estava **inoperante** em produção — o bundle
apontava a API para `localhost:8000`, o operador autenticava e nenhuma chamada
funcionava — e `POST /liquidar` devolvia 100% do capital ao teto com todas as
parcelas em aberto.

Ao longo da semana, quinze migrations (015 a 029):

- **Bordas do teto** (015): `UPDATE` de `valor_principal` em operação ativa,
  `esc_capital_social` sem trigger de `UPDATE`/`DELETE`, e redução com valor
  negativo inflando o teto.
- **Bordas da cobrança** (016): status `baixada` contornando o lastro,
  `movimento_id` repontável, `TRUNCATE` apagando trilhas append-only, e a baixa
  sem autor.
- **Gate de liquidação** (017, OC022), implementando a política decidida:
  quitação exige agenda inteira com lastro; write-off encerra a cobrança e não
  devolve capital.
- **Correções fiscais** (018): parâmetro do período em vez do de hoje, dupla
  contagem após novação, âncora do regime de caixa, e mora descartada.
- **Storage da evidência de identificação** (019): bytes de verdade, hash
  calculado no servidor, fail-closed sem credencial.
- **Hash-chain monotônica** (020): deixou de acusar adulteração falsa sob
  concorrência, e antedatar lançamento virou impossível.
- **Registro não nasce confirmado** (021), **retenção contada do encerramento**
  (022), **atipicidade ancorada na data do fato** (023).
- **Importação de extrato OFX** (024) com proveniência por sha256 dos bytes, e a
  tela que a torna usável.
- **Trilha de execução das rotinas** (025) e o serviço de cron que as agenda.
- **Gate de novação** (026, OC024): a substituta tem que cobrir o saldo devedor
  da original, calculado sobre `valor_amortizacao` com lastro bancário — e a
  original só sai do comprometido quando a substituta é **ativada**, nunca
  antes.
- **Bordas da cobrança, segunda volta** (027): o FITID passa a ser único **por
  conta**, o `INSERT` em `parcela` ganha guarda (OC025) com o `TRUNCATE` fechado
  junto, e a cobertura de valor da baixa sai de dentro de `fn_baixar_parcela`
  para o trigger (OC011), alcançável por qualquer porta.
- **Identidade da conta** (028): a chave do extrato deixa de ser a GRAFIA e
  passa a ser a IDENTIDADE da conta — consertando metade do crítico que a 027
  abriu —, a baixa passa a exigir operação em cobrança (OC026), e as três
  tabelas append-only que faltavam ganham guarda de `TRUNCATE`.
- **Identidade do crédito** (029): a conta sai da identidade. Fecha a CLASSE
  inteira — a 028 tinha fechado a metade do `<BANKID>` e deixado a do
  `<ACCTID>` —, faz `ja_registrados` ser contado em vez de derivado (o selo do
  relatório era uma tautologia que não podia falhar), e dá ao gate OC026 o
  `for share` sem o qual ele valia só na direção sequencial.

**Números:** 654 testes backend (eram 198), 219 de frontend (eram 50), 6 E2E,
93% de cobertura, 29 migrations, 25 SQLSTATEs.

---

## 3. Achados que valem mais que o código que os corrigiu

**`NaN` atravessa o teto.** `Decimal('NaN')` é literal válido, `numeric` aceita,
e o Postgres o ordena como **maior que qualquer número** — `'NaN'::numeric > 0`
e `>= 999999` são os dois verdadeiros. Um `TRNAMT` com `NaN` num OFX atravessaria
o `check (valor > 0)`, cobriria qualquer parcela na baixa e envenenaria toda soma
da carteira.

**Arredondamento assimétrico.** `0.125` vira `0,13` no Postgres e `0,12` com o
padrão do Python. Sem `ROUND_HALF_UP`, toda apuração que caísse na metade
acusaria divergência falsa de um centavo — arruinando o indicador que existe para
ser confiável.

**`pg_dump` recusa servidor mais novo.** Cravei `postgresql-client-16` lendo o
`postgres:16` do `docker-compose`, que é o banco **local**; produção roda 18.6
(era 18.4 quando isto foi escrito — o número mudou sozinho, que é precisamente
o argumento).
A correção não foi trocar 16 por 18 — foi **tirar a versão**, senão a próxima
atualização do servidor quebraria o backup em silêncio.

**Correção que quase virou defeito pior.** Ancorar a hash-chain em `seq` cortou
um amarrio acidental e passou a aceitar **append antedatado** sem acusar. Medido:
o vetor era detectado antes e deixou de ser. Fechado com o banco escrevendo o
próprio carimbo.

**E de novo, na 027: `NULLS NOT DISTINCT` é a diferença entre consertar e
trocar de furo.** A chave do extrato precisava deixar de ser `unique
(documento)` e passar a `(documento, conta_origem)`. Escrita como UNIQUE comum,
essa troca teria reaberto o problema pelo outro lado: `conta_origem` é NULL em
todo lançamento **digitado** (a 024 proíbe proveniência de arquivo no manual),
NULL nunca é igual a NULL em SQL, e dois lançamentos manuais com o mesmo
documento passariam a ser aceitos — trocando um crédito real descartado por um
crédito **duplicado**, que baixa uma segunda parcela. Com a cláusula, tudo que
não declara conta divide um único espaço de nomes, exatamente como antes; só se
separa o que o arquivo declara separado. Verificado nos três casos: mesma conta
recusa, contas diferentes aceita, dois manuais recusa.

**E uma guarda que conferia a coisa errada, fora do SQL.** O `skipif` dos testes
de shell perguntava `shutil.which("bash") is not None`. No Windows o
`C:\Windows\System32\bash.exe` do WSL está no PATH **mesmo sem distribuição
instalada**: o arquivo existe, o skip não acontece, e cinco testes ficam
vermelhos com `execvpe(/bin/bash) failed` — erro do sistema operacional, não do
código sob teste. É o mesmo erro que este projeto persegue nos triggers (conferir
**presença** onde o invariante é **usabilidade**), e o custo aqui é de
diagnóstico: uma suíte que fica vermelha por motivo errado é uma suíte que se
aprende a ignorar. A sonda passou a executar `bash -c 'exit 0'`.

---

## 4. A auditoria independente (18/08)

41 agentes sobre 11 domínios, instruídos a **não** ler a documentação existente
como verdade. **22 achados sobreviveram à refutação** — 2 críticos, 9 altos.

### O furo crítico

A renegociação aceita `valor_principal` arbitrário e `fn_novar_operacao` não o
confronta com nada. Reproduzido ao vivo:

```
capital R$ 50.000 · operação de R$ 30.000 ativa, 12 parcelas em aberto
renegociar por R$ 0,01  → comprometido cai a zero
cancelar a substituta   → continua zero
nova operação de R$ 50.000 ativa

R$ 80.000 na rua sobre R$ 50.000 de capital.
```

É o mesmo efeito que a migration 017 recusa no próprio cabeçalho, reaberto pela
porta vizinha — o gate OC022 só olha `liquidada`, e `renegociada` ficou fora do
conjunto que ocupa o teto. **A suíte de 570 testes passa verde por cima disso e
afirma o comportamento como correto.**

### O achado sobre os documentos

A versão anterior deste relatório dizia: *"Todos os defeitos de código que o
levantamento encontrou estão fechados… O que impede operar é configuração e dado
de negócio."* **As duas metades eram falsas.** E o mapeamento respondia
literalmente **"Nada."** à pergunta sobre o que faltava de código.

Outras afirmações que o código não sustentava: "a baixa tem autor" (`baixado_por`
é NULL em 100% das baixas pela API), "o relatório permite conferir que nenhuma
linha se perdeu" (falha justamente quando o FITID colide entre contas), "rate
limiting ligado" (ligado e inútil como isolamento), e comentários afirmando que a
hash-chain resiste a um DBA malicioso quando não há um único `grant` ou RLS em 25
migrations.

### O que dessas frases virou verdade — e o que não virou

**Virou:** "a baixa tem autor" (o router passa `usuario_id`, provado por um teste
que atravessa o HTTP e compara a coluna com o id do usuário autenticado) e "o
relatório permite conferir que nenhuma linha se perdeu" (chave por conta no banco
**e** deduplicação por `(fitid, conta)` no parser — consertar só um dos lados
deixaria o furo de pé para o OFX com dois statements).

**Não virou, e continua escrito aqui para não voltar a ser esquecido:** o rate
limit segue um balde único global, e **não há isolamento de privilégio no
banco**. A aplicação é dona das tabelas, então toda guarda de trigger — inclusive
as duas que a 027 acrescentou — some com um `alter table ... disable trigger`
para quem tem SQL direto. O que elas fecham é o resto: o script de correção
copiado de outro ambiente, a aplicação comprometida, e o caminho de dois comandos
que reabria a guarda de `INSERT` sem tocar em trigger nenhum. A defesa
complementar é de infraestrutura, não de SQL, e ainda não existe.

**Sobre o critério de "fechado":** cada uma das cinco correções foi rodada contra
Postgres com dado gravado pelos caminhos reais — e depois **repetida contra o
schema anterior**, onde os ataques passam. Um teste que só se vê passar não
distingue a guarda que funciona da guarda que nunca foi alcançada; foi
exatamente assim que `baixado_por` ficou NULL em produção por semanas, com um
teste verde provando que a função grava quem recebe — nunca que alguém entrega.

---

## 5. As vinte e quatro horas entre a 027, a 028 e a 029

É o episódio mais instrutivo da semana, e vale contado em ordem.

**De manhã**, a migration 027 fechou três altos de cobrança. Foi verificada com
o rigor que este projeto adota: cada ataque reproduzido contra Postgres com dado
gravado pelos caminhos reais, e cada um repetido contra o schema anterior para
provar que os testes discriminam. Suíte verde, lint limpo, commit.

**À tarde**, uma verificação domínio a domínio — onze céticos, um por domínio,
obrigados a medir — derrubou seis das onze notas. E um crítico de completude,
lendo os onze relatos juntos, achou o que nenhum deles podia achar sozinho: a
027 tinha **aberto um crítico**. Ela pôs a GRAFIA da conta na chave do extrato
supondo que a grafia identificasse a conta. O mesmo extrato exportado com e sem
`<BANKID>` passou a importar duas vezes, dobrando o lastro; e o lastro dobrado
quita a carteira e devolve o capital ao teto do Art. 5º por `liquidar`.

**No dia seguinte aconteceu de novo.** Sete lentes atacaram a 028 — com o
mandato explícito de testar as DUAS direções de cada regra, porque essa era a
lição — e acharam a metade simétrica: a 028 perguntou *"e se o `<BANKID>`
faltar?"* e não perguntou *"e se faltar o `<ACCTID>`?"*. Mesmo efeito, mesmo
destino, mesmo valor de dano, reproduzido de ponta a ponta.

Foi a segunda repetição que revelou o que a primeira não tinha: **o problema não
era a canonização estar incompleta, era a forma da solução.** As três chaves
erradas — `(documento)`, `(documento, conta_origem)`, `(documento, conta_chave)`
— partilham uma premissa que nunca foi enunciada: que o arquivo diz de qual
conta a linha é. Ele diz o que o exportador resolveu escrever, e duas
exportações da mesma conta escrevem coisas diferentes. **Canonização normaliza
formato; não recupera informação ausente.** Enquanto a conta estiver na
identidade, sempre haverá um par de exportações em que uma declara menos que a
outra, e duas declarações viram dois espaços de nomes.

A 029 tira a conta da identidade: um crédito é `(identificador, valor, data)`, e
a conta vira proveniência. Nenhuma grafia, nenhum bloco ausente e nenhuma
diferença entre lançamento manual e OFX cria espaço de nomes novo, porque a
conta não aparece na chave.

**Quatro coisas que este episódio ensina, e que nenhuma quantidade de rigor
dentro de um domínio teria ensinado:**

1. **A verificação que fecha um furo não vê o furo que ela abre.** A 027
   perguntou *"mesmo FITID em contas DIFERENTES entra?"* e comemorou o sim.
   Nunca perguntou *"e quando é a MESMA conta escrita de dois jeitos?"*. Uma
   guarda testada só na direção em que foi desenhada não foi testada.

2. **O furo mora na junta.** Capital atacou o teto por doze caminhos e nenhum
   entrava pelo extrato, porque o extrato é o domínio do vizinho. Cobrança viu a
   duplicação mas não a seguiu até o teto. Os dois estavam certos dentro do
   próprio quadrado; foi a divisão do trabalho que produziu dois verdes sobre um
   crítico.

3. **A propriedade que fazia o defeito ser invisível era a mesma nos dois
   casos**: a aritmética do relatório de importação FECHA. Antes da 027, fechava
   por cima de uma linha perdida; depois dela, por cima de uma linha duplicada. A
   028 não se contentou em estreitar a janela — separou o contador, para que o
   que sobra faça barulho. Só que o contador dela ainda era DERIVADO por
   subtração, o que fazia da soma uma identidade algébrica: o selo não podia
   falhar nem com o motor quebrado. A 029 passou a contar os três destinos.

4. **Consertar a direção que falhou não é consertar o defeito.** Depois de duas
   tentativas, a pergunta certa deixou de ser *"que outro caso eu não testei?"*
   e passou a ser *"por que este desenho tem casos que eu preciso lembrar de
   testar?"*. Uma regra cuja correção depende de enumerar variantes de entrada
   está errada na forma. A que sobreviveu não tem variantes a enumerar — e o
   teste que a guarda parametriza as sete formas conhecidas de exportação
   capada, de modo que a oitava custa uma linha e não um incidente.

---

## 6. A lição que se repetiu a semana inteira

Três vezes o mesmo padrão apareceu, e a terceira foi a auditoria inteira:

**Um comentário que descrevia a realidade deixou de descrevê-la, e ninguém releu
o comentário ao mudar a realidade.** O `baseUrl` absoluto em dev, escrito antes
de o proxy existir. O aviso em `OPERACAO.md` dizendo que o Dockerfile não copia
`scripts/`, falso desde dois commits depois. O smoke do CI afirmando provar que
as migrations aplicam, o que deixou de ser verdade no commit que moveu as
migrations para o pré-deploy.

E a versão maior disso: **documentação que promete mais do que o código entrega é
pior que documentação nenhuma**, porque desliga a desconfiança de quem lê.

O que quebrou o ciclo foi sempre a mesma coisa — um revisor com uma lente única,
obrigado a **medir em vez de argumentar**, e proibido de tomar o que estava
escrito como verdade.

---

Detalhes por domínio, achados com arquivo e linha, e a fila por dono:
[MAPEAMENTO_E_PLANO_DE_COMBATE.md](MAPEAMENTO_E_PLANO_DE_COMBATE.md).
