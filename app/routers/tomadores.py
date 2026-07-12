"""
Router: onboarding e KYC de tomadores.

STATUS: stub — não bloqueado por decisão externa, mas não implementado.

Escopo pendente:
- Cadastro de tomador (CNPJ, razão social, porte ME/EPP) com validação de
  enquadramento na LC 167/2019.
- KYC mínimo: consulta de situação cadastral na Receita Federal, verificação
  de listas restritivas (COAF/OFAC) — ver app/routers/compliance.py.
- Gate geográfico: confirmação do município de atuação (municipio_autorizado
  em app.models.Tomador) — hoje inserido manualmente via SQL/admin.
"""

from fastapi import APIRouter


router = APIRouter(prefix="/tomadores", tags=["tomadores"])
