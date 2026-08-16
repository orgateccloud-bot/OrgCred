"""
Testes do leitor de OFX (app/ofx.py).

NENHUM DELES ABRE CONEXÃO. É a prova prática de que `ler_ofx` é função pura
sobre bytes: o arquivo inteiro roda sem Postgres, sem fixture de banco e sem
TestClient — que é exatamente o motivo de o parser não conhecer SQLAlchemy.
A importação (o que vira linha em `movimento_bancario`) é provada em
tests/test_router_cobranca.py, contra banco de verdade.

Os fixtures são montados aqui, inline, e não guardados como arquivos: um OFX
de exemplo em disco é um dado opaco que ninguém revisa, e a coisa que estes
testes precisam deixar legível é justamente a FORMA do arquivo — quais tags
vêm fechadas, quais não, onde a conta é declarada.
"""

import time
from datetime import date
from decimal import Decimal

import pytest

from app.ofx import OfxInvalido, ler_ofx


# ---------------------------------------------------------------------
# Montadores de arquivo
# ---------------------------------------------------------------------
# Cabeçalho real de OFX 1.x: linhas CHAVE:VALOR que NÃO são markup, seguidas de
# uma linha em branco. É a primeira coisa que faz `xml.etree` recusar o arquivo
# — e a razão de este projeto ter leitor próprio.
_CABECALHO_SGML = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

"""


def _transacao_sgml(
    fitid: str,
    valor: str,
    dtposted: str = "20260115120000[-3:BRT]",
    tipo: str = "CREDIT",
    nome: str = "PADARIA TESTE ME",
    memo: str = "TED RECEBIDA",
) -> str:
    """Um <STMTTRN> no dialeto 1.x: agregado fechado, folhas ABERTAS."""
    return f"""<STMTTRN>
<TRNTYPE>{tipo}
<DTPOSTED>{dtposted}
<TRNAMT>{valor}
<FITID>{fitid}
<NAME>{nome}
<MEMO>{memo}
</STMTTRN>
"""


def ofx_sgml(transacoes: str, bankid: str = "001", acctid: str = "12345-6") -> str:
    """OFX 1.x completo, com os agregados que um extrato de banco traz de fato
    (CURDEF, LEDGERBAL, DTSTART/DTEND) — que o leitor tem que ignorar sem
    tropeçar."""
    return f"""{_CABECALHO_SGML}<OFX>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>{bankid}
<ACCTID>{acctid}
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260101
<DTEND>20260131
{transacoes}</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>1500.00
<DTASOF>20260131
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
"""


OFX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<?OFX OFXHEADER="200" VERSION="200" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>
<OFX>
  <BANKMSGSRSV1>
    <STMTTRNRS>
      <STMTRS>
        <CURDEF>BRL</CURDEF>
        <BANKACCTFROM>
          <BANKID>341</BANKID>
          <ACCTID>0001-9</ACCTID>
          <ACCTTYPE>CHECKING</ACCTTYPE>
        </BANKACCTFROM>
        <BANKTRANLIST>
          <STMTTRN>
            <TRNTYPE>CREDIT</TRNTYPE>
            <DTPOSTED>20260220</DTPOSTED>
            <TRNAMT>987.65</TRNAMT>
            <FITID>XML-001</FITID>
            <MEMO>PIX RECEBIDO</MEMO>
          </STMTTRN>
        </BANKTRANLIST>
      </STMTRS>
    </STMTTRNRS>
  </BANKMSGSRSV1>
</OFX>
"""


class TestDialetos:
    """O mesmo caminho de código lê SGML (1.x) e XML (2.x)."""

    def test_le_ofx_1x_sgml_com_folhas_abertas(self) -> None:
        extrato = ler_ofx(ofx_sgml(_transacao_sgml("TRN001", "1500.00")))

        assert extrato.contas == ("001/12345-6",)
        assert len(extrato.transacoes) == 1
        transacao = extrato.transacoes[0]
        assert transacao.fitid == "TRN001"
        assert transacao.data_movimento == date(2026, 1, 15)
        assert transacao.valor == Decimal("1500.00")
        assert transacao.tipo == "CREDIT"
        assert transacao.conta == "001/12345-6"

    def test_le_ofx_2x_xml(self) -> None:
        extrato = ler_ofx(OFX_XML)

        assert extrato.contas == ("341/0001-9",)
        assert len(extrato.transacoes) == 1
        assert extrato.transacoes[0].fitid == "XML-001"
        assert extrato.transacoes[0].valor == Decimal("987.65")
        assert extrato.transacoes[0].descricao == "PIX RECEBIDO"

    def test_valor_e_decimal_e_nao_float(self) -> None:
        """O valor vai para `numeric(14,2)` e é comparado com `valor_total` da
        parcela pelo banco na baixa. Float aqui reintroduziria a imprecisão
        justamente no número que decide se a parcela pode ser quitada."""
        extrato = ler_ofx(ofx_sgml(_transacao_sgml("TRN-CENT", "0.10")))

        valor = extrato.transacoes[0].valor
        assert isinstance(valor, Decimal)
        assert valor * 3 == Decimal("0.30")


