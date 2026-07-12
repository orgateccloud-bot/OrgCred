# Pesquisa: entidade registradora para o OrgCred

**Data:** 2026-07-12 · **Contexto:** bloqueador #1 de `DECISOES_PENDENTES.md` —
qual entidade registradora usar para cumprir o Art. 5º §3º da LC 167/2019.
Este documento reúne o levantamento feito para embasar a decisão; **não
substitui** confirmação comercial direta com a entidade escolhida
(tarifário atual, SLA contratual, prazo de integração real).

---

## Resumo executivo

**CRDC e SPC Grafeno empatam como as recomendações mais fortes** após a
rodada de pesquisa de 2026-07-12 — cada uma com o tipo de evidência mais
direta possível, de naturezas diferentes:

- **CRDC** tem **"Contratos ESC" como categoria de ativo nomeada dentro
  do próprio sistema de registro** — não é uma parceria comercial externa,
  é o produto em si reconhecendo ESC como tipo de operação. Tem também
  **integração nativa com sistemas de ESC** (atualização automática de
  saldo devedor e parcelas vencidas) e parceria com a Stand, fornecedor de
  software especializado em ESC/factoring/FIDC. É citada, ao lado da CERC
  — não da B3 — como o par padrão do segmento por pelo menos duas fontes
  independentes (Stand, SINFAC-SP).
- **SPC Grafeno** tem a **parceria comercial oficial e nomeada com a
  ABRAFESC** (associação da indústria de ESC), processa ~50% de todas as
  CCBs registradas no Brasil, e oferece emissão sem mensalidade.

**CERC segue como terceira finalista forte** (citada por praticamente
todas as fontes, ao lado tanto de CRDC quanto de B3/Núclea, tornando-a a
opção mais consistentemente mencionada em todo o levantamento). **B3**
tem o pedigree histórico mais antigo (primeira ESC registrada, 2019) mas
processo de credenciamento mais pesado. **TAG não é adequada**. **Núclea**
é tecnicamente capaz mas sem nenhum sinal de adequação ao ESC.

**Recomendação prática:** abrir conversa comercial em paralelo com CRDC,
SPC Grafeno e CERC — as três com evidência de produto/parceria mais
direta — mantendo B3 como alternativa institucional caso as três primeiras
não confirmem boas condições. Vale nota: a CRDC está no meio de uma
disputa antitruste (o CADE recomendou reprovar a compra de 60% da CRDC
pela B3, decisão final pendente) — hoje a CRDC segue 100%
independente/controlada pela ACSP, o que é positivo para uma ESC pequena
que prefira uma contraparte não dominada por um player maior, mas vale
acompanhar o desfecho.

---

## As 6 registradoras autorizadas pelo Banco Central (panorama)

Seis entidades foram identificadas como autorizadas pelo Banco Central
para registro de ativos financeiros/recebíveis relevantes a este caso de
uso: **CRDC**, **CERC**, **B3 Registradora**, **Núclea (ex-CIP)**, **TAG
Infraestrutura** e **SPC Grafeno** (joint venture SPC Brasil + Grafeno,
autorizada em novembro de 2023 — a mais recente das seis). Todas as seis
foram agora pesquisadas em algum nível de detalhe — CRDC e SPC Grafeno
em rodadas dedicadas, adicionais ao levantamento original.

Importante: essas entidades nasceram, em sua maioria, para registrar
**recebíveis de cartão de crédito/débito** (Resolução CMN 4.734, Circular
BACEN 3.952). O registro de operações de ESC (empréstimo, financiamento,
desconto de título — não recebíveis de arranjo de pagamento) é um uso da
mesma base legal (Art. 28, Lei 12.810/2013), mas nem toda registradora
expandiu seu produto para cobrir isso — TAG é o exemplo claro de quem não
expandiu; CRDC, SPC Grafeno, CERC e B3 expandiram e têm evidência de uso
por ESC; Núclea tem o produto mas sem evidência de uso por ESC.

---

## Comparação detalhada

