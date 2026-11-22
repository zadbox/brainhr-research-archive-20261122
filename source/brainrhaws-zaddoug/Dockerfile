FROM --platform=linux/amd64 node:22.23.1-trixie-slim@sha256:0294f5e1475165b804b2c585c6ab4f6cab5e4d8fb5bf2c856006632a1037ca26 AS company-cv-node-deps

WORKDIR /renderer

COPY tools/company_cv_html_renderer/package.json tools/company_cv_html_renderer/package-lock.json ./
RUN npm ci --omit=dev

FROM python:3.11.15-slim-trixie@sha256:a7bce671c71744cd4dcef2bc9cd9c5eff3d7cfa6b55eca30759765047184bcdb

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends --no-install-suggests \
        ca-certificates \
        libpq5 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=company-cv-node-deps /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

COPY requirements.txt requirements-api.txt alembic.ini ./
RUN pip install -r requirements-api.txt

COPY . /app
RUN find /app \( -name '._*' -o -name '.DS_Store' -o -name '__MACOSX' \) -prune -exec rm -rf {} \;

COPY --from=company-cv-node-deps /renderer/node_modules /app/tools/company_cv_html_renderer/node_modules

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
