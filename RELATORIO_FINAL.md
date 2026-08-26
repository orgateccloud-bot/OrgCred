# OrgCred — Relatório de execução e auditoria

**Período: 12 a 26 de agosto de 2026.** Trinta e quatro commits, ~16.000 linhas.

> Este relatório tem duas metades que precisam ser lidas juntas: o que foi
> construído, e o que uma auditoria independente encontrou depois. A segunda
> corrige afirmações da primeira.

---

## 1. Veredito

**Ainda não dá para entrar em produção com dinheiro real** — mas o que impede
deixou de ser código. Não confundir as causas é o que torna a fila acionável:

1. ~~**Um defeito de código crítico e aberto.**~~ **Fechado.** A renegociação
   que liberava o teto do Art. 5º sem prova de pagamento foi barrada pela
   migration 026 (OC024), e os três altos de cobrança pela 027 (OC025/OC011).
   Todos reproduzidos **nos dois sentidos**: o ataque recusado no schema novo e
   aceito no antigo. Resta um alto de código, o rate limit global, que degrada
   disponibilidade sob abuso e não fura invariante legal nenhum.
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

Ao longo da semana, treze migrations (015 a 027):

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

**Números:** 611 testes backend (eram 198), 216 de frontend (eram 50), 6 E2E,
93% de cobertura, 27 migrations, 24 SQLSTATEs.

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
`postgres:16` do `docker-compose`, que é o banco **local**; produção roda 18.4.
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

## 5. A lição que se repetiu a semana inteira

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