class TestCamposDaTransacao:
    def test_data_ignora_hora_e_fuso(self) -> None:
        """`20260115120000.000[-3:BRT]` — o `3` do fuso não pode entrar na
        contagem de dígitos da data."""
        extrato = ler_ofx(
            ofx_sgml(_transacao_sgml("T", "10.00", dtposted="20260115120000.000[-3:BRT]"))
        )
        assert extrato.transacoes[0].data_movimento == date(2026, 1, 15)

    def test_data_sem_hora(self) -> None:
        extrato = ler_ofx(ofx_sgml(_transacao_sgml("T", "10.00", dtposted="20260115")))
        assert extrato.transacoes[0].data_movimento == date(2026, 1, 15)

    def test_descricao_junta_name_e_memo(self) -> None:
        """NAME traz a contraparte e MEMO o detalhe: ficar só com um deles
        jogaria fora o nome de quem depositou, que é como o operador acha o
        tomador."""
        extrato = ler_ofx(ofx_sgml(_transacao_sgml("T", "10.00", nome="JOSE DA SILVA", memo="PIX")))
        assert extrato.transacoes[0].descricao == "JOSE DA SILVA — PIX"

    def test_descricao_nao_duplica_quando_name_e_memo_sao_iguais(self) -> None:
        extrato = ler_ofx(ofx_sgml(_transacao_sgml("T", "10.00", nome="PIX", memo="PIX")))
        assert extrato.transacoes[0].descricao == "PIX"

    def test_descricao_ausente_vira_none_e_nao_string_vazia(self) -> None:
        bloco = """<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260115
<TRNAMT>10.00
<FITID>SEM-DESC
</STMTTRN>
"""
        extrato = ler_ofx(ofx_sgml(bloco))
        assert extrato.transacoes[0].descricao is None

    def test_entidades_sgml_sao_desfeitas(self) -> None:
        extrato = ler_ofx(ofx_sgml(_transacao_sgml("T", "10.00", memo="PADARIA &amp; CIA")))
        assert extrato.transacoes[0].descricao is not None
        assert "PADARIA & CIA" in extrato.transacoes[0].descricao

    def test_valor_com_virgula_decimal(self) -> None:
        """Exportação de banco brasileiro às vezes foge da especificação. Sem
        ponto no número, a vírgula só pode ser o separador decimal."""
        extrato = ler_ofx(ofx_sgml(_transacao_sgml("T", "1500,45")))
        assert extrato.transacoes[0].valor == Decimal("1500.45")

    def test_acentuacao_em_cp1252(self) -> None:
        """OFX 1.x com CHARSET:1252 e nome acentuado no MEMO. Decodificar como
        UTF-8 na marra quebraria — e um `errors='replace'` gravaria a descrição
        corrompida numa tabela imutável (OC012)."""
        texto = ofx_sgml(_transacao_sgml("T", "10.00", memo="PAGAMENTO JOSE ANDRE"))
        texto = texto.replace("JOSE ANDRE", "JOSÉ ANDRÉ")

        extrato = ler_ofx(texto.encode("cp1252"))

        assert extrato.transacoes[0].descricao is not None
        assert "JOSÉ ANDRÉ" in extrato.transacoes[0].descricao


class TestConta:
    def test_extrato_de_cartao_so_com_acctid(self) -> None:
        """CCACCTFROM não tem BANKID. A conta é o que houver, não um erro."""
        cartao = f"""{_CABECALHO_SGML}<OFX>
<CREDITCARDMSGSRSV1>
<CCSTMTRS>
<CCACCTFROM>
<ACCTID>4444333322221111
</CCACCTFROM>
<BANKTRANLIST>
{_transacao_sgml("CC-1", "250.00")}</BANKTRANLIST>
</CCSTMTRS>
</CREDITCARDMSGSRSV1>
</OFX>
"""
        extrato = ler_ofx(cartao)

        assert extrato.contas == ("4444333322221111",)
        assert extrato.transacoes[0].conta == "4444333322221111"

    def test_duas_contas_no_mesmo_arquivo_nao_se_misturam(self) -> None:
        """Cada transação leva a conta do bloco em que está — e a segunda conta
        NÃO herda a primeira."""
        um = ofx_sgml(_transacao_sgml("A-1", "100.00"), bankid="001", acctid="111")
        dois = ofx_sgml(_transacao_sgml("B-1", "200.00"), bankid="341", acctid="222")
        # Cola os dois <STMTRS> dentro de um único <OFX>.
        combinado = um.replace("</OFX>\n", "") + dois.split("<OFX>", 1)[1]

        extrato = ler_ofx(combinado)

        assert {t.fitid: t.conta for t in extrato.transacoes} == {
            "A-1": "001/111",
            "B-1": "341/222",
        }

    def test_arquivo_sem_conta_declarada(self) -> None:
        sem_conta = f"""{_CABECALHO_SGML}<OFX>
<BANKMSGSRSV1>
<BANKTRANLIST>
{_transacao_sgml("SEM-CONTA", "10.00")}</BANKTRANLIST>
</BANKMSGSRSV1>
</OFX>
"""
        extrato = ler_ofx(sem_conta)

        assert extrato.contas == ()
        assert extrato.transacoes[0].conta is None


