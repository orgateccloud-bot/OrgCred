# Pesquisa: entidade registradora para o OrgCred

**Data:** 2026-07-12 · **Contexto:** bloqueador #1 de `DECISOES_PENDENTES.md` —
qual entidade registradora usar para cumprir o Art. 5º §3º da LC 167/2019.
Este documento reúne o levantamento feito para embasar a decisão; **não
substitui** confirmação comercial direta com a entidade escolhida
(tarifário atual, SLA contratual, prazo de integração real).

---

## Resumo executivo

**SPC Grafeno passa a ser a recomendação mais forte** desde a rodada de
pesquisa de 2026-07-12: é a **única candidata com parceria comercial
oficial direta com a ABRAFESC** (a própria associação da indústria de
ESC) — sinal de adequação ao caso de uso mais forte do que qualquer
citação de terceiro encontrada para CERC ou B3. Além disso, processa
**~50% de todas as CCBs registradas no Brasil** (maior fatia de mercado
entre as 5 candidatas pesquisadas) e oferece emissão de CCB **sem
mensalidade**. **CERC e B3 seguem como finalistas fortes**, cada uma com
seu próprio trade-off (ver seção dedicada). **TAG não é adequada**: produto
é especificamente recebíveis de cartão. **Núclea** é tecnicamente capaz
mas sem nenhum sinal de adequação ao segmento ESC encontrado.

**Recomendação prática:** abrir conversa comercial com as três (SPC
Grafeno, CERC, B3) em paralelo, mas dar prioridade ao primeiro contato à
**SPC Grafeno via ABRAFESC** (`comercial@abrafesc.com.br`) — o caminho de
entrada é mais direto e o desconto do parceiro escala com adoção setorial,
o que pode ser vantajoso se outras ESCs da região também aderirem.

---

## As 5 registradoras autorizadas pelo Banco Central (panorama)

Cinco entidades estão autorizadas pelo Banco Central para registro de
ativos financeiros/recebíveis relevantes a este caso de uso: **CERC**,
**B3 Registradora**, **Núclea (ex-CIP)**, **TAG Infraestrutura** e **SPC
Grafeno** (joint venture SPC Brasil + Grafeno, autorizada em novembro de
2023 — a mais recente das cinco). Uma sexta, **CRDC**, também aparece em
levantamentos de mercado mas não foi pesquisada em detalhe (fora do
escopo desta comparação, que cobriu as cinco citadas).

Importante: essas entidades nasceram, em sua maioria, para registrar
**recebíveis de cartão de crédito/débito** (Resolução CMN 4.734, Circular
BACEN 3.952). O registro de operações de ESC (empréstimo, financiamento,
desconto de título — não recebíveis de arranjo de pagamento) é um uso da
mesma base legal (Art. 28, Lei 12.810/2013), mas nem toda registradora
expandiu seu produto para cobrir isso — TAG é o exemplo claro de quem não
expandiu; SPC Grafeno, CERC e B3 expandiram e têm evidência de uso por
ESC; Núclea tem o produto mas sem evidência de uso por ESC.

---

## Comparação detalhada

