# OrgCred — imagem multi-stage: build do frontend (Vite) + backend (uv),
# servidos por um único processo FastAPI (Fase F4 — ver app/main.py,
# StaticFiles com fallback de SPA).
FROM node:24-slim AS frontend-builder

# O Vite resolve `import.meta.env.VITE_*` em tempo de BUILD, não de runtime —
# definir essas variáveis só no serviço do Railway não teria efeito algum, o
# bundle sairia com os placeholders e o login ficaria inerte. O Railway injeta
# variáveis do serviço como build args apenas quando declaradas com ARG na
# stage que as usa (ver docs.railway.com/builds/dockerfiles).
#
# Sem valor, o ARG fica vazio e `supabaseConfigurado` (frontend/src/auth/
# supabaseClient.ts) continua false — degradação controlada, não quebra.
#
# A anon key é pública por design (o Supabase a expõe no cliente; quem protege
# os dados é a RLS, não o segredo da chave). Assar no bundle é o uso correto —
# o que NUNCA pode entrar aqui é a service_role key.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY

# O ENV não é redundante com o ARG acima. O valor de um ARG já chega ao `RUN`
# como variável de ambiente, mas o Docker só invalida o cache de uma camada
# quando a variável é *referenciada* textualmente na instrução — e
# `RUN npm run build` não menciona $VITE_SUPABASE_URL. Resultado: trocar o
# valor no Railway não invalidava nada e o build reaproveitava o bundle antigo,
# com os placeholders assados dentro (observado em produção).
#
# A instrução ENV entra no histórico da imagem com o valor já resolvido, então
# qualquer troca desses valores invalida esta camada e todas abaixo dela —
# incluindo o `npm run build`.
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /build
COPY pyproject.toml ./
RUN uv pip install --system --no-cache .

FROM python:3.12-slim AS runtime

RUN useradd --create-home --shell /bin/bash orgcred
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY --from=frontend-builder /frontend/dist ./static/

USER orgcred

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# As migrations NÃO rodam aqui. Elas são a `preDeployCommand` do railway.json,
# fase que executa UMA vez por deploy, antes de qualquer réplica subir.
#
# Enquanto estavam neste CMD, cada réplica aplicava o schema no seu próprio
# start: com mais de uma, duas instâncias corriam `alembic upgrade head` contra
# o mesmo banco ao mesmo tempo. E uma migration que falhasse no meio deixava o
# schema parcialmente aplicado com o contêiner em loop de restart, tentando de
# novo — cada tentativa partindo de um estado diferente do anterior.
#
# O fluxo local não depende disto: o docker-compose sobrescreve `command` e
# aplica as migrations por lá (ver docker-compose.yml).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
