"""
Router: instrumento contratual e registro na entidade registradora.

O QUE ESTE MÓDULO RESOLVEU: `operacao_credito.registro_entidade_ref` era
texto livre, e o gate OC004 só verificava que não estava vazio — escrever
"x" ali passava pela exigência do Art. 5º §3º da LC 167/2019. Aqui o
registro virou entidade de primeira classe (entidade, protocolo, status,
datas), com máquina de estados no banco.

O GATE ESTÁ LIGADO desde a migration 013: ativar exige registro CONFIRMADO,
e `registro_entidade_ref` virou campo informativo — tanto que saiu do corpo
do contrato, que hoje cita a entidade e o protocolo do registro confirmado.
`GET /contratos/registros/pendencias` deixou de ser só medida da lacuna — é
a relação de operações que não conseguem ativar.

AINDA BLOQUEADO pela escolha da entidade registradora (CRDC, Núclea, SPC
Grafeno, B3, CERC — ver PESQUISA_ENTIDADE_REGISTRADORA.md):
- Integração com a API da entidade. Não existe API genérica; o que existe
  aqui é o SEAM — confirmar o registro é uma chamada, e o adaptador da
  entidade escolhida será a única peça a escrever.
- Assinatura eletrônica (ICP-Brasil ou não), que muda o fluxo conforme o
  provedor.
"""

import base64
import binascii
import hashlib
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.contrato import TIPO_INSTRUMENTO, gerar_corpo
from app.core.config import settings
from app.core.db_errors import traduzir_erro_banco
from app.core.security import get_current_user, get_operador_user
from app.db import get_db
from app.models import Usuario


router = APIRouter(prefix="/contratos", tags=["contratos"])


# ---------------------------------------------------------------------
# Instrumento contratual
# ---------------------------------------------------------------------


class ContratoOut(BaseModel):
    id: UUID
    operacao_id: UUID
    versao: int
    tipo_instrumento: str
    sha256: str
    emitido_em: datetime


class ContratoDetalheOut(ContratoOut):
    corpo: str


