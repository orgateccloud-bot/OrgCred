# OrgCred V1 — Relatório de Modernização & Plano de Ação
**Data:** 12 de julho de 2026 · **Método:** Análise adversarial multi-agente + pesquisa de mercado  
**Status:** Snapshot parcial analisado; projeto sem git, Postgres real testado (Art. 5º LC 167/2019 comprovado)

---

## RESUMO EXECUTIVO

O OrgCred é um motor de microcrédito bem arquitetado no núcleo (triggers PL/pgSQL com teto de capital serializado), mas com **fragilidades operacionais críticas** que o tornam inviável para produção sem mudanças:

1. **Isolamento crítico:** Sem git, pyproject.toml, lockfile ou testes Python — código não é versionável nem reproduzível.
2. **Lacuna de segurança:** API sem autenticação/autorização; qualquer pessoa com acesso de rede ativa operações.
3. **Falta de observabilidade:** Nenhum logging estruturado, métricas, alertas ou trilha de auditoria com autor.
4. **Bloqueadores de negócio:** Entidade registradora não escolhida, regime de IOF não definido, capital social inicial ausente.

**Ganho potencial de modernização:** Estrutura operável, defensável legalmente, e escalável para 2-3 operadores sem reengenharia.

---

## PARTE 1: MAPA DO PROJETO ATUAL

### Dimensão: Arquitetura Python

**Status:** Bem desenhada no pequeno, mas operacionalmente quebrada

| Achado | Severidade | Descrição |
|--------|-----------|-----------|
| **Snapshot não reconstituível** | 🔴 Alta | Imports relativos (`from ..db`, `from ..models`) apontam para uma árvore de pacote que não existe em disco. Faltam: `db.py`, `models.py`, `main.py`, migrations 001/002, `requirements.txt`, `.env.example`. O código Python atual é não-importável. |
| **OC005 fora do mapa de erros** | 🟡 Média | `capital_engine.py` não mapeia SQLSTATE OC005 → `ReducaoCapitalBloqueada` na tradução de erros. Recusa legítima de redução de capital vira erro 500 em vez de 422. |
| **Contrato HTTP sem código SQLSTATE** | 🟡 Média | Router devolve apenas `detail: str` com mensagem em português. Cliente precisa fazer substring-matching para distinguir OC001 de OC002 — reintroduz o anti-padrão que a revisão de 2026-07-11 eliminou no banco. |
| **Config.py com efeito colateral de import** | 🟡 Média | Validação roda no import (não no startup da aplicação) → prejudica testabilidade. Guarda produção é opt-in (`ORGCRED_ENV=production` deve ser setado) — erro operacional típico (não setar variável) passa liso. |
| **Zero testes Python** | 🟡 Média | Toda cobertura é SQL (7 cenários + concorrência). Tradução pgcode→exceção→HTTP não tem teste. Idempotência do POST /ativar (retry de rede) é segura por dois níveis de proteção, mas não provada; regressão é silenciosa. |
| **SQLAlchemy em estilo legacy** | 🟢 Baixa | Usa `db.query()` em vez de `select()` (estilo 2.0). Vale modernizar em refactoring; não é bloqueador. Async não vale aqui (baixo throughput). |

**Recomendação estratégica:** Antes de qualquer melhoria, reconstituir a árvore do README, validar `uvicorn app.main:app` + testes, e ter git.

---

### Dimensão: Banco de Dados & Ledger

**Status:** Núcleo sólido (race condition F1, redução de capital F2, máquina de estados F3 todas corrigidas), mas design incompleto

