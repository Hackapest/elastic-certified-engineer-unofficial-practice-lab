"""Commands for tasks, scenarios, progress and selftest."""

import os
import random
import subprocess
import sys
import textwrap

from . import client, docker, exam, lab, preflight, scenariolib, state, tasklib, taxonomy

STATUS_MARK = {"passed": "✔", "attempted": "~", None: " "}


# --- Shared helpers ------------------------------------------------------------

def templates():
    return tasklib.load_templates()


def require_running():
    if not docker.running_services():
        raise SystemExit("The lab is not running. Start it with ./install.sh")


def template_status(results, template_id):
    rs = [r for r in results if r["template"] == template_id]
    if any(r["passed"] for r in rs):
        return "passed"
    return "attempted" if rs else None


def template_domain(task):
    """Template IDs start with their domain: data-..., ingest-..., search-..."""
    prefix = task.id.split("-")[0]
    return prefix if prefix in taxonomy.DOMAIN_MODULES else "other"


def resolve_instance(iid):
    data = state.tasks()
    iid = iid or data["last"]
    if not iid:
        raise SystemExit("No task given and no recent task. Start one with `./ece next` or `./ece new <template>`.")
    if iid not in data["instances"]:
        raise SystemExit(f"No open task '{iid}'. See `./ece tasks`.")
    inst = data["instances"][iid]
    all_templates = templates()
    if inst["template"] not in all_templates:
        raise SystemExit(f"Task {iid} uses template '{inst['template']}', which no longer exists. "
                         f"Remove it with `./ece drop {iid}`.")
    task = all_templates[inst["template"]]
    return iid, inst, task, tasklib.Context(task, iid, inst["params"])


def entries_by_id():
    return {e.full_id: e for e in taxonomy.entries(taxonomy.load())}


def doc_links(covers):
    by_id, links = entries_by_id(), []
    for entry_id in covers:
        for url in by_id[entry_id].docs if entry_id in by_id else []:
            if url not in links:
                links.append(url)
    return links


def answer_hint(task, iid):
    if task.answer == "query":
        return (f"Write your request in Kibana Dev Tools. When it works, hand it in with\n"
                f"`./ece answer {iid}` (opens vim; paste it exactly as in Dev Tools) or\n"
                f"`./ece answer {iid} --paste`, then grade it with `./ece check {iid}`.")
    return f"Do the task in Kibana Dev Tools (or with curl), then grade it with `./ece check {iid}`."


def print_task(iid, inst, task, ctx, with_docs=True):
    print(f"Task {iid} · {task.title}  [{task.id}, cluster {task.cluster.upper()}]")
    print()
    print(textwrap.indent(task.prompt(ctx).strip(), "  "))
    print()
    if task.requires:
        print(f"Requires: {', '.join(task.requires)}")
    if with_docs:
        links = doc_links(task.covers)
        if links:
            print("Docs:")
            print("\n".join(f"  {url}" for url in links))
            print()
    print(answer_hint(task, iid))


def create_instance(task, seed=None):
    require_running()
    data = state.tasks()
    iid = tasklib.new_iid(data["instances"])
    seed = random.randrange(2**31) if seed is None else seed
    params = tasklib.make_params(task, seed, iid)
    ctx = tasklib.Context(task, iid, params)
    task.setup(ctx)
    state.add_instance(iid, task.id, seed, params)
    return iid, state.tasks()["instances"][iid], ctx


# --- Task commands -------------------------------------------------------------