class TestArquivoSemTransacao:
    def test_periodo_sem_movimento_e_arquivo_valido(self) -> None:
        """Extrato de período parado NÃO é arquivo corrompido. Recusá-lo diria
        ao operador que o arquivo do banco está errado quando não está — e a
        importação deve relatar zero, que é a verdade."""
        extrato = ler_ofx(ofx_sgml(""))

        assert extrato.transacoes == ()
        # A conta continua sendo informada: é dela que o extrato vazio fala.
        assert extrato.contas == ("001/12345-6",)


class TestFitidRepetidoNoArquivo:
    def test_leitor_devolve_as_duas_linhas_fielmente(self) -> None:
        """O leitor não filtra: FITID duplicado é anomalia do arquivo do BANCO,
        e quem a esconde na leitura impede o importador de contá-la e reportá-la.
        A deduplicação (e o número) vivem em `importar_extrato_ofx`."""
        duplicado = _transacao_sgml("REPETIDO", "100.00") + _transacao_sgml("REPETIDO", "100.00")

        extrato = ler_ofx(ofx_sgml(duplicado))

        assert [t.fitid for t in extrato.transacoes] == ["REPETIDO", "REPETIDO"]


class TestCreditoEDebito:
    def test_sinal_e_preservado(self) -> None:
        """O leitor não decide o que entra: devolve o sinal como está. Filtrar
        débito aqui esconderia do relatório quantos foram ignorados."""
        misto = _transacao_sgml("CRED", "1500.00") + _transacao_sgml(
            "DEB", "-320.50", tipo="DEBIT", memo="TARIFA"
        )

        extrato = ler_ofx(ofx_sgml(misto))

        assert [t.valor for t in extrato.transacoes] == [Decimal("1500.00"), Decimal("-320.50")]


