"""User state in .state/: task instances, results, answers, reading progress, active scenario.

Lives outside Docker, so `./ece reset` never touches it.
"""

import json
from datetime import datetime, timezone

from . import config

TASKS_FILE = config.STATE_DIR / "tasks.json"
PROGRESS_FILE = config.STATE_DIR / "progress.json"
SCENARIO_FILE = config.STATE_DIR / "scenario.json"
ANSWERS_DIR = config.STATE_DIR / "answers"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def _save(path, data):
    config.STATE_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


# --- Task instances ----------------------------------------------------------
# {"instances": {iid: {template, seed, params, created}}, "last": iid}

def tasks():
    return _load(TASKS_FILE, {"instances": {}, "last": None})


def add_instance(iid, template_id, seed, params):
    data = tasks()
    data["instances"][iid] = {"template": template_id, "seed": seed, "params": params, "created": now()}
    data["last"] = iid
    _save(TASKS_FILE, data)


def remove_instance(iid):
    data = tasks()
    data["instances"].pop(iid, None)
    if data["last"] == iid:
        data["last"] = None
    _save(TASKS_FILE, data)
    answer_path(iid).unlink(missing_ok=True)


def clear_open():
    """Forget open task instances, their answers and the active scenario (after a reset)."""
    for iid in tasks()["instances"]:
        answer_path(iid).unlink(missing_ok=True)
    _save(TASKS_FILE, {"instances": {}, "last": None})
    _save(SCENARIO_FILE, {})


def set_last(iid):
    data = tasks()
    data["last"] = iid
    _save(TASKS_FILE, data)


# --- Progress ----------------------------------------------------------------
# {"results": [{iid, template, time, passed, solution_viewed}], "reading": [entry ids]}

def progress():
    return _load(PROGRESS_FILE, {"results": [], "reading": []})


def record_result(iid, template_id, passed, solution_viewed):
    data = progress()
    data["results"].append({"iid": iid, "template": template_id, "time": now(), "passed": passed,
                            "solution_viewed": solution_viewed})
    _save(PROGRESS_FILE, data)


def mark_reading(entry_id, done=True):
    data = progress()
    reading = set(data["reading"])
    reading.add(entry_id) if done else reading.discard(entry_id)
    data["reading"] = sorted(reading)
    _save(PROGRESS_FILE, data)


def mark_solution_viewed(iid):
    data = tasks()
    if iid in data["instances"]:
        data["instances"][iid]["solution_viewed"] = True
        _save(TASKS_FILE, data)


# --- Answers -----------------------------------------------------------------

def answer_path(iid):
    return ANSWERS_DIR / f"{iid}.txt"


# --- Active scenario ---------------------------------------------------------
# {"id", "seed", "params", "started"} or {}

def scenario():
    return _load(SCENARIO_FILE, {})


def set_scenario(data):
    _save(SCENARIO_FILE, data)
