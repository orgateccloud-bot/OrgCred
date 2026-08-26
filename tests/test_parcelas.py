"""
Agenda de parcelas (migration 007) contra Postgres real.

Três coisas estão sob teste aqui, e as duas últimas importam tanto quanto a
primeira: que a matemática de PRICE e SAC feche EXATAMENTE (sem centavo
sobrando), que a agenda seja imutável depois de emitida (OC009) e que ela só
possa ser ESCRITA pela ativação (OC025, migration 027) — o INSERT ficou sem
dono da 007 até a 027, e uma parcela avulsa entra no aging e na apuração
fiscal como se o banco a tivesse emitido.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.capital_engine import ativar_operacao, novar_operacao, transicionar_operacao
from tests.conftest import baixar_parcelas, confirmar_registro, sqlstate_de


def _criar(
    db_session: Session,
    tomador_id: uuid.UUID,
    valor: str,
    taxa: str = "2.5",
    sistema: str = "PRICE",
    parcelas: int = 12,
) -> uuid.UUID:
    result = db_session.execute(
        text(
            """
            insert into operacao_credito
                (tomador_id, tipo, valor_principal, taxa_juros_mensal,
                 sistema_amortizacao, numero_parcelas, status, registro_entidade_ref)
            values (:t, 'emprestimo', :v, :taxa, :sis, :n, 'registrada', 'REG-TEST')
            returning id
            """
        ),
        {"t": str(tomador_id), "v": valor, "taxa": taxa, "sis": sistema, "n": parcelas},
    )
    db_session.commit()
    op_id = result.scalar_one()
    confirmar_registro(db_session, op_id)
    return op_id


def _agenda(db_session: Session, op_id: uuid.UUID) -> list:
    return db_session.execute(
        text("""
        select numero, vencimento, valor_amortizacao, valor_juros,
               valor_total, saldo_devedor_pos, status
        from parcela where operacao_id = :id order by numero
        """),
        {"id": str(op_id)},
    ).all()


# ---------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------


def test_ativacao_gera_agenda_completa(db_session, tomador_autorizado, capital_constituido):
    """Não existe operação ativa sem agenda: o trigger roda na mesma transação."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert len(agenda) == 12
    assert [p.numero for p in agenda] == list(range(1, 13))
    assert all(p.status == "aberta" for p in agenda)


def test_operacao_nao_ativada_nao_tem_agenda(db_session, tomador_autorizado, capital_constituido):
    """A agenda é emitida na ativação, não na criação — antes disso não há
    o que cobrar nem data a partir da qual contar vencimentos."""
    op_id = _criar(db_session, tomador_autorizado, "12000")
    assert _agenda(db_session, op_id) == []


def test_price_amortizacao_fecha_exatamente(db_session, tomador_autorizado, capital_constituido):
    """A soma das amortizações é EXATAMENTE o principal e o saldo devedor
    final é 0,00. Se sobrar centavo, a quitação nunca fecha."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="2.5", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("12000.00")
    assert agenda[-1].saldo_devedor_pos == Decimal("0.00")


def test_price_prestacao_constante(db_session, tomador_autorizado, capital_constituido):
    """Característica que define o PRICE: a prestação não muda. A última é
    a única que pode divergir, por absorver o resíduo de arredondamento."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="2.5", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    totais = {p.valor_total for p in agenda[:-1]}
    assert len(totais) == 1, f"prestação PRICE deveria ser constante, veio {totais}"

    # E os juros decrescem, porque incidem sobre saldo devedor que cai.
    juros = [p.valor_juros for p in agenda]
    assert juros == sorted(juros, reverse=True)


