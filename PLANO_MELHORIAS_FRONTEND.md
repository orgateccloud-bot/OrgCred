# Plano de Melhorias — Frontend OrgCred (V2)

> Análise realizada em 2026-07-23 sobre o código real de `frontend/src/` e
> `app/routers/`. Continua a numeração de fases do projeto (F0–F4 concluídas);
> este plano cobre **F5–F9**.
>
> **Pré-requisito absoluto:** nada aqui começa antes do deploy atual subir e o
> login funcionar ponta a ponta (bundle em produção ainda é o antigo com
> placeholder; ver DECISOES_PENDENTES.md).

---

## 1. Diagnóstico rigoroso do estado atual

### 1.1 O que está bom (não mexer sem motivo)

| Área | Evidência |
|------|-----------|
| Stack moderna | React 19, Vite 8, Tailwind v4, TanStack Router/Query/Table, shadcn sobre Radix, Zustand |
| Contrato de API | Cliente Hey API gerado do OpenAPI real — zero fetch manual, tipos honestos |
| Erros de negócio | Dicionário SQLSTATE `OC*` → mensagem de UI (`api/errors.ts`), mapeado por código, não por substring |
| Qualidade | Vitest (29 testes), Playwright E2E real, Storybook, CI com job E2E completo |
| Confirmação de ação irreversível | `AtivarOperacaoDialog` mostra valor + % do teto resultante antes de confirmar |
| Auditoria em duas camadas | Narrativa humana + tabela técnica hash-chain com quebras destacadas |

### 1.2 Lacunas críticas (bloqueiam uso real)

1. **Sem navegação global.** `__root.tsx` e `_authenticated.tsx` renderizam
   `<Outlet />` puro. Não há sidebar, header, logout, nem indicação de onde o
   usuário está. Trocar de tela exige digitar URL.
2. **Detalhe de operação é stub** (`operacoes/$id.tsx` imprime só o ID).
   O link da tabela leva a uma tela vazia. Não existe `GET /operacoes/{id}`
   no backend.
3. **Sem feedback de sucesso.** Ativação de operação fecha o dialog em
   silêncio — nenhum toast, nenhuma confirmação visual.
4. **Sem fluxo de criação.** Não há como criar tomador nem operação pela UI
   (nem endpoints: `POST /operacoes` e CRUD de tomadores não existem).
5. **Dashboard mono-métrica.** Um único card. O ledger tem série temporal
   completa (hash-chain) e nada é plotado. Sem atividade recente, sem alerta
   de teto R$ 0,00 — **que é o estado real de produção hoje** (capital social
   não integralizado).

### 1.3 Lacunas importantes (degradam percepção de qualidade)

6. **Identidade visual ausente.** Tema shadcn neutro default (cinza,
   `oklch(0.205 0 0)` como primary). Nenhum traço de Aurora Blue.
   ⚠️ O design system canônico (`C:\OrgConc\design-system\MASTER.md`) não
   existe nesta máquina — os tokens usados virão da spec da persona global
   (gradiente `#0052FF → #4D7CFF → #0EA5E9`), não do arquivo canônico.
7. **Dark mode pronto no CSS, inacessível na UI** — variante `.dark` completa
   em `index.css`, nenhum toggle.
8. **Estados de carregamento pobres** — texto "Carregando…" em vez de
   skeletons; empty states sem CTA.
9. **Sem 404 nem error boundary de rota** (`defaultNotFoundComponent` /
   `errorComponent` do TanStack Router não configurados).
10. **Login sem identidade e sem recuperação de senha** — a tela
    `/definir-senha` existe, mas nada na UI leva até ela (não há botão
    "esqueci minha senha" que dispare `resetPasswordForEmail`).
11. **Tabela de operações sem paginação, filtro ou busca** — tudo
    client-side; com centenas de operações vira problema real.
12. **Bug latente na store:** `useAppStore.usuario` só é populado no submit do
    login. Após F5, a sessão Supabase persiste mas a store volta vazia —
    qualquer tela que dependa de `usuario` quebra silenciosamente.

### 1.4 Débitos menores (registrar, não urgente)

- Headers de sort sem `aria-sort` nem suporte a teclado; ícones de sort em
  texto (`▲/▼`) em vez de ícone acessível.
- `Number(valor)` sobre strings decimais de dinheiro — aceitável para
  percentuais de exibição; **nunca** usar para aritmética de negócio (que já
  vive no banco, corretamente).
- Guarda de rota é client-side (`beforeLoad`) — aceitável porque a API valida
  o JWT em toda chamada; documentar para não virar falsa sensação de
  segurança.
