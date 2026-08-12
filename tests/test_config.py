"""
Testes de app.core.config — valida a guarda de produção (Fase 0/1 da revisão:
o `__post_init_check__` antigo nunca era chamado; a versão atual roda no
startup via `validate_startup()`).
"""

import pytest

from app.core.config import JWT_SECRET_DEV_DEFAULT, ConfigError, Settings


SECRET_REAL = "uma-jwt-secret-real-de-instancia-supabase"
URL_PROD = "postgresql://user:pass@prod-db.example.com:5432/orgcred"


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Isola a configuração das duas fontes que o ambiente local injeta.

    Sem isso o resultado depende da máquina de quem roda a suíte: uma
    `ORGCRED_SUPABASE_JWT_SECRET` exportada no shell faria o teste do
    default passar por acidente. O `.env` é a mesma armadilha por outro
    caminho — SETUP.md manda copiar `.env.example` para `.env` e editar com
    credenciais reais, e pydantic-settings lê esse arquivo; quem tiver a
    secret real do Supabase no `.env` veria falhar os testes que exigem o
    fallback para o default.
    """
    monkeypatch.delenv("ORGCRED_DATABASE_URL", raising=False)
    monkeypatch.delenv("ORGCRED_SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


class TestValidacaoProducao:
    def test_producao_com_localhost_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORGCRED_DATABASE_URL", "postgresql://localhost/orgcred_dev")
        monkeypatch.setenv("ORGCRED_SUPABASE_JWT_SECRET", SECRET_REAL)
        settings = Settings(environment="production")

        with pytest.raises(ConfigError, match="ORGCRED_DATABASE_URL"):
            settings.validate_startup()

    def test_producao_sem_variavel_de_ambiente_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORGCRED_SUPABASE_JWT_SECRET", SECRET_REAL)
        settings = Settings(environment="production")

        with pytest.raises(ConfigError, match="ORGCRED_DATABASE_URL"):
            settings.validate_startup()

    def test_producao_com_url_explicita_nao_localhost_passa(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ORGCRED_DATABASE_URL", URL_PROD)
        monkeypatch.setenv("ORGCRED_SUPABASE_JWT_SECRET", SECRET_REAL)
        settings = Settings(environment="production")

        settings.validate_startup()  # não deve lançar

    def test_desenvolvimento_com_localhost_passa(self) -> None:
        settings = Settings(environment="development")
        settings.validate_startup()  # não deve lançar


class TestGuardaJwtSecret:
    """
    Regressão do incidente: com o default público versionado no repo,
    qualquer um assina um JWT que o backend aceita. Produção tem que
    recusar iniciar.
    """

    def test_producao_com_secret_default_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORGCRED_DATABASE_URL", URL_PROD)
        monkeypatch.setenv("ORGCRED_SUPABASE_JWT_SECRET", JWT_SECRET_DEV_DEFAULT)
        settings = Settings(environment="production")

        with pytest.raises(ConfigError, match="ORGCRED_SUPABASE_JWT_SECRET"):
            settings.validate_startup()

    def test_producao_sem_secret_nenhuma_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sem a variável no ambiente, o campo cai no default — mesmo buraco."""
        monkeypatch.setenv("ORGCRED_DATABASE_URL", URL_PROD)
        settings = Settings(environment="production")

        assert settings.supabase_jwt_secret == JWT_SECRET_DEV_DEFAULT
        with pytest.raises(ConfigError, match="ORGCRED_SUPABASE_JWT_SECRET"):
            settings.validate_startup()

    def test_producao_com_secret_vazia_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORGCRED_DATABASE_URL", URL_PROD)
        monkeypatch.setenv("ORGCRED_SUPABASE_JWT_SECRET", "   ")
        settings = Settings(environment="production")

        with pytest.raises(ConfigError, match="ORGCRED_SUPABASE_JWT_SECRET"):
            settings.validate_startup()

    def test_producao_com_secret_real_passa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORGCRED_DATABASE_URL", URL_PROD)
        monkeypatch.setenv("ORGCRED_SUPABASE_JWT_SECRET", SECRET_REAL)
        settings = Settings(environment="production")

        settings.validate_startup()  # não deve lançar

    def test_producao_ignora_secret_sem_prefixo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        `SUPABASE_JWT_SECRET` sem o prefixo `ORGCRED_` não é lida pelo
        pydantic-settings (env_prefix). Quem provisiona ambiente novo copiando
        o nome errado fica com o default — e o startup tem que recusar, não
        aceitar por engano. É o nome que o .env.example ensinava antes.
        """
        monkeypatch.setenv("ORGCRED_DATABASE_URL", URL_PROD)
        monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET_REAL)
        settings = Settings(environment="production")

        assert settings.supabase_jwt_secret == JWT_SECRET_DEV_DEFAULT
        with pytest.raises(ConfigError, match="ORGCRED_SUPABASE_JWT_SECRET"):
            settings.validate_startup()

    def test_desenvolvimento_com_secret_default_passa(self) -> None:
        """O fluxo local não pode quebrar: em dev o default é aceito."""
        settings = Settings(environment="development")

        assert settings.supabase_jwt_secret == JWT_SECRET_DEV_DEFAULT
        settings.validate_startup()  # não deve lançar