def cmd_list(args):
    all_templates = templates()
    results = state.progress()["results"]
    by_domain = {}
    for t in all_templates.values():
        by_domain.setdefault(template_domain(t), []).append(t)
    shown = 0
    for domain in taxonomy.DOMAIN_MODULES + ("other",):
        rows = []
        for t in sorted(by_domain.get(domain, []), key=lambda t: t.id):
            status = template_status(results, t.id)
            if args.todo and status == "passed":
                continue
            rows.append(f"  {STATUS_MARK[status]} {t.id:<40} {t.size:<5} {t.answer:<5}  {t.title}")
        if rows and (not args.domain or args.domain == domain):
            print(f"{domain}:")
            print("\n".join(rows))
            print()
            shown += len(rows)
    print(f"{shown} templates.  ✔ passed  ~ attempted.  Start one with `./ece new <template>` or `./ece next`.")
    if tasklib.BROKEN:
        print(f"({len(tasklib.BROKEN)} template file(s) failed to load and are skipped; `./ece selftest` lists them.)")


def cmd_new(args):
    all_templates = templates()
    if args.template not in all_templates:
        raise SystemExit(f"Unknown template '{args.template}'. See `./ece list`.")
    if "ml" in all_templates[args.template].requires and not lab.ml_ready():
        raise SystemExit("This task needs the ELSER model. Run `./ece ml-setup` first (downloads ~270 MB).")
    iid, inst, ctx = create_instance(all_templates[args.template], args.seed)
    print_task(iid, inst, ctx.task, ctx)


def cmd_next(args):
    results = state.progress()["results"]
    levels = {e.full_id: e.level for e in taxonomy.entries(taxonomy.load())}
    ml = lab.ml_ready()
    candidates = [t for t in templates().values()
                  if template_status(results, t.id) != "passed" and (ml or "ml" not in t.requires)]
    if args.domain:
        candidates = [t for t in candidates if template_domain(t) == args.domain]
    if not candidates:
        raise SystemExit("Nothing left to suggest: every available template is passed.")
    core = [t for t in candidates if any(levels.get(e) == taxonomy.CORE for e in t.covers)]
    task = random.choice(core or candidates)
    iid, inst, ctx = create_instance(task)
    print_task(iid, inst, task, ctx)


def cmd_tasks(args):
    data = state.tasks()
    results = state.progress()["results"]
    if not data["instances"]:
        print("No open tasks. Start one with `./ece next` or `./ece new <template>`.")
        return
    for iid, inst in sorted(data["instances"].items(), key=lambda kv: kv[1]["created"]):
        rs = [r for r in results if r["iid"] == iid]
        status = "passed" if any(r["passed"] for r in rs) else ("attempted" if rs else "open")
        extras = []
        if state.answer_path(iid).exists():
            extras.append("answer saved")
        if inst.get("solution_viewed"):
            extras.append("solution viewed")
        last = " (last)" if data["last"] == iid else ""
        print(f"  {iid}{last:<7} {inst['template']:<36} {status:<10} {', '.join(extras)}")


def cmd_show(args):
    iid, inst, task, ctx = resolve_instance(args.task)
    state.set_last(iid)
    print_task(iid, inst, task, ctx, with_docs=not exam.in_exam(iid))


def cmd_answer(args):
    iid, inst, task, ctx = resolve_instance(args.task)
    if task.answer != "query":
        raise SystemExit(f"Task {iid} is graded by inspecting the cluster; there is nothing to hand in. "
                         f"Run `./ece check {iid}` when you're done.")
    running = exam.active()
    if running and iid in running["tasks"] and exam.time_left(running).total_seconds() <= 0:
        raise SystemExit("The exam's time is up; answers can't be changed any more. Run `./ece exam finish`.")
    path = state.answer_path(iid)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "".join(f"# {line}\n" for line in task.prompt(ctx).strip().splitlines())
    header += ("#\n# Paste your request(s) below, exactly as in Kibana Dev Tools.\n"
               "# Lines starting with # are ignored. The response of the last request is graded.\n\n")
    if args.paste:
        print("Paste your request(s), then press Ctrl-D on an empty line:", flush=True)
        path.write_text(header + sys.stdin.read())
    else:
        if not path.exists():
            path.write_text(header)
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vim"
        subprocess.call([editor, str(path)])
    print(f"Answer saved. Grade it with `./ece check {iid}`.")