def test_sac_amortizacao_constante_e_parcela_decrescente(
    db_session, tomador_autorizado, capital_constituido
):
    """Característica que define o SAC: amortização fixa, prestação caindo."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="2.5", sistema="SAC", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    amortizacoes = {p.valor_amortizacao for p in agenda}
    assert len(amortizacoes) == 1  # 12000/12 = 1000, divisão exata, nem a última diverge
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("12000.00")

    totais = [p.valor_total for p in agenda]
    assert totais == sorted(totais, reverse=True)
    assert totais[0] > totais[-1]


def test_sac_com_divisao_inexata_ainda_fecha(db_session, tomador_autorizado, capital_constituido):
    """10.000 em 3 parcelas dá 3.333,33... — o resíduo tem que ir para a
    última, senão faltam centavos no total."""
    op_id = _criar(db_session, tomador_autorizado, "10000", sistema="SAC", parcelas=3)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("10000.00")
    assert agenda[-1].saldo_devedor_pos == Decimal("0.00")
    assert agenda[-1].valor_amortizacao == Decimal("3333.34")


def test_taxa_zero_nao_quebra_a_ativacao(db_session, tomador_autorizado, capital_constituido):
    """Com i = 0 o denominador do PRICE (1 - (1+i)^-n) vira zero. Sem o
    desvio explícito, uma operação sem juros — válida — derrubaria a
    ativação com division_by_zero."""
    op_id = _criar(db_session, tomador_autorizado, "12000", taxa="0", parcelas=12)
    ativar_operacao(db_session, op_id)

    agenda = _agenda(db_session, op_id)
    assert len(agenda) == 12
    assert all(p.valor_juros == Decimal("0.00") for p in agenda)
    assert all(p.valor_total == Decimal("1000.00") for p in agenda)
    assert sum(p.valor_amortizacao for p in agenda) == Decimal("12000.00")


def test_vencimentos_mensais_crescentes(db_session, tomador_autorizado, capital_constituido):
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=6)
    ativar_operacao(db_session, op_id)

    vencimentos = [p.vencimento for p in _agenda(db_session, op_id)]
    assert vencimentos == sorted(vencimentos)
    assert len(set(vencimentos)) == 6


# ---------------------------------------------------------------------
# Idempotência
# ---------------------------------------------------------------------


def test_reativar_inadimplente_nao_regenera_agenda(
    db_session, tomador_autorizado, capital_constituido
):
    """Regenerar a agenda ao reativar reescreveria vencimentos já vencidos
    com datas novas — apagaria justamente a prova da inadimplência."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)
    original = _agenda(db_session, op_id)

    transicionar_operacao(db_session, op_id, "inadimplente")
    ativar_operacao(db_session, op_id)

    depois = _agenda(db_session, op_id)
    assert len(depois) == 12
    assert [p.vencimento for p in depois] == [p.vencimento for p in original]
    assert [p.valor_total for p in depois] == [p.valor_total for p in original]


def test_novacao_gera_agenda_propria_para_a_substituta(
    db_session, tomador_autorizado, capital_constituido
):
    """A substituta é outra operação, com outras condições: ativá-la emite
    a agenda dela, e a da original permanece intacta como histórico.

    O valor é o mesmo da original de propósito: desde a migration 026 a
    substituta não pode ser menor que o saldo devedor com lastro, e aqui
    nenhuma parcela foi baixada. O que muda é o prazo (12 -> 8), que é o que
    este teste quer provar — agenda própria, com outro número de linhas."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    nova = novar_operacao(
        db_session,
        op_id,
        valor_principal=Decimal("12000"),
        taxa_juros_mensal=Decimal("1.5"),
        sistema_amortizacao="SAC",
        numero_parcelas=8,
        registro_entidade_ref="REG-NOVA",
    )
    # A substituta é OUTRA operação: precisa do próprio registro confirmado.
    # É a leitura correta da lei — a novação cria um novo título, e o novo
    # título tem que ser registrado.
    confirmar_registro(db_session, nova.id)
    ativar_operacao(db_session, nova.id)

    assert len(_agenda(db_session, op_id)) == 12  # original preservada
    agenda_nova = _agenda(db_session, nova.id)
    assert len(agenda_nova) == 8
    assert sum(p.valor_amortizacao for p in agenda_nova) == Decimal("12000.00")


# ---------------------------------------------------------------------
# Imutabilidade (OC009)
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("valor_total", "1.00"),
        ("valor_juros", "0.00"),
        ("valor_amortizacao", "9999.00"),
        ("vencimento", "2030-01-01"),
        ("numero", "99"),
        ("saldo_devedor_pos", "0.00"),
    ],
)
def test_alterar_parcela_emitida_e_recusado(
    db_session, tomador_autorizado, capital_constituido, campo, valor
):
    """Nenhum valor nem data da agenda muda depois de emitida. Se mudasse,
    a cobrança deixaria de ser defensável — não haveria como provar o que
    foi acordado na ativação."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        db_session.execute(
            text(f"update parcela set {campo} = :v where operacao_id = :id and numero = 1"),
            {"v": valor, "id": str(op_id)},
        )
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC009"
    db_session.rollback()


