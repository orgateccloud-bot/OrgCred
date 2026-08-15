# OrgCred — Relatório de execução, 12–15 de agosto de 2026

Dez commits, ~12.500 linhas. O que segue é o que foi feito, o que
foi provado, e o que continua aberto — nesta ordem, porque a terceira parte é a
que decide se dá para operar.

---

## 1. O ponto de partida

Um levantamento de 53 agentes sobre os 10 domínios do sistema, com rodada
adversarial: todo achado grave passou por um cético cuja tarefa era **refutá-lo**,
não confirmá-lo. Dos achados levantados, **32 sobreviveram** — 2 críticos, 13
altos, 17 médios.

Esse desenho existe porque, no mesmo dia, eu havia produzido quatro diagnósticos
plausíveis e errados sobre um gatilho de deploy. Um mapeamento cheio de achados
que não se sustentam é pior que nenhum: ele consome atenção e ensina a
desconfiar do relatório inteiro.

Dois achados críticos explicavam o estado real:

**O sistema estava inoperante em produção.** O bundle servido continha
literalmente `setConfig({baseUrl:'http://localhost:8000'})` — o operador
autenticava pelo Supabase, que é outra origem, e nenhuma chamada de API
funcionava.

**`POST /liquidar` devolvia 100% do capital ao teto** com todas as parcelas em
aberto e zero centavo comprovado. Era o caminho mais curto para furar o Art. 5º
da LC 167/2019, alcançável por qualquer operador.

---

## 2. O que foi construído

### Condição 1 — tirar produção do estado inoperante (`2fc99e8`)

`baseUrl` relativo (o FastAPI serve a SPA na mesma origem), guarda fail-closed
que recusa iniciar em produção com a JWT secret no default, logging que de fato
emite, e redes de CI: falha dura sem banco, sincronia entre as três fontes de
verdade do schema, piso de cobertura.

### Condição 2 — fechar as bordas (`5520cce`, `22ac72e`)

**Migration 015** — três furos alcançáveis por SQL direto, nenhum deixando
rastro no ledger: `UPDATE` de `valor_principal` em operação ativa, `esc_capital_social`
sem trigger de `UPDATE`/`DELETE`, e `reducao` com valor negativo inflando o teto.

**Migration 016** — status `baixada` contornando o lastro, `movimento_id`
repontável, `TRUNCATE` apagando as trilhas append-only, e a baixa sem autor.

**Migration 017** — o gate de liquidação, implementando a política decidida:
quitação exige a agenda inteira baixada contra movimento bancário e devolve
capital; write-off encerra a cobrança e **não** devolve.

**Migration 018** — quatro erros de conteúdo tributário, nenhum coberto por
teste: parâmetro de hoje aplicado a período passado, dupla contagem de juros
após novação, regime de caixa ancorado na conciliação em vez do crédito
bancário, e mora e multa descartadas.

**Migration 019** — a evidência de identificação passou a ter bytes.

### Frontend (`c3072d7`)

UI de identificação — sem ela, o gate OC019 bloqueava todo tomador cadastrado
pela interface, e a mensagem de erro apontava para um lugar que não existia.
Fluxo de baixa por prejuízo. Dicionário de erros completo. Retry que não
descarta mais o corpo da requisição.

### Validação de ponta a ponta (`df9f1e9`)

Ver seção 4 — foi a etapa que rendeu mais.

### Os quatro defeitos que o levantamento deixou em aberto (`a189921`, `e712b1d`)

**Hash-chain ancorada em chave monotônica (020).** A cadeia era encadeada e
verificada por `created_at`, cujo default é `now()` — o instante de abertura da
transação, não da gravação. Uma transação que lê antes de escrever (o formato de
qualquer request que consulta capital e então ativa) carimba horário anterior ao
de outra que gravou primeiro, e a verificação acusava as duas linhas. Um stress
de 12 ativações simultâneas produziu de 4 a 6 inversões por rodada.

**Registro não nasce confirmado (021).** `fn_registro_transicao` era `before
update or delete`: o `INSERT` ficava sem guarda e uma linha podia nascer no
estado terminal com protocolo inventado, destravando o gate OC004 — que passava
a atestar que alguém digitou um protocolo.

**Contrato cita o registro confirmado.** O corpo imprimia `registro_entidade_ref`,
texto livre que a migration 013 rebaixou. O instrumento vai a terceiros.

**Retenção conta do encerramento (022).** A coluna virou piso e a retenção
efetiva é `greatest(piso, último encerramento + 5 anos)`; enquanto a relação não
encerrou, é `infinity`.

**Atipicidade ancorada na data do fato (023).** A regra de liquidação antecipada
comparava o primeiro vencimento com `current_date` em vez da data da liquidação:
detectava enquanto a varredura rodasse antes do vencimento e parava de detectar
depois, com o fato inalterado. Como a varredura só roda por clique manual, na
prática tendia a nunca disparar.

---

## 3. A decisão de negócio que destravou o gate

**Quitação** exige todas as parcelas pagas com lastro e devolve capital ao teto.
**Write-off** encerra a cobrança e não devolve.

O raciocínio: o dinheiro não voltou. Liberar teto por um empréstimo nunca pago
permitiria emprestar de novo o mesmo dinheiro que já se perdeu — exatamente o
que o Art. 5º existe para impedir.

**Consequência intencional:** o teto encolhe permanentemente a cada write-off.
Recuperar capacidade exige aporte de capital, não baixa contábil.

