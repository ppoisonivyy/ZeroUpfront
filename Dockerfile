FROM node:24-bookworm-slim AS web
WORKDIR /build
COPY web/package*.json ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM python:3.12-slim-bookworm
WORKDIR /srv/zeroupfront
COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv uv sync --locked --no-dev --no-install-project
COPY app/ app/
COPY fixtures/rulebooks.json fixtures/rulebooks.json
COPY fixtures/discharge/ fixtures/discharge/
COPY fixtures/policies/ fixtures/policies/
COPY fixtures/cases/ fixtures/cases/
COPY --from=web /build/dist/ web/dist/
ENV PATH=/srv/zeroupfront/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
EXPOSE 8080
CMD ["uvicorn","app.workspace_server:app","--host","0.0.0.0","--port","8080","--no-access-log"]
