# ---- Build Stage ----
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies if strictly needed (like gcc, libpq-dev for psycopg2-binary, though binary often avoids this)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (postgres client + OpenMP for LightGBM/XGBoost + WeasyPrint libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgomp1 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
 && rm -rf /var/lib/apt/lists/*

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create a non-root user
RUN groupadd -g 1000 appgroup && \
    useradd -u 1000 -g appgroup -s /sbin/nologin -m appuser

# Copy source code
COPY . .

# Ensure appuser owns the directory
RUN chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
