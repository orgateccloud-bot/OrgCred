"""
Leitura de extrato bancário em OFX — função PURA sobre bytes, sem banco.

Este módulo não importa SQLAlchemy, não abre sessão e não conhece
`movimento_bancario`. É deliberado: a decisão de o que fazer com uma linha de
extrato (criar, pular, recusar) é do importador, e misturá-la à interpretação
do arquivo tornaria impossível provar a leitura sem infraestrutura. Todo teste
de parsing roda sem Postgres.

POR QUE UM LEITOR PRÓPRIO, E NÃO `xml.etree` NEM UMA BIBLIOTECA NOVA
--------------------------------------------------------------------
Existem dois OFX, e os bancos brasileiros emitem os dois:

  - OFX 1.x (o comum aqui, versões 102/103/151) é SGML, NÃO é XML. Os
    elementos-folha vêm SEM tag de fechamento — `<TRNAMT>1500.00` termina na
    quebra de linha — e o arquivo começa com um cabeçalho `CHAVE:VALOR` que
    não é markup nenhum. `xml.etree.ElementTree` não lê isso: morre no
    cabeçalho e, se sobrevivesse, morreria na primeira folha aberta.

  - OFX 2.x é XML bem-formado, com declaração `<?xml?>` e um PI `<?OFX ...?>`.

O VOCABULÁRIO DE TAGS DOS DOIS É O MESMO (STMTTRN, FITID, DTPOSTED, TRNAMT,
BANKACCTFROM...) — a diferença é só a sintaxe de fechamento. Um varredor de
tags tolerante, que aceita tanto `<TAG>valor</TAG>` quanto `<TAG>valor` até o
próximo `<`, cobre os dois dialetos com UM caminho de código. Usar ElementTree
para o 2.x e um varredor para o 1.x seria manter duas leituras do mesmo
formato, com o risco clássico de corrigir um bug só num dos lados.

Por isso: NENHUMA DEPENDÊNCIA NOVA. Só `re`, `html`, `decimal` e `datetime` da
biblioteca padrão. A alternativa considerada foi `ofxparse` — que resolveria o
1.x, mas traz `beautifulsoup4` + `lxml` junto (parser C na imagem, mais
superfície de CVE para auditar num sistema cuja defesa é a rastreabilidade),
está sem release desde 2022 e devolve `float` para valor monetário. Float em
valor de extrato é justamente o que não se pode aceitar aqui: o valor entra
numa coluna `numeric(14,2)` e é comparado com `parcela.valor_total` pelo banco
na hora da baixa.

O QUE ESTE LEITOR RECUSA (OfxInvalido) — e o que ele apenas devolve vazio
------------------------------------------------------------------------
Recusa o arquivo inteiro quando não dá para confiar no que leu: sem a tag
`<OFX>`, com `<STMTTRN>` não fechado (arquivo truncado — ler tolerante ali
misturaria o FITID de uma linha com o valor da seguinte), com transação sem
FITID/DTPOSTED/TRNAMT, com data ou valor ilegíveis.

NÃO recusa arquivo sem transação nenhuma: extrato de período sem movimento é
um extrato válido, e o importador deve relatar "0 lidas" em vez de dizer ao
operador que o arquivo do banco dele está corrompido.

FITID REPETIDO DENTRO DO MESMO ARQUIVO tampouco é recusado aqui: o leitor
devolve o que está escrito, fielmente, e é o importador que decide (e conta) a
deduplicação. Um leitor que já filtra esconde do relatório uma anomalia real
do arquivo do banco.
"""

import html
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterator, List, NamedTuple, Optional, Tuple, Union


class OfxInvalido(ValueError):
    """Arquivo não é um OFX legível — não é regra de negócio, é entrada ruim.

    Herda de ValueError e não de RegraNegocioViolada de propósito: nenhum
    invariante do banco foi violado, e não há SQLSTATE da classe OC para isto.
    Quem chama traduz para 422 com a mensagem, que é o que o operador precisa
    para saber que o arquivo é que está errado.
    """


