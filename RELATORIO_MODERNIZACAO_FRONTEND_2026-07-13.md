# OrgCred — Modernização de Frontend/Dashboard: pesquisa de mercado e plano

**Data:** 2026-07-13 · **Método:** 5 pesquisas de mercado independentes (frameworks,
design system, data fetching, UX financeiro, testes/deploy) + auditoria do estado
atual do repositório. Companion deste documento:
[`RELATORIO_MODERNIZACAO_2026-07-12.md`](RELATORIO_MODERNIZACAO_2026-07-12.md) (backend).

---

## 1. Estado atual — isto é greenfield, não modernização de legado

Auditoria do repositório antes de pesquisar: **não existe frontend de produção**.
O backend (`app/`) é API REST/JSON pura, sem `StaticFiles`, sem templates, sem
nada servindo HTML. A única coisa frontend-adjacente no repo é
`_frontend-mockups/orgcred-painel/` — três protótipos visuais estáticos
(Vite+React+TS+Tailwind+shadcn/ui, 43 componentes, dados mockados) que criei a
pedido para explorar direções visuais, **não é código de produção** e não tem
integração real com a API.

Isso muda o enquadramento do pedido: não é "modernizar frontend antigo", é
"decidir a arquitetura de frontend do zero, informada por pesquisa de mercado
2026" — momento ideal para decidir bem, sem débito técnico a carregar.

**Referência de design não verificável:** o persona do squad (`@Beta`) cita um
design system "Aurora Blue" em uso no projeto irmão OrgConc
(`C:\OrgConc\design-system\MASTER.md` — gradiente `#0052FF → #4D7CFF → #0EA5E9`,
Calistoga + Inter + JetBrains Mono). **Esse repositório não existe nesta
máquina** — não consegui abrir nem confirmar a implementação real. Trato a
especificação textual como intenção de marca, não como padrão testado; a
pesquisa de mercado abaixo mostra que ela é compatível com tendências atuais,
mas recomendo confirmar com quem mantém o OrgConc antes de replicar 1:1.

---

## 2. Pesquisa de mercado consolidada (2026)

### 2.1 Framework / arquitetura de renderização

**Recomendação: Vite SPA client-side + TanStack Router + TanStack Query.**
Nem SSR, nem meta-framework "server-first".

- Next.js (App Router/RSC) é "server-first por padrão" — resolve SEO e
  primeiro-carregamento para tráfego público anônimo, **problemas que um
  painel interno autenticado não tem**. Exige runtime Node contínuo — infra
  extra para equipe pequena manter.
- React Router v7 (ex-Remix): os ganhos reais (tipagem forte, recursos
  modernos) só existem no *framework mode* (SSR). Usado como lib SPA pura,
  perde exatamente a vantagem que teria sobre concorrentes.
- **TanStack Router** é indicado explicitamente pelo mercado para "SPAs
  client-heavy, dashboards, painéis admin, ferramentas internas... onde a URL
  carrega estado de aplicação rico" — descrição literal do painel do OrgCred
  (filtros de operação, status, paginação). Tipagem de params/search params
  100% verificada em compile-time, roda sobre Vite nativamente.
- Astro (islands) não se aplica — otimizado para conteúdo majoritariamente
  estático, o oposto de um painel 100% interativo autenticado.
- Consenso de mercado (inclusive discussão pública da própria equipe Next.js):
  **"não adicione infraestrutura de servidor para um dashboard interno usado
  por poucas dezenas de pessoas."**
- React 19 (~48% de adoção diária) e React Compiler (1.0 desde out/2025,
  endossado oficialmente) são maduros o suficiente para adotar direto em
  projeto greenfield sem risco.

*Fontes: TanStack Start Comparison docs; The New Stack; MakerKit; PkgPulse;
discussão vercel/next.js#91475; State of React 2025-2026 (Strapi).*

### 2.2 Design system / component library

**Recomendação: manter Radix/shadcn (não migrar para Base UI agora); migrar
para Tailwind CSS v4 desde já; Storybook para catálogo de componentes.**

- Em julho/2026, **Base UI passou a ser o default do shadcn/ui**, sucedendo
  Radix (criado por ex-engenheiros do Radix agora na equipe MUI). Mas Radix
  **não está descontinuado** — shadcn afirma explicitamente que quem já roda
  em produção com Radix deve continuar. Como o protótipo já tem 43
  componentes shadcn/Radix instalados, **não vale o retrabalho de migrar**
  agora; código novo pode opcionalmente já nascer em Base UI.
