# OrgCred — Mapeamento, Scorecard e Plano de Combate

> Levantado em 2026-07-31 a partir de medição direta do código (cobertura
> real via `htmlcov/status.json`, contagem de statements, endpoints e
> testes), não de estimativa. Onde um número não pôde ser medido, está
> dito explicitamente.
>
> **Revisado em 2026-08-08**, após a execução das Frentes 2, 3 e da parte
> construível da Frente 4. Os números de scorecard abaixo foram
> remedidos, não estimados: 176 testes backend, cobertura total 91%,
> 50 Vitest, 5 E2E, 11 migrations. A Frente 1 segue integralmente aberta — e continua
> sendo o que separa este sistema de ser usado.

---

## 1. Retrato em uma frase

O OrgCred tem **um núcleo de crédito sólido e provado** (capital, operações,
cobrança de ponta a ponta, auditoria com hash-chain) envolto por **três
módulos regulatórios bloqueados em decisão externa** — e continua **no ar em
produção sem conseguir ser usado**, porque o teto de capital é R$ 0,00 e o
login real nunca foi ativado.

O risco dominante nunca foi qualidade de código, e depois desta rodada é
menos ainda. É que **o sistema parece pronto e não é operável**: tudo que
foi construído nas Frentes 2, 3 e 4 está em `main` e em nenhum servidor.

---

## 2. Mapa de módulos

### 2.1 Backend — 3.3k linhas, 39 endpoints, 9 routers, 11 migrations

> Contagens remedidas em 2026-08-08. As tabelas desta seção descrevem o
> levantamento original de 2026-07-31; o estado atual de cada módulo está
> no scorecard da seção 3, que foi refeito.

| Módulo | Arquivos | Stmt | Endpoints | Cobertura |
|---|---|---:|---:|---:|
| **Operações** | `routers/operacoes.py` | 108 | 9 | 84,3% |
| **Motor de capital** | `capital_engine.py` | 85 | — | 58,8% |
| **Tomadores** | `routers/tomadores.py` | 69 | 4 | 65,2% |
| **Capital (API)** | `routers/capital.py` | 42 | 4 | 81,0% |
| **Auditoria** | `routers/auditoria.py` + `core/ledger_integrity.py` | 48 | 1 | 100% |
| **Identidade** | `routers/me.py` + `core/security.py` | 51 | 1 | 92,9% / 100% |
| **Infra** | `main.py`, `db.py`, `config`, `logging`, `metrics`, `exceptions` | 231 | — | 72,4% – 100% |
| **Modelos** | `models.py` | 73 | — | 100% |
| Contratos | `routers/contratos.py` | 2 | **0** | — (stub) |
| Fiscal | `routers/fiscal.py` | 2 | **0** | — (stub) |
| Compliance | `routers/compliance.py` | 2 | **0** | — (stub) |
| Cobrança | `routers/cobranca.py` | 2 | **0** | — (stub) |
| ⚠️ Alertas | `core/alerts.py` | 37 | — | **0%** |

**5 tabelas:** `tomador`, `operacao_credito`, `capital_ledger`,
`esc_capital_social`, `usuario`. **5 migrations**, ciclo
downgrade→upgrade validado.

**Invariantes no banco (o princípio "o banco decide"):** OC001 teto de
capital · OC002 gate geográfico · OC003 máquina de estados · OC004 registro
em entidade registradora · OC005 redução de capital · OC007 ledger
append-only.

### 2.2 Frontend — 8.267 linhas, 14 rotas

| Módulo | Arquivos principais | Linhas |
|---|---|---:|
| **Dashboard** | `_authenticated/index.tsx` | 404 |
| **Operações** | `operacoes/{index,$id,nova}.tsx` | 770 |
| **Tomadores** | `tomadores/{index,$id}.tsx` | 431 |
| **Capital social** | `_authenticated/capital.tsx` | 213 |
| **Auditoria** | `_authenticated/auditoria.tsx` | 168 |
| **Auth** | `login.tsx`, `definir-senha.tsx`, `auth/sync.ts` | ~300 |
| **App shell** | `_authenticated.tsx`, `app-sidebar`, `command-palette` | 389 |
| **Design system** | `components/ui/*` (18 componentes) + `index.css` | ~2.700 |

