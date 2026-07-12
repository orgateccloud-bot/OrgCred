"""
Router: geração e registro de contratos de crédito (CCB).

STATUS: stub — BLOQUEADO por decisão de negócio pendente.

BLOQUEADOR: escolha da entidade registradora (Art. 5º §3º, LC 167/2019).
As operações de crédito de uma ESC precisam ser registradas em entidade
apodada pelo Banco Central antes da ativação — o trigger fn_check_teto_capital
já enforcement isso via operacao_credito.registro_entidade_ref (SQLSTATE
OC004), mas HOJE esse campo é preenchido manualmente; não há integração real.

Candidatas identificadas (não confirmadas): CERC, Núclea (ex-CIP), TAG.
Decisão pendente do dono do negócio — ver DECISOES_PENDENTES.md.

Escopo pendente após a decisão:
- Geração de CCB (Cédula de Crédito Bancário) a partir dos dados da operação.
- Integração com a API da entidade escolhida para registro.
- Callback/webhook de confirmação de registro -> preenche
  registro_entidade_ref e libera o POST /operacoes/{id}/ativar.
- Assinatura eletrônica do contrato (ICP-Brasil ou similar).
"""

from fastapi import APIRouter


router = APIRouter(prefix="/contratos", tags=["contratos"])
