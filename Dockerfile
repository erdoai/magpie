# Stage 1: Build web UI
FROM node:20-slim AS web-builder
WORKDIR /web
COPY web/package.json ./
RUN npm install
COPY web/ .
RUN npm run build

# Stage 2: Python app
FROM python:3.11-slim
WORKDIR /app

COPY pyproject.toml README.md ./
COPY magpie/ magpie/
COPY --from=web-builder /web/dist web/dist/

RUN pip install --no-cache-dir .

EXPOSE 8200

CMD ["magpie", "serve"]