class TransacaoOfx(NamedTuple):
    """Uma linha de extrato, como escrita no arquivo.

    `fitid` é o identificador que o banco dá à transação — é ele que vai para
    `movimento_bancario.documento` (UNIQUE desde a migration 009) e é por isso
    que reimportar o mesmo extrato é idempotente por construção.

    `conta` é o par BANKID/ACCTID do statement a que a transação pertence, ou
    None quando o arquivo não o declara (acontece em OFX de cartão, que só tem
    ACCTID, e em exportações capadas).
    """

    fitid: str
    data_movimento: date
    valor: Decimal
    tipo: Optional[str]
    descricao: Optional[str]
    conta: Optional[str]


class ExtratoOfx(NamedTuple):
    """O arquivo inteiro: as contas que ele declara e as transações que traz.

    `contas` existe separado das transações porque um extrato SEM movimento
    ainda diz de qual conta ele é — e é essa a informação que o operador
    precisa ver ao importar um arquivo que não criou nada."""

    contas: Tuple[str, ...]
    transacoes: Tuple[TransacaoOfx, ...]


# Tag SGML/XML: `<TAG>`, `</TAG>`, com espaço tolerado. O `?` de `<?xml ...?>`
# e de `<?OFX ...?>` não casa com a classe de caracteres, então as declarações
# do OFX 2.x são ignoradas sem tratamento especial.
_TAG_RE = re.compile(r"<\s*(/?)\s*([A-Za-z0-9_.]+)\s*>")
_NAO_DIGITO_RE = re.compile(r"\D")

# Campos lidos de dentro de <STMTTRN>. Os demais (CHECKNUM, REFNUM, PAYEE...)
# são ignorados de propósito: o que não vira coluna não vira dado meio-gravado.
_CAMPOS_TRANSACAO = frozenset({"FITID", "DTPOSTED", "TRNAMT", "MEMO", "NAME", "TRNTYPE"})

# A especificação OFX limita FITID a 255 caracteres. Acima disso o arquivo está
# corrompido ou não é OFX — e truncar seria pior que recusar: destruiria
# exatamente a identidade que torna a reimportação idempotente.
FITID_MAX = 255

# Cabeçalho do OFX 1.x (SGML): linhas CHAVE:VALOR antes do `<OFX>`.
_CHARSET_SGML_RE = re.compile(rb"^\s*CHARSET\s*:\s*([\w-]+)\s*$", re.IGNORECASE | re.MULTILINE)
_ENCODING_SGML_RE = re.compile(rb"^\s*ENCODING\s*:\s*([\w-]+)\s*$", re.IGNORECASE | re.MULTILINE)
# Declaração do OFX 2.x (XML).
_ENCODING_XML_RE = re.compile(rb"""encoding\s*=\s*["']([\w-]+)["']""", re.IGNORECASE)

# CHARSET do cabeçalho 1.x usa nomes que não são nomes de codec Python.
_CHARSET_PARA_CODEC = {
    "1252": "cp1252",
    "8859-1": "iso-8859-1",
    "ISO-8859-1": "iso-8859-1",
    "LATIN1": "iso-8859-1",
    "UTF-8": "utf-8",
}


