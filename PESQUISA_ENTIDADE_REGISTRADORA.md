# Pesquisa: entidade registradora para o OrgCred

**Data:** 2026-07-12 · **Contexto:** bloqueador #1 de `DECISOES_PENDENTES.md` —
qual entidade registradora usar para cumprir o Art. 5º §3º da LC 167/2019.
Este documento reúne o levantamento feito para embasar a decisão; **não
substitui** confirmação comercial direta com a entidade escolhida
(tarifário atual, SLA contratual, prazo de integração real).

---

## Resumo executivo

**CERC e B3 Registradora são as duas finalistas reais** — ambas com
histórico documentado e específico de atendimento a ESC, cada uma com um
perfil de trade-off diferente: CERC parece mais ágil para integração de
uma equipe pequena (prazo estimado 3–6 semanas, onboarding mais simples);
B3 tem o pedigree histórico mais forte no segmento (**processou os
primeiros registros de operação de ESC do mercado, em setembro de 2019**,
logo após a LC 167/2019 entrar em vigor) e está **atualmente priorizando
fintechs de crédito e bancos pequenos/médios** como estratégia declarada
— mas seu processo de credenciamento institucional (comitê de risco,
auditoria pré-operacional, possível depósito de garantia) é
estruturalmente mais pesado que o de uma fintech de infraestrutura como a
CERC. **TAG não é adequada**: seu produto é especificamente recebíveis de
cartão (arranjo de pagamento), não registro de operações de crédito/CCB.
**Núclea é tecnicamente capaz** mas não tem nenhum caso de uso ESC
documentado publicamente — precisa de confirmação direta se ela atende
esse segmento na prática.

**Recomendação prática:** abrir conversa comercial com as duas (CERC e B3)
em paralelo — a decisão final depende de dados que só aparecem em
negociação direta (tarifário real, tempo de homologação, exigência de
garantia), não de pesquisa web.

---

## As 5 registradoras autorizadas pelo Banco Central (panorama)

Segundo levantamento de mercado (Destrava.ai, 2022, com dados ainda
consistentes), as entidades autorizadas para registro de recebíveis de
arranjos de pagamento são: **CRDC**, **CIP/Núclea**, **CERC**, **TAG
Infraestrutura** e **B3 Registradora**. Uma fonte adicional (Antecipa
Fácil, 2026) lista **B3, CERC, Núclea e SPC Grafeno** como as 4 autorizadas
para registro de duplicatas/títulos — SPC Grafeno não apareceu na busca
inicial e pode valer investigação futura, mas não é objeto desta
comparação.

Importante: essas entidades nasceram para registrar **recebíveis de cartão
de crédito/débito** (Resolução CMN 4.734, Circular BACEN 3.952). O
registro de operações de ESC (empréstimo, financiamento, desconto de
título — não recebíveis de arranjo de pagamento) é um uso da mesma base
legal (Art. 28, Lei 12.810/2013), mas nem toda registradora expandiu seu
produto para cobrir isso.

---

## Comparação detalhada

