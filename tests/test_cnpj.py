"""Testes unitários da validação de CNPJ (app/core/cnpj.py) — sem banco."""

import pytest

from app.core.cnpj import cnpj_valido, normalizar_cnpj


class TestNormalizarCnpj:
    def test_remove_mascara(self) -> None:
        assert normalizar_cnpj("11.222.333/0001-81") == "11222333000181"

    def test_ja_normalizado_inalterado(self) -> None:
        assert normalizar_cnpj("11222333000181") == "11222333000181"

    def test_espacos_e_vazio(self) -> None:
        assert normalizar_cnpj("  11 222 333 0001 81 ") == "11222333000181"
        assert normalizar_cnpj("") == ""


class TestCnpjValido:
    @pytest.mark.parametrize(
        "cnpj",
        [
            "11222333000181",  # base de teste clássica
            "04252011000110",  # exemplo real bem-formado
        ],
    )
    def test_cnpj_bem_formado(self, cnpj: str) -> None:
        assert cnpj_valido(cnpj) is True

    def test_dv_incorreto(self) -> None:
        # Último dígito trocado de 1 para 2
        assert cnpj_valido("11222333000182") is False

    def test_tamanho_errado(self) -> None:
        assert cnpj_valido("1122233300018") is False  # 13 dígitos
        assert cnpj_valido("112223330001810") is False  # 15 dígitos

    def test_nao_numerico(self) -> None:
        assert cnpj_valido("1122233300018X") is False

    def test_digitos_repetidos(self) -> None:
        # Passam no checksum módulo 11, mas não são CNPJs reais.
        assert cnpj_valido("00000000000000") is False
        assert cnpj_valido("11111111111111") is False