| Achado | Severidade | Descrição |
|--------|-----------|-----------|
| **Ausência de migrations 001/002** | 🔴 Alta | A pasta contém só 003_hardening_capital.sql. As migrations 001 e 002 (schema inicial, usuários/papéis) não estão presentes — testes não rodam sem elas. Presume-se que `esc_capital_social`, `operacao_credito`, `tomador`, `capital_ledger` etc. foram criadas em 001 e 002 são expandidas em 003. |
| **Ledger sem proteção contra UPDATE/DELETE** | 🟡 Média | `capital_ledger` é append-only por semântica, mas não há constraints (ON DELETE/UPDATE RESTRICT) nem triggers que protejam contra UPDATE acidental de um evento. Lição do OrgConc: ledger é a prova de conformidade — mutação silenciosa = não-auditabilidade. |
| **Falta dupla-partida contábil** | 🟡 Média | O ledger registra `ativacao_operacao`, `liquidacao` etc., mas não há contrapartida contábil (qual conta está sendo debitada/creditada no balanço?). Sistema financeiro real precisa de dupla-partida e reconciliação diária com razão contábil. |
| **Amortização parcial não libera capital** | 🟡 Média | Comprometimento usa `valor_principal` integral até liquidação. Se a interpretação correta do Art. 5º for saldo devedor, pagamento de parcela deveria liberar capital (evento `amortizacao` existe no schema e nada o dispara). Limita giro de carteira. |
| **Renegociação sem regra clara** | 🟡 Média | Status `renegociada` existe, mas se renegociar = criar nova operação, capital pode ser contado em dobro (antiga renegociada + nova ativa). Risco de violação do teto por dupla contagem. |
| **Movimentacao_bancaria e contrato_documento não-obrigatórios** | 🟡 Média | Art. 5º LC 167/2019 exige movimentação conta-a-conta formal. Tabelas existem, mas nada as exige antes de desembolso. Gate de registro (OC004) cobre parte; resto depende do fluxo de contratos (bloqueado pela escolha da entidade registradora). |
| **Migrations manuais sem Alembic** | 🟡 Média | SQL solto é aceitável em um único desenvolvedor; inaceitável com múltiplos ambientes (dev/staging/prod). Sem ferramenta, risco de rollback babelado e schema drift. |
| **Sem backup/restore testado** | 🟡 Média | Lição registrada do OrgConc: perder o ledger é perder a prova de conformidade. Sem estratégia de PITR (WAL-G, pg_basebackup), operação de crédito é não-viável. |

---

### Dimensão: Segurança & Compliance

**Status:** Crítico — múltiplas lacunas de segurança

| Achado | Severidade | Descrição |
|--------|-----------|-----------|
| **API sem autenticação nenhuma** | 🔴 CRÍTICA | Tabela `usuario` (admin/operador) existe, mas nenhum enforcement. Hoje, qualquer pessoa com acesso de rede à API ativa operações de crédito — registra eventos no ledger, compromete capital legal. Aceitável em dev local; inaceitável um dia antes de qualquer deploy. É a lacuna maior de segurança. |
| **Trilha de auditoria sem autor** | 🟡 Média | `capital_ledger.usuario_id` existe, mas triggers insere sem saber quem executou. Padrão conhecido (SET LOCAL app.user_id + current_setting()) só funciona com autenticação em produção. Auditoria atual não rastreia autoria real. |
| **LGPD: PII em logs** | 🟡 Média | Tomadores têm CNPJ/razão_social (e futuramente CPF de avalistas). Nenhum mascaramento em logs; aplicações inspecionam o banco direto. Risco de exposição em relatórios/backups. |
| **Segredos em .env plano** | 🟡 Média | `ORGCRED_DATABASE_URL` em arquivo texto (lição do OrgConc: exposição foi bloqueador real). Sem versionamento, sem segregação local/prod. |
| **Superfície de ataque aberta** | 🟡 Média | API usa FastAPI `/docs` default; sem rate limiting, sem CORS restritivo, sem TLS em produção (config não menciona). |
| **PLD/COAF stub** | 🟡 Média | `compliance.py` vazio. ESC é obrigada a COAF? Regulação atual (2026) não é clara na pasta. Risco de falta de comunicações obrigatórias. |
| **Sem supply chain security** | 🟢 Baixa | Sem requirements com hashes/lock; sem SCA (pip-audit); sem SAST (bandit/semgrep) em CI. Dependências podem ter vulnerabilidades não detectadas. |

---

### Dimensão: Testes & DevOps

**Status:** Não pronto para produção