def test_apagar_parcela_emitida_e_recusado(db_session, tomador_autorizado, capital_constituido):
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        db_session.execute(text("delete from parcela where operacao_id = :id"), {"id": str(op_id)})
        db_session.flush()
    assert sqlstate_de(exc.value) == "OC009"
    db_session.rollback()


def test_baixa_de_recebimento_e_permitida(db_session, tomador_autorizado, capital_constituido):
    """status e pago_em são a exceção deliberada à imutabilidade: é por eles
    que a baixa acontece, sem tocar nos valores acordados. Desde a migration
    009 a baixa exige lastro bancário — daí passar por `fn_baixar_parcela`."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    baixar_parcelas(db_session, op_id, [1])

    agenda = _agenda(db_session, op_id)
    assert agenda[0].status == "paga"
    assert agenda[1].status == "aberta"


# ---------------------------------------------------------------------
# A agenda não recebe apêndice (OC025, migration 027)
# ---------------------------------------------------------------------
# O furo: `fn_parcela_imutavel` nasceu na 007 como `before update or delete`,
# e a 016 — que reescreveu a função inteira — manteve o gatilho. O INSERT
# nunca teve dono. Uma décima terceira parcela num contrato de doze entra no
# aging (008, que soma toda parcela 'aberta' vencida) e na apuração fiscal
# (011, que no regime caixa soma toda parcela 'paga'): inventar inadimplência
# e inventar receita pelo mesmo comando.
#
# A guarda vale sobre o DADO (operação ativa + agenda incompleta), não sobre o
# caminho por onde o INSERT chegou — ver a justificativa dos três desenhos
# considerados no cabeçalho da migration 027.


def _apendice(db_session: Session, op_id: uuid.UUID, numero: int = 13, **campos: str) -> None:
    """Insere uma parcela à mão, no formato que `fn_gerar_parcelas` produziria.

    Existe porque cada teste desta seção muda UM detalhe do INSERT: é o
    detalhe que importa, e repetir dez colunas em cada um esconderia qual é.
    """
    colunas = {
        "operacao_id": str(op_id),
        "numero": str(numero),
        "vencimento": "2030-01-01",
        "valor_amortizacao": "1000.00",
        "valor_juros": "0.00",
        "valor_total": "1000.00",
        "saldo_devedor_pos": "0.00",
        **campos,
    }
    nomes = ", ".join(colunas)
    valores = ", ".join(f":{nome}" for nome in colunas)
    db_session.execute(text(f"insert into parcela ({nomes}) values ({valores})"), colunas)
    db_session.flush()


def test_a_guarda_de_insercao_existe_e_a_ativacao_passa_por_ela(
    db_session, tomador_autorizado, capital_constituido
):
    """CAMINHO FELIZ, e ele precisa afirmar as DUAS coisas.

    Só "a ativação gerou 12 parcelas" passaria igualmente bem se o trigger não
    tivesse sido criado — que é exatamente o estado anterior à 027. Por isso a
    primeira asserção é sobre o trigger estar instalado e HABILITADO: sem ela,
    este teste não distingue a guarda funcionando da guarda ausente.
    """
    instalado = db_session.execute(
        text("""
        select tgenabled from pg_trigger
         where tgrelid = 'parcela'::regclass and tgname = 'trg_parcela_insercao'
        """)
    ).scalar_one()
    assert instalado == "O", "trg_parcela_insercao não está instalado e habilitado"

    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    # A agenda legítima atravessa a guarda inteira: `fn_gerar_parcelas` insere
    # as doze de dentro da própria ativação, com a operação já 'ativa' e a
    # agenda ainda incompleta — a única janela em que INSERT é legítimo.
    agenda = _agenda(db_session, op_id)
    assert [p.numero for p in agenda] == list(range(1, 13))
    assert all(p.status == "aberta" for p in agenda)


def test_apendice_em_agenda_completa_e_recusado(
    db_session, tomador_autorizado, capital_constituido
):
    """O furo, na forma que a auditoria reproduziu: uma parcela a mais numa
    operação ATIVA, com a agenda inteira já emitida."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        _apendice(db_session, op_id, numero=13)
    assert sqlstate_de(exc.value) == "OC025"
    db_session.rollback()

    assert len(_agenda(db_session, op_id)) == 12