| Critério | **CRDC** | **SPC Grafeno** | **CERC** | **B3 Registradora** | **Núclea (ex-CIP)** | **TAG Infraestrutura** |
|---|---|---|---|---|---|---|
| **Fundação** | 2014, operacional desde 2016; controlada majoritariamente pela ACSP desde 2015; atuação nacional desde out/2019 | Joint venture SPC Brasil + Grafeno; autorizada pelo BC em nov/2023 (pedido levou 4 anos até aprovação) | 2015 | B3 (bolsa) é histórica; registradora de recebíveis é vertical mais recente | CIP existe há 20+ anos; rebatizada Núclea | 2018/2020 |
| **Controlador** | ACSP (Associação Comercial de São Paulo), 100% independente hoje — venda de 60% à B3 foi **recomendada para reprovação pelo CADE** (decisão final pendente) | 50/50 entre SPC Brasil (bureau de crédito) e Grafeno (fintech de infra bancária) | Independente (fintech de infra) | B3 S.A. — bolsa de valores, maior instituição de mercado de capitais do Brasil | Consórcio de instituições financeiras | Grupo Stone Co. |
| **Produto para CCB/empréstimo/ESC** | 🏆 **"Contratos ESC" é categoria de ativo NOMEADA dentro do próprio sistema de registro** — não é adaptação, é tipo de ativo reconhecido nativamente, ao lado de CCB, duplicata, CPR, nota promissória | ✅ RegistrAtivos cobre duplicatas, notas promissórias e **CCB** explicitamente; API de Crédito da Grafeno emite CCB/CPR/Nota Comercial com simulação, parcelas e amortização | ✅ Categoria explícita "Financeiros" (CCBs, contrato de crédito, mútuos, títulos bancários); site lista "Factoring & ESC" como solução nomeada | ✅ Produto de registro de CCB via plataforma "Balcão" (2 variantes: CCB-NoMe e CCB-Plataforma Balcão) — registro, alteração, consulta, conciliação, gestão de parcelas | ✅ Registra CCB, CCE, NCE, CPR e contratos de crédito genéricos via C3 Registradora — produto existe, mas sem vertical "ESC" nomeada | ❌ Não — produto é especificamente recebíveis de arranjo de pagamento (cartão) |
| **Histórico/parceria específica com ESC** | 🏆 **Integração nativa com sistemas de ESC**, com atualização automática de saldo devedor e parcelas vencidas — resolveria diretamente a limitação de "amortização parcial não libera capital" hoje documentada em `DECISOES_PENDENTES.md`. Parceria ativa com a Stand (software especializado em ESC/factoring/FIDC) para consulta prévia de registro no processo de crédito | 🏆 **Parceria comercial oficial e direta com a ABRAFESC** (associação da indústria de ESC) — desconto para membros, escalando com adoção setorial | Citada por fornecedores terceiros como parceira padrão | ✅ **Recebeu os primeiros registros de operação de ESC do mercado, em setembro de 2019** — meses após a LC 167/2019 entrar em vigor (abril/2019) | ❌ Nenhum caso de uso ESC encontrado, mesmo em pesquisa dedicada | Nenhum caso de uso ESC encontrado |
| **Market share (CCB/duplicatas)** | Não quantificado nesta pesquisa | 🏆 **~50% de todas as CCBs registradas no Brasil e ~40% das duplicatas**, R$ 250+ bi transacionados em 2025 — maior fatia de mercado entre as 6 candidatas pesquisadas | Não quantificado nesta pesquisa | Não quantificado nesta pesquisa | Não quantificado nesta pesquisa | Não aplicável ao produto de CCB |
| **Estratégia comercial atual** | IOSMF de nicho voltada a bancos, FIDCs, factoring, fintechs, securitizadoras e ESC — posicionamento explícito no público de porte pequeno/médio desde a origem | Parceria setorial ativa via associação (ABRAFESC); modelo de desconto coletivo incentiva adoção em massa pelo setor | Foco declarado em fintechs de crédito e digitalização de recebíveis | Superintendente da B3 declarou publicamente que **o primeiro esforço da área é atuar junto a fintechs de crédito e bancos pequenos e médios** | Programa "FAVO" de inovação aberta com startups — mas é parceria de co-desenvolvimento de produto, **não** canal de credenciamento de pequenas instituições como clientes do registro | Foco em recebíveis de cartão (Stone/adquirentes) |
| **Uso documentado por terceiros em software/associação ESC** | 🏆 Citada por **pelo menos 2 fontes independentes** (Stand, SINFAC-SP) — a Stand cita explicitamente **"CRDC e CERC"**, não "B3 e CERC", como o par padrão do segmento (correção de uma inferência anterior desta pesquisa) | ✅✅ **Confirmação de primeira mão pela própria associação setorial (ABRAFESC)** — mais forte que citação de fornecedor terceiro | ✅ Citada por múltiplos fornecedores independentes como padrão do segmento — a candidata mais consistentemente mencionada em toda a pesquisa (ao lado tanto de CRDC quanto de B3, dependendo da fonte) | ✅ Citada por Decisão Sistemas/Fomenti ao lado da CERC — mas a Stand, especificamente, cita CRDC em vez de B3 nesse papel | ❌ Nenhuma fonte especializada em ESC cita Núclea | ❌ Nenhum caso de uso ESC encontrado em fontes independentes |
| **Tipos de participante elegíveis** | Explicitamente: Bancos, FIDCs, Factoring, Fintechs, Securitizadoras, **Empresas Simples de Crédito (ESC)** e empresários buscando crédito com base em recebíveis — ESC nomeada literalmente na lista de público-alvo | Explicitamente: instituições financeiras (bancos, fintechs), **sociedades de crédito**, PMEs emissoras de CCB, credores diversificando carteira | Não detalhado com a mesma granularidade nesta pesquisa | Participantes de mercado de capitais + fintechs de crédito (estratégia recente) | Explicitamente: bancos, credenciadoras, fintechs, **factoring companies**, corretoras, gestores de investimento | Credenciadoras/adquirentes de cartão |
| **Certificações / governança** | IOSMF avaliada pelo Bacen segundo os Princípios PFMI (BIS/IOSCO) — mesmo padrão internacional aplicado a infraestruturas de mercado sistemicamente relevantes | 100% cloud AWS; combina base de dados de crédito do SPC Brasil (décadas de histórico) com infra bancária da Grafeno | ISO 27001, 27017, 27018 | Instituição sob regulação direta e intensa do BACEN/CVM como bolsa; "alto padrão de governança institucional" | ISO 27001, 22301 | Não encontrado nesta pesquisa |
| **Integração técnica** | API REST/JSON para registro de ativos financeiros; layout específico definido por participante em fase de onboarding; gera NUR (Número Único de Registro) por ativo | API de Crédito da Grafeno: REST, emissão/simulação/parcelas/amortização, sandbox de testes — **webhooks ainda não suportados** (requer polling) | API REST documentada (Apiary/CERC Integração Agente de Registro); ERP com certificado digital envia título via API padronizada | REST + Swagger/OpenAPI, 54 APIs no portal "Balcão", sandbox gratuito — **mas acesso é exclusivamente B2B**, requer credenciais próprias (CAU) | API, arquivo ou portal — documentação técnica detalhada (manuais MAPX) **bloqueada por erro 403** em acesso público | Documentação técnica existe mas focada em recebíveis de cartão |
| **Processo de onboarding** | Manuais de acesso/integração públicos (Portal de Registro CRDC); site institucional (`crdc.com.br`) **bloqueado por erro 403** em várias tentativas de acesso direto, mas documentação técnica (PDFs de manual) está indexada e acessível via busca | Via ABRAFESC: email direto (`comercial@abrafesc.com.br`) com CNPJ e contato — caminho mais simples encontrado entre as 6 | Adesão contratual mais leve (perfil fintech) | **Processo formal de credenciamento**: análise reputacional/jurídica/econômica + auditoria pré-operacional pela BSM + CTRC + possível depósito de garantia | Não detalhado — nenhuma evidência de requisito mínimo de porte/volume, mas também nenhuma confirmação de ausência dele | Não aplicável |
| **Prazo de integração estimado** | Não encontrado nesta pesquisa | Não encontrado prazo específico, mas onboarding via associação setorial sugere processo simplificado | 3 a 6 semanas (fonte: mercado/Celcoin, não confirmado diretamente) | Não encontrado — processo de credenciamento formal sugere ciclo mais longo que o da CERC | Não encontrado | Não aplicável |
| **Custo/modelo de cobrança** | Tabela de preços existe (`CRDC-Tabela-de-Preco-SRO`) mas **não foi acessível publicamente** (erro 403) — cobrança segue proposta comercial individual por participante | 🏆 Emissão de CCB **sem mensalidade** ("sem contratar conta ou assumir taxas mensais"); desconto adicional via parceria ABRAFESC escalando com volume setorial — modelo comercial diferente das demais | R$ 0,30 a R$ 1,50/título + R$ 0,15–0,80/evento — faixa de mercado, **não confirmada oficialmente** | R$ 0,80 a R$ 1,50/título + R$ 0,30–0,80/evento, tabela negociada acima de 50 mil títulos/mês — **também não confirmada oficialmente** | Não encontrado nesta pesquisa | Não aplicável |
| **Posição de mercado para ESC** | 🏆 **Único produto com "Contratos ESC" nomeado nativamente** + integração automática de saldo devedor — evidência de produto mais direta de todas | 🏆 **Maior sinal de adequação confirmada** (parceria direta com a associação setorial) + maior market share de CCB | Registradora de referência do segmento, mencionada de forma mais consistente em toda a pesquisa | **Pioneira histórica do segmento** + prioridade comercial declarada para fintechs pequenas, mas processo de admissão mais formal | Capaz tecnicamente, mas sem nenhum sinal público de atender o segmento ESC | Fora do escopo — produto não serve o caso de uso |

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