| Achado | Severidade | Descrição |
|--------|-----------|-----------|
| **Testes bash rodam só em Linux** | 🟡 Média | `test_capital_invariant.sh` e `test_concorrencia.py` usam `createdb`, `psql`, `/var/run/postgresql` — não rodão no Windows (máquina de dev é Windows 11). Ninguém pode testar localmente a não ser no Linux/Mac. |
| **Sem CI/CD** | 🔴 Alta | Sem repositório git, sem GitHub Actions, sem pipeline. Não há gate de teste antes de merge nem deploy automático. Mudança no banco é subida manualmente — risco de incompatibilidade não detectada. |
| **Sem Docker** | 🟡 Média | Sem `docker-compose` para dev (Postgres + API); ninguém consegue rodar localmente sem instalar Postgres à mão e saber psycopg2. Onboarding operacional é frágil. |
| **Sem logging estruturado** | 🟡 Média | Nenhuma chamada a `logging.info()` / `structlog` observável. Produção terá zero visibilidade em o que está acontecendo. |
| **Sem observabilidade** | 🟡 Média | Sem métricas de negócio (capital disponível, operações bloqueadas por OC001), sem alertas, sem OpenTelemetry. SLA é invisível. |

---

## PARTE 2: CONCEITOS DE MERCADO & BENCHMARKS

### Contexto Regulatório 2026

**ESC — Lei Complementar 167/2019 (última revisão: Marco Legal das Garantias 2023)**

- **Enquadramento:** Pessoa jurídica de direito privado; limite de capital social integralizado (não apenas promitido); limite de receita anual (enquadramento ME/EPP).
- **Restrição geográfica:** Vedado operar fora do município declarado na constituição — OrgCred implementa corretamente (tomador.municipio_autorizado + gate OC002).
- **Teto de capital:** Art. 5º — "total das operações de crédito ativo não pode exceder o capital social" — OrgCred implementa serializado com advisory lock, comprovado. Interpretação: usa principal integral até liquidação (conservadora, juridicamente segura).
- **Entidades registradoras:** Art. 5º §3º obriga registro em entidade apodada pela BC; as aptas são: CERC (Minas Gerais), Núclea/B3, TAG. **Bloqueador:** OrgCred não escolheu qual.
- **Regime tributário:** IOF-crédito pode incidir; RFB não tem posição única. **Bloqueador:** OrgCred não confirmou a interpretação.
- **PLD/COAF:** ESC está sujeita a reporte (norma BCB 59/2021 aplica?). Sem confirmação explícita, risco regulatório.

**Recomendação:** Antes de produção, escritório jurídico confirma entidade registradora, regime de IOF, e status de supervisão COAF.

---

### Stack Python 2026 — Padrões de Mercado

**Para um sistema financeiro pequeno, single-tenant, crítico:**

| Aspecto | Recomendação | Aplicação ao OrgCred |
|--------|-------------|--------|
| **Gerenciador de pacotes** | `uv` (mais rápido, lockfile garantido, cache isolado) | Adotar; substituir pip; usar `uv sync` em CI. |
| **pyproject.toml** | Padrão PEP 621 com `[project]`, `[tool.uv]`, `[tool.pytest]`, `[tool.mypy]`, `[tool.ruff]` | Criar imediatamente; lista deps com fixação de versão maior. |
| **Lint + Format** | `ruff` (70% das issues de `pylint`+`black` em um binário rápido) | Configurar: max line 100, exclude migrations, formato black. |
| **Type-checking** | `mypy` ou `pyright` (pyright é mais rápido, pyright é padrão VSCode); ambos detectam None-dereference | Usar `pyright` strict mode; excluir migrations. |
| **Config** | `pydantic-settings` v2 + BaseSettings + model_validator | Substituir `os.environ` + validação de import. |
| **FastAPI** | Versão 0.115+; lifespan context manager para startup/shutdown (shutdown = salvar backup de ledger?). | Usar atual; adicionar dependency injection para Pg session + settings. |
| **SQLAlchemy** | Versão 2.0+; estilo `select()` em vez de `Query`; async sqlalchemy para alta concorrência (não aplica aqui). | Modernizar de `Query` para `select()`; manter síncrono psycopg3. |
| **Alembic** | Padrão para versionamento de schema; padrão alembic-utils para triggers PL/pgSQL versionados. | Adotar Alembic; mover migrations 001–003 para revisões, com `raw_sql=True` e um `operations.execute()` por cada bloco de SQL. |
| **Testes** | `pytest` com `testcontainers-python` (Docker postgres automático) + `pgTAP` para triggers (testes SQL isolados). | Migrar bash/psycopg2 bruto para pytest fixtures + Postgres container; adicionar testes Python (router/service/config). |
| **Observabilidade** | `structlog` (estruturado) + `logfire` (SaaS) OU `opentelemetry-python` (self-hosted); métricas via `prometheus-client`. | Mínimo: structlog + file/stdout, métricas de capital/operações/erros; avançado: Logfire (Anthropic) ou OTel. |
| **CI/CD** | GitHub Actions com jobs paralelos: ruff+mypy+bandit+pip-audit+pytest (Postgres container). | Criar `.github/workflows/ci.yml` com gating de PR. |
| **Docker** | `python:3.12-slim` multi-stage com `uv`; `docker-compose` para dev (Postgres 16 + API). | Criar Dockerfile e docker-compose.yml; `.dockerignore` sensato. |

