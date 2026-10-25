"""Exam mode: a timed set of tasks across all domains, graded only at the end.

Like the real exam: about 10 tasks in 3 hours, no feedback and no solutions until it's over,
and no doc links handed to you (finding the right page is part of the exam).
"""

import json
import random
from datetime import datetime, timedelta, timezone

from . import client, config, lab, state, tasklib, taxonomy

EXAM_FILE = config.STATE_DIR / "exam.json"
DOMAINS = ("data", "ingest", "search", "cluster", "security", "architecture")
WEIGHTS = {"exam": 2, "drill": 1}


def load():
    try:
        return json.loads(EXAM_FILE.read_text())
    except FileNotFoundError:
        return {}


def save(data):
    config.STATE_DIR.mkdir(exist_ok=True)
    EXAM_FILE.write_text(json.dumps(data, indent=2))


def active():
    """The running exam (not finished), or None."""
    data = load()
    return data if data and not data.get("finished") else None


def in_exam(iid):
    data = active()
    return bool(data) and iid in data["tasks"]


def time_left(data):
    deadline = datetime.fromisoformat(data["deadline"])
    return deadline - datetime.now(timezone.utc)


def pick(templates, count, domain_of):
    """Exam-size tasks first (at most half), then core drills, round-robin over the domains."""
    ml = lab.ml_ready()
    levels = {e.full_id: e.level for e in taxonomy.entries(taxonomy.load())}
    usable = [t for t in templates.values() if ml or "ml" not in t.requires]
    exam_size = [t for t in usable if t.size == "exam"]
    random.shuffle(exam_size)
    chosen, used_domains = [], []
    for t in exam_size:
        if len(chosen) >= count // 2:
            break
        if domain_of(t) not in used_domains:      # one exam-size task per domain
            chosen.append(t)
            used_domains.append(domain_of(t))
    drills = [t for t in usable if t.size == "drill" and any(levels.get(e) == taxonomy.CORE for e in t.covers)]
    by_domain = {d: [t for t in drills if domain_of(t) == d] for d in DOMAINS}
    for pool in by_domain.values():
        random.shuffle(pool)
    order = sorted(DOMAINS, key=lambda d: used_domains.count(d))   # domains without a task first
    while len(chosen) < count and any(by_domain.values()):
        for d in order:
            if by_domain[d] and len(chosen) < count:
                chosen.append(by_domain[d].pop())
    return chosen


def start(templates, count, minutes, create_instance, domain_of):
    if active():
        raise SystemExit("An exam is already running. See `./ece exam`, or `./ece exam abort`.")
    chosen = pick(templates, count, domain_of)
    print(f"Preparing {len(chosen)} tasks...", flush=True)
    iids = []
    for t in chosen:
        iid, _, _ = create_instance(t)
        iids.append(iid)
    now = datetime.now(timezone.utc)
    save({"started": now.isoformat(timespec="seconds"),
          "deadline": (now + timedelta(minutes=minutes)).isoformat(timespec="seconds"),
          "minutes": minutes, "tasks": iids, "finished": False})
    print(f"\nThe exam has started: {len(iids)} tasks, {minutes} minutes.\n")


def overview(templates):
    data = load()
    if not data:
        print("No exam yet. Start one with `./ece exam start`.")
        return
    instances = state.tasks()["instances"]
    left = time_left(data)
    if data.get("finished"):
        print(f"Exam from {data['started']}: finished. Results: `./ece exam results`.")
    elif left.total_seconds() <= 0:
        print("Time is up. Grade it with `./ece exam finish`.")
    else:
        h, rest = divmod(int(left.total_seconds()), 3600)
        print(f"Exam running: {h}h {rest // 60:02d}m left.")
    print()
    for n, iid in enumerate(data["tasks"], 1):
        inst = instances.get(iid)
        t = templates.get(inst["template"]) if inst else None
        if not t:
            print(f"  {n:>2}. {iid}  (removed)")
            continue
        answered = "  (answer saved)" if t.answer == "query" and state.answer_path(iid).exists() else ""
        print(f"  {n:>2}. {iid}  {'[exam] ' if t.size == 'exam' else ''}{t.title}{answered}")
    if not data.get("finished"):
        print("\nRead a task with `./ece show <id>`; hand in query tasks with `./ece answer <id>`.")
        print("Nothing is graded and no solutions are shown until `./ece exam finish`.")


