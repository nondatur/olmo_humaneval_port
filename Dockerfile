# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip --timeout=1000 install --trusted-host pypi.python.org --trusted-host pypi.org --trusted-host=files.pythonhosted.org --no-cache-dir -r requirements.txt

# Copy application code (excluding data directory which will be mounted)
COPY . /app

# Create data directory for GCS mount point
# RUN ln -s /tmp/ibaic-genai-data /tmp/data

# Verify that the data directory exists/was mounted
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

# Expose port 5001 (default port from the app)
EXPOSE 5001

# Health check using the main route
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5001/')" || exit 1

# Default command - requires comparison_data_path to be provided
CMD ["python", "app.py", "--comparison_data_path", "data/eval_instances_mm_base.jsonl", "--host", "0.0.0.0", "--port", "5001"]
