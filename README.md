# OrgCred — estrutura do projeto

Módulo de microcrédito (ESC) da ORGATEC. **Single-tenant** — uma única
ESC, controle de acesso por papel (`admin`/`operador`), sem `org_id`
multi-tenant como OrgConc/OrgAudi. Essa é uma decisão confirmada, não
um esquecimento: o OrgCred é a operação de crédito da própria ORGATEC,
não uma plataforma para clientes terceiros.

## Estrutura

```
orgcred/
├── migrations/
│   ├── 001_initial_schema.sql      # schema completo + trigger do teto de capital
│   ├── 002_usuarios_papeis.sql     # usuário/papel (admin/operador)
│   ├── 003_hardening_capital.sql   # correções da revisão: lock, estados, capital
│   ├── 004_auditoria_autor.sql     # autor (usuario_id) nos eventos do ledger
│   ├── 005_ledger_imutavel.sql     # append-only + hash-chain do ledger
│   └── 006_capital_comprometido_renegociacao.sql  # inadimplente compromete; novação
├── app/
│   ├── main.py                     # monta a API, registra todos os routers
│   ├── db.py                       # sessão SQLAlchemy real
│   ├── models.py                   # models espelhando o schema
│   ├── capital_engine.py           # ÚNICA lógica de negócio real implementada
│   ├── core/
│   │   └── config.py               # settings via variável de ambiente
│   └── routers/
│       ├── capital.py              # ✅ implementado e testado
│       ├── operacoes.py            # ✅ implementado e testado
│       ├── tomadores.py            # ✅ cadastro implementado (KYC externo pendente)
│       ├── contratos.py            # ⛔ stub — BLOQUEADO (entidade registradora)
│       ├── fiscal.py               # ⛔ stub — parcialmente bloqueado (IOF)
│       ├── compliance.py           # ⛔ stub — PLD/COAF
│       └── cobranca.py             # ✅ inadimplência/regularização/renegociação (novação atômica)
└── tests/
    ├── test_capital_invariant.sh   # regressão: 7 cenários contra Postgres real
    └── test_concorrencia.py        # prova do teto sob transações simultâneas
```

## O que está REALMENTE testado (não só revisado)

O motor de capital foi validado contra Postgres 16 real, não só lido:

```bash
createdb orgcred_dev   # requer usuário com permissão de criar banco
psql -d orgcred_dev -f migrations/001_initial_schema.sql
psql -d orgcred_dev -f migrations/002_usuarios_papeis.sql
./tests/test_capital_invariant.sh orgcred_dev
```

Os 4 cenários que o script cobre, todos confirmados rodando de verdade:

1. Operação dentro do capital disponível → ativa normalmente
2. Operação que excede o capital disponível → **bloqueada pelo banco**, com a
   mensagem exata do Art. 5º, LC 167/2019
3. Tomador fora do município autorizado → **bloqueada pelo banco**, Art. 1º
4. Liquidar uma operação → libera capital para uma operação que antes seria rejeitada

Isso muda a entrega anterior: antes eu tinha escrito o trigger e revisado a
sintaxe, mas nunca tinha rodado contra um banco real. Agora rodou.

## O que ainda não existe

- Autenticação/autorização real (a tabela `usuario` existe, o enforcement de
  papel na API não)
- Onboarding/KYC, contratos, fiscal, compliance, cobrança — todos stubs
  documentados em seus próprios arquivos, não implementados
- Os três bloqueadores do documento de arquitetura (entidade registradora,
  regime de IOF, capital social inicial) continuam de pé — `contratos.py` e
  parte de `fiscal.py` dependem diretamente deles

## Rodando localmente

```bash
pip install -r requirements.txt --break-system-packages
cp .env.example .env   # editar com credenciais reais
uvicorn app.main:app --reload
# docs interativas em /docs
```