- **Tailwind v4** (motor Oxide/Rust): builds 2-5x mais rápidos, HMR caindo de
  ~340ms para ~12ms, config migrando de JS para CSS (`@theme`). Radix/shadcn
  já são compatíveis sem alteração. Como o projeto está sendo criado agora
  (sem débito legado), **faz sentido nascer direto em v4** em vez de v3.4,
  evitando uma migração futura previsível.
- Tendência visual fintech 2026: o azul institucional isolado **não é mais
  hegemônico** — a vertente dominante é paleta neutra/monocromática (cinza-
  chumbo) com verde/vermelho pontuais só para sinalizar estado (Stripe/Plaid
  como referência). O "Aurora Blue" é compatível com essa tendência **se**
  usado como acento sobre uma base neutra, não como cor dominante em toda a
  UI. Tipografia monoespaçada para números financeiros é padrão confirmado
  (inspiração Bloomberg Terminal) — reforça JetBrains Mono já previsto.
  **Dark mode é tratado como modo primário em 2026, não extra opcional.**
- Storybook segue dominante (agora com testes via Vitest integrados);
  alternativas leves (Ladle) só valem para prototipagem descartável, não para
  um produto fintech que precisa de rastreabilidade/QA.

*Fontes: shadcn/ui changelog 2026-07 (Base UI default); shadcn Studio;
DEV.to (Tailwind v4 migration guide); byteiota; 925 Studios (SaaS dashboard
trends); inspoai.io; PkgPulse (Storybook vs Ladle vs Histoire).*

### 2.3 Integração com a API FastAPI (data fetching)

**Recomendação: Hey API (`@hey-api/openapi-ts`) gerando tipos+cliente do
`/openapi.json` + TanStack Query v5 (server state) + Zustand (client state)
+ Supabase JS SDK com refresh automático de sessão.**

- Gerar cliente TypeScript do schema OpenAPI que o FastAPI já expõe
  nativamente evita o risco real de manter tipos manuais sincronizados à mão
  a cada mudança de schema (inclusive os códigos SQLSTATE customizados
  OC001-OC007, que já mudaram de versão em versão no backend). **Hey API**
  tem plugin oficial para gerar `queryOptions()` do TanStack Query
  diretamente tipados por endpoint.
- TanStack Query v5 segue como padrão de mercado incontestado para cache de
  estado assíncrono — não há substituto relevante em 2026.
- Zustand é a recomendação para estado de UI (usuário autenticado, tema,
  filtros) — ~1.2KB, zero boilerplate, adequado ao escopo pequeno do painel;
  Redux Toolkit é overkill para 2 papéis e uma equipe minúscula.
- **Tratamento de erro estruturado**: o backend já evita parsing de string
  (`{"detail": "...", "codigo": "OC001"}`); o frontend deve replicar a mesma
  disciplina — lançar uma classe `ApiError { codigo, detail }` tipada na
  `queryFn`, e mapear `codigo → mensagem de UI` por **dicionário de chave
  exata**, nunca por `.includes()` no texto (evitar reintroduzir no cliente o
  mesmo anti-padrão que a Fase 0 do backend já corrigiu no servidor).
- Supabase Auth no browser: SDK JS renova o access token automaticamente em
  background; anexar via `Authorization: Bearer <token>` centralizado no
  cliente gerado; interceptar 401 do FastAPI para forçar
  `refreshSession()` antes de repetir a requisição. Usar verificação via
  JWKS no FastAPI (já implementado — ver `app/core/security.py`) evita
  mismatch de chave.

*Fontes: DEV.to (comparativo de codegen OpenAPI); Kubb docs; TanStack Query
docs (does this replace Redux?); DEV.to (state management 2026); Zustand
docs; Supabase Auth/JWT docs.*

### 2.4 UX para dashboard financeiro/compliance

**Recomendação prática, específica para o caso do OrgCred:**

1. **Tabela client-side simples** (TanStack Table headless, sort/filter
   local) **sem virtualização** — o volume real (dezenas de operações, não
   milhares) não justifica TanStack Virtual; virtualização só compensa a
   partir de ~1.000+ linhas.
2. **Polling de 15-30s**, não WebSocket — o consenso de mercado é que
   WebSocket paga um custo de gerenciamento de conexão sem necessidade em
   cenários de baixo volume (poucas operações por hora). SSE é a opção
   intermediária se quiser algo mais "vivo" sem a complexidade bidirecional.
3. **Confirmação explícita para ações irreversíveis** (ativar operação de
   crédito compromete o teto legal): modal mostrando valor, impacto no teto
   resultante (%), afirmação textual clara de irreversibilidade, botão
   visualmente distinto (peso/cor) do padrão, desabilitado durante o submit
   para evitar duplo clique/duplicação.