---

### Arquitetura de Ledger Financeiro — Padrões de Mercado

**Imutabilidade:** Ledgers financeiros de mercado (Modern Treasury, TigerBeetle, ledger-cli) usam:
- **Append-only:** Inserts apenas; nenhum UPDATE/DELETE em linhas uma vez criadas.
- **Hash-chain (blockchain-like):** Cada linha referencia hash anterior; detecta tampering. Exemplo: OrgCred poderia adicionar `prev_hash` e `current_hash` com SHA256.
- **Dupla-partida:** Cada evento de crédito = débito em conta de tomador + crédito em conta de capital.
- **Reconci liação automática:** Ledger se reconcilia contra razão contábil diariamente (testes SQL).

**Aplicação ao OrgCred:**
1. Adicionar constraints `ON DELETE RESTRICT, ON UPDATE RESTRICT` em `capital_ledger`.
2. Imprensa dupla-partida: cada `ativacao_operacao` → débito em "Contas a Receber" (ativo) + crédito em "Capital Emprestado" (passivo).
3. Se amortização libera capital: evento `amortizacao` com valor = parcela paga.
4. Hash-chain: coluna `prev_hash` e trigger que computa `current_hash` de (id, evento_tipo, valor, prev_hash).

---

### Event Sourcing vs. Ledger Tradicional

**Decisão:** Ledger é suficiente aqui; event sourcing é overengineering para um sistema single-tenant de baixo throughput.

- **Ledger:** Registro imutável de transações (débitos/créditos). Questão: "qual é o capital disponível agora?" → scan do ledger + views.
- **Event sourcing:** Cadeia de eventos (OperacaoAtivada, OperacaoLiquidada, etc.); estado atual se reconstrói do histórico. Melhor para: "qual era o estado às 15h? Recrie-o". Overkill para ESC municipal.

**OrgCred fica com ledger tradicional.**

---

### Autenticação para Fintech Pequena

**Opções:**

1. **Supabase Auth (GoTrue):** ORGATEC já usa Supabase em OrgConc. JWT validado na API via middleware. Vantagem: stack conhecida; desvantagem: cloud third-party.
2. **Authentik self-hosted:** Keycloak alternativo leve. Vantagem: controle local; desvantagem: overhead operacional (2+ máquinas de HA para produção).
3. **JWT próprio:** Risco alto em sistema financeiro (rolar auth na mão é proibido em regulação); não recomendado.
4. **fastapi-users:** Wrapper sobre auth; lower-level que Supabase. Vantagem: open-source, controle total; desvantagem: requer sessões bancáveis (cookie seguro + CSRF).

**Recomendação para OrgCred:** Usar Supabase Auth (compatível com infraestrutura OrgConc). Fluxo: 
- Painel login → Supabase → retorna JWT
- API valida JWT + propaga `user_id` via `SET LOCAL app.user_id` ao banco
- Triggers usam `current_setting('app.user_id')` para trilha de auditoria