A implementação teve uma armadilha que vale registrar. O bloco que devolve
capital dispara quando o status **sai** do conjunto comprometido. Se
`baixada_prejuizo` ficasse fora desse conjunto, o write-off cairia nele e
devolveria o capital — o furo de volta com outro nome. A solução foi manter o
estado **dentro** do conjunto que ocupa o teto, e separar dois conceitos que até
então eram o mesmo: *ocupar o teto* (`ativa`, `inadimplente`,
`baixada_prejuizo`) e *estar em cobrança* (`ativa`, `inadimplente`).

---

## 4. O que a validação em navegador revelou

A intenção era fechar **uma** lacuna: o caminho real do upload multipart nunca
tinha passado por uma requisição de verdade. Apareceram três defeitos.

**A suíte E2E estava quebrada desde a migration 016.** As guardas
`BEFORE TRUNCATE` que criamos recusam o `truncate` do seed. Os quatro specs
falhavam desde aquele commit, em silêncio, porque E2E não roda na CI local.

**Um código de erro servindo a duas situações — introduzido por nós.**
`registrar_movimento` levantava `BaixaInvalida` (OC011) para documento
duplicado. Enquanto OC011 não tinha tradução no frontend, a mensagem específica
do servidor vazava e disfarçava o erro de modelagem. Quando OC011 ganhou entrada
no dicionário, quem reimportava um extrato — rotina na operação real — passou a
ler *"a baixa não tem lastro bancário válido"*, sendo mandado conferir a coisa
errada. Agora tem código próprio e HTTP 409.

**O dev server não alcançava a API** — regressão da nossa própria correção
crítica. Com `baseUrl` relativo e sem proxy no Vite, `/api` ia para o próprio
5173. Isso quebrava o desenvolvimento local e todo o E2E.

O teste novo assere sobre a **requisição**, não a resposta: a dependência de
storage é resolvida antes da validação do corpo, então o 503 viria igual com
`FormData` quebrado. Verifica `content-type` multipart com boundary, nome e
bytes do arquivo, campo `tipo`, `Authorization` presente, e **ausência** de
campo `sha256` — a garantia de que o cliente não voltou a mandar hash pronto.

---

## 5. Números

| | Antes | Depois |
|---|---|---|
| Testes backend | 198 | **405** |
| Cobertura | 92% | **93,2%** (piso de 85% ativo) |
| Testes frontend | 50 | **148** |
| E2E | 5 (todos quebrados) | **6, verdes** |
| Migrations | 14 | **23** |
| SQLSTATEs no banco | 18 | **21** |
| Suíte local | 148s | **27s** |

`ruff`, `ruff format`, `mypy` e `bandit` limpos. `alembic upgrade → downgrade →
upgrade` verificado nas nove migrations novas.

**A prova que mais importa não é a suíte verde, é a mutação.** Removendo o
`pg_advisory_xact_lock` da migration 014, duas ativações concorrentes commitam e
deixam R$ 60.000 comprometidos sobre capital de R$ 50.000 — a falha original que
deu origem a este projeto, reproduzida 3 de 3 vezes. O teste novo a reprova.
Antes disso, o único teste de concorrência aplicava as migrations 001–003 e
estava excluído do pytest por `--ignore`: provava o lock de um trigger
redefinido cinco vezes depois.

---

## 6. O que continua aberto

### Nenhum defeito conhecido em aberto

Os cinco foram fechados. Dois merecem nota, porque em ambos a **revisão** pegou
o que a implementação não viu.

**Hash-chain:** a correção quase introduziu um defeito pior que o original.
Ancorar em `seq` cortou um amarrio acidental — até então, percorrer por
`created_at` obrigava o carimbo a ser coerente com a posição, e um append
forjado com data retroativa era acusado. Medido: append antedatado em 400 dias,
a versão anterior acusa duas quebras, a correção inicial não acusava nenhuma, e
bastava privilégio de `INSERT`. Fechado com `new.created_at := now()` no
trigger — antedatar virou impossível, não apenas detectável.

**Atipicidade:** o SQL estava certo, mas a suíte não provava o que dizia provar.
Teste de mutação com cinco mutantes: trocar `min()` por `max()` e remover o ramo
de encerramento nulo **sobreviviam à suíte inteira**. E o teste de invariância
temporal movia as duas pontas do cenário juntas, então não testava invariância
nenhuma.

O padrão que se repetiu nas duas: correção que passa em todos os testes e mesmo
assim está errada, porque os testes foram escritos por quem já acreditava na
correção. O que quebrou o ciclo foi ter um revisor com uma lente única, obrigado
a medir em vez de argumentar.

### Seu, e é o que impede operar

O serviço Railway duplicado continua vivo com a `DATABASE_URL` de produção. A
JWT Secret precisa ser conferida no Supabase — e agora isso é **pré-requisito de
deploy**, porque a guarda fail-closed recusa iniciar sem ela. Faltam o bucket e
a `service_role` key do Storage, o `railway.json` com o gatilho no serviço
certo, e por fim os dados da ESC e o capital social.

---

## 7. Veredito

**Ainda não dá para emprestar dinheiro**, mas o motivo mudou de natureza. Ontem
o sistema estava inoperante e o teto tinha duas portas abertas alcançáveis por
qualquer operador. Hoje as portas estão fechadas e provadas por mutação, e a
interface funciona de ponta a ponta.

O que impede operar é configuração e dado de negócio — mais quatro defeitos
conhecidos, nenhum alcançável pela API.

O **piloto fechado** está disponível: sem capital social, sem parâmetro fiscal,
poucos operadores, nenhuma operação real. Valida deploy, login, observabilidade
e fluxo de tela sem risco legal, porque o sistema recusa operar sem os dados de
negócio — e agora recusa também subir mal configurado.

Detalhes por domínio, scorecard e plano ordenado: ver
[MAPEAMENTO_E_PLANO_DE_COMBATE.md](MAPEAMENTO_E_PLANO_DE_COMBATE.md).
