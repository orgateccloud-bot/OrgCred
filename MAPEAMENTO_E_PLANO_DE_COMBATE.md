# OrgCred — Mapeamento, Scorecard e Plano de Combate

> Levantado em 2026-07-31 a partir de medição direta do código (cobertura
> real via `htmlcov/status.json`, contagem de statements, endpoints e
> testes), não de estimativa. Onde um número não pôde ser medido, está
> dito explicitamente.

---

## 1. Retrato em uma frase

O OrgCred tem **um núcleo de crédito sólido e provado** (capital, operações,
auditoria com hash-chain) envolto por **quatro módulos regulatórios que são
casca vazia** — e está **no ar em produção sem conseguir ser usado**, porque
o teto de capital é R$ 0,00 e o login real nunca foi ativado.

O risco dominante não é qualidade de código. É que **o sistema parece pronto
e não é operável**.

---

## 2. Mapa de módulos

### 2.1 Backend — 1.914 linhas, 19 endpoints, 9 routers

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

### 2.2 Frontend — 6.692 linhas, 10 rotas

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

### 2.3 Testes — 52 backend + 32 frontend + 1 E2E

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
| 2 | Identidade / Zero-Trust | 🟢 | 🟢 | 🔴 | **7,5** | `security.py` 100% coberto, papéis aplicados; **mas login real nunca funcionou em prod** |
| 3 | Operações | 🟢 | 🟡 | 🟡 | **7,5** | 9 endpoints, ciclo de vida completo, 84% cobertura; E2E cobre só ativação |
| 4 | Motor de capital | 🟢 | 🟡 | 🔴 | **7,0** | Núcleo legal correto (advisory lock provado); **58,8% cobertura** no arquivo mais crítico do sistema; teto R$ 0,00 em prod |
| 5 | Modelos / migrations | 🟢 | 🟢 | 🟢 | **9,0** | 100% cobertura, ciclo up/down validado |
| 6 | Capital (API + tela) | 🟢 | 🟡 | 🔴 | **6,5** | 81% cobertura, tela admin pronta; sem nenhum evento de constituição em prod |
| 7 | Design system | 🟢 | 🟡 | 🟡 | **7,0** | DS canônico ORGATEC, 14 pares de contraste ≥4,5:1 medidos; sem teste de regressão visual |
| 8 | App shell | 🟢 | 🔴 | 🟡 | **6,5** | Sidebar, ⌘K, temas; **zero teste** — o bug do TooltipProvider derrubou tudo e só o E2E pegou |
| 9 | Tomadores | 🟡 | 🔴 | 🟡 | **5,5** | CRUD + gate OC002; **65% cobertura, 24 stmt mortos**, sem KYC, sem teste de tela |
| 10 | Dashboard | 🟡 | 🔴 | 🟡 | **5,5** | KPIs, 2 gráficos, banners; **404 linhas sem um único teste** |
| 11 | Observabilidade | 🟡 | 🟡 | 🟡 | **5,0** | Prometheus + logging estruturado ativos; **`alerts.py` é código morto (0 refs, 0%)** |
| 12 | CI/CD | 🟡 | — | 🔴 | **4,0** | Migrado para CircleCI, mas **nunca executou uma vez** — GH Actions morreu por billing |
| 13 | **Cobrança** | 🔴 | 🔴 | 🔴 | **1,0** | Stub. Não bloqueado por terceiro — só não foi feito |
| 14 | **Contratos** | 🔴 | 🔴 | 🔴 | **0,5** | Stub. Bloqueado: entidade registradora não escolhida |
| 15 | **Fiscal** | 🔴 | 🔴 | 🔴 | **0,5** | Stub. Bloqueado: parecer de IOF |
| 16 | **Compliance** | 🔴 | 🔴 | 🔴 | **0,5** | Stub. Bloqueado: regime PLD/COAF |