def test_apendice_dentro_da_numeracao_tambem_e_recusado(
    db_session, tomador_autorizado, capital_constituido
):
    """A guarda não é sobre o NÚMERO da parcela, e este teste separa as duas
    coisas: com numero=7 o UNIQUE (operacao_id, numero) também recusaria, mas
    com 23505 — fora do PGCODE_MAP, HTTP 500. A guarda responde antes, com o
    código que a UI sabe traduzir."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        _apendice(db_session, op_id, numero=7)
    assert sqlstate_de(exc.value) == "OC025"
    db_session.rollback()


def test_parcela_em_operacao_nao_ativa_e_recusada(
    db_session, tomador_autorizado, capital_constituido
):
    """O caminho mais barato do furo, e o que a condição de status fecha:
    operação 'registrada' tem ZERO parcelas, então a checagem de agenda
    incompleta sozinha a deixaria passar — bastaria escrever a agenda inteira
    à mão antes de ativar, e `fn_gerar_parcelas` (idempotente) devolveria 0 na
    ativação, deixando a agenda forjada de pé como se o banco a tivesse
    emitido."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)

    with pytest.raises(Exception) as exc:
        _apendice(db_session, op_id, numero=1)
    assert sqlstate_de(exc.value) == "OC025"
    db_session.rollback()

    assert _agenda(db_session, op_id) == []


def _abrir_janela_de_emissao(db_session: Session, op_id: uuid.UUID, numero: int = 12) -> None:
    """Deixa a operação 'ativa' com a agenda INCOMPLETA, apagando uma parcela.

    Existe porque duas das quatro condições da guarda — o número caber no
    contratado e a parcela nascer em aberto — só são ALCANÇADAS depois que as
    duas primeiras passam, e as duas primeiras (operação ativa, agenda
    incompleta) só passam ao mesmo tempo dentro da transação de ativação.
    Testá-las com uma operação 'registrada' ou com a agenda cheia não prova
    nada: a recusa vem da condição anterior, e as duas últimas poderiam ser
    apagadas da migration sem que nenhum teste percebesse (foi exatamente o que
    a revisão desta migration encontrou, mutando cada condição uma a uma).

    Apagar parcela exige desligar `trg_parcela_imutavel` (OC009) — o mesmo
    recurso que esta suíte já usa para antedatar vencimentos. É a única forma
    de reproduzir a janela de fora da ativação, e é o que a torna
    inofensiva na prática: quem consegue abri-la já tem SQL de dono da tabela.
    Aqui ela serve de bancada, não de ameaça.
    """
    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    try:
        db_session.execute(
            text("delete from parcela where operacao_id = :id and numero = :n"),
            {"id": str(op_id), "n": numero},
        )
    finally:
        # Dentro da mesma transação: um rollback do teste desfaz os dois
        # comandos e o trigger fica como estava, ligado.
        db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
    db_session.flush()


