# OrgCred — Mapeamento, Scorecard e Plano de Combate

> **Levantamento original: 2026-07-31.** **Remedido e reescrito em
> 2026-08-09**, após a execução das Frentes 2, 3 e 4. Todos os números
> abaixo vêm de medição direta (cobertura real de `pytest --cov`, contagem
> de statements, endpoints, tabelas e testes), não de estimativa. Onde algo
> não pôde ser medido, está dito.
>
> O documento foi reescrito em vez de remendado: as tabelas da seção 2
> descreviam o estado de julho e tinham virado ruído.

---

## 1. Retrato em uma frase

O OrgCred tem hoje **um sistema de crédito completo e provado** — capital,
operações, cobrança de ponta a ponta, contratos, fiscal, compliance e
auditoria com hash-chain — e **continua no ar sem conseguir ser usado**,
porque o teto de capital é R$ 0,00 e o login real nunca foi ativado.

O risco dominante nunca foi qualidade de código, e depois desta rodada é
menos ainda: **o sistema parece pronto, é pronto, e não é operável.** Tudo
que foi construído está em `main` e em nenhum servidor.

---

## 2. Mapa de módulos

### 2.1 Backend — 1.360 statements, 44 endpoints, 9 routers, 14 migrations

| Módulo | Arquivo | Stmt | Endpoints | Cobertura |
|---|---|---:|---:|---:|
| **Operações** | `routers/operacoes.py` | 156 | 10 | 90% |
| **Contratos e registro** | `routers/contratos.py` + `contrato.py` | 217 | 8 | 96% / 99% |
| **Compliance** | `routers/compliance.py` | 94 | 6 | **100%** |
| **Fiscal** | `routers/fiscal.py` | 92 | 5 | **100%** |
| **Cobrança** | `routers/cobranca.py` | 74 | 5 | **100%** |
| **Motor de capital** | `capital_engine.py` | 114 | — | 90% |
| **Tomadores** | `routers/tomadores.py` | 69 | 4 | 65% |
| **Capital (API)** | `routers/capital.py` | 42 | 4 | 81% |
| **Auditoria** | `routers/auditoria.py` + `core/ledger_integrity.py` | 48 | 1 | **100%** |
| **Identidade** | `routers/me.py` + `core/security.py` | 51 | 1 | 93% / **100%** |
| **Modelos** | `models.py` | 150 | — | **100%** |
| **Infra** | `main.py`, `db.py`, `config`, `db_errors`, `logging`, `metrics`, `exceptions` | 253 | — | 64% – 100% |

**14 tabelas:** `tomador`, `operacao_credito`, `parcela`, `capital_ledger`,
`operacao_evento`, `movimento_bancario`, `esc_capital_social`, `usuario`,
`contrato_emprestimo`, `registro_operacao`, `tomador_documento`,
`ocorrencia_atipicidade`, `parametro_fiscal`, `apuracao_fiscal`.

### 2.2 Invariantes no banco — o princípio "o banco decide"

18 SQLSTATEs da classe `OC`, todos com teste que falha se forem afrouxados:

| Código | Invariante | Base |
|---|---|---|
| OC001 | Teto de capital | LC 167/2019, art. 5º |
| OC002 | Gate geográfico | LC 167/2019, art. 1º |
| OC003 | Máquina de estados da operação | — |
| OC004 | **Registro CONFIRMADO** em entidade registradora | LC 167/2019, art. 5º §3º |
| OC005 | Redução de capital abaixo do comprometido | LC 167/2019, art. 5º |
| OC007 | Ledger de capital append-only | — |
| OC008 | Renegociação só por novação atômica | LC 167/2019, art. 5º |
| OC009 | Agenda de parcelas imutável | — |
| OC010 | Trilha de estado append-only | — |
| OC011 | Baixa exige lastro bancário | — |
| OC012 | Movimento bancário imutável | — |
| OC013 | Retenção de 5 anos da evidência | Lei 9.613/98, art. 10, III |
| OC014 | Ocorrência de atipicidade append-only | — |
| OC015 | Apuração fiscal exige parâmetro vigente | — |
| OC016 | Apuração fiscal imutável (retificação versiona) | — |
| OC017 | Instrumento contratual imutável | — |
| OC018 | Máquina de estados do registro | — |
| OC019 | **Identificação do tomador** com evidência arquivada | Lei 9.613/98, art. 10, I |