## CRDC em detalhe (pesquisa aprofundada 2026-07-12)

Rodada dedicada de pesquisa, a pedido. Veredito: **evidência de produto
mais direta de todas as seis candidatas** — não uma parceria comercial
externa (como SPC Grafeno/ABRAFESC) nem uma citação de terceiro (como
CERC/B3), mas o próprio sistema de registro reconhecendo "ESC" como tipo
de ativo nativo.

### O que a pesquisa confirmou

1. **"Contratos ESC" é uma categoria de ativo nomeada dentro do sistema
   de registro da CRDC**, ao lado de CCB, duplicata, CPR e nota
   promissória — confirmado em múltiplas fontes independentes descrevendo
   o catálogo de produtos da CRDC. Isso é qualitativamente diferente de
   "produto genérico de CCB que também serve para ESC": é o tipo de
   operação reconhecido nativamente pelo sistema.
2. **Integração nativa com sistemas de ESC**, incluindo "atualização
   automática de saldo devedor de contratos e parcelas vencidas" — a
   fonte descreve exatamente a funcionalidade que resolveria, do lado da
   registradora, a limitação hoje documentada em `DECISOES_PENDENTES.md`
   ("amortização parcial não libera capital" — interpretação conservadora
   porque o OrgCred usa `valor_principal` integral até liquidação). Se a
   CRDC já rastreia saldo devedor automaticamente, isso pode simplificar
   uma futura mudança de interpretação, caso a decisão jurídico-contábil
   pendente (item 5 de `DECISOES_PENDENTES.md`) for nessa direção.
