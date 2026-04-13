FROM python:3.12-slim

WORKDIR /app

# System deps for asyncpg and lxml
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install CPU-only torch first to avoid pulling CUDA (saves ~1.5GB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-download FinBERT so first query doesn't stall on model download
RUN python -c "from transformers import AutoTokenizer, AutoModel; AutoTokenizer.from_pretrained('ProsusAI/finbert'); AutoModel.from_pretrained('ProsusAI/finbert')"

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
