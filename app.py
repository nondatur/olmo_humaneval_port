import argparse
import hashlib
import json
import os
import random
import secrets
import time, sqlite3
from collections import Counter
from contextlib import closing
from functools import lru_cache
from io import BytesIO
import pandas as pd

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for, make_response
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool
from werkzeug.security import check_password_hash, generate_password_hash

import logging
log = logging.getLogger('human-eval')

app = Flask(__name__)

# Use environment variable for data path, fallback to default
DATA_DIR = os.environ.get('DATA_PATH', os.path.join(os.getcwd(), 'data'))
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, 'evaluation.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + DB_PATH
# The database lives on a Cloud Storage FUSE mount, which only uploads a file when it is
# closed; pooled connections would keep committed rows staged locally and never persisted.
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'poolclass': NullPool}
log.info(app.config['SQLALCHEMY_DATABASE_URI'])

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    # Ephemeral key for local runs; sessions do not survive a restart or extra instances
    SECRET_KEY = secrets.token_hex(32)
    log.warning('SECRET_KEY is not set; generated a temporary key for this process.')
app.config['SECRET_KEY'] = SECRET_KEY

# Signup is disabled unless a registration token is configured
SIGNUP_TOKEN = os.environ.get('SIGNUP_TOKEN')
MIN_PASSWORD_LENGTH = 8

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)

# GLOBAL VARIABLE for the comparison instances
COMPARISON_INSTANCES=[]

APP_VERSION = "v1.1.1"

DEFAULT_QUESTIONS_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "evaluation_questions.json"
)
QUESTIONS_CONFIG_PATH = os.environ.get(
    "EVALUATION_QUESTIONS_PATH", DEFAULT_QUESTIONS_CONFIG_PATH
)
REQUIRED_QUESTION_KEYS = {
    "feedback_question",
    "evaluation_intro",
    "acceptance_question_a",
    "acceptance_question_b",
    "preference_question",
}


def load_evaluation_questions(config_path):
    """Read the evaluator-facing question text without changing answer values."""
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            questions = json.load(config_file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Could not load evaluation questions from {config_path}: {error}"
        ) from error

    if not isinstance(questions, dict):
        raise RuntimeError("Evaluation questions configuration must be a JSON object.")

    missing_keys = REQUIRED_QUESTION_KEYS - questions.keys()
    invalid_keys = [key for key in REQUIRED_QUESTION_KEYS if not isinstance(questions.get(key), str)]
    if missing_keys or invalid_keys:
        details = []
        if missing_keys:
            details.append("missing: " + ", ".join(sorted(missing_keys)))
        if invalid_keys:
            details.append("must be strings: " + ", ".join(sorted(invalid_keys)))
        raise RuntimeError("Invalid evaluation questions configuration (" + "; ".join(details) + ").")

    # Add optional button labels with defaults
    defaults = {
        "preference_label_a_clearly_better": "A is clearly better",
        "preference_label_a_slightly_better": "A is slightly better",
        "preference_label_tie": "Tie",
        "preference_label_b_slightly_better": "B is slightly better",
        "preference_label_b_clearly_better": "B is clearly better",
    }
    for key, default_value in defaults.items():
        if key not in questions:
            questions[key] = default_value
        elif not isinstance(questions[key], str):
            questions[key] = default_value

    return questions


EVALUATION_QUESTIONS = load_evaluation_questions(QUESTIONS_CONFIG_PATH)


@app.context_processor
def inject_app_version():
    return {"app_version": APP_VERSION}


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))


class EvaluationRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    instance_index = db.Column(db.Integer)
    instance_id = db.Column(db.String(200))
    prompt = db.Column(db.String(1e4))
    model_a = db.Column(db.String(200))
    model_b = db.Column(db.String(200))
    completion_a = db.Column(db.String(1e4))
    completion_b = db.Column(db.String(1e4))
    completion_a_is_acceptable = db.Column(db.String(50))
    completion_b_is_acceptable = db.Column(db.String(50))
    preference = db.Column(db.String(50))
    instance_quality = db.Column(db.String(50))
    comment = db.Column(db.String(1e4))
    evaluator = db.Column(db.String(100))
    timestamp = db.Column(db.String(100))


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            # Redirect to first unsubmitted instance
            first_pos = get_first_unsubmitted_position()
            return redirect(url_for('instances', index=first_pos))
        else:
            return 'Invalid username or password'
    else:
        return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if not SIGNUP_TOKEN:
        abort(404)
    if request.method == 'POST':
        if not secrets.compare_digest(request.form.get('token', ''), SIGNUP_TOKEN):
            return render_template('login.html', error='Invalid registration token.'), 403

        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username:
            return render_template('login.html', error='Username is required.'), 400
        if len(password) < MIN_PASSWORD_LENGTH:
            return render_template(
                'login.html',
                error=f'Password must be at least {MIN_PASSWORD_LENGTH} characters.'
            ), 400
        if User.query.filter_by(username=username).first():
            return render_template('login.html', error='That username is already taken.'), 409

        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return render_template('login.html', error='That username is already taken.'), 409
        return redirect(url_for('login'))
    else:
        return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/')
def index():
    # check if the user is logged in
    if current_user.is_authenticated:
        first_pos = get_first_unsubmitted_position()
        return redirect(url_for('instances', index=first_pos, current_user=current_user))
    else:
        return redirect(url_for('login'))


@app.route('/instances/<int:index>')
def instances(index):
    progress = get_user_progress_payload(current_user.username if current_user.is_authenticated else None)
    return render_template(
        'index.html',
        index=index,
        current_user=current_user,
        questions=EVALUATION_QUESTIONS,
        progress=progress,
    )


def _stable_seed(*parts):
    raw = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def _user_key():
    return current_user.username if current_user.is_authenticated else "anonymous"


@lru_cache(maxsize=None)
def _instance_order(user_key, num_instances):
    order = list(range(num_instances))
    random.Random(_stable_seed("order", user_key)).shuffle(order)
    return order


def instance_order():
    """Global instance indices in the order this user should evaluate them."""
    return _instance_order(_user_key(), len(COMPARISON_INSTANCES))


def get_first_unsubmitted_position():
    """Get the position in the user's personal ordering of the first unsubmitted instance."""
    if not current_user.is_authenticated:
        return 0
    
    order = instance_order()
    user_records = EvaluationRecord.query.filter_by(
        evaluator=current_user.username
    ).filter(EvaluationRecord.preference != "").all()
    completed_indices = {record.instance_index for record in user_records}
    
    for position, global_index in enumerate(order):
        if global_index not in completed_indices:
            return position
    
    if not order:
        return 0

    # All instances completed, return last position
    return len(order) - 1


def get_user_progress_payload(username=None):
    """Compute user progress with unique instance counts and bounded percentage."""
    total = len(COMPARISON_INSTANCES)
    if not username:
        return {"completed": 0, "total": total, "percentage": 0}

    user_records = EvaluationRecord.query.filter_by(
        evaluator=username
    ).filter(EvaluationRecord.preference != "").all()
    completed_indices = {record.instance_index for record in user_records}
    completed = len(completed_indices)

    if total == 0:
        percentage = 0
    else:
        percentage = int((completed / total) * 100)
        percentage = max(0, min(100, percentage))

    return {
        "completed": completed,
        "total": total,
        "percentage": percentage,
    }


def ordered_completions(instance):
    """Copy of the completions, side-swapped at random on every view."""
    completions = list(instance["completions"])
    if random.random() < 0.5:
        completions.reverse()
    return completions


@app.route("/api/model-outputs/<int:position>", methods=["GET"])
def get_model_outputs(position):
    order = instance_order()
    if 0 <= position < len(order):
        instance = COMPARISON_INSTANCES[order[position]]
        return jsonify({
            "prompt": instance["prompt"],
            "completions": ordered_completions(instance),
            "instance_index": order[position],
            "total": len(order),
        }), 200
    return jsonify({"error": "Index out of range"}), 200


@app.route("/summary", methods=["GET"])
@login_required
def summary():
    results = summarize_results()
    return jsonify(results), 200


@app.route("/export_results", methods=["GET"])
@login_required
def export():

    # Export the evaluation results as excel
    with closing(sqlite3.connect(DB_PATH)) as conn:
        df = pd.read_sql_query("SELECT * from evaluation_record", conn)

    # Write Excel file to an in-memory buffer
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    output.seek(0)

    # Build a response with the xlsx file
    response = make_response(output.read())
    response.headers["Content-Disposition"] = "attachment; filename=mm_evaluation_data.xlsx"
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Return the response
    return response, 200


