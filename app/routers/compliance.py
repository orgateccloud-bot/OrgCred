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

Trilha de auditoria com autor: JÁ IMPLEMENTADA (Fase 6, migration 004) —
app.core.security.get_current_user resolve o usuário autenticado a partir
do JWT (Zero-Trust: papel/ativo vêm do banco, não de claims do token),
app.capital_engine.ativar_operacao propaga usuario_id via
`SET LOCAL app.user_id`, e o trigger lê via
`current_setting('app.user_id', true)` ao inserir em capital_ledger.
"""

from fastapi import APIRouter


router = APIRouter(prefix="/compliance", tags=["compliance"])
