# Docker Usage Guide

## Building the Docker Image

```bash
docker build -t human-eval-olmo .
```

## Running the Container

### Basic Usage
```bash
docker run -p 5001:5001 -v $(pwd)/data:/app/data human-eval-olmo
```

### With Custom Data File
```bash
docker run -p 5001:5001 -v $(pwd)/data:/app/data human-eval-olmo \
    python app.py --comparison_data_path data/your_data_file.jsonl --host 0.0.0.0 --port 5001
```

### Development Mode with Debug
```bash
docker run -p 5001:5001 -v $(pwd):/app human-eval-olmo \
    python app.py --comparison_data_path data/your_data_file.jsonl --host 0.0.0.0 --port 5001 --debug
```

## Docker Compose (Alternative)

Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  human-eval-olmo:
    build: .
    ports:
      - "5001:5001"
    volumes:
      - ./data:/app/data
    environment:
      - FLASK_ENV=production
    restart: unless-stopped
```

Then run:
```bash
# Production
docker-compose up -d

# Development with file watching
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

## Important Notes

1. **Data Persistence**: The SQLite database is stored in the `data/` directory. Make sure to mount this volume to persist evaluation data.

2. **Port Configuration**: The default port is 5001. Change both the host port mapping and the container command if you need a different port.

3. **Security**: The default secret key is hardcoded. For production, set a secure secret key via environment variable.

4. **Data File**: Ensure your comparison data file (JSONL format) is available in the `data/` directory before starting the container.

## Environment Variables

- `FLASK_ENV`: Set to `development` for debug mode
- `PYTHONUNBUFFERED`: Ensures Python output is not buffered (already set in Dockerfile)
- `PYTHONDONTWRITEBYTECODE`: Prevents Python from writing .pyc files (already set in Dockerfile)

## Accessing the Application

Once running, access the application at: http://localhost:5001