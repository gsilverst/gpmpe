FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Backend dependencies
RUN pip install --no-cache-dir \
  "fastapi>=0.116.0,<1.0.0" \
  "fpdf2>=2.8,<3.0" \
  "Pillow>=11.0,<12.0" \
  "PyYAML>=6.0.2,<7.0.0" \
  "reportlab>=4.0,<5.0" \
  "uvicorn[standard]>=0.32.0,<1.0.0"

COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/out/ ./backend/app/static/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