def test_a_janela_de_emissao_aceita_a_parcela_que_falta(
    db_session, tomador_autorizado, capital_constituido
):
    """CONTROLE POSITIVO dos dois testes seguintes, e a razão de ele vir antes.

    Sem esta afirmação, "o INSERT foi recusado com OC025" na janela aberta não
    distingue a condição sob teste de uma janela que nunca abriu — e um teste
    que não distingue as duas coisas é o defeito que estes três consertam.
    Aqui a agenda incompleta recebe, de fato, a parcela que falta.
    """
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)
    _abrir_janela_de_emissao(db_session, op_id, numero=12)
    assert len(_agenda(db_session, op_id)) == 11

    _apendice(db_session, op_id, numero=12)

    agenda = _agenda(db_session, op_id)
    assert [p.numero for p in agenda] == list(range(1, 13))
    db_session.rollback()


def test_numero_acima_do_contratado_e_recusado_com_a_agenda_incompleta(
    db_session, tomador_autorizado, capital_constituido
):
    """A terceira condição, na única janela em que ela é alcançada: agenda
    incompleta (11 de 12) e um INSERT de número 13. As duas condições
    anteriores deixam passar; quem recusa é o teto da numeração contratada,
    que a 015 congela (OC020) justamente para que ele signifique alguma
    coisa."""
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)
    _abrir_janela_de_emissao(db_session, op_id, numero=12)

    with pytest.raises(Exception) as exc:
        _apendice(db_session, op_id, numero=13)
    assert sqlstate_de(exc.value) == "OC025"
    db_session.rollback()


def test_parcela_nao_nasce_paga(db_session, tomador_autorizado, capital_constituido):
    """A porta lateral do furo da COBERTURA (o outro achado da 027): a
    checagem de valor do movimento vive no UPDATE, então uma parcela INSERIDA
    já 'paga' contra uma tarifa de um centavo não passaria por ela. Parcela
    nasce em aberto — sempre —, e é isso que torna verdadeira a frase de que o
    único jeito de sair de aberta é um UPDATE, que agora confere o valor.

    NA JANELA ABERTA, e não com a operação 'registrada': ali a recusa viria da
    primeira condição da guarda (operação não está sendo ativada) e este teste
    passaria com a quarta condição apagada da migration.
    """
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)
    _abrir_janela_de_emissao(db_session, op_id, numero=12)
    movimento = db_session.execute(
        text("""
        insert into movimento_bancario (data_movimento, valor, documento)
        values (current_date, 0.01, :doc) returning id
        """),
        {"doc": f"DOC-APENDICE-{uuid.uuid4().hex[:10]}"},
    ).scalar_one()

    with pytest.raises(Exception) as exc:
        _apendice(db_session, op_id, numero=12, status="paga", movimento_id=str(movimento))
    assert sqlstate_de(exc.value) == "OC025"
    db_session.rollback()


def test_parcela_de_operacao_inexistente_recusa_com_codigo_tratado(db_session):
    """A FK só é verificada DEPOIS do BEFORE ROW (restrições de chave
    estrangeira são triggers AFTER), então sem esta condição a recusa viria
    como 23503 — fora do PGCODE_MAP, HTTP 500 — em vez da regra."""
    with pytest.raises(Exception) as exc:
        _apendice(db_session, uuid.uuid4(), numero=1)
    assert sqlstate_de(exc.value) == "OC025"
    db_session.rollback()


def test_guarda_de_insercao_nao_cai_junto_com_a_de_imutabilidade(
    db_session, tomador_autorizado, capital_constituido
):
    """Por que a guarda de INSERT é um trigger SEPARADO de
    `trg_parcela_imutavel`, e não um ramo dentro dele.

    Esta suíte desliga `trg_parcela_imutavel` POR NOME para fabricar cenários
    de atraso (tests/test_baixa_recebimento.py, tests/test_router_cobranca.py).
    Se as duas guardas morassem no mesmo trigger, a de INSERT cairia junto — e
    uma proteção que some quando um teste antedata um vencimento não protege
    nada.
    """
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    db_session.execute(text("alter table parcela disable trigger trg_parcela_imutavel"))
    try:
        with pytest.raises(Exception) as exc:
            _apendice(db_session, op_id, numero=13)
        assert sqlstate_de(exc.value) == "OC025"
    finally:
        db_session.rollback()
        db_session.execute(text("alter table parcela enable trigger trg_parcela_imutavel"))
        db_session.commit()