def exam_guard(iid, what):
    if exam.in_exam(iid):
        raise SystemExit(f"Task {iid} is part of the running exam: no {what} until it's over. "
                         f"Finish it with `./ece exam finish`.")


def cmd_check(args):
    require_running()
    iid, inst, task, ctx = resolve_instance(args.task)
    exam_guard(iid, "grading")
    state.set_last(iid)
    c = tasklib.Checker()
    if task.answer == "query":
        path = state.answer_path(iid)
        if not path.exists():
            if preflight.ask("You haven't handed in an answer for this task yet. Open the editor now?"):
                args.paste = False
                cmd_answer(args)
            if not path.exists():
                print(f"Nothing to grade yet. Hand in your request with `./ece answer {iid}`.")
                return 1
        answer_results, error = tasklib.run_console(ctx.es, path.read_text())
        if error:
            c.fail("your answer runs without errors", error)
        else:
            reference_results, ref_error = tasklib.run_console(ctx.es, task.solution(ctx))
            if ref_error:
                raise SystemExit(f"The reference solution failed, which is a bug in the template: {ref_error}")
            task.grade(ctx, c, answer_results[-1][2], reference_results[-1][2])
    else:
        try:
            task.verify(ctx, c)
        except client.HttpError as e:
            c.fail("the cluster answered the checks", str(e))
    viewed = bool(inst.get("solution_viewed"))
    state.record_result(iid, task.id, c.passed, viewed)
    print(f"Task {iid} · {task.title}")
    print(c.report())
    if c.passed:
        print(f"\nPASSED{' (after viewing the solution)' if viewed else ''}. "
              f"Clean up with `./ece drop {iid}`, or get another task with `./ece next`.")
    else:
        passed = sum(ok for ok, _, _ in c.results)
        print(f"\nNOT YET: {passed} of {len(c.results)} checks pass. Fix it and run `./ece check {iid}` again.")
    return 0 if c.passed else 1


def cmd_solution(args):
    iid, inst, task, ctx = resolve_instance(args.task)
    exam_guard(iid, "solutions")
    state.mark_solution_viewed(iid)
    print(f"Reference solution for task {iid} · {task.title}\n")
    print(task.solution(ctx).strip())
    if task.answer == "query":
        print("\nAny request that returns the same results passes; it doesn't have to match this one.")


def drop_instance(iid):
    iid, inst, task, ctx = resolve_instance(iid)
    for cluster in ("a", "b"):
        tasklib.cleanup_resources(client.es(cluster), iid)
    task.cleanup(ctx)
    state.remove_instance(iid)


def cmd_drop(args):
    iid = resolve_instance(args.task)[0]
    require_running()
    if exam.in_exam(iid):
        raise SystemExit(f"Task {iid} is part of the running exam. Use `./ece exam abort` to cancel the exam.")
    drop_instance(iid)
    print(f"Task {iid} and everything it created are removed. Its results stay in your progress.")


# --- Progress ------------------------------------------------------------------

def compute_progress():
    domains = taxonomy.load()
    all_templates = templates()
    scenarios = scenariolib.load()
    prog = state.progress()
    covering = {}
    for t in list(all_templates.values()) + list(scenarios.values()):
        for entry in t.covers:
            covering.setdefault(entry, []).append(t.id)
    status = {}
    for e in taxonomy.entries(domains):
        if e.kind == taxonomy.READING:
            status[e.full_id] = "passed" if e.full_id in prog["reading"] else None
        elif e.full_id not in covering:
            status[e.full_id] = "no-tasks"
        else:
            states = [template_status(prog["results"], t) for t in covering[e.full_id]]
            status[e.full_id] = "passed" if "passed" in states else ("attempted" if "attempted" in states else None)
    return domains, status