**Média ponderada por criticidade: 5,4/10.**
Núcleo (1–8): **7,5**. Periferia regulatória (13–16): **0,6**.

---

## 4. Achados desta varredura

1. **`app/core/alerts.py` é código morto.** 37 statements, 0% de cobertura,
   **zero referências** em todo o projeto. Implementa alerta de capital
   baixo e rajada de bloqueios — exatamente os dois eventos que mais
   importam operacionalmente — e nunca é invocado. Ou liga, ou remove;
   deixar dá falsa sensação de que existe alerta.

2. **O motor de capital tem a menor cobertura entre os módulos ativos
   (58,8%)** e é o arquivo que carrega a responsabilidade legal do
   Art. 5º. 35 statements sem cobertura — provavelmente os caminhos novos
   (`transicionar_operacao`, `criar_operacao`, `registrar_evento_capital`)
   adicionados na F7/F8.

3. **Produção serve bundle antigo** (`index-CsQRsW7J.js`) — o deploy do
   Railway não dispara de `main` desde antes do PR #12. Tudo que foi
   entregue nas fases F5–F9 **não está no ar**.

4. **1 teste E2E para 10 rotas.** O único E2E existente já pegou dois bugs
   graves (TooltipProvider, heading ausente). É o teste com maior retorno
   por unidade de esforço no projeto e está subutilizado.

5. **Nenhuma das 5 telas principais tem teste de componente** — dashboard
   (404 linhas), operações lista/detalhe/nova, tomadores, capital.

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

### 🟡 Frente 2 — Fechar o flanco de testes (2–3 dias)

| # | Ação | Por quê |
|---|---|---|
| 2.1 | Subir cobertura de `capital_engine.py` de 58,8% para ≥90% | é o arquivo com peso legal e a menor cobertura ativa |
| 2.2 | E2E: criação → registro → liquidação, e OC002 (município não autorizado) | o E2E é o teste que mais achou bug real |
| 2.3 | Teste de componente para dashboard, operações e tomadores | 5 telas, 0 testes |
| 2.4 | Decidir `alerts.py`: ligar nos pontos reais ou remover | código morto que simula uma capacidade inexistente |

### 🟢 Frente 3 — Cobrança (1–2 semanas, **não bloqueada**)

O único módulo de negócio que **não depende de terceiro** — só não foi
feito. Ordem correta:

1. Agenda de parcelas gerada no banco na ativação (PRICE e SAC), imutável.
2. **Novação atômica** para renegociação — sob o mesmo `pg_advisory_xact_lock`
   do teto, com novo SQLSTATE. Sem isto, renegociar conta capital em dobro
   e viola o Art. 5º sem ninguém agir de má-fé.
3. Aging de inadimplência com transição automática e trilha de autor.
4. Baixa de recebimento amarrada a movimentação bancária.

### ⚪ Frente 4 — Desbloquear o regulatório (ação externa)

| Módulo | Ação necessária | Quem |
|---|---|---|
| Contratos | Contato comercial: CRDC, SPC Grafeno (via ABRAFESC), CERC, B3 | você — formulários já mapeados |
| Fiscal | Parecer jurídico-tributário sobre IOF em ESC | contador/advogado |
| Compliance | Confirmação do regime PLD/COAF para ESC | advogado |

Enquanto não saem, vale construir o que é **indiscutível**: identificação
com evidência arquivada, retenção de 5 anos, detecção interna de
atipicidade — com o canal externo como adaptador plugável.

---

## 6. Sequência recomendada

```
Frente 1 (operável)  ─── destrava valor real, dias
   └─ Frente 2 (testes) ─── protege o que já existe, dias
        └─ Frente 3 (cobrança) ─── único módulo de negócio livre, semanas
             └─ Frente 4 ─── quando as decisões externas saírem
```

Se só uma coisa for feita nesta semana: **item 1.3 — o valor do capital
social.** É uma linha de SQL que transforma uma vitrine em uma ESC operante.