**Os três gates legais de ativação estão LIGADOS:** teto (OC001), registro
confirmado (OC004) e identificação (OC019). Nenhum é retroativo — todos
rodam na transição, e reativar inadimplente não revalida.

### 2.3 Frontend — 9.302 linhas, 15 rotas

| Módulo | Arquivos principais |
|---|---|
| **Dashboard** | `_authenticated/index.tsx` |
| **Operações** | `operacoes/{index,$id,nova}.tsx` + agenda, contrato, registro, diálogos |
| **Cobrança** | `_authenticated/cobranca.tsx` (aging, régua, extrato) |
| **Compliance** | `_authenticated/compliance.tsx` (identificação, registro, atipicidades) |
| **Fiscal** | `_authenticated/fiscal.tsx` (parâmetros, apurações) |
| **Tomadores** | `tomadores/{index,$id}.tsx` |
| **Capital social** | `_authenticated/capital.tsx` |
| **Auditoria** | `_authenticated/auditoria.tsx` |
| **Auth** | `login.tsx`, `definir-senha.tsx`, `auth/sync.ts` |
| **App shell** | `_authenticated.tsx`, `app-sidebar`, `command-palette` |
| **Design system** | `components/ui/*` + `index.css` (DS ORGATEC) |

### 2.4 Testes — 209 backend + 50 Vitest + 5 E2E

> Eram **52 + 32 + 1** em 2026-07-31. Cobertura backend total: **92%**.

| Suíte | Testes | Onde concentra | Onde **não** cobre |
|---|---:|---|---|
| Backend | 209 | capital (30), contratos (27), compliance (22), cobrança (21), fiscal (18), parcelas (18), aging (22) | `tomadores` (24 stmt), `main.py` (27 stmt) |
| Vitest | 50 | dicionário de erro, derivações de capital, rótulos, diálogos | telas em si, cobertas indiretamente pelos E2E |
| Playwright | 5 | ciclo completo, OC001, OC002, régua de aging, baixa com lastro | tomadores, capital social, fiscal |

Todos os E2E assertam **zero erro de console** — foi assim que apareceram o
`TooltipProvider` ausente, HTML inválido no breadcrumb e três bugs de
invalidação de query nesta rodada.

---

## 3. Scorecard por módulo

Escala: 🟢 sólido · 🟡 funcional com lacuna · 🔴 crítico/ausente

| # | Módulo | Função | Testes | Prod | Nota | Justificativa medida |
|---|---|:---:|:---:|:---:|:---:|---|
| 1 | Auditoria / hash-chain | 🟢 | 🟢 | 🟢 | **9,0** | 100% cobertura, ledger append-only por trigger, UI em duas camadas |
| 2 | Modelos / migrations | 🟢 | 🟢 | 🟢 | **9,0** | 100% cobertura, 14 migrations com ciclo up/down validado |
| 3 | Operações | 🟢 | 🟢 | 🔴 | **8,5** | 10 endpoints, ciclo completo, 90% cobertura, E2E ponta a ponta |
| 4 | Motor de capital | 🟢 | 🟢 | 🔴 | **8,5** | 90% cobertura; **dois furos do Art. 5º fechados**; teto R$ 0,00 em prod |
| 5 | **Cobrança** | 🟢 | 🟢 | 🔴 | **8,5** | Agenda imutável, novação atômica, aging com autoria, baixa com lastro; 100% |
| 6 | Identidade / Zero-Trust | 🟢 | 🟢 | 🔴 | **7,5** | `security.py` 100%, papéis aplicados; **login real nunca funcionou em prod** |
| 7 | **Contratos** | 🟢 | 🟢 | 🔴 | **7,0** | Instrumento com hash do banco, registro com protocolo, gate ligado; 96% |
| 8 | **Compliance** | 🟢 | 🟢 | 🔴 | **7,0** | Identificação, retenção, atipicidade, gate ligado; 100% |
| 9 | Design system | 🟢 | 🟡 | 🟡 | **7,0** | DS ORGATEC, 14 pares de contraste ≥4,5:1 medidos; sem regressão visual |
| 10 | App shell | 🟢 | 🟡 | 🟡 | **7,0** | Sidebar, ⌘K, temas; coberto indiretamente por 5 E2E |
| 11 | Capital (API + tela) | 🟢 | 🟡 | 🔴 | **6,5** | 81% cobertura, tela admin pronta; sem evento de constituição em prod |
| 12 | Tomadores | 🟡 | 🟡 | 🟡 | **6,5** | CRUD + gate OC002; 65% cobertura; KYC existe via Compliance, sem tela própria |
| 13 | Dashboard | 🟡 | 🟡 | 🟡 | **6,0** | KPIs e gráficos; derivações extraídas para `lib/capital.ts` e cobertas |
| 14 | Observabilidade | 🟡 | 🟡 | 🟡 | **6,0** | Prometheus + logging estruturado; `alerts.py` arquivado (era código morto) |
| 15 | **Fiscal** | 🟡 | 🟢 | 🔴 | **5,5** | Apuração no Lucro Presumido, 100% coberta; **IOF bloqueado em parecer** |
| 16 | CI/CD | 🟡 | — | 🔴 | **4,0** | CircleCI configurado, **nunca executou** — aguarda autorização do GitHub App |