def cmd_progress(args):
    domains, status = compute_progress()
    mark = {"passed": "✔", "attempted": "~", None: "·", "no-tasks": "-"}
    lines_md = ["# Progress", ""]
    print(f"{'':<44}{'done':>6}{'of':>5}   (practicable entries + reading items)")
    for d in domains:
        es = [e for t in d.topics for e in t.entries]
        practicable = [e for e in es if status[e.full_id] != "no-tasks"]
        done = sum(status[e.full_id] == "passed" for e in practicable)
        pct = f"{100 * done // len(practicable)}%" if practicable else "-"
        print(f"{d.title:<44}{done:>6}{len(practicable):>5}   {pct}")
        lines_md += [f"## {d.title} ({done}/{len(practicable)})", ""]
        for t in d.topics:
            if args.detail:
                t_done = sum(status[e.full_id] == "passed" for e in t.entries)
                print(f"  {t.title}  ({t_done}/{sum(status[e.full_id] != 'no-tasks' for e in t.entries)})")
            lines_md += [f"### {t.title}", ""]
            for e in t.entries:
                s = status[e.full_id]
                if args.detail:
                    print(f"    {mark[s]} {e.full_id}  {e.title}")
                box = {"passed": "[x]", "attempted": "[~]", None: "[ ]", "no-tasks": "[-]"}[s]
                kind = " (reading)" if e.kind == taxonomy.READING else ""
                lines_md.append(f"- {box} {e.title}{kind} `{e.full_id}`")
            lines_md.append("")
    print("\n✔ passed  ~ attempted  · not started  - no tasks yet" if args.detail else
          "\nRun with --detail for every entry, or --md to write a Markdown checklist.")
    if args.md:
        path = state.config.STATE_DIR / "progress.md"
        state.config.STATE_DIR.mkdir(exist_ok=True)
        path.write_text("\n".join(lines_md) + "\n")
        print(f"Wrote {path}")


def cmd_done(args):
    by_id = entries_by_id()
    entry = by_id.get(args.entry)
    if not entry:
        raise SystemExit(f"Unknown entry '{args.entry}'. See `./ece progress --detail`.")
    if entry.kind != taxonomy.READING:
        raise SystemExit(f"{args.entry} is hands-on; it's ticked off by passing a task that covers it.")
    state.mark_reading(entry.full_id, not args.undo)
    print(f"{'Unmarked' if args.undo else 'Marked as read'}: {entry.title}")
    if not args.undo:
        print("\n".join(f"  {url}" for url in entry.docs))


# --- Scenarios -----------------------------------------------------------------

def active_scenario():
    data = state.scenario()
    if not data:
        return None, None, None
    scenario = scenariolib.load().get(data["id"])
    if not scenario:
        raise SystemExit(f"The active scenario '{data['id']}' no longer exists; delete .state/scenario.json.")
    return data, scenario, tasklib.Context(scenario, data["iid"], data["params"])


def cmd_scenario(args):
    action = args.action
    if action == "list":
        results = state.progress()["results"]
        for s in sorted(scenariolib.load().values(), key=lambda s: s.id):
            print(f"  {STATUS_MARK[template_status(results, s.id)]} {s.id:<36} cluster {s.cluster.upper()}  {s.title}")
        print("\nStart one with `./ece scenario start <id>` (or `./ece scenario start` for a random one).")
        return
    require_running()
    data, scenario, ctx = active_scenario()
    if action == "start":
        if data:
            raise SystemExit(f"Scenario '{data['id']}' is still active. Finish it or `./ece scenario reset`.")
        all_scenarios = scenariolib.load()
        if args.id and args.id not in all_scenarios:
            raise SystemExit(f"Unknown scenario '{args.id}'. See `./ece scenario list`.")
        scenario = all_scenarios[args.id] if args.id else random.choice(list(all_scenarios.values()))
        iid = tasklib.new_iid(state.tasks()["instances"])
        seed = random.randrange(2**31)
        params = tasklib.make_params(scenario, seed, iid)
        ctx = tasklib.Context(scenario, iid, params)
        print("Breaking something...", flush=True)
        scenario.cause(ctx)
        state.set_scenario({"id": scenario.id, "iid": iid, "seed": seed, "params": params, "started": state.now()})
        print()
        print(textwrap.indent(scenario.brief(ctx).strip(), "  "))
        print("\nDiagnose it with the cluster APIs, fix it, then run `./ece scenario check`.")
        return
    if not data:
        raise SystemExit("No active scenario. Start one with `./ece scenario start`.")
    if action == "show":
        print(f"Scenario: {scenario.title}\n")
        print(textwrap.indent(scenario.brief(ctx).strip(), "  "))
    elif action == "check":
        c = tasklib.Checker()
        scenario.verify(ctx, c)
        state.record_result(data["iid"], scenario.id, c.passed, bool(data.get("explained")))
        print(f"Scenario: {scenario.title}")
        print(c.report())
        if c.passed:
            scenario.reset(ctx)
            state.set_scenario({})
            print("\nFIXED. The scenario is cleaned up; start another with `./ece scenario start`.")
        else:
            print("\nNOT YET. Keep going, or see `./ece scenario explain`.")
        return 0 if c.passed else 1
    elif action == "explain":
        data["explained"] = True
        state.set_scenario(data)
        print(scenario.explain(ctx).strip())
        print("\nFix:\n")
        print(scenario.fix(ctx).strip())
    elif action == "reset":
        scenario.reset(ctx)
        state.set_scenario({})
        print("Scenario undone; the cluster is back to normal.")


