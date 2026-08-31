# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV DATA_PATH=/app/data
ENV COMPARISON_DATA_PATH=/app/data/eval_instances.jsonl

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip --timeout=1000 install --trusted-host pypi.python.org --trusted-host pypi.org --trusted-host=files.pythonhosted.org --no-cache-dir -r requirements.txt

# Copy application code (excluding data directory which will be mounted)
COPY . /app

# Ensure data directory exists for GCS mount
RUN mkdir -p /mnt/gcs
RUN ln -s /mnt/gcs/human-evaluation /app/data # set up before deployment!!!
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose port 5001 (default port from the app)
EXPOSE 5001

# Health check using the main route
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/')" || exit 1

# Default command - uses environment variable for data path
# Single worker: SQLite lives on a GCS FUSE mount, which cannot arbitrate writes between processes
ENTRYPOINT [ "/app/entrypoint.sh" ]
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5001} --workers 1 --threads 8 --timeout 120 --access-logfile - app:app"]