3. **Parceria ativa e nomeada com a Stand** (fornecedor de software
   especializado em Factoring/FIDC/Securitizadora/ESC — o mesmo Stand
   citado como fonte terceira em outras partes desta pesquisa) para
   consulta prévia de registro no processo de análise de crédito, evitando
   negociar recebíveis já comprometidos.
4. **Público-alvo declarado inclui ESC nominalmente**: a própria
   descrição institucional da CRDC lista "Bancos, FIDCs, Factoring,
   Fintechs, Securitizadoras, **Empresas Simples de Crédito (ESC)** e
   empresários buscando crédito com base em recebíveis" — ESC aparece
   como categoria própria, não inferida.
5. **Citada por pelo menos 2 fontes independentes** (Stand, SINFAC-SP)
   como registradora do segmento — e a Stand especificamente nomeia
   **"CRDC e CERC"**, não "B3 e CERC", como o par padrão. Isso corrige uma
   inferência anterior desta pesquisa (a seção "CERC vs. B3" original
   presumia que todos os fornecedores de software ESC citavam o mesmo
   par; na verdade, a citação varia por fornecedor).
6. **Fundação e trajetória**: criada em 2014 pela Associação Comercial de
   São Paulo (ACSP), operacional desde 2016, atuação nacional desde
   outubro de 2019 — anterior ou contemporânea à própria LC 167/2019
   (abril de 2019), sugerindo que a CRDC também esteve presente desde o
   início do arcabouço legal de ESC, como a B3.
