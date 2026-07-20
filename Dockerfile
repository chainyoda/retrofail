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

# Generate hidden targets at build time (baked in, not in git)
RUN python3 targets/generate.py --seed 42 --public 10 --hidden 100 --out-dir targets/

# Data dir (overridden by fly volume mount at /data)
ENV RETROFAIL_DATA=/data
ENV STATIC_DISABLED=1
RUN mkdir -p /data

EXPOSE 8080
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8080"]
