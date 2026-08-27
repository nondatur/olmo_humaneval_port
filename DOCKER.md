# Docker Usage Guide

## Build the Image

```bash
docker build -t human-eval-olmo .
```

The image uses Python 3.11, exposes port `5001`, and starts the app through
`entrypoint.sh`. The entrypoint waits briefly for `/mnt/gcs` before starting the
command. In Cloud Run, that path is a Cloud Storage volume mount.

## Run Locally

The Dockerfile links `/app/data` to `/mnt/gcs/human-evaluation`. For a local
run, mount the local data directory at that target path:

```bash
docker run --rm \
  -p 5001:5001 \
  -v "$(pwd)/data:/mnt/gcs/human-evaluation" \
  -e SECRET_KEY=dev-secret-key \
  -e SIGNUP_TOKEN=dev-signup-token \
  -e ADMIN_PASSWORD=dev-admin-password \
  human-eval-olmo
```

Open http://localhost:5001. The local values above are throwaway values only.
For a local Python run with the same defaults, use `./run_local.sh` instead.

### Use Another Data File

The default container command loads `/app/data/eval_instances_mm_base.jsonl`.
To select another file, pass the command after the image name; the image
entrypoint forwards it to the container:

```bash
docker run --rm \
  -p 5001:5001 \
  -v "$(pwd)/data:/mnt/gcs/human-evaluation" \
  -e SECRET_KEY=dev-secret-key \
  -e SIGNUP_TOKEN=dev-signup-token \
  -e ADMIN_PASSWORD=dev-admin-password \
  human-eval-olmo \
  python app.py --comparison_data_path /app/data/your_data_file.jsonl \
    --host 0.0.0.0 --port 5001
```

### Debug Mode

```bash
docker run --rm \
  -p 5001:5001 \
  -v "$(pwd)/data:/mnt/gcs/human-evaluation" \
  -e SECRET_KEY=dev-secret-key \
  -e SIGNUP_TOKEN=dev-signup-token \
  -e ADMIN_PASSWORD=dev-admin-password \
  human-eval-olmo \
  python app.py --comparison_data_path /app/data/your_data_file.jsonl \
    --host 0.0.0.0 --port 5001 --debug
```

## Environment Variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | Production | Signs Flask session cookies. Set a stable, random value; changing it logs users out. |
| `SIGNUP_TOKEN` | Optional | Token required for account creation. Leave unset to disable signup. |
| `ADMIN_PASSWORD` | First run | Password for the initial `admin` account. Required when the database is created. |
| `DATA_PATH` | Optional | Database directory. Defaults to `/app/data` in the image. |
| `PYTHONDONTWRITEBYTECODE` | No | Set by the Dockerfile to prevent `.pyc` files. |
| `PYTHONUNBUFFERED` | No | Set by the Dockerfile for immediate log output. |
| `FLASK_APP` | No | Set by the Dockerfile to `app.py`. |
| `FLASK_ENV` | No | Set by the Dockerfile to `production`. |

Never put production values in a Dockerfile, compose file committed to git, or
command history. Use a secret store or your deployment platform's secret
configuration. The admin account is created only once; changing
`ADMIN_PASSWORD` later does not change an existing account.

## Cloud Run Deployment

The GitHub Actions workflow in `.github/workflows/compile_and_test_gcp.yaml`
runs unit tests, builds the image, and pushes it to Artifact Registry on every
push to `master`. The Cloud Run deploy step runs only when a push contains
`[deploy]` in one of its commit messages or when a pull request is closed.

The deploy command:

- uses the second-generation execution environment;
- allows unauthenticated network access, with Flask login providing application authentication;
- limits the service to one instance because SQLite is stored on the mounted volume;
- mounts the bucket at `/mnt/gcs`;
- maps `/app/data` to the `human-evaluation` folder inside that bucket.

The following secrets must exist in the GitHub `docker-env` environment:

| Secret | Purpose |
| --- | --- |
| `GCP_SA_KEY` | Google Cloud credentials used by the workflow |
| `GCP_PROJECT` | Target Google Cloud project |
| `GCS_BUCKET` | Bucket name only, without `/human-evaluation` |
| `SECRET_KEY` | Stable Flask session signing key |
| `SIGNUP_TOKEN` | Registration token for annotators |
| `ADMIN_PASSWORD` | Initial admin account password |

The Cloud Run runtime service account needs `roles/storage.objectUser` on the
bucket because the app writes `evaluation.db` and annotation records there.

## Docker Compose

If you use Compose locally, mount the data directory at the symlink target and
provide the required runtime variables:

```yaml
services:
  human-eval-olmo:
    build: .
    ports:
      - "5001:5001"
    volumes:
      - ./data:/mnt/gcs/human-evaluation
    environment:
      SECRET_KEY: dev-secret-key
      SIGNUP_TOKEN: dev-signup-token
      ADMIN_PASSWORD: dev-admin-password
```

Do not use these example values in a deployed service.

## Data and Health Check

The database is stored at `/app/data/evaluation.db`, which resolves to the
`human-evaluation` folder in the mounted volume. The image health check requests
`http://localhost:5001/`; it may receive a redirect to `/login`, which still
confirms that the server is responding.

Evaluation files must be JSONL, with one JSON object per line containing `id`,
`prompt`, and two `completions`. See `README.md` for the complete format.

## Tests

The image includes the pytest dependencies from `requirements.txt`. Run the
unit tests from the repository with:

```bash
pytest -v tests/human_eval_tests.py
```

The tests use an isolated in-memory SQLite database and do not access the
deployment bucket or the local `data/evaluation.db`.
