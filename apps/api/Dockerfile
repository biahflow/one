# Imagem da API, do worker e do beat (ADR 0022 reescreveu esta imagem).
#
# Até a Fase 5 ela era uma imagem de desenvolvimento em produção: instalava o
# `requirements-dev.txt` — pytest e cobertura junto do runtime —, **copiava
# `tests/` para dentro** e rodava como root. Nada disso doía na stack local, que
# é a única que existia; num ambiente alcançável de fora, cada um dos três é
# superfície que não paga aluguel.
#
# Duas etapas: a primeira constrói o virtualenv com as dependências de runtime,
# a segunda leva só o virtualenv e o código. O compilador e o cache do pip ficam
# na primeira e não chegam à imagem final.

FROM python:3.14-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Só o `requirements.txt`: o `-dev` traz pytest e pytest-cov, que são ferramenta
# de quem desenvolve e não de quem serve. Os testes rodam no CI, contra o código
# do repositório, e nunca dentro desta imagem.
COPY requirements.txt ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY alembic.ini ./
COPY src ./src

# Usuário sem privilégio. A porta é 8000, acima de 1024, então nada aqui precisa
# de root — e o worker escreve só em /tmp (o `--schedule` do beat).
RUN useradd --system --uid 10001 --shell /usr/sbin/nologin portal \
    && chown -R portal:portal /app
USER portal

EXPOSE 8000
CMD ["uvicorn", "portal_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
