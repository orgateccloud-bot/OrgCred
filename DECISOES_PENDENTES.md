# OrgCred — Decisões de negócio pendentes (Fase 6)

**Data original:** 2026-07-12 · **Revisado em:** 2026-07-13 · Bloqueadores
identificados na revisão de arquitetura (ver
`RELATORIO_MODERNIZACAO_2026-07-12.md`) que **não podem ser resolvidos por
implementação técnica** — exigem decisão do dono do negócio, parecer
jurídico-tributário ou negociação comercial. Este documento existe para que
a próxima sessão de trabalho comece direto na decisão, não na investigação.

**Status da revisão de 2026-07-13:** os 5 bloqueadores abaixo continuam
**todos em aberto** — nenhum foi resolvido nesta janela, porque todos
dependem de ação externa (negociação comercial, parecer jurídico ou decisão
dos sócios) que não é algo que se resolve escrevendo código. O que avançou
foi o lastro técnico: a base do backend (Fases 0–7 da modernização, CI/CD,
autenticação Zero-Trust) está agora 100% estável e com o pipeline de CI
verde — quando cada decisão abaixo sair, a implementação correspondente
pode começar imediatamente, sem retrabalho técnico pendente na frente.

**Status do deploy — 2026-07-17:** o sistema está **no ar em produção**:
`https://orgcred-api-production.up.railway.app` (Railway, projeto
"OrgCred" — Postgres + serviço `orgcred-api`, build via Dockerfile a
partir do GitHub, CI verde nos dois workflows — backend e frontend).
Confirmado via curl real: `/` serve o painel (SPA), `/health` e
`/health/ready` respondem, rotas de negócio exigem autenticação (401
sem token). Isso é 100% lastro técnico — **nenhum dos 5 bloqueadores
abaixo foi resolvido pelo deploy**; na verdade, ir ao ar tornou dois deles
concretos, não só teóricos:

- **Item 3 (capital social inicial)**: em produção o teto ainda é
  R$ 0,00 — não existe nenhum evento `constituicao` no banco de produção.
  O sistema está no ar, mas **nenhuma operação de crédito pode ser
  ativada** até essa decisão sair e o insert de constituição ser feito.
- **Login real ainda não funciona em produção** — gap técnico-operacional
  (não é um dos 5 itens de negócio abaixo, mas bloqueia uso real do
  painel): não existe projeto Supabase real ainda, então
  `ORGCRED_SUPABASE_JWT_SECRET` em produção é um valor aleatório gerado
  nesta sessão só para a aplicação não subir com a secret de
  desenvolvimento pública. Quando o projeto Supabase existir, essa
  secret precisa ser trocada pela real (Project Settings → API → JWT
  Secret) e as variáveis `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY`
  precisam ser configuradas no build do frontend. Também é necessário
  criar pelo menos um registro em `usuario` (papel `admin` ou
  `operador`) com o mesmo UUID do usuário criado no Supabase Auth —
  sem isso a API responde `PERMISSAO_NEGADA` mesmo com login válido.

---

## 1. Entidade registradora (bloqueia `app/routers/contratos.py`)

**O que é:** o Art. 5º §3º da LC 167/2019 exige que operações de crédito de
uma ESC sejam registradas em entidade apodada pelo Banco Central antes da
ativação. O sistema já **enforcement** isso — `operacao_credito.registro_entidade_ref`
é obrigatório para ativar (SQLSTATE OC004) — mas hoje esse campo é
preenchido manualmente, sem integração real.

**Candidatas pesquisadas em detalhe (2026-07-12) — ver
[`PESQUISA_ENTIDADE_REGISTRADORA.md`](PESQUISA_ENTIDADE_REGISTRADORA.md)
para o levantamento completo com fontes:**

