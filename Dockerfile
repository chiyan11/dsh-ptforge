# ptforge — offline Packet Tracer toolkit in a container.
#
# The container ships the *offline* half of ptforge: .pkt decode/encode, topology
# building, config patching, state inspection, assertions, reports and note
# injection. The runtime tools (pt_exec / pt_ping / pt_http_get / pt_ftp / pt_gui)
# drive a real Packet Tracer window on Windows and are intentionally unavailable
# here — Packet Tracer is a Windows GUI app and does not run in this image.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/ptforge

WORKDIR /opt/ptforge

# Optional pip index override for restricted networks, e.g.
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .
ARG PIP_INDEX_URL=

# Copy only what the package needs so rebuilds stay cheap.
COPY pyproject.toml README.md LICENSE ./
COPY ptforge ./ptforge

RUN pip install --no-cache-dir ${PIP_INDEX_URL:+--index-url=${PIP_INDEX_URL}} . \
    && useradd --create-home --uid 10001 ptforge \
    && mkdir -p /work \
    && chown -R ptforge:ptforge /work /opt/ptforge

USER ptforge
WORKDIR /work

# `docker run --rm -v "$PWD:/work" ghcr.io/chiyan11/ptforge:latest build spec.json -o out.pkt`
ENTRYPOINT ["ptforge"]
CMD ["--help"]