def test_truncate_na_agenda_e_recusado(db_session, tomador_autorizado, capital_constituido):
    """TRUNCATE não visita linhas, e a recusa de DELETE (OC009) é de linha.

    A 016 instalou BEFORE TRUNCATE em cinco tabelas e deixou `parcela` de fora
    porque, até a 027, esvaziá-la só destruía a agenda — não HABILITAVA nada.
    Com a guarda de inserção, a contagem de parcelas virou permissão, e a
    tabela vazia deixou de ser só perda.
    """
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        db_session.execute(text("truncate parcela"))
    assert sqlstate_de(exc.value) == "OC009"
    db_session.rollback()

    assert len(_agenda(db_session, op_id)) == 12


def test_truncate_nao_reabre_a_janela_de_emissao(
    db_session, tomador_autorizado, capital_constituido
):
    """O ATAQUE INTEIRO, em dois comandos, e a razão de o teste acima existir.

    A guarda de inserção afirma que a janela "operação ativa + agenda
    incompleta" não é forjável de fora. `truncate parcela` a forjava: depois
    dele a operação continua 'ativa' com ZERO parcelas, e o apêndice entra sem
    recusa nenhuma — vencido, do valor que o autor escolher, direto no aging da
    008 e na apuração da 011.

    Este teste vale mais que o anterior porque não afirma só que um comando é
    recusado: afirma que a recusa é o que sustenta a OUTRA guarda. Daí o
    try/except explícito no lugar de `pytest.raises` — quando o bloqueio cai,
    a mensagem que aparece na suíte é a CONSEQUÊNCIA (a janela reabriu), e não
    "DID NOT RAISE", que não diria a quem lê por que isso importa.
    """
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    try:
        db_session.execute(text("truncate parcela cascade"))
    except Exception as exc:
        assert sqlstate_de(exc) == "OC009"
        db_session.rollback()
    else:
        restantes = db_session.execute(
            text("select count(*) from parcela where operacao_id = :id"), {"id": str(op_id)}
        ).scalar_one()
        db_session.rollback()
        pytest.fail(
            "truncate parcela foi ACEITO: a operação segue 'ativa' com "
            f"{restantes} parcelas de 12, e a guarda de inserção passa a ler "
            "isso como agenda incompleta — o apêndice entra sem recusa."
        )

    # A agenda continua completa, então a segunda metade do ataque bate na
    # condição de agenda já emitida — que é onde ela tem que bater.
    with pytest.raises(Exception) as exc:
        _apendice(db_session, op_id, numero=13)
    assert sqlstate_de(exc.value) == "OC025"
    db_session.rollback()


def test_truncate_no_movimento_nao_arrasta_a_agenda_por_cascade(
    db_session, tomador_autorizado, capital_constituido
):
    """`movimento_bancario` não ganhou trigger próprio, e não precisa.

    A FK `parcela.movimento_id` faz o Postgres recusar `truncate
    movimento_bancario` sozinho, e o `cascade` que contornaria isso arrasta
    `parcela` para o mesmo comando — onde a guarda da agenda dispara e aborta
    os dois. É por isso que uma linha fecha as duas tabelas.
    """
    op_id = _criar(db_session, tomador_autorizado, "12000", parcelas=12)
    ativar_operacao(db_session, op_id)

    with pytest.raises(Exception) as exc:
        db_session.execute(text("truncate movimento_bancario cascade"))
    assert sqlstate_de(exc.value) == "OC009"
    db_session.rollback()

    assert len(_agenda(db_session, op_id)) == 12