**Média ponderada por criticidade: 7,3/10** (era 5,4 em julho).
Núcleo: **8,0**. Periferia regulatória (Cobrança, Contratos, Fiscal,
Compliance): **7,0** — era **0,6**.

Nenhum módulo é mais casca vazia. O que resta em cada um é decisão externa:

| Módulo | O que falta | Quem decide |
|---|---|---|
| Cobrança | nada | — |
| Contratos | escolher registradora (API) e provedor de assinatura; preencher `ORGCRED_ESC_*` | você |
| Fiscal | parecer de IOF; preencher alíquotas na tela | advogado / contador |
| Compliance | regime PLD/COAF para ligar o canal externo | advogado |

---

## 4. Achados — o que aconteceu com cada um

Os cinco achados de 2026-07-31:

1. ~~**`alerts.py` é código morto.**~~ **RESOLVIDO** (`a7b5e01`): arquivado.
   Alerta que ninguém invoca dá falsa sensação de que existe.

2. ~~**Motor de capital com a menor cobertura (58,8%).**~~ **RESOLVIDO**:
   90%. E a investigação que a cobertura forçou encontrou **dois furos do
   Art. 5º já em produção** (`bdccab5`): marcar inadimplência e renegociar
   liberavam capital de empréstimo não pago. Nenhum exigia má-fé — eram
   consequência de "comprometido" contar só `ativa`.

3. **Produção serve bundle antigo.** **ABERTO — e é o maior risco atual.**
   O Railway não faz deploy de `main`. A produção roda a versão **com os
   dois furos**, sem os gates e sem cobrança, contratos, fiscal e
   compliance.

4. ~~**1 teste E2E para 10 rotas.**~~ **MELHORADO**: 5 E2E, todos com
   asserção de zero erro de console. Nesta rodada pegaram: query de parcelas
   não invalidada, diálogo da régua que não fechava, badge de status
   ambíguo e uma limpeza de seed incompleta.

5. **Telas sem teste de componente.** **PARCIAL**: derivações extraídas para
   `lib/capital.ts` e cobertas; as telas seguem cobertas indiretamente.

### Achados novos desta rodada

6. **Regras críticas sem trilha.** `ativa → inadimplente` não deixava rastro
   em lugar nenhum — declarar alguém inadimplente acontecia sem autor.
   Fechado pela `operacao_evento` (008).

7. **Gate legal honrado na palavra.** `registro_entidade_ref` era texto
   livre: `"x"` passava pela exigência do Art. 5º §3º. Fechado pelas 012 e
   013.

8. **Três erros de Postgres que só produção teria mostrado**, todos pegos
   por teste antes de existirem: `NULL` não conflita em chave única (a
   varredura de atipicidade duplicaria a cada execução); `now()` é o
   timestamp da transação, não do statement (a trilha exibiria eventos em
   ordem arbitrária); e `GET DIAGNOSTICS` não aceita expressão.

---

## 5. Plano de combate

### 🔴 Frente 1 — Tornar operável — **ABERTA, e agora é tudo que importa**

| # | Ação | Depende de | Esforço |
|---|---|---|---|
| 1.1 | Reconectar o GitHub no Railway (`main`, builder Dockerfile) | você | 30 min |
| 1.2 | Definir senha do admin no Supabase + inserir linha em `usuario` com o mesmo UUID | você | 15 min |
| 1.3 | `insert into esc_capital_social` com o capital integralizado | **decisão dos sócios** | 5 min |
| 1.4 | Autorizar o CircleCI no GitHub e validar o primeiro run | você (OAuth) | 20 min |
| 1.5 | Preencher `ORGCRED_ESC_*` com os dados reais da ESC | você | 5 min |
| 1.6 | Contador preenche presunção e alíquotas na tela Fiscal | contador | 15 min |
| 1.7 | Smoke test em produção: login real → criar → registrar → ativar | 1.1–1.5 | 1 h |