def grade(templates, resolve):
    """Grade every exam task; returns [(iid, task, checker)]."""
    data = load()
    results = []
    for iid in data["tasks"]:
        try:
            _, inst, task, ctx = resolve(iid)
        except SystemExit as e:
            results.append((iid, None, str(e)))
            continue
        c = tasklib.Checker()
        try:
            if task.answer == "query":
                path = state.answer_path(iid)
                if not path.exists():
                    c.fail("an answer was handed in", f"no answer for {iid} (`./ece answer {iid}`)")
                else:
                    answer, error = tasklib.run_console(ctx.es, path.read_text())
                    if error:
                        c.fail("the answer runs without errors", error)
                    else:
                        reference, ref_error = tasklib.run_console(ctx.es, task.solution(ctx))
                        if ref_error:
                            c.fail("the reference solution runs", ref_error)
                        else:
                            task.grade(ctx, c, answer[-1][2], reference[-1][2])
            else:
                task.verify(ctx, c)
        except client.HttpError as e:
            c.fail("the cluster answered the checks", str(e))
        state.record_result(iid, task.id, c.passed, False)
        results.append((iid, task, c))
    return results


def report(results):
    total = earned = 0
    for n, (iid, task, c) in enumerate(results, 1):
        if task is None:
            print(f"  {n:>2}. {iid}  could not be graded: {c}")
            continue
        weight = WEIGHTS[task.size]
        total += weight
        passed_checks = sum(ok for ok, _, _ in c.results)
        if c.passed:
            earned += weight
        mark = "✔" if c.passed else "✘"
        print(f"  {n:>2}. {mark} {iid}  {task.title}  ({passed_checks}/{len(c.results)} checks, weight {weight})")
        if not c.passed:
            for ok, message, detail in c.results:
                if not ok:
                    print(f"        ✘ {message}" + (f": {detail}" if detail else ""))
    pct = 100 * earned // total if total else 0
    print(f"\nScore: {earned} of {total} points ({pct}%). A task only counts when all its checks pass.")
    return pct


def finish(templates, resolve):
    data = load()
    if not data or data.get("finished"):
        raise SystemExit("No running exam. Start one with `./ece exam start`.")
    print("Grading all tasks...\n", flush=True)
    results = grade(templates, resolve)
    pct = report(results)
    data.update({"finished": True, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "score": pct, "results": {iid: bool(getattr(c, "passed", False)) for iid, _, c in results}})
    save(data)
    print("\nSolutions are available now: `./ece solution <id>`. Remove the exam's tasks with `./ece exam clean`.")


def results_again(templates):
    data = load()
    if not data or not data.get("finished"):
        raise SystemExit("No finished exam.")
    instances = state.tasks()["instances"]
    for n, iid in enumerate(data["tasks"], 1):
        inst = instances.get(iid, {})
        t = templates.get(inst.get("template"))
        mark = "✔" if data["results"].get(iid) else "✘"
        print(f"  {n:>2}. {mark} {iid}  {t.title if t else '(removed)'}")
    print(f"\nScore: {data['score']}%")


def remove_tasks(drop):
    data = load()
    for iid in data.get("tasks", []):
        if iid in state.tasks()["instances"]:
            drop(iid)


def abort(drop):
    if not active():
        raise SystemExit("No running exam.")
    remove_tasks(drop)
    EXAM_FILE.unlink(missing_ok=True)
    print("Exam cancelled; its tasks are removed. Nothing was graded.")