4. **Acessibilidade**: contraste 4.5:1 (texto normal) / 3:1 (texto
   grande/elementos não-textuais) por WCAG AA; **cor nunca é o único
   veículo de informação** — status sempre com ícone + rótulo texto junto
   da cor (ex: ✓ Ativa, ⚠ Inadimplente, ✕ Cancelada), não só a bolinha
   colorida usada nos protótipos atuais.
5. **Audit trail em duas camadas**: visão "história legível" em linguagem
   natural ("Operação X ativada por Y em Z, comprometeu R$ N") para
   auditores/reguladores não-técnicos, e visão técnica expansível com hash
   de cada elo + indicador de integridade da cadeia (verificado/quebrado)
   para operadores técnicos e QA — essa segunda visão já existe em espírito
   no Modelo 3 (Console Técnico) dos protótipos, mas falta a primeira.

*Fontes: Setproduct (data table UI); TanStack Table/Virtual docs; FlowVerify;
getstream.io; LogRocket (confirmation dialogs); Ramotion (fintech UX);
WebAIM; W3C WCAG 2.1; aesirx.io/blocsys.com (audit trail cryptographic
proof); Velt.*

### 2.5 Testes, CI/CD e deploy

**Recomendação: Vitest + Testing Library (unit/componente); Playwright
(E2E); sem ferramenta de regressão visual paga por ora; deploy como serviço
único no Railway (FastAPI servindo o build estático do Vite).**

- **Vitest** é o padrão para projetos Vite novos em 2026 (ESM nativo,
  zero-config TS, watch mode até 8-28x mais rápido que Jest). Jest só se
  justifica em bases CJS legadas — não é o caso aqui.
- **Playwright** domina o mercado (~45% adoção vs 14,4% Cypress, estagnado;
  ~30M downloads semanais vs 6,5M) — suporte nativo a WebKit (Cypress não
  tem), menor custo de CI (~40-60% menos RAM/tempo). Recomendado para os
  fluxos críticos: login, ativar operação, bloqueio por teto de capital.
- **Chromatic/Percy: não investir agora.** Para um time pequeno sem
  Storybook consolidado ainda e sem alta rotatividade visual, o
  `toHaveScreenshot()` nativo do Playwright já é suficiente — reavaliar se
  o time crescer ou o design system amadurecer.
- **Deploy no Railway**: não existe hospedagem estática dedicada tipo
  Vercel/Netlify no Railway — a prática documentada é o **FastAPI servir o
  `dist/` do Vite** via `StaticFiles` + fallback de rota para `index.html`
  (suporta SPA routing), tudo num único serviço/container. Mais simples,
  sem CORS a configurar, sem domínio extra — adequado ao estágio atual
  (painel interno, equipe pequena, já em Railway). Migrar para
  Vercel/Cloudflare Pages só faria sentido se o painel virasse produto
  público com necessidade de CDN edge global — não é o caso.
- **CI**: GitHub Actions simples (lint → vitest → playwright → build) por
  PR, mesma ferramenta já usada no backend — sem necessidade de
  Turborepo/Nx a menos que frontend e backend virem monorepo único.

*Fontes: sitepoint (Vitest vs Jest); PkgPulse; tech-insider (Cypress vs
Playwright); getautonoma.com; Delta-QA (Chromatic vs Percy); Railway deploy
templates; fastapi/fastapi#5134; WarpBuild (GitHub Actions monorepo 2026).*

---

## 3. Stack final recomendada

| Camada | Escolha | Já prototipado? |
|---|---|---|
| Build/dev server | Vite | ✅ sim |
| Framework UI | React 19 + React Compiler | ✅ sim (React, falta ativar Compiler) |
| Linguagem | TypeScript | ✅ sim |
| Roteamento | **TanStack Router** | ❌ não — protótipos usam `useState` puro |
| Estilo | Tailwind CSS **v4** (migrar de v3.4) | ⚠️ parcial — protótipo está em v3.4 |
| Componentes | shadcn/ui sobre Radix (manter) | ✅ sim, 43 componentes |
| Server state | **TanStack Query v5** | ❌ não |
| Cliente API tipado | **Hey API** a partir do `/openapi.json` | ❌ não |
| Client state (UI) | **Zustand** | ❌ não |
| Autenticação | Supabase JS SDK + refresh automático | ❌ não (protótipos usam usuário mockado) |
| Tabelas | TanStack Table (headless, sem virtualização) | ❌ não |
| Testes unit/componente | Vitest + Testing Library | ❌ não |
| Testes E2E | Playwright | ❌ não |
| Catálogo de componentes | Storybook | ❌ não |
| CI | GitHub Actions | ❌ não (frontend não tem workflow ainda) |
| Deploy | Railway, FastAPI servindo `dist/` estático | ❌ não |