def count_user_contributions(users, records):
    user_contributions = {}
    for user in users:
        user_contributions[user.username] = 0
    for record in records:
        user_contributions[record.evaluator] += 1
    user_contributions["all"] = len(records)
    return user_contributions


def get_progress(records):
    completed_instance_indices = set([record.instance_index for record in records])
    missing_instances = []
    for index in range(len(COMPARISON_INSTANCES)):
        if index not in completed_instance_indices:
            missing_instances.append(index)
    return {
        "completed": len(completed_instance_indices),
        "total": len(COMPARISON_INSTANCES),
        "missing_indices": missing_instances,
    }


def get_acceptance_results(records, target_model_a, target_model_b):
    acceptance_results = {
        target_model_a: {},
        target_model_b: {},
    }
    for record in records:
        instance_id = record.instance_id
        if instance_id not in acceptance_results[record.model_a]:
            acceptance_results[record.model_a][instance_id] = []
        acceptance_results[record.model_a][instance_id].append(record.completion_a_is_acceptable)

        if instance_id not in acceptance_results[record.model_b]:
            acceptance_results[record.model_b][instance_id] = []
        acceptance_results[record.model_b][instance_id].append(record.completion_b_is_acceptable)

    # count how many instances get multiple annotations
    instances_with_multiple_annotations = [instance_id for instance_id, results in acceptance_results[record.model_a].items() if len(results) > 1]
    agreement_results = {
        "num_instances_with_multiple_annotations": len(instances_with_multiple_annotations),
        "acceptance_agreement": None,
    }
    assert target_model_a in acceptance_results
    assert target_model_b in acceptance_results
    # get agreement on acceptance
    if len(instances_with_multiple_annotations) > 0:
        agreed_model_a_acceptance = 0
        agreed_model_b_acceptance = 0
        for instance_id in instances_with_multiple_annotations:
            if len(set(acceptance_results[target_model_a][instance_id][-2:])) == 1:
                agreed_model_a_acceptance += 1
            if len(set(acceptance_results[target_model_b][instance_id][-2:])) == 1:
                agreed_model_b_acceptance += 1
        agreement_results["acceptance_agreement"] = \
            (agreed_model_a_acceptance + agreed_model_b_acceptance) / (2 * len(instances_with_multiple_annotations))
        agreement_results[f"{target_model_a}_acceptance_agreement"] = agreed_model_a_acceptance / len(instances_with_multiple_annotations)
        agreement_results[f"{target_model_b}_acceptance_agreement"] = agreed_model_b_acceptance / len(instances_with_multiple_annotations)

    return {
        f"{target_model_a}": sum([1 if x[-1]=="yes" else 0 for _, x in acceptance_results[target_model_a].items()]) / len(acceptance_results[target_model_a]),
        f"{target_model_b}": sum([1 if x[-1]=="yes" else 0 for _, x in acceptance_results[target_model_b].items()]) / len(acceptance_results[target_model_b]),
        "agreement": agreement_results,
    }