- **CRDC e SPC Grafeno — empatam como recomendação líder** após pesquisa
  aprofundada (2026-07-12), com tipos de evidência diferentes:
  - CRDC: **"Contratos ESC" é categoria de ativo nomeada nativamente no
    próprio sistema de registro** — a evidência de produto mais direta de
    todas as 6 candidatas pesquisadas. Tem integração automática de saldo
    devedor (potencialmente relevante para a decisão pendente sobre
    amortização parcial, ver seção "O que NÃO está bloqueado" abaixo) e
    parceria com a Stand (software especializado em ESC). Ponto de
    atenção: a B3 tentou comprar 60% da CRDC, mas o CADE recomendou
    reprovar a operação — CRDC segue independente (controlada pela ACSP),
    decisão final do tribunal do CADE ainda pendente. Tarifário não
    encontrado publicamente (site bloqueou acesso em toda tentativa).
  - SPC Grafeno: **parceria comercial oficial e nomeada com a ABRAFESC**
    (associação nacional de ESC), com desconto que escala com adoção
    setorial. Processa ~50% de todas as CCBs registradas no Brasil e
    oferece emissão sem mensalidade. Adesão via e-mail direto
    (`comercial@abrafesc.com.br`). Fragilidade técnica: API de Crédito da
    Grafeno **ainda não suporta webhooks** — exigiria polling para o
    callback de `registro_entidade_ref`.
- **CERC e B3 Registradora — finalistas fortes**, cada uma com um perfil
  de trade-off diferente:
  - CERC: onboarding mais leve, prazo de integração estimado menor
    (3–6 semanas), vertical "Factoring & ESC" nomeada no site, e a
    candidata mais consistentemente citada em toda a pesquisa (emparelhada
    tanto com CRDC quanto com B3, dependendo da fonte).
  - B3: pedigree histórico mais forte (**processou as primeiras operações
    de ESC do mercado, em setembro de 2019**), apetite comercial ativo e
    declarado por fintechs de crédito pequenas/médias, governança
    institucional mais robusta — mas processo de credenciamento
    formalmente mais pesado (comitê de risco, auditoria pré-operacional).
- **Núclea (ex-CIP)** — pesquisada em profundidade em rodada dedicada:
  tecnicamente capaz (registra CCB e credencia explicitamente factoring
  companies, segmento próximo em porte à ESC) mas é a única das 6
  candidatas pesquisadas sem nenhum sinal público — direto ou indireto —
  de atender especificamente o segmento ESC; documentação técnica
  detalhada está bloqueada publicamente (erro 403 em todos os manuais).
  Não descartada, mas não é aposta natural sem contato comercial.
- **TAG** — **provavelmente não serve**: produto é especificamente
  recebíveis de arranjo de pagamento (cartão), não registro de CCB/operação
  de crédito. Recomenda-se remover das candidatas salvo confirmação
  comercial em contrário.

**Decisão necessária:** conversa comercial em paralelo com CRDC, SPC
Grafeno (via ABRAFESC), CERC e B3 (tarifário oficial, prazo real de
integração, requisito de porte mínimo/garantia — e, especificamente, para
a CRDC o status da disputa antitruste com a B3, para a SPC Grafeno o
roadmap de suporte a webhook) antes de fechar — a pesquisa web reduziu de
6 candidatas a 4 finalistas com sinal de adequação confirmado, mas não
substitui contato comercial direto.

**Atualização 2026-07-13 — contato comercial ainda NÃO foi feito:**
localizei e preenchi (sem enviar) os formulários de contato da CRDC
("Solicitar Proposta" em `crdc.com.br/solicitar-proposta`) e da SPC
Grafeno ("Contato" em `spcgrafeno.com.br/contato`), mapeando exatamente os
campos exigidos por cada um (CNPJ, empresa, responsável, telefone/e-mail,
e para a SPC Grafeno também um dropdown de "setor" sem opção "ESC" — mais
próximo é "SCD" ou "Outro"). Explicitamente **não enviei** nenhum dos
dois — essa é uma ação comercial que representa a ORGATEC perante
terceiros e requer os dados reais da empresa (CNPJ, nome do responsável,
contato), que não tenho e não devo inventar. Para retomar: forneça esses
dados e confirme o envio; os campos e o texto sugerido já estão mapeados,
não é preciso redescobrir os formulários.

**Depois da decisão:** implementar `app/routers/contratos.py` — geração de
CCB, chamada à API da entidade, callback de confirmação que preenche
`registro_entidade_ref`.

---

## 2. Regime de IOF (bloqueia metade de `app/routers/fiscal.py`)

**O que é:** não está determinado se IOF-crédito incide sobre operações de
uma ESC e, se incidir, quem arca com o custo (a ESC ou o tomador).