def _decodificar(dados: bytes) -> str:
    """Bytes -> texto, respeitando o que o próprio arquivo declara.

    Importa mais do que parece: `MEMO` traz nome de pagador, e banco brasileiro
    emite OFX 1.x em cp1252 com frequência. Decodificar como UTF-8 na marra
    quebra em "PAGAMENTO JOSÉ" — e um `errors='replace'` silencioso gravaria a
    descrição corrompida no banco, onde é imutável (OC012) e não se corrige.

    A ordem é: BOM, declaração do XML (2.x), cabeçalho SGML (1.x), e só então
    tentativa. O fallback tenta UTF-8 estrito primeiro e cai para cp1252, que
    é single-byte e nunca levanta — de modo que esta função não tem caminho de
    falha por encoding.
    """
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados.decode("utf-8-sig")

    cabecalho = dados[:1024]
    declarados: List[str] = []

    casado_xml = _ENCODING_XML_RE.search(cabecalho)
    if casado_xml:
        declarados.append(casado_xml.group(1).decode("ascii", "ignore"))

    casado_enc = _ENCODING_SGML_RE.search(cabecalho)
    if casado_enc:
        # ENCODING:USASCII vem junto de CHARSET:1252 no OFX 1.x; quem manda
        # sobre os acentos é o CHARSET, então USASCII é ignorado aqui.
        bruto = casado_enc.group(1).decode("ascii", "ignore").upper()
        if bruto not in ("USASCII", "NONE"):
            declarados.append(bruto)

    casado_charset = _CHARSET_SGML_RE.search(cabecalho)
    if casado_charset:
        bruto = casado_charset.group(1).decode("ascii", "ignore").upper()
        declarados.append(_CHARSET_PARA_CODEC.get(bruto, bruto))

    for nome in declarados:
        try:
            return dados.decode(nome)
        except (LookupError, UnicodeDecodeError):
            # Codec inexistente ou declaração mentirosa — cai para a tentativa
            # seguinte. Arquivo que mente sobre o próprio encoding é comum o
            # bastante para não valer uma recusa.
            continue

    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace")


def _tokens(texto: str) -> Iterator[Tuple[bool, str, str]]:
    """Varre o texto e devolve (é_fechamento, TAG, conteúdo).

    O conteúdo de uma tag é tudo que vem depois dela até o próximo `<` — é
    essa regra, e só ela, que faz o mesmo código ler `<TRNAMT>10.00</TRNAMT>`
    (XML) e `<TRNAMT>10.00\\n<FITID>...` (SGML). Em XML o conteúdo depois da
    tag de fechamento é espaço em branco, e quem consome ignora fechamento de
    folha.

    `html.unescape` aqui e não no consumidor: entidades (`&amp;`, `&lt;`) são
    sintaxe do arquivo, não dado, e desfazê-las uma vez só evita que um campo
    novo esqueça de fazê-lo.

    A BUSCA DO PRÓXIMO `<` É FEITA NO TEXTO INTEIRO, com deslocamento, e NUNCA
    sobre uma fatia `texto[fim:]`. A diferença não é estilo: fatiar copia todo o
    resto do arquivo A CADA TAG, o que torna a leitura QUADRÁTICA no tamanho do
    extrato. Medido nesta base, a versão com fatia levava 95 s para um arquivo
    de 3 MB com 24.000 transações — dentro dos dois tetos do endpoint (8 MiB e
    50.000 transações), ou seja, o "timeout silencioso" que os tetos existem
    para impedir acontecia ANTES do INSERT, na leitura. Com `find` deslocado a
    varredura é linear e o mesmo arquivo lê em menos de 1 s.
    """
    for casado in _TAG_RE.finditer(texto):
        inicio = casado.end()
        corte = texto.find("<", inicio)
        conteudo = texto[inicio:] if corte == -1 else texto[inicio:corte]
        yield bool(casado.group(1)), casado.group(2).upper(), html.unescape(conteudo).strip()


def _ler_data(bruto: str) -> date:
    """DTPOSTED -> date. Só a parte da data importa para o extrato.

    O formato do OFX é `YYYYMMDD` podendo vir com hora e fuso
    (`20260115120000.000[-3:BRT]`). O sufixo entre colchetes é cortado ANTES
    de filtrar dígitos — senão o `3` de `[-3:BRT]` entraria na contagem.
    """
    digitos = _NAO_DIGITO_RE.sub("", bruto.split("[", 1)[0])
    if len(digitos) < 8:
        raise OfxInvalido(f"DTPOSTED '{bruto}' não tem uma data no formato AAAAMMDD.")
    try:
        return date(int(digitos[0:4]), int(digitos[4:6]), int(digitos[6:8]))
    except ValueError as exc:
        raise OfxInvalido(f"DTPOSTED '{bruto}' não é uma data válida.") from exc