**Sem 1.3 o sistema é uma vitrine.** Continua sendo a decisão de maior
alavancagem do projeto inteiro, e não depende de nenhuma linha de código.

**Antes do deploy, medir as duas lacunas dos gates:**

```sql
select * from v_operacoes_sem_registro_confirmado;
select * from v_tomadores_sem_identificacao;
```

Operações já ativas não são afetadas — os gates rodam na transição.

### ✅ Frente 2 — Testes — **CONCLUÍDA**

| # | Ação | Estado |
|---|---|---|
| 2.1 | Cobertura de `capital_engine.py` ≥90% | ✅ 58,8% → 90% |
| 2.2 | E2E de ciclo completo e OC002 | ✅ |
| 2.3 | Teste de componente para as telas | 🟡 parcial — derivações cobertas; telas via E2E |
| 2.4 | Decidir `alerts.py` | ✅ arquivado |

### ✅ Frente 3 — Cobrança — **CONCLUÍDA**

| # | Ação | Commit |
|---|---|---|
| 3.1 | Agenda PRICE/SAC gerada no banco, imutável (OC009) | `4d5edc4` |
| 3.2 | Novação atômica (OC008) + correção dos dois furos do Art. 5º | `bdccab5` |
| 3.3 | Aging com transição automática e trilha de autoria (OC010) | `34b5b20` |
| 3.4 | Baixa amarrada a movimento bancário (OC011/OC012) | `39d29a1` |

O ciclo fecha: a agenda define o que se cobra, o aging vê o atraso a partir
dela, e só a baixa **com lastro bancário** tira a parcela do atraso.

### 🟡 Frente 4 — Regulatório — **construível concluída**

| Módulo | Construído | Commit | Bloqueado |
|---|---|---|---|
| Compliance | Identificação com evidência (hash verificável), retenção de 5 anos (OC013), detecção de atipicidade (OC014), **gate OC019 ligado** | `ba3997b`, `2031798` | canal COAF (adaptador pronto e desligado) |
| Fiscal | Apuração IRPJ/CSLL/PIS/COFINS no Lucro Presumido, alíquotas em configuração com vigência, retificação por versão | `ff02c19` | IOF-crédito |
| Contratos | Contrato de Empréstimo ESC com hash do banco, registro com protocolo obrigatório (OC018), **gate OC004 ligado** | `3394487`, `8e5e6cc` | API da registradora, assinatura eletrônica |

Três decisões de negócio tomadas nesta rodada, todas registradas em código:

- **Lucro Presumido**, apuração trimestral, alíquotas em configuração.
- **"Contrato de Empréstimo ESC"**, não CCB — a CCB é instrumento de
  instituição financeira, e a pesquisa de registradoras mostra a CRDC
  tratando "Contratos ESC" como categoria separada.
- **Os dois gates ligados**, com a lacuna medida antes.

**Continua bloqueado em ação externa:**

| Módulo | Ação necessária | Quem |
|---|---|---|
| Contratos | Contato comercial: CRDC, SPC Grafeno (via ABRAFESC), CERC, B3 | você — formulários mapeados |
| Fiscal | Parecer jurídico-tributário sobre IOF em ESC | contador/advogado |
| Compliance | Confirmação do regime PLD/COAF para ESC | advogado |

---

## 6. Sequência recomendada

```
Frente 2 (testes)      ─── ✅ concluída
Frente 3 (cobrança)    ─── ✅ concluída
Frente 4 (construível) ─── ✅ concluída
Frente 1 (operável)    ─── 🔴 ABERTA — a única coisa que resta
```

Não há mais nada de valor a construir sem você. Todo o trabalho técnico
possível foi feito; o que resta é integralmente decisão, credencial ou
contato comercial.

## 7. Fluxo de branches e deploy

O repositório tem **uma branch só: `main`**. Ela é a default do GitHub, a
branch de trabalho e a observada pelo Railway. `master` existiu em paralelo
até 2026-08-11 e foi apagada — a coexistência das duas fez o trabalho ir para
uma enquanto o deploy olhava a outra, e isso passou semanas sem ser notado.
Não recriar.

Produção roda a versão com os dois furos do Art. 5º já corrigidos e os três
gates legais ativos (deploy de 2026-08-10). O que ainda impede **operar** não
é código — está na Frente 1.