**MFA obrigatório** para operadores que ativem operações.

---

## PARTE 3: PLANO DE AÇÃO FASEADO

### Fase 0: Fundação (Semana 1–2) — PRÉ-REQUISITO

**Objetivo:** Código versionável, reproduzível, testável.

- [ ] **git init** na pasta; criar `.gitignore` (`.env`, `__pycache__`, `*.pyc`, `.venv`, `.eggs`)
- [ ] **Reconstituir árvore de pacote:**
  - [ ] Criar `app/`, `app/core/`, `app/routers/`, `migrations/`, `tests/`
  - [ ] Mover/criar: `app/main.py`, `app/db.py`, `app/models.py`
  - [ ] Recuperar migrations 001 e 002 (deduzir do schema referenciado em 003)
  - [ ] Validar: `uvicorn app.main:app --reload` sem erros
- [ ] **pyproject.toml:** Definir Python 3.11+, deps (fastapi, sqlalchemy, pydantic, psycopg, pytest, ruff, mypy, etc.), versionamento.
- [ ] **uv sync** (não `pip install`)
- [ ] **Validar testes:**
  - [ ] `./tests/test_capital_invariant.sh` passa (Linux/Mac) ou portado para pytest + testcontainers
  - [ ] `python tests/test_concorrencia.py` passa
- [ ] **Commit:** "chore: bootstrap pyproject, reconstituir árvore de pacote, validar testes"

**Esforço:** M (2–3 dias) | **Criticidade:** 🔴 Bloqueador de tudo

---

### Fase 1: Tooling & Quality (Semana 2–3)

**Objetivo:** Lint, type-check, formatação automática; base para CI.

- [ ] **ruff.toml:** Regras (max line 100, exclude migrations, format black)
  - [ ] `ruff check --fix app tests` na mão
  - [ ] Commit: "style: ruff formatter e linter configurados"
- [ ] **.pre-commit:** hooks para ruff, mypy, bandit (opcional em local)
- [ ] **mypy.ini:** strict mode; exclusão de migrations
  - [ ] `mypy app tests` sem erros
  - [ ] Commit: "type: mypy strict mode, type hints completos"
- [ ] **.github/workflows/ci.yml:** GitHub Actions
  - [ ] Job 1 (ruff + mypy + bandit)
  - [ ] Job 2 (pytest com Postgres container)
  - [ ] Passar em main antes de merge
- [ ] **requirements:** pip-audit no CI (detect CVEs)

**Esforço:** P (1–2 dias) | **Criticidade:** 🟡 Recomendado antes de commits importantes

---

### Fase 2: Segurança & Autenticação (Semana 3–4)

**Objetivo:** API defensável; autenticação em gate de operações críticas.

- [ ] **Supabase Auth integração:**
  - [ ] Criar tenant Supabase (ou reuso OrgConc)
  - [ ] Middleware FastAPI: validar `Authorization: Bearer <jwt>`
  - [ ] Dependency: `get_current_user() -> User`
  - [ ] Decorator: `@require_role("operador")`
- [ ] **Trilha de auditoria com autor:**
  - [ ] Dependency injetar `user_id` em todos os service calls
  - [ ] Service passa `user_id` ao banco via `SET LOCAL app.user_id`
  - [ ] Trigger: `current_setting('app.user_id')` em inserts de `capital_ledger`
  - [ ] Adição de coluna: `capital_ledger.usuario_id` now NOT NULL (migration 004)
- [ ] **Hierarquia de exceções:**
  - [ ] Criar `exceptions.py`: `RegraNegocioViolada(sqlstate, http_status, message)`
  - [ ] Subclasses: `TetoCapitalExcedido`, `MunicipioNaoAutorizado`, `TransicaoInvalida`, `RegistroEntidadeAusente`, `ReducaoCapitalBloqueada`
  - [ ] Router usa `except RegraNegocioViolada` (uma linha vs. enumeração)
  - [ ] Resposta HTTP: `{"codigo": "OC001", "detalhe": "..."}`
