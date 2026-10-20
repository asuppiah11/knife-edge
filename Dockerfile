# Knife-Edge API + studio UI. Runs in template mode by default; set FOUNDRY_ENDPOINT for LLM mode.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000

COPY pyproject.toml README.md ./
COPY knifeedge ./knifeedge
COPY schemas ./schemas
COPY web ./web
COPY data/sample ./data/sample

RUN pip install --no-cache-dir -e ".[mcp]" openai azure-identity

# Bake a few synthetic matches and the ratings into the image so the demo is instant and deterministic.
RUN knife-edge season --out data/ratings.json \
 && knife-edge generate --seed 42 --out data/matches/KE-000042 \
 && knife-edge generate --seed 7 --out data/matches/KE-000007 \
 && knife-edge generate --seed 1001 --out data/matches/KE-001001

ENV KNIFE_EDGE_MATCHES=/app/data/matches KNIFE_EDGE_RATINGS=/app/data/ratings.json
EXPOSE 8000
CMD ["sh", "-c", "uvicorn knifeedge.api.app:app --host 0.0.0.0 --port ${PORT}"]
