"""
O contrato de erro entre o backend e o dicionário do frontend, DERIVADO da fonte
da verdade — não de uma lista digitada à mão.

POR QUE ESTE TESTE MORA NO BACKEND: a fonte da verdade dos códigos de erro é
`PGCODE_MAP` (app/core/db_errors.py), Python. O dicionário do frontend
(frontend/src/api/errors.ts) precisa ter uma mensagem para cada código que o
backend consegue EMITIR — e quem sabe o conjunto emissível é o Python. O teste
de catálogo que existia no frontend (errors.test.ts) re-digitava a lista de
códigos: acrescentar um SQLSTATE novo ao backend não o deixava vermelho, então a
tela passava a mostrar o texto cru do trigger sem ninguém perceber. Foi
exatamente o que aconteceu com OC027.

Aqui a lista NÃO é digitada: ela é lida de `PGCODE_MAP` mais o punhado de
códigos que não vêm do banco. Um código novo no backend quebra este teste até o
frontend ganhar a mensagem — que é a única forma de a garantia valer.
"""

import re
from pathlib import Path

from app.core.db_errors import PGCODE_MAP


_ERRORS_TS = Path(__file__).resolve().parent.parent / "frontend" / "src" / "api" / "errors.ts"

# Códigos que o backend emite e que NÃO vêm do banco (não estão no PGCODE_MAP):
# escritos à mão nos handlers de app/main.py e na exceção MovimentoDuplicado.
# São poucos e mudam raramente; ficam aqui explícitos porque não há um mapa
# Python de onde derivá-los. Se um novo for criado, some-o aqui — é o único
# ponto de manutenção manual, e é minúsculo perto da lista de 20+ que estava no
# frontend.
CODIGOS_NAO_BANCO = frozenset(
    {
        "TOKEN_AUSENTE",
        "TOKEN_INVALIDO",
        "PERMISSAO_NEGADA",
        "OC429",
        "MOVIMENTO_DUPLICADO",
    }
)

# Buracos DELIBERADOS: existem no banco mas NÃO no PGCODE_MAP porque nenhum
# endpoint os alcança (não há PATCH/PUT/DELETE que os dispare). O frontend
# documenta os três como não-traduzidos de propósito; este teste não os exige e
# recusa que apareçam, para o buraco não ser tapado por engano.
BURACOS_DELIBERADOS = frozenset({"OC006", "OC020", "OC021"})


def _chaves_do_frontend() -> set[str]:
    """Extrai as chaves de MENSAGENS_POR_CODIGO de errors.ts.

    Lê o arquivo em vez de importar TS: o backend não roda o bundler, e o que
    interessa é o CONTRATO (quais códigos têm mensagem), não a execução. O regex
    casa `  OC001:` e `  MOVIMENTO_DUPLICADO:` no início da linha, dentro do
    objeto — o mesmo formato que o prettier garante.
    """
    texto = _ERRORS_TS.read_text(encoding="utf-8")
    corpo = texto.split("MENSAGENS_POR_CODIGO", 1)[1]
    corpo = corpo.split("\n}", 1)[0]
    return set(re.findall(r"^\s{2}([A-Z][A-Z0-9_]+):", corpo, re.MULTILINE))


def _emissiveis() -> set[str]:
    return set(PGCODE_MAP.keys()) | CODIGOS_NAO_BANCO


def test_todo_codigo_emissivel_tem_mensagem_no_frontend() -> None:
    """A direção que importa: se o backend pode emitir, a tela tem que saber
    dizer. Sem isto, o operador recebe o texto técnico do trigger."""
    faltando = _emissiveis() - _chaves_do_frontend()
    assert not faltando, (
        f"Códigos que o backend emite mas o frontend não traduz: {sorted(faltando)}. "
        f"Adicione a mensagem em {_ERRORS_TS.as_posix()}."
    )


def test_o_frontend_nao_tem_mensagem_morta() -> None:
    """A outra direção: uma mensagem para um código que o backend nunca emite é
    código morto que finge cobertura. O único jeito de um código estar no
    frontend é ser emissível."""
    sobrando = _chaves_do_frontend() - _emissiveis()
    assert not sobrando, (
        f"Mensagens no frontend para códigos que o backend não emite: {sorted(sobrando)}. "
        "Ou o código entrou no PGCODE_MAP e o teste precisa vê-lo, ou a mensagem é morta."
    )


def test_os_buracos_deliberados_seguem_buracos() -> None:
    """OC006/OC020/OC021 existem no banco e são, de propósito, inalcançáveis por
    endpoint. Se um deles aparecer no PGCODE_MAP ou no frontend, foi tapado —
    o que pode ser certo, mas tem que ser uma DECISÃO, não um deslize. Este
    teste força a decisão a passar por aqui."""
    no_map = BURACOS_DELIBERADOS & set(PGCODE_MAP.keys())
    assert not no_map, (
        f"{sorted(no_map)} eram buracos deliberados e entraram no PGCODE_MAP. "
        "Se um endpoint passou a alcançá-los, atualize esta lista e o frontend juntos."
    )
    no_front = BURACOS_DELIBERADOS & _chaves_do_frontend()
    assert not no_front, f"{sorted(no_front)} são buracos deliberados e não devem ter mensagem."