- [ ] **Config.py modernizado:**
  - [ ] Pydantic BaseSettings + model_validator
  - [ ] Validação no startup (lifespan), não no import
  - [ ] Recusa `ORGCRED_DATABASE_URL` ausente fora de dev
- [ ] **Mascaramento de PII em logs:**
  - [ ] structlog filter: mascara CPF/CNPJ em eventos
  - [ ] Testes: CPF nunca aparece em stdout/logs
- [ ] **Rate limiting, CORS:**
  - [ ] FastAPI middleware (opcional: usar `slowapi`)
  - [ ] CORS restritivo (localhost + OrgConc front URL)

**Esforço:** G (1–2 semanas) | **Criticidade:** 🔴 Mandatório para produção

---

### Fase 3: Observabilidade & Operação (Semana 4–5)

**Objetivo:** Visibilidade em produção; escalabilidade operacional.

- [ ] **Logging estruturado:**
  - [ ] `structlog` + `structlog.processors.JSONRenderer`
  - [ ] Contexto: `request_id`, `user_id`, `operacao_id`
  - [ ] Eventos: capital_check, ativacao_ok, ativacao_bloqueada_OC001, etc.
- [ ] **Métricas de negócio:**
  - [ ] `prometheus-client`: counters (operacoes_ativadas, bloqueadas_por_OC*), gauges (capital_disponivel)
  - [ ] Endpoint `/metrics` no FastAPI
  - [ ] Opcional: scrape com Prometheus + Grafana (dashboards locais)
- [ ] **Alerts simples:**
  - [ ] Email se capital_disponivel cair abaixo de 20%
  - [ ] Email se 5+ ativações bloqueadas em 1h (padrão de ataque?)
- [ ] **Docker & docker-compose:**
  - [ ] Dockerfile multi-stage (builder + runtime slim)
  - [ ] docker-compose.yml: Postgres 16 (volume persistente) + API (port 8000)
  - [ ] Env: DB_URL, JWT_SECRET, LOG_LEVEL
  - [ ] Documentação: `docker-compose up` para dev
- [ ] **Backup automático:**
  - [ ] Postgres backup diário via pg_basebackup + WAL-G para S3
  - [ ] Script: `/scripts/backup.sh` (teste de restore 1x/mês)
  - [ ] Documentação: RTO 2h, RPO 1h

**Esforço:** G (1–2 semanas) | **Criticidade:** 🟡 Recomendado para operação sustentável

---

### Fase 4: Testes & Confiabilidade (Semana 5–6)

**Objetivo:** Cobertura de Python; proteção contra regressão; confiança deployement.

- [ ] **Suite pytest:**
  - [ ] Fixture: Postgres container via testcontainers
  - [ ] Fixtures: migrations 001–003 aplicadas automaticamente
  - [ ] Testes de exceção por SQLSTATE: OC001, OC002, OC003, OC004, OC005
  - [ ] Testes de idempotência: POST /ativar com retry (não duplica capital)
  - [ ] Testes de config: produção + localhost → ConfigError
  - [ ] Mínimo 70% de cobertura (ruff report, pytest-cov)
- [ ] **Migração de testes bash → pytest:**
  - [ ] Reescrever 7 cenários de `test_capital_invariant.sh` como parametrização pytest
  - [ ] Manter `test_concorrencia.py` ou replicar em pytest threading
- [ ] **pgTAP para triggers:**
  - [ ] Testes SQL isolados (trigger behavior, constraints, views)
  - [ ] Verificar: `pg_advisory_xact_lock` realmente serializa; UPDATE de status já='ativa' ignora; etc.
- [ ] **Testes de segurança:**
  - [ ] JWT inválido → 401
  - [ ] JWT sem `operador` role → 403
  - [ ] Operação de outro tomador → 403 (futuramente, se multi-tenant)

**Esforço:** G (1–2 semanas) | **Criticidade:** 🔴 Essencial antes de produção

---

### Fase 5: Alembic & Schema Evolution (Semana 6–7)

**Objetivo:** Migrations versionadas, reversíveis, team-safe.