7. **Status societário independente confirmado**: a B3 tentou comprar 60%
   da CRDC; a Superintendência-Geral do CADE **recomendou reprovar** a
   operação por preocupação de concentração de mercado (decisão final
   ainda pendente no tribunal do CADE). Hoje a CRDC segue 100% controlada
   pela ACSP. Isso é relevante para o OrgCred de duas formas: (a) positivo
   — significa que a CRDC não está subordinada à mesma instituição que
   controla a B3, oferecendo uma contraparte de registro genuinamente
   independente; (b) pontos de atenção — a disputa societária é uma fonte
   de incerteza de médio prazo que vale monitorar antes de um compromisso
   de longo prazo.

### O que a pesquisa NÃO conseguiu confirmar

1. **Tarifário público não encontrado** — a tabela de preços da CRDC
   existe (`CRDC-Tabela-de-Preco-SRO`) mas retornou erro 403 em toda
   tentativa de acesso direto; a cobrança parece seguir proposta
   comercial individual por participante, sem tabela pública simples
   como a estimativa de mercado disponível para CERC/B3.
2. **Prazo de integração técnica** não foi encontrado especificamente.
3. **O site institucional principal (`crdc.com.br`) bloqueou WebFetch em
   toda tentativa** (erro 403) — o material disponível veio de PDFs
   indexados (manuais de produto, regulamentos) e de descrições de
   terceiros, não da leitura direta das páginas institucionais "A CRDC",
   "Soluções" ou "Parceiros". Uma conversa comercial direta é ainda mais
   necessária aqui do que para as outras candidatas, já que a barreira de
   acesso público é a mais alta de todas as seis.

### Conclusão

CRDC tem a evidência de adequação ao caso de uso mais forte e mais direta
de toda a pesquisa: "Contratos ESC" nomeado nativamente no sistema, não
inferido nem dependente de uma parceria comercial externa. A soma dessa
evidência de produto com a integração automática de saldo devedor
(potencialmente relevante para a decisão pendente sobre amortização
parcial) torna a CRDC uma finalista tão forte quanto a SPC Grafeno — a
diferença é que a SPC Grafeno tem evidência mais forte do lado comercial
(parceria nomeada, desconto setorial, sem mensalidade) enquanto a CRDC
tem evidência mais forte do lado de produto/funcionalidade.

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

## CRDC vs. SPC Grafeno vs. CERC vs. B3: os quatro finalistas, lado a lado

As quatro passam no teste básico (produto para CCB/ESC existe, uso
documentado, API REST). A diferença está no **perfil de trade-off** e,
mais importante, no **tipo de evidência** que sustenta cada uma:

### A favor da CRDC
1. **Evidência de produto mais direta de todas**: "Contratos ESC" é tipo
   de ativo nomeado nativamente no sistema de registro — não uma
   adaptação de produto genérico, não uma parceria comercial externa, é o
   próprio catálogo de ativos reconhecendo ESC.
2. **Integração automática de saldo devedor** — potencialmente relevante
   para a decisão pendente sobre amortização parcial (`DECISOES_PENDENTES.md`,
   item "O que NÃO está bloqueado").
3. **Independência societária protegida por decisão antitruste**
   (CADE recomendou reprovar a compra de 60% pela B3) — contraparte não
   subordinada a outro player maior do mercado, ao menos por ora.
4. Parceria nomeada com a Stand (software especializado em ESC) para
   consulta prévia no processo de crédito.

