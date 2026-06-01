FROM python:3.12-slim

ARG GIT_SHA=dev
WORKDIR /app

# Install system dependencies (curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .
RUN echo "$GIT_SHA" > VERSION

# Create data directory
RUN mkdir -p /var/lib/internapp

# Run as non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app /var/lib/internapp
USER appuser

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