- [ ] **Alembic init & migrate existing:**
  - [ ] `alembic init migrations`
  - [ ] Converter 001–003 em revisões Alembic (raw_sql mode)
  - [ ] Nova migration 004: adicionar `capital_ledger.usuario_id`, FK, constraints
  - [ ] `alembic current` + `alembic upgrade head` verificação
- [ ] **Workflow de migrations:**
  - [ ] Develop: `alembic revision -m "descrição"` + edit .sql
  - [ ] Test: `alembic upgrade head; pytest`
  - [ ] Prod: `alembic upgrade head` como pré-deploy
  - [ ] Rollback: `alembic downgrade -1` (documentado para emergência)
- [ ] **CI:** `alembic current` deve bater com `app.models` (validação explícita em CI, não automática)

**Esforço:** M (3–5 dias) | **Criticidade:** 🟡 Recomendado antes de múltiplos ambientes

---

### Fase 6: Conformidade & Blockers de Negócio (Semana 7–8)

**Objetivo:** Fechar lacunas regulatórias; desbloqueadores de produção.

- [ ] **Entidade registradora:**
  - [ ] Engajamento com CERC / Núclea / TAG
  - [ ] Contrato de API + credenciais de teste
  - [ ] Roteador interno: `POST /operacoes/{id}/registrar` → chamar entidade registradora → atualizar `registro_entidade_ref`
- [ ] **Regime de IOF:**
  - [ ] Parecer jurídico: incide IOF-crédito? Se sim, alíquota, quem paga (ESC ou tomador)?
  - [ ] Schema: adicionar coluna `iof_valor`, `iof_pago` em operacao_credito
  - [ ] Business rule: ativação falha se tomador não tem limite de IOF disponível (novo gate)
- [ ] **Capital social inicial definido:**
  - [ ] Acionistas confirmam valor (ex.: R$ 100k)
  - [ ] Migration: seed de `esc_capital_social` com evento `constituicao`
  - [ ] Validação: api recusa operações se capital é zero
- [ ] **PLD/COAF:**
  - [ ] Integração com API COAF (ex.: verificar tomador em lista de embargados)
  - [ ] Comunicação de operações acima de limiar (R$ 30k?)
  - [ ] Compliance router stub → implementado
- [ ] **Contrato & movimentação bancária:**
  - [ ] Integração com PSP de desembolso (ex.: Pix via API de PSP)
  - [ ] Fluxo: ativação → geração de CCB (contrato de crédito) via sistema de assinatura (ex.: A3 da Meu Brasil) → desembolso Pix → evento movimentacao_bancaria
  - [ ] Validação de contrato antes de desembolso (gate na liquidação)

**Esforço:** G (2–3 semanas) | **Criticidade:** 🔴 Bloqueadores de produção da empresa

---

### Fase 7: Modernização de Banco & Integridade (Semana 8–9)

**Objetivo:** Ledger imutável, dupla-partida, reconciliação.

- [ ] **Proteção de ledger:**
  - [ ] Adicionar constraints: `ON DELETE RESTRICT, ON UPDATE RESTRICT` em `capital_ledger`
  - [ ] Teste: tenta UPDATE/DELETE → erro banco
- [ ] **Hash-chain (opcional, avançado):**
  - [ ] Coluna `prev_hash`, `current_hash` (SHA256)
  - [ ] Trigger: calcula `current_hash` de (id, evento_tipo, valor, operacao_id, prev_hash)
  - [ ] Validação em aplicação: ao ler ledger, recomputa hashes, detecta tampering
  - [ ] Teste: simula UPDATE fraudulento → hash bate falso
- [ ] **Dupla-partida:**
  - [ ] Schema: tabelas `plano_contas` (1 = Capital Integralizado, 2 = Operações Ativas, 3 = Receita de Juros, etc.)
  - [ ] Schema: tabela `razao_contabil` (account_id, debit, credit, data, operacao_id)
  - [ ] Trigger: cada evento de `capital_ledger` gera duas linhas em razao_contabil (dupla-partida automática)
  - [ ] Daily reconciliation: ledger + razao_contabil + saldos são coerentes