# --- Selftest ------------------------------------------------------------------

def selftest_task(task):
    """Returns a list of problems (empty if the template works)."""
    iid = "st" + tasklib.new_iid({})
    params = tasklib.make_params(task, random.randrange(2**31), iid)
    ctx = tasklib.Context(task, iid, params)
    problems = []
    try:
        task.setup(ctx)
        task.prompt(ctx)
        if task.answer == "state":
            before = tasklib.Checker()
            task.verify(ctx, before)
            if before.passed:
                problems.append("verify passes before the solution is applied")
            error = task.apply_solution(ctx)
            if error:
                problems.append(f"solution failed: {error}")
            after = tasklib.Checker()
            task.verify(ctx, after)
            if not after.passed:
                problems.append("verify fails after the solution:\n" + after.report())
        else:
            ref, error = tasklib.run_console(ctx.es, task.solution(ctx))
            if error:
                problems.append(f"solution failed: {error}")
            else:
                c = tasklib.Checker()
                task.grade(ctx, c, ref[-1][2], ref[-1][2])
                if not c.passed:
                    problems.append("the solution doesn't pass its own grading:\n" + c.report())
                wrong = task.wrong_answer(ctx)
                if wrong:
                    got, error = tasklib.run_console(ctx.es, wrong)
                    c = tasklib.Checker()
                    if error:
                        problems.append(f"wrong_answer failed to run: {error}")
                    else:
                        task.grade(ctx, c, got[-1][2], ref[-1][2])
                        if c.passed:
                            problems.append("the wrong answer passes grading")
    except Exception as e:  # report and continue with the next template
        problems.append(f"{type(e).__name__}: {e}")
    finally:
        for cluster in ("a", "b"):
            tasklib.cleanup_resources(client.es(cluster), iid)
        try:
            task.cleanup(ctx)
        except Exception as e:
            problems.append(f"cleanup failed: {type(e).__name__}: {e}")
    return problems


def result_size_problem(task, response):
    """For a query task's reference response: is the result empty or (for 'all hits' tasks) truncated?"""
    if type(task).grade is not tasklib.Task.grade:
        return None   # custom grading: the response shape is the template's business
    if task.compare in ("hits", "hits_ordered", "hits_scored"):
        hits = tasklib.get(response, "hits.hits", [])
        total = tasklib.get(response, "hits.total.value", 0)
        if not hits:
            return "no hits"
        if task.compare == "hits" and total > len(hits):
            return f"only {len(hits)} of {total} hits returned"
    elif task.compare == "aggs":
        if not any(kind != "buckets" or buckets for kind, buckets in
                   tasklib.canonical_aggs(tasklib.get(response, "aggregations"))):
            return "no buckets"
    elif task.compare == "esql" and not tasklib.get(response, "values"):
        return "no rows"
    return None


