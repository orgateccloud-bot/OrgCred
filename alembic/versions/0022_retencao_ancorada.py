"""022 - a retenção de documento conta do ENCERRAMENTO da relação de negócio,
não do arquivamento: `tomador_documento.retencao_ate` vira PISO e o prazo
efetivo passa a ser derivado (OC013, Lei 9.613/98 art. 10, III).

Baseline convertido de migrations/022_retencao_ancorada.sql.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-15
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


def upgrade() -> None:
    """NENHUMA LINHA DE DADO É TOCADA, e é esse o ponto do desenho escolhido.

    `retencao_ate` continua com o valor que tinha; o que muda é que ele passa
    a ser lido como PISO, e a data-limite do DELETE passa a ser derivada por
    `fn_retencao_efetiva`. Não há backfill porque não há o que preencher — a
    âncora sai de `operacao_evento` (008), que já está gravada.

    O EFEITO IMEDIATO EM BASE COM DADOS É AMPLIAR RETENÇÃO, nunca reduzir:
    todo documento cujo tomador tenha operação viva, ou encerrada há menos de
    cinco anos, passa a ser recusado no DELETE onde antes (dependendo do
    piso) poderia passar. Documento de tomador sem operação nenhuma continua
    exatamente como estava. Se alguma rotina de expurgo existir do lado de
    fora, ela vai passar a receber OC013 em casos novos — que é o
    comportamento correto e o motivo desta migration.

    O QUE ESTA MIGRATION NÃO CONSEGUE DESFAZER: documentos que já foram
    apagados sob a regra antiga, no intervalo entre a 010 e hoje. Não há
    trilha de DELETE em `tomador_documento` e não haveria como reconstruir os
    bytes de qualquer forma. Quem quiser medir a exposição pode comparar as
    evidências existentes com os tomadores que já tiveram operação:

        select t.id, t.cnpj, t.razao_social
          from tomador t
         where exists (select 1 from operacao_credito o where o.tomador_id = t.id)
           and not exists (select 1 from tomador_documento d where d.tomador_id = t.id);

    Tomador com operação e sem NENHUMA evidência arquivada é ou cadastro
    anterior ao gate OC019 (014), ou expurgo indevido consumado.
    """
    sql = (_SQL_DIR / "022_retencao_ancorada.sql").read_text(encoding="utf-8")
    op.execute(sql)


def downgrade() -> None:
    """Reaplica a definição da 010 e, com ela, o defeito.

    Descer daqui devolve `fn_documento_retencao` à versão que compara
    `old.retencao_ate` com `current_date` — ou seja, volta a autorizar o
    DELETE de evidência de identificação cinco anos depois do ARQUIVAMENTO,
    que numa operação de 60 parcelas é cerca de cinco anos antes do que a Lei
    9.613/98, art. 10, III exige. É a única migration deste projeto cujo
    downgrade reabre uma janela de descumprimento legal, e por isso está
    escrito aqui em vez de ficar implícito.

    A DEFINIÇÃO ANTIGA É REESCRITA AQUI, e o arquivo da 010 NÃO é reexecutado.
    Reexecutá-lo seria o caminho curto e traria junto o que a 010 tem de
    desatualizado: ela recria `v_tomadores_sem_identificacao` sem
    'baixada_prejuizo' no filtro de capital exposto — correção que a 017 fez —
    e um downgrade que apaga a correção de outra migration não é downgrade,
    é regressão. O único objeto que a 022 alterou foi
    `fn_documento_retencao`, e é só ele que volta.

    As views e funções INTRODUZIDAS aqui são derrubadas explicitamente. A
    ordem importa: as funções dependem de `v_operacao_encerramento` e a view
    de leitura depende das funções, então sai de fora para dentro.
    """
    op.execute("""
        create or replace function fn_documento_retencao()
        returns trigger as $$
        begin
            if tg_op = 'DELETE' then
                if old.retencao_ate >= current_date then
                    raise exception
                        'Documento % do tomador % está em retenção legal até % (Lei 9.613/98, art. 10, III).',
                        old.nome_arquivo, old.tomador_id, old.retencao_ate
                        using errcode = 'OC013';
                end if;
                return old;
            end if;

            raise exception 'Evidência de identificação não pode ser alterada, apenas substituída por nova.'
                using errcode = 'OC013';
        end;
        $$ language plpgsql;
    """)
    op.execute("""
        comment on function fn_documento_retencao() is
            'OC013 — evidência de identificação: DELETE só depois de vencida a retenção (Lei 9.613/98, art. 10, III) e UPDATE nunca, em coluna nenhuma. Isso inclui storage_objeto (migration 019): repontar a linha para outro objeto seria trocar o documento arquivado sem trocar o hash.';
    """)

    op.execute("drop view if exists v_documento_retencao")
    op.execute("drop function if exists fn_retencao_efetiva(uuid, date)")
    op.execute("drop function if exists fn_retencao_efetiva_em(uuid, date, date)")
    op.execute("drop function if exists fn_encerramento_relacao(uuid, date)")
    op.execute("drop function if exists fn_relacao_em_curso(uuid, date)")
    op.execute("drop view if exists v_operacao_encerramento")
