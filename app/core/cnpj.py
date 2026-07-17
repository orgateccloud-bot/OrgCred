"""
Validação de CNPJ — normalização e dígitos verificadores (módulo 11).

Usado no onboarding de tomadores (app/routers/tomadores.py). A validação de
dígito verificador é local e determinística; NÃO substitui a consulta de
situação cadastral na Receita Federal (KYC externo, ainda pendente — ver
DECISOES_PENDENTES.md), apenas garante que o número informado é bem-formado
antes de persistir.
"""

import re


_APENAS_DIGITOS = re.compile(r"\D")

# Pesos do módulo 11 para o 1º e o 2º dígito verificador do CNPJ.
_PESOS_DV1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS_DV2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def normalizar_cnpj(raw: str) -> str:
    """Remove qualquer caractere não numérico (pontos, barra, traço, espaços)."""
    return _APENAS_DIGITOS.sub("", raw or "")


def _dv(base: str, pesos: list[int]) -> str:
    """Calcula um dígito verificador módulo 11 para os dígitos de `base`."""
    soma = sum(int(d) * p for d, p in zip(base, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(cnpj: str) -> bool:
    """
    Retorna True se `cnpj` (já normalizado, só dígitos) é válido:
    14 dígitos, não é uma sequência repetida (ex. 00000000000000) e ambos
    os dígitos verificadores conferem pelo módulo 11.
    """
    if len(cnpj) != 14 or not cnpj.isdigit():
        return False
    # Sequências de um único dígito passam no checksum, mas não são CNPJs reais.
    if cnpj == cnpj[0] * 14:
        return False
    dv1 = _dv(cnpj[:12], _PESOS_DV1)
    dv2 = _dv(cnpj[:12] + dv1, _PESOS_DV2)
    return cnpj[12] == dv1 and cnpj[13] == dv2
