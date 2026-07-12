# Pesquisa: entidade registradora para o OrgCred

**Data:** 2026-07-12 · **Contexto:** bloqueador #1 de `DECISOES_PENDENTES.md` —
qual entidade registradora usar para cumprir o Art. 5º §3º da LC 167/2019.
Este documento reúne o levantamento feito para embasar a decisão; **não
substitui** confirmação comercial direta com a entidade escolhida
(tarifário atual, SLA contratual, prazo de integração real).

---

## Resumo executivo

**CERC é a recomendação**, com **B3 Registradora** como segunda opção —
essas duas são consistentemente citadas por fornecedores independentes de
software para ESC (não é só marketing da própria CERC) como o par padrão de
mercado para este segmento. **TAG não é adequada**: seu produto é
especificamente recebíveis de cartão (arranjo de pagamento), não
registro de operações de crédito/CCB. **Núclea é tecnicamente capaz** mas
não tem nenhum caso de uso ESC documentado publicamente — precisa de
confirmação direta se ela atende esse segmento na prática.

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

| Critério | **CERC** | **Núclea (ex-CIP)** | **TAG Infraestrutura** |
|---|---|---|---|
| **Fundação** | 2015 | CIP existe há 20+ anos; rebatizada Núclea | 2018/2020 |
| **Controlador** | Independente (fintech de infra) | Consórcio de instituições financeiras | Grupo Stone Co. |
| **Produto para CCB/empréstimo/ESC** | ✅ Sim — categoria explícita "Financeiros" cobrindo CCBs, contrato de crédito, mútuos, títulos bancários, crédito consignado; site lista "Factoring & ESC" como solução nomeada | ⚠️ Tem "Registro de Ativos" e "SRCC" (crédito consignado) — não encontrei confirmação específica de produto para ESC/CCB genérico | ❌ Não — produto é especificamente recebíveis de arranjo de pagamento (cartão); "vendas com voucher e Pix não são consideradas na registradora" |
| **Uso documentado por terceiros em software ESC** | ✅ Citada por 3 fornecedores independentes de software ESC (APPESC/Decisão Sistemas, Fomenti, Stand) como registradora padrão do segmento, ao lado da B3 | ❌ Nenhum caso de uso ESC encontrado em fontes independentes | ❌ Nenhum caso de uso ESC encontrado em fontes independentes |
| **Certificações de segurança** | ISO 27001, 27017, 27018 | ISO 27001, 22301 | Não encontrado nesta pesquisa |
| **Clientes conhecidos** | PagSeguro, Mercado Pago, MagaluPay, iFood, Vindi | Cielo, Rede, Getnet, SafraPay | Stone Co., PagarMe, Yapay, Rappi |
| **Integração técnica** | API REST documentada (Apiary/CERC Integração Agente de Registro); ERP autenticado com certificado digital envia título via API padronizada | API, arquivo ou portal, "conforme necessidade de cada entidade" — não encontrei doc técnica pública equivalente | Documentação técnica existe (`docs.taginfraestrutura.com.br`) mas focada em recebíveis de arranjo de pagamento |
| **Prazo de integração estimado** | 3 a 6 semanas (fonte: Celcoin/mercado, não confirmado com a CERC diretamente) | Não encontrado | Não aplicável (produto errado para o caso de uso) |
| **Custo por título registrado** | R$ 0,30 a R$ 1,50 por título; R$ 0,15 a R$ 0,80 por evento subsequente (amortização, liquidação, protesto) — faixa de mercado, **não é tarifário oficial confirmado** | Não encontrado nesta pesquisa | Não aplicável |
| **Posição de mercado para ESC** | **Registradora de referência do segmento**, junto com B3 | Grande player geral, mas sem evidência de foco em ESC | Fora do escopo — produto não serve o caso de uso |

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

## Por que CERC (e B3 como plano B) faz sentido

1. **Único software de mercado dedicado a ESC** (APPESC, da Decisão
   Sistemas) integra nomeadamente com CERC e B3 — "os dois principais
   registros do mercado" para esse segmento, segundo três fontes
   independentes (Decisão Sistemas, Fomenti, Stand).
2. CERC lista explicitamente **"Factoring & ESC"** como categoria de
   solução em seu próprio site — não é um produto genérico adaptado, é uma
   vertical nomeada.
3. **API REST documentada publicamente** (Apiary) — compatível com o
   padrão de integração já usado no resto do OrgCred (FastAPI + REST).
4. Faixa de custo (R$ 0,30–1,50/título) é baixa o suficiente para não ser
   um fator decisório dado o volume esperado de uma ESC municipal pequena.

---

## Próximos passos concretos

1. **Contato comercial direto com CERC**: confirmar (a) tarifário oficial
   2026 para operações tipo CCB/empréstimo (não recebível de cartão), (b)
   prazo real de integração para uma equipe pequena, (c) se há algum
   requisito de porte/volume mínimo que uma ESC municipal pequena não
   atenderia.
2. **Contato comercial com B3 Registradora** em paralelo, como
   comparação/plano B — a B3 aparece emparelhada com a CERC em toda
   literatura de mercado sobre ESC, mas não foi pesquisada em detalhe
   nesta rodada (fora do escopo original da pergunta, que pediu CERC/
   Núclea/TAG).
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
- [Sistema de Registro de Operações — Núclea](https://www.nuclea.com.br/sistema-de-registro-de-operacoes/)
- [Registro de Ativos — Núclea](https://www.nuclea.com.br/registro-de-ativos/)
- [Registro de Crédito Consignado — Núclea](https://www.nuclea.com.br/registro-de-credito-consignado/)
- [Núclea CIP: conheça a história e evolução da empresa](https://www.nuclea.com.br/nuclea-cip-conheca-a-historia-e-evolucao-da-empresa/)
- [Registro de Recebíveis de Arranjo de Pagamento — TAG](https://docs.taginfraestrutura.com.br/docs/registro-arranjo)
- [Recebíveis de cartão — TAG](https://www.taginfraestrutura.com.br/recebiveis-cartao)
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
número final.
