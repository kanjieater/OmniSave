# Stage 1: Build React UI
FROM node:20-slim AS ui-builder
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ .
RUN rm -f node_modules/.tmp/tsconfig.app.tsbuildinfo && npx vite build

# Stage 2: Python server
FROM python:3.11-slim
ARG GIT_SHA=unknown
ENV OMNISAVE_VERSION=${GIT_SHA}
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ /app/src/
COPY --from=ui-builder /ui/dist/ /app/static/
CMD ["python", "-u", "src/main.py"]
