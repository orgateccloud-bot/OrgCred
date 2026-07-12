"""
Router: compliance PLD/FT (Prevenção à Lavagem de Dinheiro e Financiamento
do Terrorismo) e comunicações regulatórias.

STATUS: stub — bloqueado por decisão de negócio pendente.

BLOQUEADOR: não confirmado se a ESC está sujeita a supervisão/reporte COAF
como as demais instituições financeiras, e sob qual órgão regulador (Banco
Central supervisiona ESC como IF, mas o regime de comunicação PLD/FT
aplicável especificamente a ESC não foi verificado juridicamente).
Ver DECISOES_PENDENTES.md.

Escopo pendente após a confirmação regulatória:
- KYC mínimo do tomador (ver app/routers/tomadores.py): verificação de
  Pessoa Exposta Politicamente (PEP) e listas restritivas.
- Comunicação de operações suspeitas ou acima de limiar ao COAF, se aplicável.
- Retenção de registros conforme prazo legal (5 anos é o padrão do setor).
- Trilha de auditoria com autor: capital_ledger.usuario_id já existe no
  schema (migration 002) e o pipeline de autenticação (app/core/auth.py,
  Fase 2) já extrai o usuário do JWT — falta propagar esse user_id para o
  trigger via `SET LOCAL app.user_id` antes de cada commit em
  app.capital_engine.ativar_operacao, e o trigger ler via
  `current_setting('app.user_id', true)` ao inserir em capital_ledger.
  Essa parte NÃO depende de decisão externa — é puramente técnica e pode
  ser implementada a qualquer momento.
"""

from fastapi import APIRouter


router = APIRouter(prefix="/compliance", tags=["compliance"])
