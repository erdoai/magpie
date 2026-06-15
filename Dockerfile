# Base images come from the AWS ECR Public mirror of Docker's official library,
# not Docker Hub — Docker Hub anonymous pull limits throttle shared CI/builder
# IPs (e.g. Railway), which stalls `load metadata` for minutes per build.

# Stage 1: build the web UI
FROM public.ecr.aws/docker/library/node:24-slim AS web-builder
WORKDIR /web
# Install from the lockfile first so this layer is cached until deps change —
# and so the image matches the committed yarn.lock instead of re-resolving.
COPY web/package.json web/yarn.lock ./
RUN yarn install --frozen-lockfile
COPY web/ .
RUN yarn build

# Stage 2: Python runtime
FROM public.ecr.aws/docker/library/python:3.14-slim
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY magpie/ magpie/
COPY --from=web-builder /web/dist web/dist/

RUN pip install .

EXPOSE 8200

# serve does NOT auto-migrate; platforms should run `magpie migrate` first
# (see railway.json startCommand / docker-compose command).
CMD ["magpie", "serve"]
