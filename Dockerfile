# Image du serveur SourcIA (config/serveur.yaml) : Gemini, recherche légère, données dans le volume /data.
# Construire : docker build -t sourcia .       Lancer sur son PC : docker compose up (voir docker-compose.yml)
# Aucun secret ni aucune donnée dans l'image (.dockerignore) : GEMINI_API_KEY et SOURCIA_SESSION_SECRET sont donnés
# au démarrage par l'hébergeur ; catalogue, comptes et dossiers vivent dans /data.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SOURCIA_CONFIG=config/serveur.yaml \
    SOURCIA_DATA_DIR=/data \
    PORT=8000

WORKDIR /app

# utilisateur sans droits d'administrateur ; il possède seulement le volume des données
RUN useradd --create-home --uid 10001 sourcia && mkdir -p /data && chown sourcia:sourcia /data

# dépendances du serveur seulement (pas de PyTorch : la recherche légère n'en a pas besoin)
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install -e ".[api,cloud,pptx,word]" "pymupdf>=1.24"

COPY config ./config
COPY scripts ./scripts

USER sourcia
VOLUME /data
EXPOSE 8000

# l'hébergeur redémarre le conteneur si l'application ne répond plus
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/etat' % os.environ.get('PORT', '8000'), timeout=4)"

# PORT : beaucoup d'hébergeurs imposent leur port par cette variable
CMD ["sh", "-c", "exec sourcia serve --host 0.0.0.0 --port \"${PORT:-8000}\""]
