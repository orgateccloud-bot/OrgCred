"""
Configuração central — via variáveis de ambiente, nunca hardcoded
(lição registrada do OrgConc: exposição de credencial foi bloqueador real).

Correção da revisão de 2026-07-11: a versão anterior tinha um método
__post_init_check__ que NUNCA era executado (nome inventado, sem
mecanismo que o chamasse) — ou seja, a proteção contra subir produção
com banco default era código morto. Agora a validação roda no import.
"""
import os


class ConfigError(RuntimeError):
    pass


DATABASE_URL = os.environ.get(
    "ORGCRED_DATABASE_URL",
    "postgresql://localhost/orgcred_dev",  # só dev local
)
ENVIRONMENT = os.environ.get("ORGCRED_ENV", "development")

if ENVIRONMENT == "production" and "localhost" in DATABASE_URL:
    raise ConfigError(
        "ORGCRED_DATABASE_URL não configurada para produção — "
        "recusando iniciar com valor default de desenvolvimento."
    )


class Settings:
    database_url: str = DATABASE_URL
    environment: str = ENVIRONMENT


settings = Settings()