### 2.3 Testes — 176 backend + 50 Vitest + 5 E2E

> Eram 52 + 32 + 1 em 2026-07-31. Cobertura backend total: 91%.

| Suíte | Testes | Onde concentra | Onde **não** cobre |
|---|---:|---|---|
| Backend | 52 | `capital_engine` (15), `security` (12), `operacoes` (8) | `alerts` (0), tomadores (24 stmt sem cobertura) |
| Vitest | 32 | erros (6), ativar-dialog (5), rótulos (3), badge (2) | 5 das 10 rotas sem teste algum |
| Playwright | **1** | login → dashboard → ativação → bloqueio OC001 | criação, liquidação, tomadores, capital |

---

## 3. Scorecard por módulo

Escala: 🟢 sólido · 🟡 funcional com lacuna · 🔴 crítico/ausente

| # | Módulo | Função | Testes | Prod | Nota | Justificativa medida |
|---|---|:---:|:---:|:---:|:---:|---|
| 1 | Auditoria / hash-chain | 🟢 | 🟢 | 🟢 | **9,0** | 100% cobertura, ledger append-only por trigger, UI em duas camadas |
| 2 | Identidade / Zero-Trust | 🟢 | 🟢 | 🔴 | **7,5** | `security.py` 100% coberto, papéis aplicados; **login real nunca funcionou em prod** |
| 3 | Operações | 🟢 | 🟢 | 🔴 | **8,5** | 11 endpoints, ciclo completo, 87% cobertura; E2E cobre criar→registrar→ativar→liquidar e OC002 |
| 4 | Motor de capital | 🟢 | 🟢 | 🔴 | **8,5** | 90% cobertura (era 58,8%); **dois furos do Art. 5º fechados** (inadimplência e novação); teto R$ 0,00 em prod |
| 5 | Modelos / migrations | 🟢 | 🟢 | 🟢 | **9,0** | 100% cobertura, 10 migrations com ciclo up/down validado |
| 6 | Capital (API + tela) | 🟢 | 🟡 | 🔴 | **6,5** | 81% cobertura, tela admin pronta; sem nenhum evento de constituição em prod |
| 7 | Design system | 🟢 | 🟡 | 🟡 | **7,0** | DS canônico ORGATEC, 14 pares de contraste ≥4,5:1 medidos; sem regressão visual |
| 8 | App shell | 🟢 | 🟡 | 🟡 | **7,0** | Sidebar, ⌘K, temas; coberto indiretamente por 5 E2E com asserção de erro de console |
| 9 | Tomadores | 🟡 | 🟡 | 🟡 | **6,5** | CRUD + gate OC002; 65% cobertura; **KYC agora existe** (via Compliance), mas sem tela própria |
| 10 | Dashboard | 🟡 | 🟡 | 🟡 | **6,0** | KPIs, 2 gráficos, banners; derivações extraídas para `lib/capital.ts` e cobertas por Vitest |
| 11 | Observabilidade | 🟡 | 🟡 | 🟡 | **6,0** | Prometheus + logging estruturado ativos; `alerts.py` arquivado (era código morto) |
| 12 | CI/CD | 🟡 | — | 🔴 | **4,0** | CircleCI configurado, mas **nunca executou** — aguarda autorização do GitHub App |
| 13 | **Cobrança** | 🟢 | 🟢 | 🔴 | **8,5** | Agenda PRICE/SAC imutável, novação atômica, aging com trilha de autoria, baixa com lastro bancário; 100% cobertura |
| 14 | **Contratos** | 🔴 | 🔴 | 🔴 | **0,5** | Stub. Bloqueado: entidade registradora não escolhida |
| 15 | **Fiscal** | 🟡 | 🟢 | 🔴 | **5,5** | Apuração IRPJ/CSLL/PIS/COFINS no Lucro Presumido pronta e 100% coberta, alíquotas em configuração; **IOF segue bloqueado em parecer** |
| 16 | **Compliance** | 🟡 | 🟢 | 🔴 | **6,0** | Identificação com evidência, retenção de 5 anos e detecção de atipicidade prontas e 100% cobertas; **canal COAF é adaptador desligado** |