def sweep_task(task, runs):
    """Run a query task's reference solution for many variants; report empty or truncated results."""
    problems = []
    for _ in range(runs):
        iid = "sw" + tasklib.new_iid({})
        seed = random.randrange(2**31)
        params = tasklib.make_params(task, seed, iid)
        ctx = tasklib.Context(task, iid, params)
        try:
            task.setup(ctx)
            results, error = tasklib.run_console(ctx.es, task.solution(ctx))
            problem = error or result_size_problem(task, results[-1][2])
            if problem:
                shown = {k: v for k, v in params.items() if not isinstance(v, (list, dict)) or len(str(v)) < 60}
                problems.append(f"{problem} for {shown}")
        finally:
            for cluster in ("a", "b"):
                tasklib.cleanup_resources(client.es(cluster), iid)
            task.cleanup(ctx)
    return sorted(set(problems))


def selftest_scenario(scenario):
    iid = "st" + tasklib.new_iid({})
    ctx = tasklib.Context(scenario, iid, tasklib.make_params(scenario, random.randrange(2**31), iid))
    problems = []
    try:
        scenario.cause(ctx)
        scenario.brief(ctx)
        before = tasklib.Checker()
        scenario.verify(ctx, before)
        if before.passed:
            problems.append("verify passes while the cluster is broken")
        error = scenario.apply_fix(ctx)
        if error:
            problems.append(f"fix failed: {error}")
        after = tasklib.Checker()
        scenario.verify(ctx, after)
        if not after.passed:
            problems.append("verify fails after the fix:\n" + after.report())
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    finally:
        scenario.reset(ctx)
    return problems


def cmd_selftest(args):
    require_running()
    all_templates, all_scenarios = templates(), scenariolib.load()
    problems = tasklib.validate_templates({**all_templates, **all_scenarios})
    problems += [f"{path} doesn't load: {error}" for path, error in tasklib.BROKEN.items()]
    for p in problems:
        print(f"✘ {p}")
    items = [("task", t) for t in all_templates.values()] + [("scenario", s) for s in all_scenarios.values()]
    if args.only:
        items = [(kind, x) for kind, x in items if x.id in args.only or x.id.startswith(tuple(args.only))]
    failed = bool(problems)
    ml = lab.ml_ready()
    for kind, item in sorted(items, key=lambda kx: kx[1].id):
        print(f"{kind:<9}{item.id:<40}", end="", flush=True)
        if "ml" in item.requires and not ml:
            print("skipped (needs ./ece ml-setup)")
            continue
        found = selftest_task(item) if kind == "task" else selftest_scenario(item)
        if args.sweep and kind == "task" and item.answer == "query" and not found:
            found = sweep_task(item, args.sweep)
        print("ok" if not found else "FAILED")
        for p in found:
            print(textwrap.indent(p, "    "))
        failed |= bool(found)
    print("\nAll good." if not failed else "\nSome checks failed.")
    return 1 if failed else 0


# --- Exam mode -----------------------------------------------------------------

def cmd_exam(args):
    action = args.action or "status"
    all_templates = templates()
    if action == "status":
        exam.overview(all_templates)
    elif action == "start":
        require_running()
        exam.start(all_templates, args.count, args.minutes, lambda t: create_instance(t), template_domain)
        exam.overview(all_templates)
    elif action == "finish":
        require_running()
        exam.finish(all_templates, resolve_instance)
    elif action == "results":
        exam.results_again(all_templates)
    elif action == "abort":
        require_running()
        exam.abort(drop_instance)
    elif action == "clean":
        require_running()
        data = exam.load()
        if not data.get("finished"):
            raise SystemExit("Only a finished exam can be cleaned up; to cancel a running one: `./ece exam abort`.")
        exam.remove_tasks(drop_instance)
        print("The exam's tasks are removed. Its results stay in your progress.")