### A favor da SPC Grafeno
1. **Evidência comercial mais forte**: parceria nomeada com a própria
   associação da indústria (ABRAFESC), com termos publicados.
2. **Maior participação de mercado em CCB** (~50%) entre as seis
   candidatas — reduz o risco de escolher uma registradora com pouca
   adoção do lado credor/investidor.
3. **Caminho de adesão mais simples e nomeado** (e-mail direto via
   ABRAFESC) — sem processo de credenciamento formal documentado.
4. **Modelo de cobrança sem mensalidade** pode ser vantajoso para o volume
   baixo esperado de uma ESC municipal pequena no início de operação.

### A favor da CERC
1. **Onboarding mais leve** — adesão contratual de perfil fintech, sem o
   aparato de comitê de risco/auditoria pré-operacional que a B3 exige.
2. **Prazo de integração estimado menor** (3–6 semanas, fonte de mercado)
   — ainda que não confirmado diretamente com a CERC.
3. Vertical **"Factoring & ESC"** nomeada explicitamente no site.
4. **A candidata mais consistentemente citada** em toda a pesquisa —
   aparece emparelhada tanto com CRDC quanto com B3, dependendo da fonte,
   sugerindo reconhecimento amplo no setor independentemente de qual seja
   a "segunda" registradora citada.

### A favor da B3
1. **Pedigree histórico mais antigo**: processou as primeiras operações
   de ESC do mercado, em setembro de 2019.
2. **Apetite comercial ativo e recente** por fintechs de crédito e bancos
   pequenos/médios, declarado publicamente pela própria B3.
3. **Governança institucional mais robusta** — relevante se, no futuro, o
   OrgCred precisar demonstrar a auditores externos, investidores ou ao
   próprio Banco Central que opera com uma contraparte do mais alto
   padrão do mercado.
4. **Maturidade técnica da plataforma de API** (Swagger/OpenAPI, sandbox
   gratuito, 54 endpoints documentados) mais extensa que a documentação
   pública das demais.

### Leitura prática

Não há uma vencedora óbvia entre CRDC e SPC Grafeno — são o tipo de
evidência mais forte de toda a pesquisa, mas de naturezas diferentes
(produto nativo vs. parceria comercial nomeada). **Recomenda-se contato
comercial com as duas em paralelo como primeira prioridade**, seguido de
CERC (opção mais consistentemente citada, onboarding mais leve) e B3
(mais sólida institucionalmente, mas processo mais pesado). Pontos
específicos a resolver em cada conversa:
- **CRDC**: tarifário (não encontrado publicamente) e se a
  independência societária segue estável após a decisão final do CADE.
- **SPC Grafeno**: roadmap de suporte a webhook (hoje exige polling).
- **CERC**: confirmação de que o onboarding realmente é mais rápido na
  prática, não só no papel.
- **B3**: se o apetite declarado por fintechs pequenas realmente
  simplifica o processo formal de credenciamento na prática.

Nenhuma das quatro foi eliminada pela pesquisa; a escolha final depende
de dados que só saem em conversa comercial direta.

---

## Próximos passos concretos

1. **Contato comercial direto com CRDC** — solicitar proposta via
   `crdc.com.br/solicitar-proposta` (o site bloqueou acesso direto de
   pesquisa, mas o formulário deve estar acessível normalmente para um
   usuário real). Confirmar: (a) tarifário para "Contratos ESC" — não
   encontrado publicamente, (b) se a integração automática de saldo
   devedor está disponível desde o início ou é add-on, (c) prazo real de
   integração técnica, (d) impacto prático da disputa CADE/B3 na
   independência operacional a médio prazo.
2. **Contato comercial direto com SPC Grafeno via ABRAFESC**
   (`comercial@abrafesc.com.br`) — confirmar: (a) tarifário real por
   CCB/evento (o material público só diz "sem mensalidade", sem detalhar
   cobrança por operação), (b) se/quando o suporte a webhook será
   lançado — hoje a API exige polling, o que muda o design do callback em
   `app/routers/contratos.py`, (c) prazo real de integração técnica
   (distinto do prazo comercial de adesão via associação), (d) condições
   específicas do desconto coletivo — quantas ESCs já aderiram pela
   ABRAFESC.
