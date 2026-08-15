"""
Geração do instrumento contratual a partir dos dados da operação.

Vive em Python, e não em PL/pgSQL, porque isto é APRESENTAÇÃO e não regra de
negócio — o banco continua sendo dono dos invariantes. A garantia que
importa está na migration 012: o SHA-256 é calculado pelo BANCO no INSERT,
então corpo e hash não podem divergir nem ser forjados.

O texto é DETERMINÍSTICO: mesma operação, mesma agenda, mesmo corpo, mesmo
hash. Nada de data de geração ou identificador aleatório dentro do corpo —
seria impossível conferir depois se duas emissões descrevem o mesmo acordo.
A data de emissão fica na coluna `emitido_em`, fora do texto assinado.

Os dados do registro (entidade, protocolo, data de confirmação) entram no
corpo sem quebrar isso: 'confirmado' é estado TERMINAL (OC018), então essas
três colunas não mudam mais depois de gravadas.

DETERMINÍSTICO NÃO É IMUTÁVEL: duas emissões do MESMO estado dão o mesmo
corpo, mas o estado muda com o tempo — a agenda só existe depois da
ativação, o registro pode ser confirmado depois, o status avança. Por isso
reemitir cria VERSÃO NOVA (migration 012) e a anterior fica intocada com o
hash que o banco calculou nela.

TIPO: "Contrato de Empréstimo ESC", não CCB. A CCB (Lei 10.931/2004) é
instrumento de instituição financeira, e uma ESC não é — ver a nota no topo
da migration 012.
"""

from decimal import Decimal
from typing import Any, List


TIPO_INSTRUMENTO = "contrato_emprestimo_esc"

_SISTEMAS = {
    "PRICE": "Tabela Price (prestações constantes)",
    "SAC": "Sistema de Amortização Constante (amortização constante)",
}

# Status em que o principal JÁ SAIU do caixa da ESC — hoje ou algum dia.
# 'inadimplente' entra porque o dinheiro continua fora (mesma leitura de
# `fn_check_teto_capital`); 'liquidada' e 'renegociada' entram porque foi
# liberado um dia, e o instrumento não pode dizer que não foi. Existe para a
# seção 4 não afirmar "nenhum valor é liberado" sobre operação que consumiu
# teto: o gate da migration 013 só roda NA TRANSIÇÃO, então operações
# ativadas antes dele seguem ativas sem registro confirmado — é o que a view
# `v_operacoes_sem_registro_confirmado` conta, com coluna `tem_contrato` e
# tudo.
_STATUS_COM_CAPITAL_LIBERADO = frozenset({"ativa", "inadimplente", "liquidada", "renegociada"})


def _moeda(valor: Decimal | int | str) -> str:
    """R$ 1.234,56 — ponto de milhar e vírgula decimal, como manda o
    português. Formatar em locale do sistema tornaria o corpo (e o hash)
    dependente da máquina que gerou."""
    texto = f"{Decimal(valor):,.2f}"
    return "R$ " + texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _cnpj(digitos: str) -> str:
    d = "".join(c for c in digitos if c.isdigit())
    if len(d) != 14:
        return digitos
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _data(valor: Any) -> str:
    return str(valor.strftime("%d/%m/%Y"))


