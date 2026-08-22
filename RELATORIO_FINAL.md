# OrgCred — Relatório de execução e auditoria

**Período: 12 a 18 de agosto de 2026.** Vinte e três commits, ~16.000 linhas.

> Este relatório tem duas metades que precisam ser lidas juntas: o que foi
> construído, e o que uma auditoria independente encontrou depois. A segunda
> corrige afirmações da primeira.

---

## 1. Veredito

**Não dá para entrar em produção com dinheiro real hoje.** O motivo mudou de
natureza ao longo da semana e é importante não confundir as três causas:

1. **Um defeito de código crítico e aberto.** A renegociação libera o teto do
   Art. 5º por inteiro, sem prova de pagamento, em duas chamadas de API com
   papel de operador.
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

Ao longo da semana, onze migrations (015 a 025):

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

**Números:** 570 testes backend (eram 198), 210 de frontend (eram 50), 6 E2E,
94,2% de cobertura, 25 migrations, 22 SQLSTATEs.

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