3. **Contato comercial direto com CERC**: confirmar (a) tarifário oficial
   2026 para operações tipo CCB/empréstimo (não recebível de cartão), (b)
   prazo real de integração para uma equipe pequena, (c) se há algum
   requisito de porte/volume mínimo que uma ESC municipal pequena não
   atenderia.
4. **Contato comercial direto com B3 Registradora**: pedir explicitamente
   (a) tarifário oficial para registro de CCB de ESC — não achamos a
   tabela pública detalhada, só estimativa de mercado, (b) se o processo
   de credenciamento (CTRC, auditoria BSM) tem uma trilha simplificada
   para ESCs pequenas dado o apetite comercial declarado por esse
   segmento, (c) prazo real ponta a ponta até produção.
5. **Pergunta direta à Núclea** se atendem ESC e como — depois da pesquisa
   aprofundada, especificamente perguntar: (a) qual produto seria usado
   para registrar CCB de empréstimo de ESC (C3 Registradora? Registro de
   Ativos?), (b) se factoring companies já credenciadas dão precedente
   direto para uma ESC de porte semelhante, (c) requisito mínimo de
   volume/porte, se houver, (d) acesso à documentação técnica completa
   (os manuais MAPX estão bloqueados publicamente).
6. Depois da escolha: implementar a integração em `app/routers/contratos.py`
   (hoje stub) — geração de CCB, chamada à API, callback que preenche
   `operacao_credito.registro_entidade_ref`. Se a escolhida for a SPC
   Grafeno e o webhook ainda não estiver disponível, desenhar o
   preenchimento de `registro_entidade_ref` via polling/job periódico em
   vez de callback assíncrono. Se for a CRDC, avaliar se a integração
   automática de saldo devedor influencia a decisão pendente sobre
   amortização parcial (item "O que NÃO está bloqueado" em
   `DECISOES_PENDENTES.md`).

---

## Fontes consultadas

- [Central de Registro de Direitos Creditórios — CRDC (home)](https://www.crdc.com.br/)
- [A CRDC — Central de Registro de Direitos Creditórios](https://www.crdc.com.br/a-crdc/)
- [CRDC recebe autorização do BC para registro de novos ativos financeiros — Finsiders Brasil](https://finsidersbrasil.com.br/regulamentacao/crdc-recebe-autorizacao-do-bc-para-registro-de-novos-ativos-financeiros/)
- [Banco Central autoriza CRDC da Associação Comercial de SP a ser registradora de duplicatas — ACSP](https://acsp.com.br/publicacao-imprensa/s/banco-central-autoriza-crdc-da-associacao-comercial-de-sp-a-ser-registradora-de-duplicatas)
- [Cade recomenda reprovação da compra da CRDC pela B3 — Gov.br/CADE](https://www.gov.br/cade/pt-br/assuntos/noticias/cade-recomenda-reprovacao-da-compra-da-crdc-pela-b3-e-o-acordo-de-parceria-delas-com-acsp)
- [Manual do Produto — CCB, Sistema de Registro CRDC](https://www.crdc.com.br/wp-content/uploads/2025/04/21154_CRDC_Manual_CCB_v1.0_original.pdf)
- [Manual de Integração — CRDC](https://www.crdc.com.br/wp-content/uploads/2024/11/CRDC_Manual_de_Integracao_SRO-Pessoas-Orientacoes.pdf)
- [Entenda a ESC — Empresa Simples de Crédito — Stand](https://www.stand.com.br/blog/entenda-a-esc-empresa-simples-de-credito/) (cita explicitamente "CRDC e CERC")
- [ESC – Contrato de financiamento com caução de recebíveis — SINFAC-SP](https://www.sinfacsp.com.br/conteudo/esc-contrato-de-financiamento-com-caucao-de-recebiveis)
- Tabela de preços CRDC (`CRDC-Tabela-de-Preco-SRO`) — **inacessível publicamente** (erro 403 em todas as tentativas de fetch direto)
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
