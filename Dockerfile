# Shared Debian/glibc base; dependency layers do not depend on application source.
FROM python:3.14-slim-trixie AS common
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends gosu libseccomp2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
COPY scripts/runtime_requirements.py scripts/runtime_requirements.py
RUN python scripts/runtime_requirements.py api > /tmp/api-requirements.txt \
    && pip install --no-cache-dir -r /tmp/api-requirements.txt \
    && rm /tmp/api-requirements.txt
COPY docker-entrypoint.sh .
RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data \
    && chown appuser:appuser /app/data && chmod 755 /app/docker-entrypoint.sh
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]

FROM common AS document-deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libjpeg62-turbo libopenjp2-7 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
RUN python scripts/runtime_requirements.py documents > /tmp/document-requirements.txt \
    && pip install --no-cache-dir -r /tmp/document-requirements.txt \
    && rm /tmp/document-requirements.txt

FROM common AS browser-deps
RUN python scripts/runtime_requirements.py browser > /tmp/browser-requirements.txt \
    && pip install --no-cache-dir -r /tmp/browser-requirements.txt \
    && python -m playwright install --with-deps --no-shell chromium \
    && rm /tmp/browser-requirements.txt && rm -rf /var/lib/apt/lists/*

FROM common AS api
COPY . .
ENV CVTAILOR_RUNTIME_ROLE=api PROCESSING_REQUIRED=true

FROM document-deps AS documents
# Preserve the legacy Chromium image's font coverage and Arial metrics for PDF.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation fonts-freefont-ttf fonts-ipafont-gothic fonts-wqy-zenhei \
    fonts-noto-color-emoji fonts-tlwg-loma-otf fonts-unifont xfonts-scalable \
    && rm -rf /var/lib/apt/lists/*
COPY . .
ENV PROCESSING_ROLE=documents
USER 10001:10001
EXPOSE 8080
ENTRYPOINT []
CMD ["uvicorn", "app.processing_server:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--limit-concurrency", "8"]
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"

FROM browser-deps AS browser
COPY . .
ENV PROCESSING_ROLE=browser
USER 10001:10001
EXPOSE 8080
ENTRYPOINT []
CMD ["uvicorn", "app.processing_server:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--limit-concurrency", "8"]
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"

# Compatibility target for existing CD/Kubernetes tooling and full-stack tests.
# New Compose services select api/documents/browser explicitly.
FROM document-deps AS full-deps
RUN python scripts/runtime_requirements.py browser > /tmp/browser-requirements.txt \
    && pip install --no-cache-dir -r /tmp/browser-requirements.txt \
    && python -m playwright install --with-deps chromium \
    && rm /tmp/browser-requirements.txt && rm -rf /var/lib/apt/lists/*

FROM full-deps AS full
COPY . .
ENV PROCESSING_ROLE=full CVTAILOR_RUNTIME_ROLE=full