| Critério | **CERC** | **B3 Registradora** | **Núclea (ex-CIP)** | **TAG Infraestrutura** |
|---|---|---|---|---|
| **Fundação** | 2015 | B3 (bolsa) é histórica; registradora de recebíveis é vertical mais recente | CIP existe há 20+ anos; rebatizada Núclea | 2018/2020 |
| **Controlador** | Independente (fintech de infra) | B3 S.A. — bolsa de valores, maior instituição de mercado de capitais do Brasil | Consórcio de instituições financeiras | Grupo Stone Co. |
| **Produto para CCB/empréstimo/ESC** | ✅ Categoria explícita "Financeiros" (CCBs, contrato de crédito, mútuos, títulos bancários); site lista "Factoring & ESC" como solução nomeada | ✅ Produto de registro de CCB via plataforma "Balcão" (2 variantes: CCB-NoMe e CCB-Plataforma Balcão) — registro, alteração, consulta, conciliação, gestão de parcelas | ⚠️ Tem "Registro de Ativos" e "SRCC" (crédito consignado) — sem confirmação de produto ESC/CCB genérico | ❌ Não — produto é especificamente recebíveis de arranjo de pagamento (cartão) |
| **Histórico específico com ESC** | Citada por fornecedores terceiros como parceira padrão | ✅ **Recebeu os primeiros registros de operação de ESC do mercado, em setembro de 2019** — meses após a LC 167/2019 entrar em vigor (abril/2019) | Nenhum caso de uso ESC encontrado | Nenhum caso de uso ESC encontrado |
| **Estratégia comercial atual** | Foco declarado em fintechs de crédito e digitalização de recebíveis | Superintendente da B3 declarou publicamente que **o primeiro esforço da área é atuar junto a fintechs de crédito e bancos pequenos e médios** — sinaliza apetite ativo por clientes do porte do OrgCred | Não encontrado | Foco em recebíveis de cartão (Stone/adquirentes) |
| **Uso documentado por terceiros em software ESC** | ✅ Citada por 3 fornecedores independentes (APPESC/Decisão Sistemas, Fomenti, Stand) como padrão do segmento, ao lado da B3 | ✅ Mesma citação — aparece emparelhada com CERC nos mesmos 3 fornecedores | ❌ Nenhum caso de uso ESC encontrado em fontes independentes | ❌ Nenhum caso de uso ESC encontrado em fontes independentes |
| **Certificações / governança** | ISO 27001, 27017, 27018 | Instituição sob regulação direta e intensa do BACEN/CVM como bolsa; "alto padrão de governança institucional" segundo comparativo de mercado — acima do padrão de uma fintech | ISO 27001, 22301 | Não encontrado nesta pesquisa |
| **Clientes conhecidos** | PagSeguro, Mercado Pago, MagaluPay, iFood, Vindi | Ecossistema de participantes de mercado de capitais + fintechs de crédito/bancos pequenos (estratégia recente) | Cielo, Rede, Getnet, SafraPay | Stone Co., PagarMe, Yapay, Rappi |
| **Integração técnica** | API REST documentada (Apiary/CERC Integração Agente de Registro); ERP com certificado digital envia título via API padronizada | REST + Swagger/OpenAPI, 54 APIs no portal "Balcão", ambiente de sandbox/certificação gratuito — **mas acesso é exclusivamente B2B**, requer credenciais próprias (CAU) | API, arquivo ou portal, "conforme necessidade de cada entidade" — sem doc técnica pública equivalente | Documentação técnica existe mas focada em recebíveis de cartão |
| **Processo de onboarding** | Adesão contratual mais leve (perfil fintech) | **Processo formal de credenciamento**: análise reputacional/jurídica/econômica + auditoria pré-operacional pela BSM + aprovação do Comitê Técnico de Risco de Crédito (CTRC) + possível depósito de garantia — estruturalmente mais pesado | Não detalhado nesta pesquisa | Não aplicável |
| **Prazo de integração estimado** | 3 a 6 semanas (fonte: mercado/Celcoin, não confirmado diretamente) | Não encontrado prazo específico — processo de credenciamento formal sugere ciclo mais longo que o da CERC | Não encontrado | Não aplicável |
| **Custo por título registrado** | R$ 0,30 a R$ 1,50/título + R$ 0,15–0,80/evento — faixa de mercado, **não confirmada oficialmente** | R$ 0,80 a R$ 1,50/título + R$ 0,30–0,80/evento, com tabela negociada acima de 50 mil títulos/mês — faixa de mercado similar à CERC, **também não confirmada oficialmente na página de tarifas pública** | Não encontrado nesta pesquisa | Não aplicável |
| **Posição de mercado para ESC** | Registradora de referência do segmento, ágil para integração pequena | **Pioneira histórica do segmento** + prioridade comercial declarada para fintechs pequenas, mas com processo de admissão institucional mais formal | Grande player geral, sem evidência de foco em ESC | Fora do escopo — produto não serve o caso de uso |

---

## Por que TAG provavelmente não serve

A TAG foi criada especificamente sob a Resolução 4.734/CMN e Circular
3.952/BACEN, que regulam **recebíveis de arranjos de pagamento** — ou seja,
o direito de receber de uma venda feita com cartão. O que o OrgCred precisa
registrar é uma **operação de crédito** (empréstimo/financiamento/desconto
de título, formalizada como CCB) — uma categoria de ativo diferente, ainda
que ambas caiam sob o guarda-chuva legal do Art. 28 da Lei 12.810/2013.
Nenhuma fonte consultada (incluindo o site institucional da própria TAG)
menciona um produto de registro de CCB ou operação de crédito — só
recebíveis de cartão.

**Conclusão:** TAG deveria ser removida das candidatas, a menos que uma
confirmação comercial direta revele um produto não descoberto nesta
pesquisa.