| Critério | **SPC Grafeno** | **CERC** | **B3 Registradora** | **Núclea (ex-CIP)** | **TAG Infraestrutura** |
|---|---|---|---|---|---|
| **Fundação** | Joint venture SPC Brasil + Grafeno; autorizada pelo BC em nov/2023 (pedido levou 4 anos até aprovação) | 2015 | B3 (bolsa) é histórica; registradora de recebíveis é vertical mais recente | CIP existe há 20+ anos; rebatizada Núclea | 2018/2020 |
| **Controlador** | 50/50 entre SPC Brasil (bureau de crédito) e Grafeno (fintech de infra bancária) | Independente (fintech de infra) | B3 S.A. — bolsa de valores, maior instituição de mercado de capitais do Brasil | Consórcio de instituições financeiras | Grupo Stone Co. |
| **Produto para CCB/empréstimo/ESC** | ✅ RegistrAtivos cobre duplicatas, notas promissórias e **CCB** explicitamente; API de Crédito da Grafeno emite CCB/CPR/Nota Comercial com simulação, parcelas e amortização | ✅ Categoria explícita "Financeiros" (CCBs, contrato de crédito, mútuos, títulos bancários); site lista "Factoring & ESC" como solução nomeada | ✅ Produto de registro de CCB via plataforma "Balcão" (2 variantes: CCB-NoMe e CCB-Plataforma Balcão) — registro, alteração, consulta, conciliação, gestão de parcelas | ✅ Registra CCB, CCE, NCE, CPR e contratos de crédito genéricos via C3 Registradora — produto existe, mas sem vertical "ESC" nomeada | ❌ Não — produto é especificamente recebíveis de arranjo de pagamento (cartão) |
| **Histórico/parceria específica com ESC** | 🏆 **Parceria comercial oficial e direta com a ABRAFESC** (associação da indústria de ESC) — desconto para membros, escalando com adoção setorial; sinal mais direto de todas as candidatas | Citada por fornecedores terceiros como parceira padrão | ✅ **Recebeu os primeiros registros de operação de ESC do mercado, em setembro de 2019** — meses após a LC 167/2019 entrar em vigor (abril/2019) | ❌ Nenhum caso de uso ESC encontrado, mesmo em pesquisa dedicada | Nenhum caso de uso ESC encontrado |
| **Market share (CCB/duplicatas)** | 🏆 **~50% de todas as CCBs registradas no Brasil e ~40% das duplicatas**, R$ 250+ bi transacionados em 2025 — maior fatia de mercado entre as 5 candidatas pesquisadas | Não quantificado nesta pesquisa | Não quantificado nesta pesquisa | Não quantificado nesta pesquisa | Não aplicável ao produto de CCB |
| **Estratégia comercial atual** | Parceria setorial ativa via associação (ABRAFESC); modelo de desconto coletivo incentiva adoção em massa pelo setor | Foco declarado em fintechs de crédito e digitalização de recebíveis | Superintendente da B3 declarou publicamente que **o primeiro esforço da área é atuar junto a fintechs de crédito e bancos pequenos e médios** | Programa "FAVO" de inovação aberta com startups — mas é parceria de co-desenvolvimento de produto, **não** canal de credenciamento de pequenas instituições como clientes do registro | Foco em recebíveis de cartão (Stone/adquirentes) |
| **Uso documentado por terceiros em software/associação ESC** | ✅✅ **Confirmação de primeira mão pela própria associação setorial (ABRAFESC)** — mais forte que citação de fornecedor terceiro | ✅ Citada por 3 fornecedores independentes (APPESC/Decisão Sistemas, Fomenti, Stand) como padrão do segmento, ao lado da B3 | ✅ Mesma citação — aparece emparelhada com CERC nos mesmos 3 fornecedores | ❌ Nenhum dos 3 fornecedores especializados em ESC cita Núclea | ❌ Nenhum caso de uso ESC encontrado em fontes independentes |
| **Tipos de participante elegíveis** | Explicitamente: instituições financeiras (bancos, fintechs), **sociedades de crédito**, PMEs emissoras de CCB, credores diversificando carteira | Não detalhado com a mesma granularidade nesta pesquisa | Participantes de mercado de capitais + fintechs de crédito (estratégia recente) | Explicitamente: bancos, credenciadoras, fintechs, **factoring companies**, corretoras, gestores de investimento | Credenciadoras/adquirentes de cartão |
| **Certificações / governança** | 100% cloud AWS; combina base de dados de crédito do SPC Brasil (décadas de histórico) com infra bancária da Grafeno | ISO 27001, 27017, 27018 | Instituição sob regulação direta e intensa do BACEN/CVM como bolsa; "alto padrão de governança institucional" | ISO 27001, 22301 | Não encontrado nesta pesquisa |
| **Integração técnica** | API de Crédito da Grafeno: REST, emissão/simulação/parcelas/amortização, sandbox de testes — **webhooks ainda não suportados** (requer polling) | API REST documentada (Apiary/CERC Integração Agente de Registro); ERP com certificado digital envia título via API padronizada | REST + Swagger/OpenAPI, 54 APIs no portal "Balcão", sandbox gratuito — **mas acesso é exclusivamente B2B**, requer credenciais próprias (CAU) | API, arquivo ou portal — documentação técnica detalhada (manuais MAPX) **bloqueada por erro 403** em acesso público | Documentação técnica existe mas focada em recebíveis de cartão |
| **Processo de onboarding** | Via ABRAFESC: email direto (`comercial@abrafesc.com.br`) com CNPJ e contato — caminho mais simples encontrado entre as 5 | Adesão contratual mais leve (perfil fintech) | **Processo formal de credenciamento**: análise reputacional/jurídica/econômica + auditoria pré-operacional pela BSM + CTRC + possível depósito de garantia | Não detalhado — nenhuma evidência de requisito mínimo de porte/volume, mas também nenhuma confirmação de ausência dele | Não aplicável |
| **Prazo de integração estimado** | Não encontrado prazo específico, mas onboarding via associação setorial sugere processo simplificado | 3 a 6 semanas (fonte: mercado/Celcoin, não confirmado diretamente) | Não encontrado — processo de credenciamento formal sugere ciclo mais longo que o da CERC | Não encontrado | Não aplicável |
| **Custo/modelo de cobrança** | 🏆 Emissão de CCB **sem mensalidade** ("sem contratar conta ou assumir taxas mensais"); desconto adicional via parceria ABRAFESC escalando com volume setorial — modelo comercial diferente das demais | R$ 0,30 a R$ 1,50/título + R$ 0,15–0,80/evento — faixa de mercado, **não confirmada oficialmente** | R$ 0,80 a R$ 1,50/título + R$ 0,30–0,80/evento, tabela negociada acima de 50 mil títulos/mês — **também não confirmada oficialmente** | Não encontrado nesta pesquisa | Não aplicável |
| **Posição de mercado para ESC** | 🏆 **Maior sinal de adequação confirmada** (parceria direta com a associação setorial) + maior market share de CCB | Registradora de referência do segmento, ágil para integração pequena | **Pioneira histórica do segmento** + prioridade comercial declarada para fintechs pequenas, mas processo de admissão mais formal | Capaz tecnicamente, mas sem nenhum sinal público de atender o segmento ESC | Fora do escopo — produto não serve o caso de uso |

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

