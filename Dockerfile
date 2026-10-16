FROM node:22-alpine AS ui
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npx tsc --noEmit && npx vite build --outDir /ui --emptyOutDir

FROM python:3.12-slim-bookworm
ARG SOURCE_SHA=development
LABEL org.opencontainers.image.title="Lo-Fi Studio OS" org.opencontainers.image.revision="${SOURCE_SHA}"
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10002 --create-home studio
COPY studio ./studio
COPY web ./web
COPY --from=ui /ui ./web/app
USER 10002
CMD ["uvicorn","studio.api:app","--host","0.0.0.0","--port","8787"]