## Por que Núclea é incerta

Núclea (ex-CIP) é claramente capaz tecnicamente — é descrita como "a maior
registradora de ativos financeiros do mercado" e tem produtos como
"Registro de Ativos" e "SRCC" (Serviço de Registro de Crédito Consignado).
O problema não é capacidade, é **evidência de adequação ao caso de uso**:
nenhuma fonte independente (fornecedores de software ESC, artigos
setoriais) cita Núclea como opção para esse segmento — só CERC e B3
aparecem nesse contexto específico. Isso pode significar (a) Núclea
simplesmente não é usada por ESCs pequenas na prática, (b) é usada mas sem
cobertura editorial, ou (c) atende via um produto genérico que não foi
encontrado nesta pesquisa. **Vale uma pergunta direta ao suporte comercial
da Núclea** antes de descartá-la — mas não é a aposta natural sem essa
confirmação.

## CERC vs. B3: os dois finalistas, lado a lado

Ambas passam no teste básico (produto para CCB/ESC existe, uso documentado
por terceiros, API REST). A diferença real está no **perfil de trade-off**:

### A favor da CERC
1. **Onboarding mais leve** — adesão contratual de perfil fintech, sem o
   aparato de comitê de risco/auditoria pré-operacional que a B3 exige.
   Para uma ESC municipal pequena com equipe técnica mínima (o próprio
   OrgCred), isso reduz tempo e custo de entrada.
2. **Prazo de integração estimado menor** (3–6 semanas, fonte de mercado)
   — ainda que não confirmado diretamente com a CERC.
3. Vertical **"Factoring & ESC"** nomeada explicitamente no site — sinal
   de que o produto foi desenhado (ou pelo menos empacotado) para esse
   público, não é uma adaptação genérica.

### A favor da B3
1. **Pedigree histórico mais forte no segmento**: foi a registradora que
   processou as primeiras operações de ESC do mercado, em setembro de
   2019 — meses depois da lei existir. Nenhuma outra candidata tem esse
   histórico.
2. **Apetite comercial ativo e recente por clientes do porte do
   OrgCred** — a própria B3 declarou publicamente (via seu superintendente
   da área) que a prioridade atual é fintechs de crédito e bancos
   pequenos/médios. Isso pode significar condições comerciais mais
   favoráveis para um novo entrante pequeno do que o processo de
   credenciamento formal sugere à primeira vista.
3. **Governança institucional mais robusta** — relevante se, no futuro, o
   OrgCred precisar demonstrar a auditores externos, investidores ou ao
   próprio Banco Central que opera com uma contraparte de registro do mais
   alto padrão do mercado. Isso pode pesar mais conforme a operação
   cresce, mesmo que não seja crítico no primeiro ano.
4. **Maturidade técnica da plataforma de API** (Swagger/OpenAPI, sandbox
   gratuito, 54 endpoints documentados) é, pelo material público, mais
   extensa do que a documentação encontrada da CERC — ainda que ambas
   sejam tecnicamente viáveis.

### Leitura prática

Se a prioridade da ORGATEC for **velocidade de lançamento e simplicidade
operacional**, CERC tem a vantagem no papel. Se a prioridade for
**solidez institucional de longo prazo e alinhamento com uma registradora
que já testou especificamente o caso de uso ESC desde o primeiro momento
da lei**, B3 tem argumento forte — especialmente dado que a B3 está
ativamente recrutando esse perfil de cliente agora. Nenhuma das duas foi
eliminada pela pesquisa; a escolha final depende de dados que só saem em
conversa comercial direta.

---

## Próximos passos concretos

1. **Contato comercial direto com CERC**: confirmar (a) tarifário oficial
   2026 para operações tipo CCB/empréstimo (não recebível de cartão), (b)
   prazo real de integração para uma equipe pequena, (c) se há algum
   requisito de porte/volume mínimo que uma ESC municipal pequena não
   atenderia.
2. **Contato comercial direto com B3 Registradora**: pedir explicitamente
   (a) tarifário oficial para registro de CCB de ESC — não achamos a
   tabela pública detalhada, só estimativa de mercado, (b) se o processo
   de credenciamento (CTRC, auditoria BSM) tem uma trilha simplificada
   para ESCs pequenas dado o apetite comercial declarado por esse
   segmento, (c) prazo real ponta a ponta até produção.
