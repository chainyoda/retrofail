FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    python-multipart \
    rdkit \
    pandas

# Targets are committed to git (public.csv + hidden.csv from USPTO-190)

# Data dir (overridden by fly volume mount at /data)
ENV RETROFAIL_DATA=/data
ENV STATIC_DISABLED=1
RUN mkdir -p /data

EXPOSE 8080
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080"]