- Polling fixo de 20 s no dashboard; sem `staleTime` tunado.

### 1.5 Mapa backend → frontend (cobertura de módulos)

| Domínio | Backend | Frontend | Situação |
|---------|---------|----------|----------|
| Capital | `GET /capital/snapshot`, `/disponivel` | Dashboard (1 card) | Parcial |
| Operações | `GET /operacoes`, `POST /{id}/ativar` | Lista + ativação | Parcial (sem detalhe, sem criação, sem transições) |
| Auditoria | `GET /auditoria` | Tela completa | ✅ |
| Tomadores | **router vazio** | — | Inexistente |
| Capital social | tabela `esc_capital_social` sem endpoint | — | Inexistente (hoje: INSERT manual) |
| Cobrança | **router vazio** | — | Inexistente |
| Contratos | **router vazio** | — | Inexistente |
| Fiscal | **router vazio** | — | Inexistente |
| Compliance | **router vazio** | — | Inexistente |

---

## 2. Plano por fases

Ordenado por ROI: primeiro o que transforma a percepção do produto com menor
risco, depois módulos que exigem backend novo. Cada fase termina com o ritual
já validado no projeto: suite verde + lint + tsc + E2E, PR para `main`.

### F5 — App Shell & Identidade (fundação visual) 🔴→🟢

*Sem backend novo. Maior ROI do plano inteiro.*

1. **Sidebar + header** com o componente `Sidebar` oficial do shadcn
   (colapsável, atalho de teclado, persistência do estado, variante de
   ícones): Dashboard / Operações / Auditoria, rodapé com usuário + logout.
   Breadcrumbs no header derivados das rotas do TanStack Router.
2. **Tema Aurora Blue** nos tokens oklch de `index.css`:
   - `--primary` → azul Aurora (#0052FF convertido a oklch), ring/accent
     derivados; gradiente da marca reservado a momentos de destaque (login,
     CTA), nunca em texto corrido.
   - **Separação marca vs. semântica** (aprendizado validado na landing
     OrgConc): verde/âmbar/vermelho de status de operação e integridade de
     cadeia permanecem semânticos — Aurora é identidade, não substitui
     significado.
   - Validar contraste AA (4.5:1) com medição real via canvas (método já
     validado — parser RGB ingênuo lê oklch errado).
3. **Dark mode**: toggle no header + `localStorage` + `prefers-color-scheme`
   (o CSS já está pronto; falta só o mecanismo).
4. **Sistema de feedback**: `sonner` para toasts (sucesso de ativação,
   erros de rede); skeletons (`Skeleton` do shadcn) nos três loaders;
   empty states com ícone + CTA.
5. **Rotas de erro**: `defaultNotFoundComponent` (404 amigável) e
   `errorComponent` com retry no nível `_authenticated`.
6. **Login com identidade**: logo/gradiente Aurora, link "esqueci minha
   senha" → `resetPasswordForEmail` (redireciona ao `/definir-senha` já
   existente), mensagem clara quando Supabase não configurado.
7. **Fix da store**: hidratar `usuario` a partir de `getSession()` no boot
   (listener `onAuthStateChange`), não só no submit do login.

**Aceite:** navegar entre as 3 telas sem tocar na URL; logout funcional;
dark mode persistente; toast ao ativar operação; contraste AA medido.

### F6 — Dashboard de densidade forense 🔴→🟢

*Backend: zero a um endpoint novo (a série temporal já vem de `GET /auditoria`).*

1. **Grid de KPIs** (4–5 cards): Disponível, Comprometido, Total,
   Operações ativas, % utilização — com deltas vs. período anterior.
2. **Gráfico de área — evolução do saldo disponível** a partir de
   `saldo_disponivel_pos` do ledger (Recharts, tema-aware, tooltips pt-BR).
3. **Donut — composição do comprometido por tipo de operação.**
4. **Atividade recente** — últimos N eventos do ledger em narrativa humana
   (reuso do gerador de narrativa da Auditoria).
5. **Banner de estado crítico**: teto R$ 0,00 (capital não integralizado) ou
   cadeia de auditoria quebrada — visíveis sem clicar em nada.
6. Biblioteca de gráficos: **Recharts** (integra com os tokens `--chart-*` já
   presentes no CSS; componente `ChartContainer` do shadcn dá theming e
   tooltip prontos).

**Aceite:** dashboard responde "posso ativar mais crédito hoje?" em um olhar;
gráficos legíveis nos dois temas.

### F7 — Módulo Operações completo 🟡→🟢