**Média ponderada por criticidade: 7,2/10** (era 5,4).
Núcleo (1–8): **7,9** (era 7,5). Periferia regulatória (13–16): **5,1** (era 0,6).

O salto da periferia vem de Cobrança, Compliance e Fiscal — tudo que **não
dependia de terceiro**. Só **Contratos** continua em 0,5: nenhuma linha de
código o desbloqueia enquanto a entidade registradora não for escolhida.

---

## 4. Achados — o que aconteceu com cada um

Os cinco achados de 2026-07-31, e o estado deles em 2026-08-08:

1. ~~**`app/core/alerts.py` é código morto.**~~ **RESOLVIDO** (`a7b5e01`):
   arquivado. Alerta que ninguém invoca dá falsa sensação de que existe.

2. ~~**Motor de capital com a menor cobertura entre os módulos ativos
   (58,8%).**~~ **RESOLVIDO**: 90%. E a investigação que a cobertura
   forçou encontrou **dois furos do Art. 5º já em produção** (`bdccab5`):
   marcar inadimplência e renegociar liberavam capital de empréstimo não
   pago. Nenhum dos dois exigia má-fé — eram consequência da definição de
   "comprometido" contar só `ativa`.

3. **Produção serve bundle antigo.** **ABERTO.** O Railway não faz deploy
   de `main`. Tudo entregue de F5 até aqui — inclusive os dois furos
   fechados — segue fora do ar. É o item de maior risco do projeto agora:
   a produção roda a versão COM os furos.

4. ~~**1 teste E2E para 10 rotas.**~~ **MELHORADO**: 5 E2E, todos com
   asserção de zero erro de console. Nesta rodada, o E2E pegou: query de
   parcelas não invalidada, diálogo da régua que não fechava, e badge de
   status ambíguo. Segue sendo o teste com maior retorno por esforço.

5. **Nenhuma das 5 telas principais tem teste de componente.**
   **PARCIAL**: as derivações do dashboard foram extraídas para
   `lib/capital.ts` e cobertas; as telas em si continuam sem teste próprio,
   cobertas indiretamente pelos E2E.

### Achados novos desta rodada

6. **Regras de negócio críticas estavam sem trilha.** `ativa →
   inadimplente` não deixava rastro em lugar nenhum — declarar alguém
   inadimplente acontecia sem autor. Fechado pela `operacao_evento` (008).

7. **Dois erros de Postgres que só produção teria mostrado**, ambos
   pegos por teste antes de existirem: `NULL` não conflita em chave única
   (a varredura de atipicidade duplicaria a cada execução), e `now()` é o
   timestamp da transação, não do statement (a trilha exibiria eventos em
   ordem arbitrária).

---

## 5. Plano de combate

Ordenado por **risco removido por hora de trabalho**, não por conforto.

### 🔴 Frente 1 — Tornar operável (bloqueia tudo)

Sem isto, todo o resto é investimento em algo que ninguém usa.

| # | Ação | Depende de | Esforço |
|---|---|---|---|
| 1.1 | Destravar o deploy do Railway a partir de `main` | reautenticar MCP ou dashboard | 30 min |
| 1.2 | Definir senha do admin no Supabase + inserir linha em `usuario` com o mesmo UUID | você | 15 min |
| 1.3 | `insert into esc_capital_social` com o capital integralizado | **decisão dos sócios** | 5 min após a decisão |
| 1.4 | Autorizar CircleCI no GitHub e validar o primeiro run | você (OAuth) | 20 min |
| 1.5 | Smoke test end-to-end em produção: login real → criar → registrar → ativar | 1.1–1.3 | 1 h |

**Sem 1.3 o sistema é uma vitrine.** É a decisão de maior alavancagem do
projeto inteiro e não depende de nenhuma linha de código.

### ✅ Frente 2 — Fechar o flanco de testes — **CONCLUÍDA**

| # | Ação | Estado |
|---|---|---|
| 2.1 | Cobertura de `capital_engine.py` ≥90% | ✅ 58,8% → 90% |
| 2.2 | E2E de ciclo completo e OC002 | ✅ `68abb82` |
| 2.3 | Teste de componente para as telas | 🟡 parcial — derivações extraídas e cobertas; telas ainda sem teste próprio |
| 2.4 | Decidir `alerts.py` | ✅ arquivado em `a7b5e01` |

