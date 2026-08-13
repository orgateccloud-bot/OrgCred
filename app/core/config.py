"""
Configuração central via variáveis de ambiente (pydantic-settings).

Validação ocorre no startup da aplicação (lifespan), não no import de módulo.
Recusa iniciar em produção sem `ORGCRED_DATABASE_URL` e sem
`ORGCRED_SUPABASE_JWT_SECRET` explícitas.
"""

import os

from pydantic_settings import BaseSettings


# Segredo de JWT de desenvolvimento. Está versionado neste repositório de
# propósito (docker-compose e o seed do e2e mintam token com ele), o que
# significa que em produção ele não é segredo nenhum: qualquer um que leia o
# repo assina um JWT válido. A guarda de startup precisa reconhecê-lo, daí a
# constante em vez do literal solto no default do campo.
# nosec B105: o bandit acerta o diagnóstico e erra o alvo — isto é mesmo um
# segredo em código, e é assim de propósito. Justamente por isso a guarda de
# `validate_startup` recusa iniciar em produção com este valor.
JWT_SECRET_DEV_DEFAULT = "dev-secret-key-change-in-prod"  # nosec B105


class ConfigError(RuntimeError):
    """Erro de configuração durante startup."""

    pass


class Settings(BaseSettings):
    """Configurações centralizadas."""

    database_url: str = "postgresql+psycopg://localhost/orgcred_dev"
    environment: str = "development"
    debug: bool = False
    supabase_jwt_secret: str = JWT_SECRET_DEV_DEFAULT

    # ------------------------------------------------------------------
    # Storage dos documentos de identificação (Supabase Storage)
    # ------------------------------------------------------------------
    # TRÊS COISAS DIFERENTES, e o painel do Supabase as mostra juntas, o que
    # é a origem da confusão:
    #
    #   1. JWT Secret (`supabase_jwt_secret`, acima) — segredo de ASSINATURA.
    #      Serve para VALIDAR os tokens que o frontend manda
    #      (app/core/security.py). Não abre porta nenhuma sozinho.
    #   2. anon key — chave PÚBLICA, assada no bundle do frontend em tempo de
    #      build (ver os ARG do Dockerfile). Quem protege os dados por trás
    #      dela é a RLS, não o segredo dela. Não aparece aqui de propósito:
    #      o backend não tem uso para ela.
    #   3. service_role key (`supabase_service_key`, abaixo) — chave de
    #      SERVIDOR, atravessa RLS. É a que grava no bucket. NUNCA pode ir
    #      para o frontend, nem para log, nem para mensagem de erro.
    #
    # Trocar uma pela outra não produz erro de configuração: produz 401 do
    # bucket na hora de arquivar um documento, com o resto da aplicação de
    # pé — o sintoma mais caro de diagnosticar que existe aqui.
    #
    # SEM DEFAULT, e essa é a decisão que corrige o defeito histórico. Vazio,
    # `storage_configurado` é falso e arquivar evidência é RECUSADO (503, ver
    # app/core/storage.py e app/routers/compliance.py). Um default plausível
    # faria o arquivamento aceitar o documento e perder os bytes em silêncio,
    # que é exatamente o que o sistema fazia antes da migration 019: afirmar
    # que a identificação está arquivada sem nada arquivado.
    #
    # O STARTUP NÃO QUEBRA sem estas duas. O OrgCred opera sem compliance
    # ativo — capital, operações, cobrança e fiscal não dependem do bucket —,
    # então derrubar a aplicação inteira por causa do storage trocaria uma
    # operação recusada por um sistema fora do ar. Por isso `validate_startup`
    # não as exige, ao contrário da URL do banco e do JWT Secret.
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Nome do bucket. Tem default porque é NOME, não credencial: errá-lo dá
    # 404 imediato e explícito na primeira gravação, não uma falha silenciosa.
    # Fica gravado junto de cada referência em `tomador_documento.storage_objeto`
    # (migration 019) — a retenção é de 5 anos e o bucket configurado muda,
    # então a linha antiga não pode depender deste valor para achar o objeto.
    supabase_storage_bucket: str = "identificacao-tomador"

    @property
    def storage_configurado(self) -> bool:
        """Há onde guardar os bytes da evidência de identificação?

        Os dois campos juntos, e não um só: a URL sem a chave dá 401 e a
        chave sem a URL não tem para onde apontar. Meia configuração é
        configuração nenhuma, e a única resposta honesta é recusar antes de
        aceitar o arquivo.
        """
        return bool(self.supabase_url.strip() and self.supabase_service_key.strip())

    # Identificação da própria ESC, usada como CREDORA no instrumento
    # contratual. Vazio por padrão de propósito: um default plausível
    # ("ORGATEC ESC LTDA", um CNPJ qualquer) entraria num documento com
    # efeito jurídico como se fosse dado real. Sem configuração, a emissão
    # do contrato é recusada — ver app/routers/contratos.py.
    esc_razao_social: str = ""
    esc_cnpj: str = ""
    esc_municipio: str = ""
    esc_uf: str = ""

    @property
    def esc_identificada(self) -> bool:
        return all([self.esc_razao_social, self.esc_cnpj, self.esc_municipio, self.esc_uf])

    class Config:
        env_prefix = "ORGCRED_"
        env_file = ".env"
        case_sensitive = False

    def validate_startup(self) -> None:
        """Validação crítica chamada no startup da aplicação."""
        if self.environment == "production":
            # Exige URL explícita em produção
            from_env = os.environ.get("ORGCRED_DATABASE_URL")
            if not from_env or "localhost" in from_env:
                raise ConfigError(
                    "ORGCRED_DATABASE_URL não configurada para produção — "
                    "recusando iniciar com valor default de desenvolvimento."
                )

            # Exige segredo de JWT próprio pelo mesmo motivo: com o default
            # público qualquer um assina um token que o backend aceita.
            # Atenção ao prefixo — pydantic-settings lê
            # `ORGCRED_SUPABASE_JWT_SECRET`; `SUPABASE_JWT_SECRET` sem prefixo
            # é ignorado e cai silenciosamente no default.
            if (
                not self.supabase_jwt_secret.strip()
                or self.supabase_jwt_secret == JWT_SECRET_DEV_DEFAULT
            ):
                raise ConfigError(
                    "ORGCRED_SUPABASE_JWT_SECRET não configurada para produção — "
                    "recusando iniciar com valor default de desenvolvimento."
                )


def get_settings() -> Settings:
    """Factory com validação integrada."""
    settings = Settings()
    settings.validate_startup()
    return settings


settings = get_settings()
