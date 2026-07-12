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
**Núclea** foi pesquisada em profundidade (rodada dedicada,
2026-07-12) e permanece **tecnicamente capaz mas sem confirmação de
adequação ao caso de uso**: registra os tipos de ativo certos (CCB
incluída) e credencia explicitamente "factoring companies" — segmento
próximo em porte/risco ao de uma ESC — mas nenhum caso de uso ESC nomeado
foi encontrado em nenhuma fonte, e a documentação técnica mais detalhada
está atrás de barreira de acesso (vários manuais retornaram erro 403),
diferente da abertura pública da CERC e da B3. Não é "não", é "sem dado
suficiente" — decisão real depende de contato comercial direto.

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
| **Produto para CCB/empréstimo/ESC** | ✅ Categoria explícita "Financeiros" (CCBs, contrato de crédito, mútuos, títulos bancários); site lista "Factoring & ESC" como solução nomeada | ✅ Produto de registro de CCB via plataforma "Balcão" (2 variantes: CCB-NoMe e CCB-Plataforma Balcão) — registro, alteração, consulta, conciliação, gestão de parcelas | ✅ Registra CCB, CCE, NCE, CPR e contratos de crédito genéricos via C3 Registradora — produto existe, mas sem vertical "ESC" nomeada | ❌ Não — produto é especificamente recebíveis de arranjo de pagamento (cartão) |
| **Histórico específico com ESC** | Citada por fornecedores terceiros como parceira padrão | ✅ **Recebeu os primeiros registros de operação de ESC do mercado, em setembro de 2019** — meses após a LC 167/2019 entrar em vigor (abril/2019) | ❌ Nenhum caso de uso ESC encontrado, mesmo em pesquisa dedicada | Nenhum caso de uso ESC encontrado |
| **Estratégia comercial atual** | Foco declarado em fintechs de crédito e digitalização de recebíveis | Superintendente da B3 declarou publicamente que **o primeiro esforço da área é atuar junto a fintechs de crédito e bancos pequenos e médios** — sinaliza apetite ativo por clientes do porte do OrgCred | Programa "FAVO" de inovação aberta com startups — mas é parceria de co-desenvolvimento de produto, **não** canal de credenciamento de pequenas instituições como clientes do registro | Foco em recebíveis de cartão (Stone/adquirentes) |
| **Uso documentado por terceiros em software ESC** | ✅ Citada por 3 fornecedores independentes (APPESC/Decisão Sistemas, Fomenti, Stand) como padrão do segmento, ao lado da B3 | ✅ Mesma citação — aparece emparelhada com CERC nos mesmos 3 fornecedores | ❌ Nenhum dos 3 fornecedores especializados em ESC cita Núclea | ❌ Nenhum caso de uso ESC encontrado em fontes independentes |
| **Tipos de participante elegíveis** | Não detalhado com a mesma granularidade nesta pesquisa | Participantes de mercado de capitais + fintechs de crédito (estratégia recente) | Explicitamente: bancos, credenciadoras, **fintechs, factoring companies**, corretoras, gestores de investimento — factoring é sinal indireto de abertura a instituições de porte pequeno | Credenciadoras/adquirentes de cartão |
| **Certificações / governança** | ISO 27001, 27017, 27018 | Instituição sob regulação direta e intensa do BACEN/CVM como bolsa; "alto padrão de governança institucional" segundo comparativo de mercado — acima do padrão de uma fintech | ISO 27001, 22301 | Não encontrado nesta pesquisa |
| **Clientes conhecidos** | PagSeguro, Mercado Pago, MagaluPay, iFood, Vindi | Ecossistema de participantes de mercado de capitais + fintechs de crédito/bancos pequenos (estratégia recente) | Cielo, Rede, Getnet, SafraPay | Stone Co., PagarMe, Yapay, Rappi |
| **Integração técnica** | API REST documentada (Apiary/CERC Integração Agente de Registro); ERP com certificado digital envia título via API padronizada | REST + Swagger/OpenAPI, 54 APIs no portal "Balcão", ambiente de sandbox/certificação gratuito — **mas acesso é exclusivamente B2B**, requer credenciais próprias (CAU) | API, arquivo ou portal, "conforme necessidade de cada entidade" — documentação técnica detalhada (manuais MAPX) **bloqueada por erro 403** em acesso público, sugerindo exigência de credencial de participante para ver o material completo | Documentação técnica existe mas focada em recebíveis de cartão |
| **Processo de onboarding** | Adesão contratual mais leve (perfil fintech) | **Processo formal de credenciamento**: análise reputacional/jurídica/econômica + auditoria pré-operacional pela BSM + aprovação do Comitê Técnico de Risco de Crédito (CTRC) + possível depósito de garantia — estruturalmente mais pesado | Não detalhado nesta pesquisa — nenhuma evidência de requisito mínimo de porte/volume, mas também nenhuma confirmação de ausência dele | Não aplicável |
| **Prazo de integração estimado** | 3 a 6 semanas (fonte: mercado/Celcoin, não confirmado diretamente) | Não encontrado prazo específico — processo de credenciamento formal sugere ciclo mais longo que o da CERC | Não encontrado | Não aplicável |
| **Custo por título registrado** | R$ 0,30 a R$ 1,50/título + R$ 0,15–0,80/evento — faixa de mercado, **não confirmada oficialmente** | R$ 0,80 a R$ 1,50/título + R$ 0,30–0,80/evento, com tabela negociada acima de 50 mil títulos/mês — faixa de mercado similar à CERC, **também não confirmada oficialmente na página de tarifas pública** | Não encontrado nesta pesquisa | Não aplicável |
| **Posição de mercado para ESC** | Registradora de referência do segmento, ágil para integração pequena | **Pioneira histórica do segmento** + prioridade comercial declarada para fintechs pequenas, mas com processo de admissão institucional mais formal | Capaz tecnicamente, mas é a única das 3 candidatas originais sem NENHUM sinal público de atender o segmento ESC especificamente | Fora do escopo — produto não serve o caso de uso |

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