- [ ] **Amortização parcial (se confirmado legalmente):**
  - [ ] Se Art. 5º permite liberar capital por pagamento parcial:
    - [ ] Schema: `operacao_parcelas` (operacao_id, numero, vencimento, valor_principal, valor_juros, status)
    - [ ] Evento: `amortizacao` em ledger com valor = principal pago
    - [ ] Lógica: capital_disponivel = capital_atual - SUM(valor_principal operacoes ativas) + SUM(amortizacoes)
- [ ] **Renegociação clara:**
  - [ ] Status renegociada → gera novo evento liquidacao_antecipada (da operação antiga) + nova operacao (status registrada)
  - [ ] Ambos sob mesmo lock: atomic, sem dupla contagem

**Esforço:** G (2 semanas) | **Criticidade:** 🟡 Recomendado para conformidade total

---

## PARTE 4: MATRIZ DE PRIORIZAÇÃO

| Fase | Semanas | Criticidade | Esforço | Pré-requisito |
|------|---------|-----------|--------|--------------|
| 0 (Fundação) | 1–2 | 🔴 | M | Nenhum |
| 1 (Tooling) | 2–3 | 🟡 | P | Fase 0 |
| 2 (Auth) | 3–4 | 🔴 | G | Fase 0 |
| 3 (Observabilidade) | 4–5 | 🟡 | G | Fase 1 |
| 4 (Testes) | 5–6 | 🔴 | G | Fase 0, 1 |
| 5 (Alembic) | 6–7 | 🟡 | M | Fase 0 |
| 6 (Compliance) | 7–8 | 🔴 | G | Fase 0, 2 |
| 7 (Banco) | 8–9 | 🟡 | G | Fase 0, 6 |

**Caminho crítico (produção):** Fase 0 → 1 → 2 → 4 → 6 (~6–8 semanas, 1 dev sênior)  
**Caminho ideal (longo prazo):** Todas as fases (~9 semanas)

---

## PARTE 5: GUIA DE DECISÃO EXECUTIVA

### Pode ir para staging com o que tem agora?
**NÃO.** Três bloqueadores:
1. Sem autenticação → qualquer um ativa operações
2. Sem entidade registradora → operações registram sem confirmação legal (inválidas)
3. Sem capital social definido → teto é desconhecido

### Pode ir para produção com Fase 0–4?
**SIM, com ressalva:** Código operável, defensável (auth + logs + testes). Mas **3 regulatórios ainda de pé** (entidade registradora, IOF, capital).

### Timeline realista com 1 dev sênior?
- **Fase 0–2:** 4 semanas → staging (code-ready)
- **Fase 3–4:** +2 semanas → produção (observável, testável)
- **Fase 6 em paralelo:** +2 semanas → conformidade legal (governo/supervisão)
- **Total:** 6–8 semanas até produção com compliance confirmado

### E se for 2 devs?
- 1 dev: Python/FastAPI (Fase 0–4)
- 1 dev: Banco/Alembic/schema (Fase 5–7 em paralelo)
- Timeline: 4–5 semanas de compressão

---

## CONCLUSÃO

O OrgCred tem **núcleo bem arquitetado** (triggers PL/pgSQL comprovados contra ataque) mas **não é operável** (sem git, sem auth, sem testes Python, sem observabilidade). 

**Investimento de 6–9 semanas** (1 dev sênior) torna-o:
- ✅ Versionável e reproduzível (git + pyproject + Alembic)
- ✅ Seguro (Supabase Auth + trilha com autor + mascaramento de PII)
- ✅ Observável (logs estruturados, métricas, alertas)
- ✅ Testável (pytest + Postgres container + triggers)
- ✅ Conforme (3 bloqueadores de negócio endereçados)

Ganho: **operação sustentável de microcrédito municipal.**

---

**Próximos passos:**
1. Executar Fase 0 (reconstituição + git)
2. Paralle apresentar "Bloqueadores de Negócio" (entidade registradora, IOF, capital) para decisão executiva
3. Commit & comece Fase 1–2

---

*Relatório gerado com análise adversarial multi-agente + pesquisa web. Equipe: @Alfa (arquitetura), @Sigma (tributário), @Delta (security), @Epsilon (análise forense).*