def get_comparison_results(records, target_model_a, target_model_b):
    comparison_results = {}
    for record in records:
        instance_id = record.instance_id
        model_a = record.model_a
        model_b = record.model_b
        if instance_id not in comparison_results:
            comparison_results[instance_id] = []

        if record.preference == "a-is-better":
            comparison_results[instance_id].append(f"{model_a} is clearly better")
        elif record.preference == "a-is-slightly-better":
            comparison_results[instance_id].append(f"{model_a} is slightly better")
        elif record.preference == "b-is-better":
            comparison_results[instance_id].append(f"{model_b} is clearly better")
        elif record.preference == "b-is-slightly-better":
            comparison_results[instance_id].append(f"{model_b} is slightly better")
        elif record.preference == "tie":
            comparison_results[instance_id].append("tie")
        else:
            log.warning("-------------------------------------")
            log.warning("Unknown preference value.")
            log.warning(record)

    # there can be multiple annotations for each instance
    # use the latest comparison result for each instance
    latest_comparison_results = [results[-1] for _,
                                 results in comparison_results.items()]
    model_wins_counter = Counter(latest_comparison_results)
    model_wins_rates = {
        result: count / len(latest_comparison_results) for result,
        count in model_wins_counter.items()
    }
    # merge the clearly better and slightly better results
    model_wins_rates[f"{target_model_a}_wins"] = \
        sum([v for k, v in model_wins_rates.items() if target_model_a in k])
    model_wins_rates[f"{target_model_b}_wins"] = \
        sum([v for k, v in model_wins_rates.items() if target_model_b in k])

    # count how many instances get multiple annotations
    instances_with_multiple_annotations = [
                instance_id for instance_id,
                results in comparison_results.items() if len(results) > 1]
    agreement_results = {"num_instances_with_multiple_annotations":
                         len(instances_with_multiple_annotations),
                         "comparison_agreement": None,
                         "relexed_comparison_agreement": None,
                         }
    if instances_with_multiple_annotations:
        agreed_comparison = 0
        relexed_agreed_comparison = 0
        for instance_id in instances_with_multiple_annotations:
            simplified_comparisons = []
            for comparison_result in comparison_results[instance_id]:
                if comparison_result == "tie":
                    simplified_comparisons.append("tie")
                elif target_model_a in comparison_result:
                    simplified_comparisons.append(target_model_a)
                elif target_model_b in comparison_result:
                    simplified_comparisons.append(target_model_b)
                else:
                    log.warning("Unknown comparison result.")
                    log.warning(comparison_result)
            if len(set(simplified_comparisons[-2:])) == 1:
                agreed_comparison += 1
                relexed_agreed_comparison += 1
            else:
                if "tie" in simplified_comparisons[-2:]:
                    relexed_agreed_comparison += 0.5
        agreement_results["comparison_agreement"] = (agreed_comparison /
                                                     len(instances_with_multiple_annotations))
        agreement_results["relexed_comparison_agreement"] = (relexed_agreed_comparison /
                                                             len(instances_with_multiple_annotations))

    model_wins_rates["agreement"] = agreement_results
    return model_wins_rates


def summarize_results():
    results = {}
    users = User.query.all()
    records = EvaluationRecord.query.all()

    # get the number of completed instances for all and each user
    results["user_contributions"] = count_user_contributions(users, records)

    # get the missing instances
    results["progress"] = get_progress(records)

    # get the comparison model pairs
    model_pairs = set([tuple(sorted([record.model_a, record.model_b])) for record in records])
    results["model_pairs"] = list(model_pairs)

    results["results"] = {}
    for target_model_a, target_model_b in model_pairs:
        feedback_records = {}
        comparison_records = []
        for record in records:

            # instance id is used to identify the comparison instance
            # there could be multiple records for the same instance
            # instance_id = record.instance_id

            # skip if the record is not for the target model pair
            if set([target_model_a, target_model_b]) != set([record.model_a, record.model_b]):
                assert any([set([record.model_a, record.model_b]) == set(pair) for pair in model_pairs])
                continue

            # skip if the record is a feedback
            if record.instance_quality:
                if record.instance_quality not in feedback_records:
                    feedback_records[record.instance_quality] = []
                feedback_records[record.instance_quality].append(record.instance_index)
                continue

            comparison_records.append(record)

        acceptance_results = get_acceptance_results(comparison_records, 
                                                    target_model_a, target_model_b)
        comparison_results = get_comparison_results(comparison_records, 
                                                    target_model_a, target_model_b)
        results["results"][f"{target_model_a}_vs_{target_model_b}"] = {
            "acceptance_results": acceptance_results,
            "comparison_results": comparison_results,
            "feedback_records": feedback_records,
        }
    return results


