FROM python:3.13-slim-bookworm AS caixa
RUN apt-get update && apt-get install -y --no-install-recommends bash git nodejs chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home residente \
    && mkdir /workspace && chown 1000:1000 /workspace
RUN pip install --no-cache-dir websocket-client==1.9.2
COPY sentury/residentes/caixa_cdp.py /opt/sentury/caixa_cdp.py
ENV HOME=/workspace PYTHONUNBUFFERED=1
USER 1000:1000
WORKDIR /workspace
CMD ["sleep", "infinity"]

FROM python:3.13-slim-bookworm AS hq
RUN apt-get update && apt-get install -y --no-install-recommends docker.io git ffmpeg libmagic1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY sentury/plugins/robinbandit ./sentury/plugins/robinbandit
RUN pip install --no-cache-dir -e "./sentury/plugins/robinbandit[yaml,providers]"
COPY pyproject.toml README.md sentury.py ./
COPY sentury ./sentury
RUN pip install --no-cache-dir -e .
ENV SENTURY_HOME=/var/lib/sentury PYTHONUNBUFFERED=1 PYTHONUTF8=1 SENTURY_DOMAIN=generalista
EXPOSE 8000
CMD ["python", "-m", "sentury.residentes.servidor_hq"]
