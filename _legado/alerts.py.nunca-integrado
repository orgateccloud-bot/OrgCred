"""
Alertas simples via email (SMTP) para eventos operacionais críticos.

Escopo mínimo viável: dois gatilhos documentados na Fase 3 do plano de
modernização — capital baixo e rajada de bloqueios (possível ataque).
Produção real deve integrar com um canal de alerta já monitorado (Slack,
PagerDuty); este módulo é o ponto de extensão.
"""

import os
import smtplib
from email.mime.text import MIMEText

from app.core.logging import get_logger


logger = get_logger("app.alerts")

CAPITAL_BAIXO_LIMIAR_PCT = 0.20  # alerta se capital disponível < 20% do capital total
BLOQUEIOS_RAJADA_LIMIAR = 5  # alerta se 5+ bloqueios em janela curta

ALERT_EMAIL_TO = os.environ.get("ORGCRED_ALERT_EMAIL_TO", "")
ALERT_SMTP_HOST = os.environ.get("ORGCRED_SMTP_HOST", "")
ALERT_SMTP_PORT = int(os.environ.get("ORGCRED_SMTP_PORT", "587"))
ALERT_SMTP_USER = os.environ.get("ORGCRED_SMTP_USER", "")
ALERT_SMTP_PASSWORD = os.environ.get("ORGCRED_SMTP_PASSWORD", "")


def _enviar_email(assunto: str, corpo: str) -> None:
    """Envia email de alerta via SMTP configurado. No-op se não configurado."""
    if not (ALERT_EMAIL_TO and ALERT_SMTP_HOST and ALERT_SMTP_USER):
        logger.warning(
            "alert_smtp_nao_configurado",
            assunto=assunto,
            motivo="ORGCRED_ALERT_EMAIL_TO/SMTP_HOST/SMTP_USER ausentes",
        )
        return

    msg = MIMEText(corpo)
    msg["Subject"] = f"[OrgCred ALERTA] {assunto}"
    msg["From"] = ALERT_SMTP_USER
    msg["To"] = ALERT_EMAIL_TO

    try:
        with smtplib.SMTP(ALERT_SMTP_HOST, ALERT_SMTP_PORT) as server:
            server.starttls()
            server.login(ALERT_SMTP_USER, ALERT_SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("alert_email_enviado", assunto=assunto)
    except Exception as e:
        logger.error("alert_email_falhou", assunto=assunto, erro=str(e))


def checar_capital_baixo(capital_disponivel: float, capital_total: float) -> None:
    """Dispara alerta se capital disponível cair abaixo do limiar."""
    if capital_total <= 0:
        return
    pct = capital_disponivel / capital_total
    if pct < CAPITAL_BAIXO_LIMIAR_PCT:
        _enviar_email(
            "Capital disponível baixo",
            f"Capital disponível: R$ {capital_disponivel:,.2f} "
            f"({pct:.1%} do capital total de R$ {capital_total:,.2f}). "
            f"Limiar de alerta: {CAPITAL_BAIXO_LIMIAR_PCT:.0%}.",
        )


def checar_rajada_bloqueios(contagem_ultima_hora: int) -> None:
    """Dispara alerta se houver rajada de bloqueios (possível ataque ou erro sistêmico)."""
    if contagem_ultima_hora >= BLOQUEIOS_RAJADA_LIMIAR:
        _enviar_email(
            "Rajada de operações bloqueadas",
            f"{contagem_ultima_hora} operações bloqueadas na última hora "
            f"(limiar: {BLOQUEIOS_RAJADA_LIMIAR}). Verificar logs para padrão de ataque "
            f"ou erro sistêmico.",
        )