def _ler_valor(bruto: str) -> Decimal:
    """TRNAMT -> Decimal. Nunca float.

    A especificação manda ponto decimal e proíbe separador de milhar, mas
    exportação de banco brasileiro às vezes sai com vírgula; aceitar vírgula
    QUANDO NÃO HÁ PONTO é tolerância segura — com os dois presentes, seria
    adivinhação sobre qual é o separador de milhar, e adivinhar valor monetário
    é o que este módulo existe para não fazer.

    `is_finite` não é preciosismo. `Decimal('NaN')` e `Decimal('Infinity')` são
    literais VÁLIDOS de Decimal, o tipo `numeric` do Postgres ACEITA NaN, e —
    ao contrário do IEEE 754 — o Postgres ordena NaN como MAIOR que qualquer
    número: `'NaN'::numeric > 0` é TRUE. Ou seja, um NaN vindo de um TRNAMT
    atravessaria o check `movimento_valor_positivo` da migration 009, seria
    aceito como crédito, contaminaria toda soma da carteira e ainda cobriria
    qualquer parcela na comparação `v_movimento.valor < v_parcela.valor_total`
    de `fn_baixar_parcela` — baixa com lastro de nada. Recusar na leitura é
    onde custa uma linha.
    """
    limpo = bruto.strip().replace(" ", "").lstrip("+")
    if "," in limpo and "." not in limpo:
        limpo = limpo.replace(",", ".")
    try:
        valor = Decimal(limpo)
    except InvalidOperation as exc:
        raise OfxInvalido(f"TRNAMT '{bruto}' não é um valor numérico.") from exc
    if not valor.is_finite():
        raise OfxInvalido(f"TRNAMT '{bruto}' não é um valor finito.")
    return valor


def _descricao(nome: Optional[str], memo: Optional[str]) -> Optional[str]:
    """NAME + MEMO viram uma descrição só.

    Os dois carregam coisas diferentes e ambas servem à conciliação: NAME
    costuma trazer a contraparte (quem pagou) e MEMO o detalhe do lançamento.
    Ficar só com o MEMO — o caminho mais curto — jogaria fora justamente o
    nome de quem depositou, que é o que o operador usa para achar o tomador.
    Iguais, um só; ausentes, None (e não string vazia, que ocuparia a coluna
    fingindo conteúdo).
    """
    partes = [p for p in (nome, memo) if p]
    if not partes:
        return None
    if len(partes) == 2 and partes[0] == partes[1]:
        return partes[0]
    return " — ".join(partes)


def _formatar_conta(bankid: Optional[str], acctid: Optional[str]) -> Optional[str]:
    """BANKID + ACCTID -> "banco/conta". Só ACCTID (cartão) vira só a conta."""
    if bankid and acctid:
        return f"{bankid}/{acctid}"
    return acctid or bankid or None


