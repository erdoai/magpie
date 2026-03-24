FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY magpie/ magpie/
COPY web/dist/ web/dist/

RUN pip install --no-cache-dir .

EXPOSE 8200

CMD ["magpie", "serve"]