@app.route("/api/submit-evaluation", methods=["POST"])
@login_required
def submit_evaluation():
    evaluation_data = request.get_json()
    log.info("Got new evaluation data:")
    log.info(evaluation_data)
    instance_index = evaluation_data["index"]
    if not isinstance(instance_index, int) or not 0 <= instance_index < len(COMPARISON_INSTANCES):
        return jsonify({"error": "Invalid instance index"}), 400
    
    # A feedback row for this instance does not prevent its evaluation.
    existing_record = EvaluationRecord.query.filter_by(
        evaluator=current_user.username,
        instance_index=instance_index
    ).filter(EvaluationRecord.preference != "").first()
    if existing_record:
        return jsonify({"error": "You already submitted an evaluation for this instance."}), 409
    
    # write to the database
    new_record = EvaluationRecord(
        instance_index=instance_index,
        instance_id=COMPARISON_INSTANCES[instance_index]["id"],
        prompt=evaluation_data["prompt"],
        model_a=evaluation_data["model_a"],
        model_b=evaluation_data["model_b"],
        completion_a=evaluation_data["completion_a"],
        completion_b=evaluation_data["completion_b"],
        completion_a_is_acceptable=evaluation_data["completion_a_is_acceptable"],
        completion_b_is_acceptable=evaluation_data["completion_b_is_acceptable"],
        preference=evaluation_data["preference"],
        instance_quality="",
        comment="",
        evaluator=current_user.username,
        timestamp=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
    )
    db.session.add(new_record)
    db.session.commit()
    return jsonify({"message": "Evaluation data submitted successfully"}), 200


@app.route("/api/submit-feedback", methods=["POST"])
@login_required
def submit_feedback():
    feedback_data = request.get_json()
    log.info("Got new feedback:")
    log.info(feedback_data)
    instance_index = feedback_data["index"]
    if not isinstance(instance_index, int) or not 0 <= instance_index < len(COMPARISON_INSTANCES):
        return jsonify({"error": "Invalid instance index"}), 400
    
    # Feedback and evaluation are separate submissions, but feedback itself is unique.
    existing_records = EvaluationRecord.query.filter_by(
        evaluator=current_user.username,
        instance_index=instance_index
    ).all()
    if any(
        record.instance_quality not in (None, "") or record.comment not in (None, "")
        for record in existing_records
    ):
        return jsonify({"error": "You already submitted feedback for this instance."}), 409
    
    # write to the database
    new_record = EvaluationRecord(
        instance_index=instance_index,
        instance_id=COMPARISON_INSTANCES[instance_index]["id"],
        prompt=feedback_data["prompt"],
        model_a=feedback_data["model_a"],
        model_b=feedback_data["model_b"],
        completion_a=feedback_data["completion_a"],
        completion_b=feedback_data["completion_b"],
        completion_a_is_acceptable="",
        completion_b_is_acceptable="",
        preference="",
        instance_quality=feedback_data["instance_quality"],
        comment=feedback_data["comment"],
        evaluator=current_user.username,
        timestamp=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time()))
    )
    db.session.add(new_record)
    db.session.commit()
    return jsonify({"message": "Evaluation data submitted successfully"}), 200


@app.route("/api/user-progress", methods=["GET"])
@login_required
def get_user_progress():
    """Return the current user's evaluation progress."""
    return jsonify(get_user_progress_payload(current_user.username)), 200


def bootstrap_database():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="admin").first():
            admin_password = os.environ.get('ADMIN_PASSWORD')
            if not admin_password:
                raise SystemExit("ADMIN_PASSWORD is not set; refusing to create the admin account.")
            new_user = User(
                username="admin",
                password=generate_password_hash(admin_password, method='pbkdf2')
            )
            db.session.add(new_user)
            db.session.commit()


def init_app(comparison_data_path):
    """Prepare the database and load the comparison instances; must run before serving."""
    bootstrap_database()

    global COMPARISON_INSTANCES
    with open(comparison_data_path, "r") as f:
        COMPARISON_INSTANCES = [json.loads(line.strip()) for line in f.readlines()]

    log.info("Total number of comparison instances: {}".format(len(COMPARISON_INSTANCES)))


# Gunicorn imports this module instead of calling main(), so initialise here when configured.
if os.environ.get("COMPARISON_DATA_PATH"):
    init_app(os.environ["COMPARISON_DATA_PATH"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--comparison_data_path",
        type=str,
        required=True,
        help="The path to the data file containing the instances to be evaluated. "
             "Each instance should have a prompt and two completions."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="The host of the server."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5001,
        help="The port of the server."
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Whether to run the server in debug mode."
    )
    args = parser.parse_args()

    init_app(args.comparison_data_path)

    # run the app and listen on port 5000
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == '__main__':
    main()


if __name__ == '__main__':
    main()