def _montar_transacao(campos: Dict[str, str], conta: Optional[str]) -> TransacaoOfx:
    """Fecha um <STMTTRN>, exigindo o mínimo que faz dele uma transação.

    Os três obrigatórios não são escolha de estilo: sem FITID não há
    idempotência (é ele que vira o `documento` UNIQUE), sem DTPOSTED não há
    data de movimento e sem TRNAMT não há valor. Faltando qualquer um, o
    arquivo inteiro é recusado — importar as outras linhas e omitir esta
    criaria um extrato parcial que ninguém saberia estar incompleto.
    """
    fitid = campos.get("FITID")
    if not fitid:
        raise OfxInvalido("Transação sem FITID: não há como identificar a linha do extrato.")
    if len(fitid) > FITID_MAX:
        raise OfxInvalido(f"FITID com {len(fitid)} caracteres excede o limite de {FITID_MAX}.")

    dtposted = campos.get("DTPOSTED")
    if not dtposted:
        raise OfxInvalido(f"Transação {fitid} sem DTPOSTED.")

    trnamt = campos.get("TRNAMT")
    if not trnamt:
        raise OfxInvalido(f"Transação {fitid} sem TRNAMT.")

    return TransacaoOfx(
        fitid=fitid,
        data_movimento=_ler_data(dtposted),
        valor=_ler_valor(trnamt),
        tipo=campos.get("TRNTYPE"),
        descricao=_descricao(campos.get("NAME"), campos.get("MEMO")),
        conta=conta,
    )


def ler_ofx(dados: Union[bytes, str]) -> ExtratoOfx:
    """Lê um OFX 1.x (SGML) ou 2.x (XML) e devolve o que está escrito nele.

    Uma passada só sobre o texto. A conta corrente é rastreada enquanto a
    varredura anda: `<BANKACCTFROM>`/`<CCACCTFROM>` zera o par e o `<ACCTID>`
    o fecha, de modo que um arquivo com VÁRIOS statements (duas contas no mesmo
    OFX) associa cada transação à conta do bloco em que ela está, sem exigir
    uma segunda estrutura de agrupamento.

    Zerar no ABRIR do agregado, e não só ao fechar, é o que impede o caso
    silencioso: um segundo statement sem ACCTID herdaria a conta do primeiro e
    gravaria proveniência errada — e proveniência errada é pior que ausente.
    """
    texto = _decodificar(dados) if isinstance(dados, bytes) else dados

    transacoes: List[TransacaoOfx] = []
    contas: List[str] = []
    bankid: Optional[str] = None
    acctid: Optional[str] = None
    conta_atual: Optional[str] = None
    pendente: Optional[Dict[str, str]] = None
    viu_ofx = False

    for fechamento, tag, conteudo in _tokens(texto):
        if tag == "OFX":
            viu_ofx = True
            continue

        if fechamento:
            if tag == "STMTTRN":
                if pendente is None:
                    raise OfxInvalido("</STMTTRN> sem <STMTTRN> correspondente.")
                transacoes.append(_montar_transacao(pendente, conta_atual))
                pendente = None
            continue

        if tag == "STMTTRN":
            # Agregado não fechado. Em OFX (1.x SGML e 2.x XML) o fechamento de
            # AGREGADO é obrigatório — só as folhas podem vir abertas. Um
            # <STMTTRN> novo com outro pendente significa arquivo truncado ou
            # corrompido, e seguir tolerante aqui misturaria campos de duas
            # linhas do banco numa transação que não existe.
            if pendente is not None:
                raise OfxInvalido("<STMTTRN> aberto dentro de outro: o arquivo está truncado.")
            pendente = {}
            continue

        if pendente is not None:
            if tag in _CAMPOS_TRANSACAO and conteudo:
                pendente[tag] = conteudo
            continue

        if tag in ("BANKACCTFROM", "CCACCTFROM"):
            bankid = acctid = conta_atual = None
        elif tag == "BANKID":
            bankid = conteudo or None
        elif tag == "ACCTID":
            acctid = conteudo or None
            conta_atual = _formatar_conta(bankid, acctid)
            if conta_atual and conta_atual not in contas:
                contas.append(conta_atual)

    if not viu_ofx:
        raise OfxInvalido("Arquivo não contém a tag <OFX>: não é um extrato OFX.")
    if pendente is not None:
        raise OfxInvalido("<STMTTRN> não foi fechado: o arquivo termina no meio de uma transação.")

    return ExtratoOfx(contas=tuple(contas), transacoes=tuple(transacoes))