class TestArquivoMalformado:
    def test_arquivo_que_nao_e_ofx(self) -> None:
        with pytest.raises(OfxInvalido, match="<OFX>"):
            ler_ofx(b"data;valor;historico\n2026-01-15;1500,00;TED\n")

    def test_arquivo_vazio(self) -> None:
        with pytest.raises(OfxInvalido):
            ler_ofx(b"")

    def test_pdf_disfarcado_de_extrato(self) -> None:
        """O caso real: o operador exporta o extrato em PDF e sobe assim."""
        with pytest.raises(OfxInvalido):
            ler_ofx(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n")

    def test_transacao_sem_fitid_recusa_o_arquivo_inteiro(self) -> None:
        """Sem FITID não há idempotência — é ele que vira o `documento` UNIQUE.
        Importar as outras linhas e omitir esta produziria um extrato parcial
        que ninguém saberia estar incompleto."""
        sem_fitid = """<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260115
<TRNAMT>1500.00
<MEMO>TED
</STMTTRN>
"""
        with pytest.raises(OfxInvalido, match="FITID"):
            ler_ofx(ofx_sgml(_transacao_sgml("OK-1", "10.00") + sem_fitid))

    def test_transacao_sem_dtposted(self) -> None:
        bloco = """<STMTTRN>
<TRNTYPE>CREDIT
<TRNAMT>1500.00
<FITID>SEM-DATA
</STMTTRN>
"""
        with pytest.raises(OfxInvalido, match="DTPOSTED"):
            ler_ofx(ofx_sgml(bloco))

    def test_transacao_sem_trnamt(self) -> None:
        bloco = """<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260115
<FITID>SEM-VALOR
</STMTTRN>
"""
        with pytest.raises(OfxInvalido, match="TRNAMT"):
            ler_ofx(ofx_sgml(bloco))

    def test_data_impossivel(self) -> None:
        with pytest.raises(OfxInvalido, match="data válida"):
            ler_ofx(ofx_sgml(_transacao_sgml("T", "10.00", dtposted="20260231")))

    def test_data_curta_demais(self) -> None:
        with pytest.raises(OfxInvalido, match="AAAAMMDD"):
            ler_ofx(ofx_sgml(_transacao_sgml("T", "10.00", dtposted="2026")))

    def test_valor_nao_numerico(self) -> None:
        with pytest.raises(OfxInvalido, match="numérico"):
            ler_ofx(ofx_sgml(_transacao_sgml("T", "MIL REAIS")))

    def test_valor_nan_e_recusado(self) -> None:
        """`Decimal('NaN')` é literal VÁLIDO e o `numeric` do Postgres aceita
        NaN — e o ordena como MAIOR que qualquer número. Um NaN atravessaria o
        check `valor > 0` (009) e cobriria qualquer parcela na comparação de
        `fn_baixar_parcela`: baixa com lastro de nada."""
        with pytest.raises(OfxInvalido, match="finito"):
            ler_ofx(ofx_sgml(_transacao_sgml("T", "NaN")))

    def test_valor_infinito_e_recusado(self) -> None:
        with pytest.raises(OfxInvalido, match="finito"):
            ler_ofx(ofx_sgml(_transacao_sgml("T", "Infinity")))

    def test_stmttrn_nao_fechado_no_fim_do_arquivo(self) -> None:
        """Arquivo truncado no meio de uma transação. Ler tolerante aqui daria
        um movimento com o FITID de uma linha e o valor de outra."""
        truncado = f"""{_CABECALHO_SGML}<OFX>
<BANKTRANLIST>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260115
<TRNAMT>1500.00
<FITID>TRUNCADO
"""
        with pytest.raises(OfxInvalido, match="não foi fechado"):
            ler_ofx(truncado)

    def test_stmttrn_aberto_dentro_de_outro(self) -> None:
        """Em OFX, agregado SEMPRE fecha — só as folhas podem vir abertas. Dois
        <STMTTRN> aninhados significam arquivo corrompido."""
        aninhado = """<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260115
<TRNAMT>1500.00
<FITID>A
<STMTTRN>
<FITID>B
</STMTTRN>
"""
        with pytest.raises(OfxInvalido, match="truncado"):
            ler_ofx(ofx_sgml(aninhado))

    def test_fechamento_sem_abertura(self) -> None:
        with pytest.raises(OfxInvalido, match="sem <STMTTRN>"):
            ler_ofx(ofx_sgml("</STMTTRN>\n"))

    def test_fitid_absurdamente_longo(self) -> None:
        """255 é o limite da especificação. Truncar destruiria a identidade que
        torna a reimportação idempotente — recusar é o certo."""
        with pytest.raises(OfxInvalido, match="255"):
            ler_ofx(ofx_sgml(_transacao_sgml("X" * 256, "10.00")))


class TestLeituraEscalaLinearmente:
    """O extrato grande tem que CABER no tempo — senão os tetos não protegem nada.

    O endpoint aceita até 8 MiB e 50.000 transações, e a justificativa escrita
    para o INSERT único é impedir que "o arquivo grande vire timeout". Isso só
    vale se a LEITURA também aguentar: ela roda antes do INSERT, no mesmo
    request.

    Uma versão anterior de `_tokens` fatiava `texto[fim:]` a cada tag, copiando
    todo o resto do arquivo por tag e tornando a varredura QUADRÁTICA. Medido
    nesta base: 95 s para o arquivo abaixo, que está DENTRO dos dois tetos (3 MB,
    24.000 transações) — o timeout acontecia justamente onde ninguém olhava, e
    passava em todos os testes funcionais, porque todos usam arquivos de poucas
    linhas.

    O orçamento é folgado de propósito (a versão linear lê isto em ~0,5 s, e o
    teto inteiro de 50.000 em ~1 s): o que se quer detectar é a volta da
    complexidade quadrática, que estoura por duas ordens de grandeza, não uma
    variação de máquina carregada.
    """

    def test_extrato_grande_dentro_dos_tetos_le_em_tempo_linear(self) -> None:
        transacoes = 24_000
        arquivo = ofx_sgml("".join(_transacao_sgml(f"F{i}", "10.00") for i in range(transacoes)))
        assert len(arquivo.encode("utf-8")) < 8 * 1024 * 1024  # dentro do teto de bytes

        inicio = time.perf_counter()
        extrato = ler_ofx(arquivo.encode("utf-8"))
        decorrido = time.perf_counter() - inicio

        assert len(extrato.transacoes) == transacoes
        assert decorrido < 15.0, (
            f"leitura de {transacoes} transações levou {decorrido:.1f}s — "
            "sinal de varredura quadrática (fatia por tag) em _tokens"
        )
