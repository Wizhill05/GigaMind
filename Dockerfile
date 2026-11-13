# Stage 1: Build React Frontend SPA
FROM node:22.23.4-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python FastAPI Backend Server
FROM python:3.12.16-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gigamind/*.py ./gigamind/
COPY gigamind/db/*.py ./gigamind/db/
COPY gigamind/services/*.py ./gigamind/services/
COPY gigamind/routers/*.py ./gigamind/routers/
COPY gigamind/middleware/*.py ./gigamind/middleware/
COPY gigamind/cli/*.py ./gigamind/cli/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "gigamind.main:app", "--host", "0.0.0.0", "--port", "8000"]