3. **Pergunta direta à Núclea** se atendem ESC e como, antes de descartar
   de vez — o silêncio editorial não é prova de inadequação, só de menor
   visibilidade nesse nicho.
4. Depois da escolha: implementar a integração em `app/routers/contratos.py`
   (hoje stub) — geração de CCB, chamada à API, callback que preenche
   `operacao_credito.registro_entidade_ref`.

---

## Fontes consultadas

- [5 registradoras de recebíveis autorizadas pelo Banco Central — Destrava.ai](https://www.destrava.ai/blog/conheca-as-5-registradoras-de-recebiveis-autorizadas-pelo-banco-central-2022)
- [Home — CERC](https://www.cerc.com/)
- [Parcerias — CERC](https://www.cerc.com/parcerias/)
- [API CERC — Agente de Registro (Apiary)](https://cercintegagentederegistro.docs.apiary.io/)
- [Como registrar duplicata escritural: passo a passo 2026 — Antecipa Fácil](https://antecipafacil.com.br/artigo/como-registrar-duplicata-escritural-cerc-b3-passo-a-passo-2026)
- [CERC vs B3: 5 diferenças para registrar duplicatas — Antecipa Fácil](https://antecipafacil.com.br/artigo/cerc-vs-b3-qual-escolher-para-registro-de-duplicatas)
- [Sistema de Registro de Operações — Núclea](https://www.nuclea.com.br/sistema-de-registro-de-operacoes/)
- [Registro de Ativos — Núclea](https://www.nuclea.com.br/registro-de-ativos/)
- [Registro de Crédito Consignado — Núclea](https://www.nuclea.com.br/registro-de-credito-consignado/)
- [Núclea CIP: conheça a história e evolução da empresa](https://www.nuclea.com.br/nuclea-cip-conheca-a-historia-e-evolucao-da-empresa/)
- [Registro de Recebíveis de Arranjo de Pagamento — TAG](https://docs.taginfraestrutura.com.br/docs/registro-arranjo)
- [Recebíveis de cartão — TAG](https://www.taginfraestrutura.com.br/recebiveis-cartao)
- [Cédula de Crédito Bancário — B3](https://www.b3.com.br/pt_br/produtos-e-servicos/registro/renda-fixa-e-valores-mobiliarios/cedula-de-credito-bancario.htm)
- [APIs Balcão (CCB) — B3 Developers](https://developers.b3.com.br/apis/api-balcao)
- [Tarifas — B3](https://www.b3.com.br/pt_br/produtos-e-servicos/tarifas/)
- [Processo de credenciamento — B3](https://www.b3.com.br/pt_br/produtos-e-servicos/participantes/clearing-de-cambio/processo-de-credenciamento/)
- [Operações — B3 (histórico de primeiras operações registradas, incl. ESC)](https://www.b3.com.br/pt_br/noticias/operacoes.htm)
- [B3 na mira: os concorrentes avançam por todos os lados — NeoFeed](https://neofeed.com.br/negocios/b3-na-mira-os-concorrentes-avancam-por-todos-lados-para-tentar-acabar-com-o-seu-reinado/)
- [8 funcionalidades do APPESC — Decisão Sistemas](https://decisaosistemas.com.br/funcionalidades-do-appesc/)
- [Sistema para Factoring e FIDC — Stand](https://www.stand.com.br/home/solucoes/sistema-factoring-e-fidc/)
- [Fomenti — sistema para factoring, securitizadora, ESC, FIDC](https://www.fomenti.com.br/)
- [Empresa Simples de Crédito (ESC) — Jusbrasil](https://www.jusbrasil.com.br/artigos/empresa-simples-de-credito-esc/736584620)
- [Empresa Simples de Crédito: registre o seu contrato — Abrafesc](https://abrafesc.com.br/esc-empresa-simples-de-credito-registre-o-seu-contrato/)
- [LC 167/2019 — Planalto](https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp167.htm)

**Limitação:** esta pesquisa é baseada em busca web e não em contato
comercial direto com as entidades. Custos, SLAs e requisitos de
elegibilidade citados são estimativas de mercado, não tarifários oficiais
confirmados — tratar como ponto de partida para negociação, não como
número final. A afirmação de que a B3 registrou as primeiras operações de
ESC do mercado em setembro de 2019 vem de conteúdo institucional da
própria B3 (`b3.com.br/pt_br/noticias/operacoes.htm`) e não foi
triangulada com uma segunda fonte independente — tratar como
altamente provável, não como certeza absoluta.