---

## 4. Plano faseado

### Fase F0 — Fundação do projeto real (separar de `_frontend-mockups/`)
- Criar `frontend/` na raiz do repo (não mais em pasta descartável) com a
  stack final: Vite + React 19 + TS + Tailwind v4 + shadcn/ui (Radix).
- Configurar TanStack Router com rotas tipadas: `/login`, `/`  (dashboard),
  `/operacoes`, `/operacoes/:id`, `/auditoria`.
- `.gitignore`, ESLint (ou manter oxlint, já usado no bundler), Prettier
  alinhado ao `ruff format` do backend em espírito (mesma disciplina).
- Decisão a confirmar com o time: single-repo (frontend/ dentro de
  OrgCredV1) vs repositório separado — recomendo single-repo dado o
  tamanho da equipe, revisitar só se o CI ficar lento.

### Fase F1 — Integração com a API
- Gerar cliente Hey API a partir de `http://localhost:8000/openapi.json`
  (rodando localmente contra o backend já funcional).
- Configurar TanStack Query com o cliente gerado; implementar o dicionário
  `SQLSTATE → mensagem de UI` (OC001-OC007, ver `app/core/exceptions.py`
  como fonte de verdade).
- Integrar Supabase JS SDK: tela de login, guarda de rota autenticada
  (TanStack Router `beforeLoad`), interceptor de 401 → refresh → retry.
- Zustand store mínima: usuário autenticado, papel, tema (dark/light).

### Fase F2 — Telas core (portar e evoluir os 3 protótipos)
- Dashboard: capital disponível/comprometido/total, barra de utilização do
  teto — reaproveitar layout do Modelo 1 (Torre de Controle) como base,
  mas com paleta neutra + acento Aurora Blue (não azul dominante), dark
  mode como padrão.
- Lista de operações: TanStack Table real (dados da API, não mock), status
  sempre com ícone+texto+cor.
- Fluxo de ativação: modal de confirmação explícito (valor, % do teto
  resultante, aviso de irreversibilidade), chamada real ao
  `POST /operacoes/{id}/ativar`, tratamento de erro via dicionário SQLSTATE.
- Auditoria: view em duas camadas (história legível + hash-chain técnico)
  — combinar o tom do Modelo 2 (Compliance) com o rigor técnico do Modelo 3.
- Polling de 15-30s no dashboard (TanStack Query `refetchInterval`).

### Fase F3 — Qualidade
- Vitest + Testing Library: cobertura dos componentes de tela e do
  dicionário de erro SQLSTATE.
- Playwright: fluxo login → ver dashboard → ativar operação → ver bloqueio
  por teto (cenário espelhando o `test_capital_engine.py` do backend).
- Storybook: catálogo dos componentes shadcn customizados + variantes de
  status/badge.
- GitHub Actions: `lint → vitest → playwright → build`, paralelo ao
  workflow já existente do backend.

### Fase F4 — Deploy
- Multi-stage Dockerfile do frontend (build Vite) + `StaticFiles` no
  FastAPI servindo `dist/` com fallback SPA — um único serviço Railway.
- Ou, se preferirem isolar deploys, serviço Railway separado (template
  "Deploy Vite + React" já existe pronto) — decisão de infraestrutura, não
  bloqueador técnico.

---

## 5. Riscos e decisões pendentes

1. **Aurora Blue não confirmado**: a especificação existe só em texto no
   persona do squad; sem acesso ao repositório OrgConc, não posso confirmar
   a implementação real (tokens de cor exatos, uso de gradiente em que
   componentes). Recomendo pedir para quem mantém o OrgConc exportar os
   tokens reais (ex: arquivo de CSS variables) antes da Fase F2.
2. **React Compiler**: maduro para greenfield segundo a pesquisa, mas ainda
   não testado neste projeto especificamente — validar com o bundle real
   antes de assumir zero atrito.
3. **Hey API vs escrever cliente manual**: decisão de baixo risco e
   reversível — se o gerador causar fricção inesperada, o fallback é
   `openapi-typescript` (mais leve, só tipos) sem custo de retrabalho
   grande.
4. **Single-repo vs multi-repo**: não pesquisado em profundidade nesta
   rodada — decisão de organização de equipe, não de tecnologia.
5. Nenhuma das cinco pesquisas encontrou dados quantitativos comparáveis
   para todas as afirmações (ex: tração de Ark UI/React Aria, alvo de
   toque WCAG exato, custo real de hospedar frontend separado no Railway)
   — pontos sinalizados explicitamente nas seções acima como não
   verificados, não devem ser tratados como fato consolidado sem
   confirmação adicional.
