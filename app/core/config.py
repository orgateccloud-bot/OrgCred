"""
Configuração central via variáveis de ambiente (pydantic-settings).

Validação ocorre no startup da aplicação (lifespan), não no import de módulo.
Recusa iniciar em produção sem `ORGCRED_DATABASE_URL` explícita.
"""

import os

from pydantic_settings import BaseSettings


class ConfigError(RuntimeError):
    """Erro de configuração durante startup."""

    pass


class Settings(BaseSettings):
    """Configurações centralizadas."""

    database_url: str = "postgresql://localhost/orgcred_dev"
    environment: str = "development"
    debug: bool = False
    supabase_jwt_secret: str = "dev-secret-key-change-in-prod"

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


def get_settings() -> Settings:
    """Factory com validação integrada."""
    settings = Settings()
    settings.validate_startup()
    return settings


settings = get_settings()
