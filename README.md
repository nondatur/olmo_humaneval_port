# Human Evaluation Annotation Interface

This folder contains the code for the human eval annotation interface used in the paper [How Far Can Camels Go? Exploring the State of Instruction Tuning on Open Resources](https://arxiv.org/abs/2306.04751).

## Installation

```bash
conda create -n human_eval python=3.11
conda activate human_eval
pip install -r requirements.txt
```

## Running the Interface

Before running the app, you need to put evaluation instance in the `data` folder. Each instance should have a prompt and two completions from two different models. We provide an example in `data/eval_instances_tulu_1.jsonl`.

Each line of this file should be in the following format:

```json
{
    "id": "unique instance id",
    "prompt": "prompt text",
    "completions": [
        {
            "model": "model 1 name",
            "completion": "completion text"
        },
        {
            "model": "model 2 name",
            "completion": "completion text"
        }
    ]
}
```

The `id` field is required: it is stored with every submitted annotation and is used to group
repeated annotations of the same instance when computing agreement.

### Configuration and secrets

The app is configured through environment variables. Nothing sensitive is stored in the code.

| Variable | Required | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | Recommended | Signs Flask session cookies. If unset, a random key is generated at startup, which invalidates sessions on every restart. Must be set in any real deployment. |
| `SIGNUP_TOKEN` | Optional | Registration token. **If unset, `/signup` returns 404 and no new accounts can be created.** |
| `ADMIN_PASSWORD` | On first run | Password for the initial `admin` account. The app refuses to start rather than fall back to a default password. |
| `DATA_PATH` | Optional | Directory holding `evaluation.db`. Defaults to `./data`. |

Generate values with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"     # SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(24))" # SIGNUP_TOKEN
```

Now you can run the app with:
```bash
SECRET_KEY=... SIGNUP_TOKEN=... ADMIN_PASSWORD=... \
    python app.py --comparison_data_path data/your_data_file.jsonl --host 0.0.0.0 --port 5001
```

Or, in debug mode:
```bash
python app.py --comparison_data_path data/your_data_file.jsonl --host 0.0.0.0 --port 5001 --debug
```

For local testing there is a helper script that sets throwaway credentials and starts the app on
`127.0.0.1:5001`:

```bash
./run_local.sh                                          # defaults
DATA_FILE=data/eval_instances_tulu_1.jsonl ./run_local.sh
PORT=8080 ./run_local.sh --debug
```

### Accounts

The `admin` account is created once, on the first run, when `data/evaluation.db` does not yet exist.
Changing `ADMIN_PASSWORD` afterwards does not update the existing account.

Other annotators register themselves: click **Switch to Signup** and supply the username, a password
of at least 8 characters, and the registration token you share with them. Leave `SIGNUP_TOKEN` unset
to disable registration entirely once everyone is onboarded.

You can open the app in your browser at http://localhost:5001. When doing the annotation, you can track the progress at the following url: http://localhost:5001/summary.

### Endpoints

| Endpoint | Method | Auth | Description |
| --- | --- | --- | --- |
| `/` | GET | – | Redirects to the first instance, or to the login page |
| `/login` | GET, POST | – | Login form and submission |
| `/signup` | GET, POST | Registration token | Account creation; 404 when `SIGNUP_TOKEN` is unset |
| `/logout` | GET | Session | Logs the current user out |
| `/instances/<index>` | GET | – | Annotation interface for one instance |
| `/api/model-outputs/<index>` | GET | – | Prompt and completions, order randomised |
| `/api/submit-evaluation` | POST | Session | Stores an acceptance/preference annotation |
| `/api/submit-feedback` | POST | Session | Stores instance-quality feedback and comments |
| `/summary` | GET | Session | Progress, contributions and agreement metrics as JSON |
| `/export_results` | GET | Session | Downloads all annotations as an `.xlsx` file |

Here is a screenshot of the annotation interface:

<center>

   ![image](./screenshot.png)

</center>

## Post-processing and Analysis

The annotation results are saved in a database file `data/evaluation.db` by default. You can use the following command to export the results to an excel file:

```bash
python export_db.py data/eval_annotations.xlsx
```

Then, you can use the following command to compute the evaluation metrics and agreements:

```bash
python compute_metrics.py data/eval_annotations.xlsx
```

This generates the metrics JSON file and two Matplotlib charts:

```text
data/eval_annotations_results.json
data/eval_annotations_acceptance_rates.png
data/eval_annotations_comparison_preferences.png
```

## Tests

To run the unit tests, type:
```bash
pytest -v tests/human_eval_tests.py
```

The tests are self-contained: they run against a fresh in-memory SQLite database and never touch
`data/evaluation.db`.

## Deployment

The workflow in `.github/workflows/compile_and_test_gcp.yaml` runs the unit tests, builds the
container and pushes it to Artifact Registry. Deployment to Cloud Run is a separate, opt-in stage.

| Stage | When it runs |
| --- | --- |
| Test, build, push | Every push to `master` |
| Deploy to Cloud Run | Only when a pushed commit message contains `[deploy]`, or when a pull request is closed |

The deploy step mounts a Cloud Storage bucket at `/mnt/gcs` using Cloud Storage FUSE. The image
symlinks `/app/data` to `/mnt/gcs/human-evaluation`, so `evaluation.db` lives in the bucket and
survives restarts and scale-to-zero. The service runs with `--max-instances=1`, because SQLite over
Cloud Storage FUSE is not safe to write from several instances at once, and with
`--allow-unauthenticated`, so the application login is the only access control.

The following repository/environment secrets must be defined in the `docker-env` GitHub environment:

| Secret | Purpose |
| --- | --- |
| `GCP_SA_KEY` | Service account key used to authenticate to Google Cloud |
| `GCP_PROJECT` | Target Google Cloud project |
| `GCS_BUCKET` | Bucket mounted at `/mnt/gcs` (bucket name only, without the `human-evaluation` folder) |
| `SECRET_KEY` | Flask session signing key |
| `SIGNUP_TOKEN` | Registration token handed to annotators |
| `ADMIN_PASSWORD` | Password of the initial `admin` account |

The deploy step fails fast if `GCS_BUCKET`, `SECRET_KEY` or `ADMIN_PASSWORD` is missing. The Cloud
Run service identity needs `roles/storage.objectUser` on the bucket, since the app writes to it.

## Notes

- The application version is defined by `APP_VERSION` in `app.py` and shown in the bottom-left corner of the interface
- This repository is derived from [Allen AI's Open Instruct project](https://github.com/allenai/open-instruct) (`human_eval`)
- The original license is Apache 2.0
- To build the container, check its [Docker](DOCKER.md) documentation