@router.get("/operacoes/{operacao_id}/contrato", response_model=Optional[ContratoDetalheOut])
def get_contrato(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> Optional[ContratoDetalheOut]:
    """Contrato vigente (última versão) da operação, com o corpo.

    Devolve `null` quando ainda não houve emissão — a tela precisa
    distinguir 'não emitido' de 'erro ao carregar'."""
    row = db.execute(
        text("select * from v_contrato_vigente where operacao_id = :o"),
        {"o": str(operacao_id)},
    ).first()
    if row is None:
        return None
    return ContratoDetalheOut(
        id=row.id,
        operacao_id=row.operacao_id,
        versao=row.versao,
        tipo_instrumento=row.tipo_instrumento,
        sha256=row.sha256,
        emitido_em=row.emitido_em,
        corpo=row.corpo,
    )


@router.post(
    "/operacoes/{operacao_id}/contrato", response_model=ContratoDetalheOut, status_code=201
)
def post_emitir_contrato(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> ContratoDetalheOut:
    """
    Emite o instrumento a partir dos dados da operação e da agenda.

    Reemitir gera uma NOVA VERSÃO: o contrato anterior permanece, porque o
    tomador tem uma via dele e editar o original destruiria a prova do que
    foi acordado.

    Exige a ESC identificada em configuração. Sem isso, o contrato sairia
    com credora em branco — um documento com efeito jurídico e sem uma das
    partes.

    NÃO exige registro confirmado: emitir antes é legítimo (a registradora
    costuma pedir o instrumento para registrar). O que o corpo faz é dizer
    a verdade sobre o que existe no momento da emissão — entidade e
    protocolo quando há registro confirmado, marca explícita de ausência
    quando não há. Confirmado depois, reemitir gera a versão que cita o
    protocolo, e a anterior continua íntegra e válida.
    """
    if not settings.esc_identificada:
        raise HTTPException(
            status_code=422,
            detail=(
                "Dados da ESC não configurados (ORGCRED_ESC_RAZAO_SOCIAL, "
                "ORGCRED_ESC_CNPJ, ORGCRED_ESC_MUNICIPIO, ORGCRED_ESC_UF). "
                "O contrato não pode ser emitido sem identificar a credora."
            ),
        )

    operacao = db.execute(
        text("select * from operacao_credito where id = :o"), {"o": str(operacao_id)}
    ).first()
    if operacao is None:
        raise HTTPException(status_code=404, detail=f"Operação {operacao_id} não existe.")

    tomador = db.execute(
        text("select * from tomador where id = :t"), {"t": str(operacao.tomador_id)}
    ).one()
    parcelas = db.execute(
        text("""
        select numero, vencimento, valor_amortizacao, valor_juros, valor_total
        from parcela where operacao_id = :o order by numero
        """),
        {"o": str(operacao_id)},
    ).all()

    # O corpo cita o registro CONFIRMADO, não mais o `registro_entidade_ref`
    # de texto livre. `.first()` basta: o índice único parcial da migration
    # 012 garante no máximo um confirmado por operação. Vindo None, o corpo
    # imprime a marca de "sem registro confirmado" — a emissão não é recusada
    # porque a registradora costuma exigir o instrumento para registrar.
    registro = db.execute(
        text("""
        select entidade, protocolo, confirmado_em
        from registro_operacao
        where operacao_id = :o and status = 'confirmado'
        """),
        {"o": str(operacao_id)},
    ).first()

    credor = type(
        "Credor",
        (),
        {
            "razao_social": settings.esc_razao_social,
            "cnpj": settings.esc_cnpj,
            "municipio": settings.esc_municipio,
            "uf": settings.esc_uf,
        },
    )()

    corpo = gerar_corpo(operacao, tomador, list(parcelas), credor, registro)

    # O sha256 NÃO é enviado: o trigger da migration 012 o calcula a partir
    # do corpo. Assim corpo e hash não podem divergir, nem por bug aqui nem
    # por escrita direta no banco.
    row = db.execute(
        text("""
        insert into contrato_emprestimo (operacao_id, versao, tipo_instrumento, corpo, sha256, usuario_id)
        values (
            :o,
            (select coalesce(max(versao), 0) + 1 from contrato_emprestimo where operacao_id = :o),
            :tipo, :corpo, '', :u
        )
        returning *
        """),
        {"o": str(operacao_id), "tipo": TIPO_INSTRUMENTO, "corpo": corpo, "u": str(user.id)},
    ).one()
    db.commit()

    return ContratoDetalheOut(
        id=row.id,
        operacao_id=row.operacao_id,
        versao=row.versao,
        tipo_instrumento=row.tipo_instrumento,
        sha256=row.sha256,
        emitido_em=row.emitido_em,
        corpo=row.corpo,
    )


class VerificacaoContratoIn(BaseModel):
    """Conteúdo em base64 do arquivo a conferir contra o que foi emitido."""

    conteudo_base64: str = Field(min_length=1)


class VerificacaoContratoOut(BaseModel):
    sha256_calculado: str
    confere: bool


@router.post("/{contrato_id}/verificar", response_model=VerificacaoContratoOut)
def post_verificar_contrato(
    contrato_id: UUID,
    body: VerificacaoContratoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> VerificacaoContratoOut:
    """Confere se um arquivo é bit a bit o instrumento emitido.

    É o que dá utilidade ao hash: sem esta conferência, ele seria um número
    guardado sem uso — e a via que o tomador apresenta não teria como ser
    confrontada com a do sistema."""
    row = db.execute(
        text("select sha256 from contrato_emprestimo where id = :c"), {"c": str(contrato_id)}
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Contrato {contrato_id} não existe.")

    try:
        conteudo = base64.b64decode(body.conteudo_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Conteúdo não é base64 válido.") from exc

    calculado = hashlib.sha256(conteudo).hexdigest()
    return VerificacaoContratoOut(sha256_calculado=calculado, confere=calculado == row.sha256)


# ---------------------------------------------------------------------
# Registro na entidade registradora
# ---------------------------------------------------------------------


class RegistroOut(BaseModel):
    id: UUID
    operacao_id: UUID
    entidade: str
    protocolo: Optional[str]
    status: str
    enviado_em: datetime
    confirmado_em: Optional[datetime]
    motivo_rejeicao: Optional[str]


def _registro_out(r: object) -> RegistroOut:
    return RegistroOut(
        id=r.id,  # type: ignore[attr-defined]
        operacao_id=r.operacao_id,  # type: ignore[attr-defined]
        entidade=r.entidade,  # type: ignore[attr-defined]
        protocolo=r.protocolo,  # type: ignore[attr-defined]
        status=r.status,  # type: ignore[attr-defined]
        enviado_em=r.enviado_em,  # type: ignore[attr-defined]
        confirmado_em=r.confirmado_em,  # type: ignore[attr-defined]
        motivo_rejeicao=r.motivo_rejeicao,  # type: ignore[attr-defined]
    )


class AbrirRegistroIn(BaseModel):
    """`entidade` é texto livre porque a escolha entre CRDC, Núclea, SPC
    Grafeno, B3 e CERC não foi feita — e um enum obrigaria mudança de código
    a cada troca de fornecedor, inclusive durante um piloto com duas."""

    entidade: str = Field(min_length=1, max_length=100)


@router.get("/operacoes/{operacao_id}/registros", response_model=List[RegistroOut])
def get_registros(
    operacao_id: UUID,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[RegistroOut]:
    rows = db.execute(
        text("select * from registro_operacao where operacao_id = :o order by enviado_em desc"),
        {"o": str(operacao_id)},
    ).all()
    return [_registro_out(r) for r in rows]


@router.post("/operacoes/{operacao_id}/registros", response_model=RegistroOut, status_code=201)
def post_abrir_registro(
    operacao_id: UUID,
    body: AbrirRegistroIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> RegistroOut:
    """Abre um registro em 'pendente'.

    Hoje o envio à entidade é manual — não há integração porque não há
    entidade escolhida. Quando houver, este endpoint chama o adaptador e o
    resto do fluxo permanece igual.
    """
    existe = db.execute(
        text("select 1 from operacao_credito where id = :o"), {"o": str(operacao_id)}
    ).first()
    if existe is None:
        raise HTTPException(status_code=404, detail=f"Operação {operacao_id} não existe.")

    try:
        row = db.execute(
            text("""
            insert into registro_operacao (operacao_id, entidade, usuario_id)
            values (:o, :e, :u) returning *
            """),
            {"o": str(operacao_id), "e": body.entidade, "u": str(user.id)},
        ).one()
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise traduzir_erro_banco(exc) from exc
    return _registro_out(row)


class ConfirmarRegistroIn(BaseModel):
    protocolo: str = Field(min_length=1, max_length=255)


@router.post("/registros/{registro_id}/confirmar", response_model=RegistroOut)
def post_confirmar_registro(
    registro_id: UUID,
    body: ConfirmarRegistroIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> RegistroOut:
    """
    Confirma o registro com o protocolo devolvido pela entidade.

    Protocolo é obrigatório por constraint no banco: registro confirmado sem
    número é indistinguível de alguém marcando a caixinha — que é
    exatamente o problema do `registro_entidade_ref` de texto livre.

    Confirmado é estado TERMINAL (OC018): reverter apagaria a prova de que a
    operação existe legalmente.
    """
    try:
        row = db.execute(
            text("""
            update registro_operacao
               set status = 'confirmado', protocolo = :p, confirmado_em = clock_timestamp()
             where id = :r
            returning *
            """),
            {"r": str(registro_id), "p": body.protocolo},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Registro {registro_id} não existe.")
        db.commit()
    except IntegrityError as exc:
        # Violação do índice único de confirmado: é regra de negócio, não
        # falha de infraestrutura, e precisa de mensagem própria — deixá-la
        # cair no handler genérico devolveria 500 para algo previsto.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Esta operação já tem um registro confirmado em entidade registradora.",
        ) from exc
    except DBAPIError as exc:
        db.rollback()
        raise traduzir_erro_banco(exc) from exc
    return _registro_out(row)


class RejeitarRegistroIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=500)


@router.post("/registros/{registro_id}/rejeitar", response_model=RegistroOut)
def post_rejeitar_registro(
    registro_id: UUID,
    body: RejeitarRegistroIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_operador_user),
) -> RegistroOut:
    """Rejeição exige motivo: sem ele, a próxima tentativa repete o erro."""
    try:
        row = db.execute(
            text("""
            update registro_operacao
               set status = 'rejeitado', motivo_rejeicao = :m
             where id = :r
            returning *
            """),
            {"r": str(registro_id), "m": body.motivo},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Registro {registro_id} não existe.")
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        raise traduzir_erro_banco(exc) from exc
    return _registro_out(row)


class PendenciaRegistroOut(BaseModel):
    operacao_id: UUID
    status: str
    valor_principal: Decimal
    registro_entidade_ref: Optional[str]
    tomador_razao_social: str
    tem_registro_pendente: bool
    tem_contrato: bool


@router.get("/registros/pendencias", response_model=List[PendenciaRegistroOut])
def get_pendencias_registro(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> List[PendenciaRegistroOut]:
    """
    Operações registradas, ativas ou inadimplentes SEM registro confirmado.

    É a medida da lacuna: hoje `registro_entidade_ref` é texto livre e o
    gate aceita qualquer string. Esta lista existe para embasar a decisão de
    ligar a exigência de registro confirmado na ativação — com o número na
    mão, e não no escuro.
    """
    rows = db.execute(
        text("""
        select operacao_id, status, valor_principal, registro_entidade_ref,
               tomador_razao_social, tem_registro_pendente, tem_contrato
        from v_operacoes_sem_registro_confirmado
        order by valor_principal desc
    """)
    ).all()
    return [
        PendenciaRegistroOut(
            operacao_id=r.operacao_id,
            status=r.status,
            valor_principal=r.valor_principal,
            registro_entidade_ref=r.registro_entidade_ref,
            tomador_razao_social=r.tomador_razao_social,
            tem_registro_pendente=r.tem_registro_pendente,
            tem_contrato=r.tem_contrato,
        )
        for r in rows
    ]