*Backend novo: `GET /operacoes/{id}`, `POST /operacoes`, transições.*

1. **Detalhe da operação real**: dados do tomador, valores, parcelas,
   **timeline da máquina de estados** (proposta → registrada → ativa →
   liquidada/renegociada/inadimplente/cancelada) com carimbo de quem/quando
   a partir do ledger.
2. **Criação de operação** (wizard 2 passos: tomador + condições → revisão):
   validações client espelham as triggers, mas o banco continua decidindo —
   erros `OC*` renderizados no passo de revisão.
3. **Transições de estado** (registrar, liquidar, renegociar, cancelar) com
   o mesmo padrão de confirmação irreversível do Ativar.
4. **Tabela adulta**: paginação server-side, filtro por status/tipo, busca
   por tomador, coluna de ações consolidada, export CSV. `aria-sort` e
   navegação por teclado nos headers.

**Aceite:** ciclo de vida completo de uma operação sem sair da UI; E2E cobre
criação → ativação → bloqueio de teto (OC001) → liquidação.

### F8 — Módulos de domínio novos 🟡

*Backend novo substancial (implementar routers hoje vazios).*

1. **Tomadores**: CRUD + validação de município (gate geográfico OC002
   visível na UI antes de submeter); ficha do tomador com histórico de
   operações.
2. **Capital Social** (admin only, via `get_admin_user`): registrar aporte /
   redução (OC005 na UI), linha do tempo de eventos, projeção de teto.
   Elimina o INSERT manual em produção documentado em DECISOES_PENDENTES.
3. **Permissões na UI**: menu e ações sensíveis a `papel`
   (admin vs. operador) — hoje a UI ignora papel por completo.

### F9 — Cobrança, Compliance & polimento (backlog priorizável)

- **Cobrança**: agenda de parcelas, aging de inadimplência, marcação de
  recebimento.
- **Compliance**: relatório LC 167/2019 (teto, limites, município) exportável
  em PDF — insumo direto para o contador/fiscalização.
- **Auditoria+**: filtro por período/tipo, verificação visual da hash-chain
  (diff do hash esperado vs. gravado em caso de quebra).
- **Command palette** (`cmdk`, ⌘K): pular para operação/tomador/tela.
- Virtualização de tabelas se o volume justificar (`@tanstack/react-virtual`).

---

## 3. Decisões técnicas propostas (para ratificar)

| Decisão | Proposta | Alternativa descartada |
|---------|----------|------------------------|
| Gráficos | Recharts via `ChartContainer` do shadcn | visx (mais poderoso, muito mais verboso p/ 3 gráficos) |
| Toasts | sonner | Radix Toast puro (mais boilerplate) |
| Sidebar | shadcn Sidebar (blocks oficiais) | Layout artesanal (reinventar colapso/a11y) |
| Dark mode | Toggle próprio ~20 linhas (class no `<html>` + localStorage) | next-themes (dependência desenhada p/ Next) |
| Fonte | Manter Geist Variable (densidade de dados); avaliar Calistoga só em display de login | Trocar tudo p/ Inter (perda sem ganho) |
| Tipografia numérica | `font-mono` + `tabular-nums` em toda coluna monetária | — |
| Datas | Manter `toLocaleString('pt-BR')`; adotar date-fns apenas se surgir cálculo relativo | dayjs |

## 4. Riscos e dependências

1. **Deploy travado** — o Railway não está autodeployando de `main`; até
   resolver, nenhuma melhoria chega a produção (independe deste plano, já em
   tratamento).
2. **Aurora Blue sem fonte canônica** — tokens virão da spec da persona; se o
   `MASTER.md` do OrgConc reaparecer, reconciliar numa passada única.
3. **F7/F8 dependem de backend novo** — cada endpoint novo segue o princípio
   "o banco decide": validação em trigger primeiro, endpoint traduz SQLSTATE,
   e o teste roda contra Postgres real via Docker (padrão já estabelecido).
4. **Capital social R$ 0,00 em produção** — o dashboard de F6 vai expor isso
   com um banner; é feature, não bug: força a decisão pendente dos sócios
   (item 3 de DECISOES_PENDENTES.md).

## 5. Sequência recomendada

```
F5 (shell + tema + feedback)  ← começar aqui, maior ROI, zero backend
  └─ F6 (dashboard denso)     ← reaproveita tema/skeletons/toasts de F5
       └─ F7 (operações)      ← primeiro backend novo
            └─ F8 (tomadores + capital social)
                 └─ F9 (backlog priorizável a cada ciclo)
```
