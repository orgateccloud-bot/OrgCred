"""
Métricas de negócio via prometheus-client.

Expostas em GET /metrics para scraping por Prometheus.
Cobrem: operações ativadas, bloqueios por SQLSTATE, capital disponível.
"""

from prometheus_client import Counter, Gauge, Histogram


# Contadores de eventos de negócio
operacoes_ativadas_total = Counter(
    "orgcred_operacoes_ativadas_total",
    "Total de operações de crédito ativadas com sucesso",
)

operacoes_bloqueadas_total = Counter(
    "orgcred_operacoes_bloqueadas_total",
    "Total de tentativas de ativação bloqueadas, por código SQLSTATE",
    labelnames=["sqlstate"],
)

operacoes_liquidadas_total = Counter(
    "orgcred_operacoes_liquidadas_total",
    "Total de operações de crédito liquidadas",
)

operacoes_renegociadas_total = Counter(
    "orgcred_operacoes_renegociadas_total",
    "Total de renegociações (novações) concluídas",
)

auth_falhas_total = Counter(
    "orgcred_auth_falhas_total",
    "Total de falhas de autenticação/autorização",
    labelnames=["tipo"],  # token_ausente, token_invalido, permissao_negada
)

# Gauge: capital disponível no momento da última consulta
capital_disponivel_gauge = Gauge(
    "orgcred_capital_disponivel",
    "Capital disponível para novas operações (última leitura)",
)

# Histograma: latência de requisições HTTP
http_request_duration_seconds = Histogram(
    "orgcred_http_request_duration_seconds",
    "Duração de requisições HTTP em segundos",
    labelnames=["method", "path", "status_code"],
)


def registrar_ativacao() -> None:
    """Incrementa contador de ativação bem-sucedida."""
    operacoes_ativadas_total.inc()


def registrar_liquidacao() -> None:
    """Incrementa contador de liquidação bem-sucedida."""
    operacoes_liquidadas_total.inc()


def registrar_renegociacao() -> None:
    """Incrementa contador de renegociação (novação) concluída."""
    operacoes_renegociadas_total.inc()


def registrar_bloqueio(sqlstate: str) -> None:
    """Incrementa contador de bloqueio por código SQLSTATE."""
    operacoes_bloqueadas_total.labels(sqlstate=sqlstate).inc()


def registrar_falha_auth(tipo: str) -> None:
    """Incrementa contador de falha de autenticação."""
    auth_falhas_total.labels(tipo=tipo).inc()


def atualizar_capital_disponivel(valor: float) -> None:
    """Atualiza gauge de capital disponível."""
    capital_disponivel_gauge.set(valor)