## SPC Grafeno em detalhe (pesquisa aprofundada 2026-07-12)

Rodada adicional de pesquisa dedicada, a pedido. Veredito: **maior
convicção de todas as cinco candidatas** de que atende ESC — evidência
direta, não inferida por citação de terceiro.

### O que a pesquisa confirmou

1. **Parceria comercial oficial com a ABRAFESC.** A própria associação
   nacional de Empresas Simples de Crédito lista a SPC Grafeno como
   parceira em [abrafesc.com.br/spc-grafeno](https://abrafesc.com.br/spc-grafeno),
   com condições de desconto para empresas associadas. O modelo é
   explicitamente coletivo: "quanto mais empresas do setor aderirem ao
   contrato da parceria, maior será o desconto" — ou seja, o preço melhora
   se outras ESCs da região também aderirem, criando um incentivo de rede
   que nenhuma outra candidata oferece.
2. **Adesão via canal simples e nomeado**: e-mail direto a
   `comercial@abrafesc.com.br` com CNPJ, telefone e responsável — não há
   processo de credenciamento formal documentado (ao contrário da B3) nem
   silêncio total sobre o caminho de entrada (ao contrário da Núclea).
3. **Escala de mercado muito acima das outras candidatas**: **~50% de
   todas as CCBs registradas no Brasil e ~40% das duplicatas**, R$ 250+
   bilhões transacionados em 2025. Para efeito de comparação, nenhuma
   outra candidata desta pesquisa divulgou um número de participação de
   mercado dessa magnitude.
4. **Autorização do Banco Central levou 4 anos de análise** (pedido em
   2019, aprovação em novembro de 2023) — sinaliza escrutínio regulatório
   extenso já superado, não é uma operação recém-testada.
5. **Modelo de cobrança de CCB é diferente**: emissão "sem contratar conta
   ou assumir taxas mensais" — um modelo comercial de tarifa-por-evento ou
   embutida na operação, não a mensalidade/tarifa-por-título fixa que CERC
   e B3 praticam. Isso pode ser vantajoso para o volume baixo esperado de
   uma ESC municipal pequena no início.
6. **Tipos de participante elegível incluem explicitamente "sociedades de
   crédito"** — categoria mais próxima textualmente de "Empresa Simples de
   Crédito" do que qualquer termo usado pelas outras quatro candidatas.
7. **API de Crédito da Grafeno é funcionalmente completa** para o caso de
   uso: emissão de CCB, simulação de operação, gestão de parcelas e
   amortização — cobre o ciclo que o `app/routers/contratos.py` (hoje
   stub) precisaria orquestrar.

### O que a pesquisa NÃO conseguiu confirmar

1. **Tarifário oficial por título/operação** não foi encontrado — o
   material público enfatiza "sem mensalidade" mas não detalha se há
   cobrança por CCB emitida, por consulta, ou por outro evento.
2. **Suporte a webhook ainda não existe** na API de Crédito ("webhooks are
   not yet supported") — a integração exigiria polling ativo de status em
   vez de notificação em tempo real, uma limitação técnica real para o
   fluxo de `registro_entidade_ref` (hoje pensado como callback).
3. **Prazo de integração** não foi encontrado especificamente — o caminho
   de adesão via ABRAFESC parece simples, mas isso é sobre contrato
   comercial, não necessariamente sobre tempo de integração técnica.

### Conclusão

SPC Grafeno tem a evidência mais direta e verificável de todas as cinco
candidatas — não uma inferência de "aparece ao lado de CERC/B3 em
material de terceiros" (como CERC e B3), nem um "produto existe mas sem
caso de uso" (como Núclea): é uma **parceria nomeada, com a própria
associação da indústria, com termos comerciais publicados**. A ausência
de suporte a webhook é a única fragilidade técnica concreta encontrada e
deve ser confirmada/mitigada antes de fechar.

---

## SPC Grafeno vs. CERC vs. B3: os três finalistas, lado a lado

As três passam no teste básico (produto para CCB/ESC existe, uso
documentado, API REST). A diferença está no **perfil de trade-off**:

### A favor da SPC Grafeno
1. **Evidência de adequação mais forte e mais direta**: parceria comercial
   nomeada com a própria associação da indústria (ABRAFESC), não uma
   citação de terceiro nem um caso histórico — a diferença entre "a
   associação da indústria escolheu esta registradora como parceira" e
   "fornecedores de software citam esta registradora" é qualitativa, não
   só de grau.
2. **Maior participação de mercado em CCB** (~50%) entre as cinco
   candidatas — reduz o risco de escolher uma registradora com pouca
   adoção do lado credor/investidor.
3. **Caminho de adesão mais simples e nomeado** (e-mail direto via
   ABRAFESC) — sem processo de credenciamento formal documentado.
4. **Modelo de cobrança sem mensalidade** pode ser vantajoso para o volume
   baixo esperado de uma ESC municipal pequena no início de operação.
5. **Desconto que escala com adoção setorial** — argumento de rede que
   nenhuma outra candidata oferece.

### A favor da CERC
1. **Onboarding mais leve** — adesão contratual de perfil fintech, sem o
   aparato de comitê de risco/auditoria pré-operacional que a B3 exige.
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
   pequenos/médios.
3. **Governança institucional mais robusta** — relevante se, no futuro, o
   OrgCred precisar demonstrar a auditores externos, investidores ou ao
   próprio Banco Central que opera com uma contraparte de registro do mais
   alto padrão do mercado.
4. **Maturidade técnica da plataforma de API** (Swagger/OpenAPI, sandbox
   gratuito, 54 endpoints documentados) mais extensa do que a
   documentação pública da CERC ou da SPC Grafeno.

### Leitura prática

**SPC Grafeno tem a evidência mais forte de adequação ao caso de uso e o
caminho de entrada mais simples** — é o primeiro contato recomendado. A
única fragilidade técnica concreta encontrada (webhooks ainda não
suportados na API de Crédito) precisa ser confirmada/mitigada antes de
fechar, já que o fluxo de `registro_entidade_ref` do OrgCred foi pensado
como callback assíncrono. Se a SPC Grafeno não confirmar boas condições
para o porte do OrgCred, CERC continua sendo a alternativa mais ágil
operacionalmente, e B3 a mais sólida institucionalmente a longo prazo.
Nenhuma das três foi eliminada pela pesquisa; a escolha final depende de
dados que só saem em conversa comercial direta com as três em paralelo.

---

## Próximos passos concretos

1. **Contato comercial direto com SPC Grafeno via ABRAFESC**
   (`comercial@abrafesc.com.br`) — primeiro contato recomendado dado o
   sinal de adequação mais forte. Confirmar: (a) tarifário real por
   CCB/evento (o material público só diz "sem mensalidade", sem detalhar
   cobrança por operação), (b) se/quando o suporte a webhook será
   lançado — hoje a API exige polling, o que muda o design do callback em
   `app/routers/contratos.py`, (c) prazo real de integração técnica
   (distinto do prazo comercial de adesão via associação), (d) condições
   específicas do desconto coletivo — quantas ESCs já aderiram pela
   ABRAFESC.
2. **Contato comercial direto com CERC**: confirmar (a) tarifário oficial
   2026 para operações tipo CCB/empréstimo (não recebível de cartão), (b)
   prazo real de integração para uma equipe pequena, (c) se há algum
   requisito de porte/volume mínimo que uma ESC municipal pequena não
   atenderia.
3. **Contato comercial direto com B3 Registradora**: pedir explicitamente
   (a) tarifário oficial para registro de CCB de ESC — não achamos a
   tabela pública detalhada, só estimativa de mercado, (b) se o processo
   de credenciamento (CTRC, auditoria BSM) tem uma trilha simplificada
   para ESCs pequenas dado o apetite comercial declarado por esse
   segmento, (c) prazo real ponta a ponta até produção.
4. **Pergunta direta à Núclea** se atendem ESC e como — depois da pesquisa
   aprofundada, especificamente perguntar: (a) qual produto seria usado
   para registrar CCB de empréstimo de ESC (C3 Registradora? Registro de
   Ativos?), (b) se factoring companies já credenciadas dão precedente
   direto para uma ESC de porte semelhante, (c) requisito mínimo de
   volume/porte, se houver, (d) acesso à documentação técnica completa
   (os manuais MAPX estão bloqueados publicamente).
5. Depois da escolha: implementar a integração em `app/routers/contratos.py`
   (hoje stub) — geração de CCB, chamada à API, callback que preenche
   `operacao_credito.registro_entidade_ref`. Se a escolhida for a SPC
   Grafeno e o webhook ainda não estiver disponível, desenhar o
   preenchimento de `registro_entidade_ref` via polling/job periódico em
   vez de callback assíncrono.

---

## Fontes consultadas

- [SPC GRAFENO é a nova parceira da ABRAFESC — Abrafesc](https://abrafesc.com.br/spc-grafeno)
- [BC aprova nova registradora SPC Grafeno — Finsiders Brasil](https://finsidersbrasil.com.br/regulamentacao/bc-aprova-nova-registradora-spc-grafeno-adyen-e-zapay-sao-autorizadas-como-ip/)
- [SPC Grafeno, registradora 100% em nuvem, é autorizada a operar pelo Banco Central — Universo do Seguro](https://universodoseguro.com.br/spc-grafeno-registradora-100-em-nuvem-e-autorizada-a-operar-pelo-banco-central/)
- [SPC Grafeno entra em registro de duplicatas — Grafeno Digital](https://grafeno.digital/blog/spc-grafeno-entra-em-registro-de-duplicatas/)
- [Página Inicial — SPC Grafeno](https://spcgrafeno.com.br/)
- [Produtos — SPC Grafeno](https://spcgrafeno.com.br/produtos/)
- [Registro de Ativos Financeiros — SPC Grafeno](https://spcgrafeno.com.br/registro-de-ativos/)
- [Escrituração e Registro de Ativos: a evolução e o papel da SPC Grafeno no mercado](https://spcgrafeno.com.br/escrituracao-e-registro-de-ativos-a-evolucao-e-o-papel-da-spc-grafeno-no-mercado/)
- [SPC Grafeno pronta para o BC e mercado de R$10 trilhões — SPC Brasil](https://www.spcbrasil.com.br/blog/duplicatas-spc-grafeno)
- [SPC Brasil se associa à fintech para atuar no mercado de registro de ativos financeiros — Varejo S.A](https://cndl.org.br/varejosa/spc-brasil-se-associa-a-fintech-para-atuar-no-mercado-de-registro-de-ativos-financeiros/)
- [API Grafeno Ativos — Crédito](https://docs.grafeno.digital/v1.0/reference/credits)
- [Emissão de CCB — Grafeno Digital](https://grafeno.digital/emissao-de-ccb/)
- [O que é CCB: entenda tudo sobre Cédula de Crédito Bancário — Grafeno Digital](https://grafeno.digital/blog/tudo-sobre-ccb/)
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
altamente provável, não como certeza absoluta. A parceria SPC Grafeno
– ABRAFESC foi confirmada diretamente na página da própria ABRAFESC
(fonte primária da associação, não de terceiro), mas os termos comerciais
exatos do desconto (percentual, faixas de volume) não foram publicados —
só a existência e o modelo geral ("mais adesão = mais desconto").