### ✅ Frente 3 — Cobrança — **CONCLUÍDA**

| # | Ação | Commit |
|---|---|---|
| 3.1 | Agenda PRICE/SAC gerada no banco na ativação, imutável (OC009) | `4d5edc4` |
| 3.2 | Novação atômica (OC008) + correção dos dois furos do Art. 5º | `bdccab5` |
| 3.3 | Aging com transição automática e trilha de autoria (OC010) | `34b5b20` |
| 3.4 | Baixa de recebimento amarrada a movimento bancário (OC011/OC012) | `39d29a1` |

O ciclo fecha: a agenda define o que se cobra, o aging vê o atraso a partir
dela, e só a baixa **com lastro bancário** tira a parcela do atraso.

### 🟡 Frente 4 — Regulatório

**Construído sem depender de ninguém** (migration 010):

| Item | Estado |
|---|---|
| Identificação com evidência arquivada (hash SHA-256 verificável) | ✅ |
| Retenção de 5 anos garantida pelo banco (Lei 9.613/98, art. 10, III — OC013) | ✅ |
| Detecção interna de atipicidade: fracionamento, liquidação antecipada, pagamento em excesso | ✅ |
| Canal externo COAF | 🔌 adaptador pronto e **desligado** |

**Fiscal — apuração da receita da ESC construída** (migration 011):

| Item | Estado |
|---|---|
| Regime Lucro Presumido, apuração trimestral | ✅ decidido pelo dono do negócio |
| IRPJ, adicional, CSLL, PIS e COFINS sobre a receita de JUROS | ✅ |
| Presunção, alíquotas e limite do adicional em configuração, com vigência | ✅ nada semeado no código |
| Retificação por versão (a apuração original nunca é editada) | ✅ |
| IOF-crédito | 🔴 bloqueado em parecer |

A base é só o juro — a amortização devolve principal e não é resultado. Sem
parâmetro configurado, apurar é **recusado** (OC015) em vez de devolver um
número plausível calculado com alíquota escolhida pelo sistema.

**Continua bloqueado em ação externa:**

| Módulo | Ação necessária | Quem |
|---|---|---|
| Contratos | Contato comercial: CRDC, SPC Grafeno (via ABRAFESC), CERC, B3 | você — formulários já mapeados |
| Fiscal (só o IOF) | Parecer jurídico-tributário sobre IOF em ESC | contador/advogado |
| Compliance (só o canal) | Confirmação do regime PLD/COAF para ESC | advogado |
| Fiscal (para usar) | Preencher presunção e alíquotas na tela | contador |

**Uma decisão de negócio pendente, agora com o número na mão:** exigir
identificação arquivada antes de ativar uma operação. A amarra não foi
ligada de propósito — hoje existem tomadores sem evidência, e ativá-la sem
aviso pararia a operação. `GET /compliance/identificacao/pendencias` mostra
quanto capital está exposto a tomadores sem identificação.

---

## 6. Sequência recomendada

```
Frente 2 (testes)    ─── ✅ concluída
Frente 3 (cobrança)  ─── ✅ concluída
Frente 4 (construível) ─ ✅ concluída — compliance E fiscal
Frente 1 (operável)  ─── 🔴 ABERTA — e agora é a ÚNICA coisa que importa
```

Não há mais nada de valor a construir sem você. Todo o trabalho técnico
possível foi feito; o que resta é integralmente decisão ou credencial:

1. **Reconectar o GitHub no Railway** para `main`. Sem isso, produção segue
   rodando a versão **com os dois furos do Art. 5º** que já foram
   corrigidos aqui. Este é hoje o maior risco do projeto.
2. **Valor do capital social integralizado** — decisão dos sócios. Uma
   linha de SQL que transforma uma vitrine em uma ESC operante.
3. **Senha do admin no Supabase** + linha em `usuario` com o mesmo UUID.
4. **Autorizar o CircleCI** no GitHub.
5. **Decidir** se identificação arquivada passa a ser pré-requisito de
   ativação (ver Frente 4).
6. **Contador preenche** presunção e alíquotas na tela Fiscal — sem isso a
   apuração recusa, de propósito.