def gerar_corpo(
    operacao: Any, tomador: Any, parcelas: List[Any], credor: Any, registro: Any | None
) -> str:
    """
    Monta o texto do contrato.

    `credor` traz os dados da ESC (razão social, CNPJ, município/UF) — vêm de
    fora porque são dados da empresa, não da operação, e não há tabela de
    cadastro da própria ESC no schema.

    `registro` é a linha CONFIRMADA de `registro_operacao` (entidade,
    protocolo, confirmado_em), ou None quando ainda não existe. É parâmetro
    obrigatório — sem default — justamente para que nenhum chamador emita o
    instrumento sem antes ter olhado se há registro confirmado.
    """
    linhas: List[str] = []
    add = linhas.append

    add("CONTRATO DE EMPRÉSTIMO — EMPRESA SIMPLES DE CRÉDITO (ESC)")
    add("Lei Complementar nº 167, de 24 de abril de 2019")
    add("")
    add("1. PARTES")
    add("")
    add("CREDORA:")
    add(f"  Razão social: {credor.razao_social}")
    add(f"  CNPJ: {_cnpj(credor.cnpj)}")
    add(f"  Município/UF: {credor.municipio}/{credor.uf}")
    add("")
    add("DEVEDORA:")
    add(f"  Razão social: {tomador.razao_social}")
    add(f"  CNPJ: {_cnpj(tomador.cnpj)}")
    add(f"  Porte: {tomador.porte}")
    add(f"  Município/UF: {tomador.municipio}/{tomador.uf}")
    add("")
    add("2. OBJETO E CONDIÇÕES")
    add("")
    add(f"  Operação nº: {operacao.id}")
    add(f"  Modalidade: {operacao.tipo}")
    add(f"  Valor principal: {_moeda(operacao.valor_principal)}")
    add(f"  Taxa de juros: {operacao.taxa_juros_mensal}% ao mês")
    add(
        f"  Sistema de amortização: "
        f"{_SISTEMAS.get(operacao.sistema_amortizacao, operacao.sistema_amortizacao)}"
    )
    add(f"  Número de parcelas: {operacao.numero_parcelas}")
    add("")

    if parcelas:
        total_amort = sum((Decimal(p.valor_amortizacao) for p in parcelas), Decimal("0"))
        total_juros = sum((Decimal(p.valor_juros) for p in parcelas), Decimal("0"))
        total_geral = sum((Decimal(p.valor_total) for p in parcelas), Decimal("0"))

        add("3. AGENDA DE PAGAMENTOS")
        add("")
        add("  Parc.  Vencimento    Amortização        Juros      Prestação")
        add("  " + "-" * 62)
        for p in parcelas:
            add(
                f"  {p.numero:>4}   {_data(p.vencimento)}  "
                f"{_moeda(p.valor_amortizacao):>14}  "
                f"{_moeda(p.valor_juros):>11}  "
                f"{_moeda(p.valor_total):>13}"
            )
        add("  " + "-" * 62)
        add(
            f"  Totais            {_moeda(total_amort):>14}  "
            f"{_moeda(total_juros):>11}  {_moeda(total_geral):>13}"
        )
        add("")
        add(f"  Custo total do crédito: {_moeda(total_juros)} em juros.")
    else:
        # Sem agenda o contrato não descreve o que será cobrado. Dizer isso
        # no corpo é melhor do que emitir um documento que parece completo.
        add("3. AGENDA DE PAGAMENTOS")
        add("")
        add("  A agenda é emitida pelo sistema no momento da ativação da")
        add("  operação e passa a integrar este contrato. Enquanto a operação")
        add("  não for ativada, não há agenda a reproduzir aqui.")

    add("")
    add("4. REGISTRO EM ENTIDADE REGISTRADORA")
    add("")
    # Aqui se citava `operacao.registro_entidade_ref` — texto livre que a
    # migration 013 rebaixou a campo informativo quando o gate passou a
    # exigir registro CONFIRMADO. Este documento vai a terceiros: citar uma
    # referência que ninguém validou seria afirmar no papel algo mais fraco
    # do que o sistema sabe. O que vale é a linha confirmada de
    # `registro_operacao` — entidade, protocolo e data, com protocolo
    # garantido por constraint da migration 012.
    if registro is not None:
        add("  Nos termos do art. 5º, §3º, da Lei Complementar nº 167/2019, esta")
        add("  operação está registrada em entidade registradora autorizada pelo")
        add("  Banco Central do Brasil.")
        add("")
        add(f"  Entidade registradora: {registro.entidade}")
        add(f"  Protocolo do registro: {registro.protocolo}")
        add(f"  Registro confirmado em: {_data(registro.confirmado_em)}")
    else:
        # Recusar a emissão seria pior: a entidade registradora costuma pedir
        # o instrumento para registrar, e travar a emissão até haver registro
        # fecharia o ciclo sobre si mesmo. Então emite-se — mas dizendo, em
        # letras de forma, que não há registro a citar.
        add("  Nos termos do art. 5º, §3º, da Lei Complementar nº 167/2019, esta")
        add("  operação deve ser registrada em entidade registradora autorizada")
        add("  pelo Banco Central do Brasil.")
        add("")
        add("  SEM REGISTRO CONFIRMADO ATÉ ESTA EMISSÃO. Não há entidade nem")
        add("  protocolo a citar.")
        add("")
        if operacao.status in _STATUS_COM_CAPITAL_LIBERADO:
            # A ausência aqui não é "condição ainda não atingida": é PENDÊNCIA,
            # com o dinheiro já fora. Dizer a frase do caso comum ("nenhum
            # valor é liberado") sobre uma operação ativa seria o mesmo pecado
            # que motivou esta seção — o papel afirmando algo que o sistema
            # sabe ser falso, só que agora na direção que favorece a ESC.
            add("  Esta operação JÁ COMPROMETEU CAPITAL da CREDORA: o valor foi")
            add("  liberado sob a regra vigente à época da ativação, anterior à")
            add("  exigência de registro confirmado. A ausência de registro é,")
            add("  portanto, PENDÊNCIA A REGULARIZAR perante a entidade")
            add("  registradora — e não condição ainda não atingida.")
        else:
            add("  Enquanto não houver registro confirmado a operação não pode")
            add("  ser ativada e nenhum valor é liberado.")
        add("")
        add("  Confirmado o registro, este instrumento é reemitido em nova")
        add("  versão citando a entidade e o protocolo.")
    add("")
    add("5. DISPOSIÇÕES")
    add("")
    add("  5.1. A CREDORA é Empresa Simples de Crédito e opera exclusivamente")
    add("       com recursos próprios, nos termos do art. 1º da LC 167/2019.")
    add("  5.2. A CREDORA não é instituição financeira e não capta recursos")
    add("       do público.")
    add("  5.3. A DEVEDORA declara estar sediada no município de atuação da")
    add("       CREDORA ou em município limítrofe, conforme art. 1º da")
    add("       LC 167/2019.")
    add("  5.4. Este instrumento é gerado eletronicamente e sua integridade é")
    add("       verificável pelo resumo criptográfico (SHA-256) registrado no")
    add("       sistema da CREDORA no momento da emissão.")

    return "\n".join(linhas)
