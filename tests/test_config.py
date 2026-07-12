"""
Testes de app.core.config — valida a guarda de produção (Fase 0/1 da revisão:
o `__post_init_check__` antigo nunca era chamado; a versão atual roda no
startup via `validate_startup()`).
"""

import pytest

from app.core.config import ConfigError, Settings


class TestValidacaoProducao:
    def test_producao_com_localhost_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORGCRED_DATABASE_URL", "postgresql://localhost/orgcred_dev")
        settings = Settings(environment="production")

        with pytest.raises(ConfigError, match="recusando iniciar"):
            settings.validate_startup()

    def test_producao_sem_variavel_de_ambiente_falha(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ORGCRED_DATABASE_URL", raising=False)
        settings = Settings(environment="production")

        with pytest.raises(ConfigError):
            settings.validate_startup()

    def test_producao_com_url_explicita_nao_localhost_passa(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "ORGCRED_DATABASE_URL", "postgresql://user:pass@prod-db.example.com:5432/orgcred"
        )
        settings = Settings(environment="production")

        settings.validate_startup()  # não deve lançar

    def test_desenvolvimento_com_localhost_passa(self) -> None:
        settings = Settings(environment="development")
        settings.validate_startup()  # não deve lançar
