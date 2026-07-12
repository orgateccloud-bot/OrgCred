"""Testes de app.core.logging — mascaramento de PII (LGPD)."""

from app.core.logging import mask_pii


class TestMaskPII:
    def test_mascara_cpf_formatado(self) -> None:
        texto = "Tomador com CPF 123.456.789-01 solicitou crédito"
        assert "123.456.789-01" not in mask_pii(texto)
        assert "***.***.***-**" in mask_pii(texto)

    def test_mascara_cnpj_formatado(self) -> None:
        texto = "Empresa CNPJ 12.345.678/0001-99 ativou operação"
        resultado = mask_pii(texto)
        assert "12.345.678/0001-99" not in resultado

    def test_mascara_cpf_sem_formatacao(self) -> None:
        texto = "CPF bruto: 12345678901 no payload"
        resultado = mask_pii(texto)
        assert "12345678901" not in resultado

    def test_nao_mascara_texto_sem_pii(self) -> None:
        texto = "Operação ativada com sucesso, valor R$ 30000.00"
        assert mask_pii(texto) == texto

    def test_nao_mascara_numeros_curtos(self) -> None:
        texto = "Operação 12345 processada"
        assert mask_pii(texto) == texto