**Decisão necessária:** parecer jurídico-tributário confirmando (a) se há
incidência, (b) a alíquota aplicável, (c) o responsável pelo recolhimento.

**Depois da decisão:** migration nova adicionando `iof_valor`/`iof_pago` em
`operacao_credito`; gate de ativação (SQLSTATE novo, ex. OC006) se IOF for
devido e não pago.

---

## 3. Capital social inicial — 🟡 AGUARDANDO VALOR (bloqueia o teto operacional real)

**O que é:** sem o valor do capital social integralizado, o teto legal do
Art. 5º (total de operações ativas ≤ capital social) é desconhecido — o
sistema está tecnicamente pronto (trigger + advisory lock testados), mas
não há `esc_capital_social` com evento `constituicao` em produção.

**Decisão necessária:** valor definido pelos sócios, confirmado como
efetivamente integralizado (não apenas subscrito).

**Depois da decisão:** `insert into esc_capital_social (valor, tipo_evento)
values (<valor>, 'constituicao')` — uma linha, sem mudança de código.

**Atualização 2026-07-17:** o sistema já está no ar em produção (ver
"Status do deploy" no topo deste documento) rodando contra o Postgres
real do Railway — essa decisão agora bloqueia uso real, não só
implantação. O insert acima pode ser feito a qualquer momento assim que
o valor for definido, direto no Postgres de produção.

**Atualização 2026-07-18:** confirmado com o usuário — assim que o valor
sair, o insert de constituição deve ser aplicado imediatamente no
Postgres de produção (Railway, projeto "OrgCred"), sem esperar por outra
sessão de trabalho. Até lá, o teto em produção permanece R$ 0,00 e
nenhuma operação pode ser ativada.

---

## 4. Divisão societária entre os sócios

Registrada como pendência no `REVISAO_2026-07-11.md`, sem insistência — os
sócios decidiram tratar depois. Não bloqueia nenhum caminho técnico
atual; relevante só se/quando o sistema precisar refletir participação
societária (ex. relatórios de distribuição de lucro).

---

## 5. Status regulatório de PLD/COAF para ESC

**O que é:** não confirmado se a ESC está sujeita a comunicação COAF como
as demais instituições financeiras, nem sob qual regime específico.

**Decisão necessária:** confirmação jurídica de que órgão supervisiona ESC
para fins de PLD/FT e quais comunicações são obrigatórias.

**Depois da decisão:** implementar `app/routers/compliance.py` — hoje é
stub. Nota: a propagação de `usuario_id` para a trilha de auditoria (quem
executou cada ativação) **já foi implementada** (migration 004,
independente desta decisão) — o que falta é especificamente a integração
com comunicações regulatórias externas.

**Atualização 2026-07-13:** essa propagação foi ainda **corrigida e
endurecida**. Um bug real foi encontrado em produção (via CI, não em
teste manual): a implementação original usava `SET LOCAL app.user_id =
:usuario_id` com bind parameter — o Postgres não aceita parâmetro bind
dentro do comando `SET`, só literais. Isso funcionava por acidente com o
driver antigo (psycopg2) mas quebrou com a migração para psycopg3 (SQLSTATE
de sintaxe, `syntax error at or near "$1"`). Corrigido trocando para
`select set_config('app.user_id', :usuario_id, true)` (função regular,
aceita bind parameter normalmente). Validado com 44/44 testes contra
Postgres 16 real e CI verde. Ou seja: a trilha de auditoria com autor não
só está implementada, está agora comprovadamente funcional — não é mais
um risco técnico latente por trás desta decisão de compliance.

---

## O que NÃO está bloqueado (só não implementado ainda)

Para não confundir bloqueio de decisão com trabalho técnico pendente:

- **Renegociação sem dupla contagem** (`app/routers/cobranca.py`): precisa
  de uma regra explícita de novação atômica, mas é decisão de design técnico,
  não de negócio externo — pode ser feita a qualquer momento.
- **Amortização parcial libera capital**: interpretação conservadora atual
  (usa `valor_principal` integral até liquidação) é juridicamente segura;
  mudar para saldo devedor é decisão de interpretação contábil-jurídica
  interna, não depende de terceiros.
- **Onboarding/KYC de tomadores** (`app/routers/tomadores.py`): escopo
  técnico normal, sem bloqueador externo identificado.