## Núclea em detalhe (pesquisa aprofundada 2026-07-12)

Rodada adicional de pesquisa, especificamente para tentar confirmar ou
descartar a Núclea como opção viável. Veredito: **capacidade técnica
confirmada, adequação ao caso de uso ESC permanece não-confirmada** — nem
descartada, nem validada.

### O que a pesquisa confirmou

1. **Produto de registro de crédito geral existe e é robusto.** Além do
   "Registro de Ativos" e do "SRCC" (crédito consignado), a Núclea/CIP
   registra explicitamente **CCB, CCE (Cédula de Crédito à Exportação),
   NCE (Nota de Crédito à Exportação) e CPR (Cédula de Produto Rural)** —
   ou seja, o tipo de ativo que o OrgCred precisaria registrar (CCB de
   empréstimo) está dentro do escopo documentado de produtos da Núclea,
   não é uma lacuna de produto.
2. **A C3 Registradora de Ativos Financeiros** (unidade específica da
   Núclea) permite que participantes registrem "contratos de crédito
   celebrados com seus clientes" e operações de cessão/bloqueio — a
   descrição genérica bate com o que uma ESC precisaria.
3. **Tipos de participante elegíveis incluem explicitamente "factoring
   companies"** (empresas de fomento mercantil), ao lado de bancos,
   fintechs, corretoras e gestores de investimento. Isso é um sinal
   indireto relevante: factoring e ESC são segmentos de porte e perfil de
   risco semelhantes — se a Núclea já credencia factorings, a barreira de
   entrada para uma ESC pequena provavelmente não é estruturalmente maior.
4. **Velocidade de lançamento de produtos novos é alta**: a Núclea lançou
   uma solução de crédito com garantia em previdência/capitalização
   (Resolução Conjunta CMN/CNSP 12) e bateu R$ 1 bilhão em contratos em
   apenas um mês — evidência de que a empresa constrói e escala produtos
   de registro de contrato de crédito rapidamente quando há demanda de
   mercado, não é uma operação lenta ou legada.
5. **Programa "FAVO"** de inovação aberta com startups existe, mas é um
   programa de parceria/co-desenvolvimento de produtos complementares
   (crédito, cobrança, fraude, dados) — **não é um canal de credenciamento
   de pequenas instituições de crédito como clientes diretos do
   registro**. Não deve ser confundido com "Núclea atende ESC pequenas".

### O que a pesquisa NÃO conseguiu confirmar

1. **Nenhum caso de uso ESC nomeado** em nenhuma fonte — nem no site da
   própria Núclea, nem em fornecedores de software especializados em ESC
   (os mesmos que citam CERC/B3 explicitamente não citam Núclea nenhuma
   vez).
2. **Nenhum requisito mínimo de volume/porte encontrado** publicamente —
   não há evidência de que a Núclea *exclua* pequenas instituições, mas
   também não há confirmação de que as *aceite* sem barreira adicional.
3. Vários documentos técnicos oficiais da Núclea (manuais de operação,
   regulamento geral do C3 Registradora) retornaram **erro 403** ao
   tentar acesso direto — o material técnico mais detalhado está atrás de
   alguma barreira de acesso (provavelmente exige login/credencial de
   participante), o que por si só é um dado: o nível de abertura pública
   da documentação é menor que o da CERC (Apiary público) ou da B3
   (portal de developers público com sandbox).

### Conclusão

Núclea não deve ser descartada por incapacidade técnica — o produto
existe. Mas também não é a aposta natural sem confirmação, porque **é a
única das três candidatas originais sem nenhuma evidência pública,
direta ou indireta, de atender especificamente o segmento ESC**, ao
contrário de CERC e B3, ambas com sinais concretos (vertical nomeada /
histórico de primeira operação registrada). Se o custo de uma ligação
comercial for baixo, vale perguntar diretamente — a documentação técnica
bloqueada sugere que a resposta completa só vem por esse canal mesmo.

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
3. **Pergunta direta à Núclea** se atendem ESC e como — depois da pesquisa
   aprofundada, especificamente perguntar: (a) qual produto seria usado
   para registrar CCB de empréstimo de ESC (C3 Registradora? Registro de
   Ativos?), (b) se factoring companies já credenciadas dão precedente
   direto para uma ESC de porte semelhante, (c) requisito mínimo de
   volume/porte, se houver, (d) acesso à documentação técnica completa
   (os manuais MAPX estão bloqueados publicamente).
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
- [Registro de Duplicatas — Núclea (institucional)](https://institucional.nuclea.com.br/registro-de-duplicatas)
- [Como a Núclea (antiga CIP) quer crescer com as startups — Finsiders Brasil](https://finsidersbrasil.com.br/reportagem-exclusiva-fintechs/como-a-nuclea-antiga-cip-quer-crescer-com-as-startups/)
- [Núclea bate R$ 1 bilhão em contratos de crédito vinculados à previdência e capitalização — SEGS](https://www.segs.com.br/seguros/437909-nuclea-bate-r-1-bilhao-em-contratos-de-credito-vinculados-a-previdencia-e-capitalizacao)
- [Consulta financeira de CNPJ — Núclea](https://www.nuclea.com.br/consulta-financeira-de-cnpj/)
- Manuais técnicos MAPX (C3 Registradora, Registradora Núclea) — **inacessíveis publicamente** (erro 403 em todas as tentativas de fetch direto)
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
