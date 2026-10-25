"""Command-line interface: ./ece <command>"""

import argparse
import os
import shutil
from dataclasses import dataclass, field

from . import config, docker, lab, preflight, state, taskcli, taxonomy


def confirm(question, assume_yes):
    return assume_yes or preflight.ask(question)


def cmd_install(args):
    preflight.run(args.yes)
    lab.up()
    print("\nThe lab is ready.\n")
    lab.status()


def cmd_status(args):
    lab.status()


def cmd_reset(args):
    if not confirm("This deletes both clusters, including all data and settings, and rebuilds "
                   "them from scratch. Your progress is kept. Continue?", args.yes):
        return
    lab.down()
    state.clear_open()
    lab.up()
    print("\nReset complete. Open tasks and any active scenario were dropped; your progress is kept.\n")
    lab.status()


def cmd_uninstall(args):
    if not confirm("Remove all containers, volumes and images of the lab?", args.yes):
        return
    lab.down(remove_images=True)
    config.CA_CERT.unlink(missing_ok=True)
    print(f"Uninstalled. Your progress is still in {config.STATE_DIR}; delete that folder to remove it.")


def cmd_shell(args):
    service = lab.node_service(args.node)
    os.execvp("docker", ["docker", "compose", "--project-directory", str(config.ROOT),
                         "exec", service, "bash"])


def cmd_config(args):
    service = lab.node_service(args.node)
    if not service.startswith("es-"):
        raise SystemExit("Only Elasticsearch nodes have an elasticsearch.yml (a1..a3, b1..b3).")
    lab.edit_node_config(service)


def cmd_restart(args):
    docker.compose("restart", lab.node_service(args.node))


def cmd_stop(args):
    docker.compose("stop", lab.node_service(args.node))


def cmd_start(args):
    docker.compose("start", lab.node_service(args.node))


def cmd_taxonomy(args):
    domains = taxonomy.load()
    problems = taxonomy.validate(domains)
    if args.tree:
        for d in domains:
            print(f"{d.id}  {d.title}")
            for t in d.topics:
                print(f"  {t.full_id}  {t.title}")
                for e in t.entries:
                    marks = " ".join(filter(None, [e.level, "reading" if e.kind == taxonomy.READING else "",
                                                   *e.requires]))
                    print(f"    {e.full_id}  {e.title}  [{marks}]")
        print()

    all_entries = taxonomy.entries(domains)
    print(f"{'domain':<14}{'topics':>7}{'hands-on':>10}{'reading':>9}{'core':>6}{'common':>8}{'extended':>10}")
    for d in domains + [None]:
        es = all_entries if d is None else taxonomy.entries([d])
        n_topics = sum(len(x.topics) for x in domains) if d is None else len(d.topics)
        count = lambda f: sum(1 for e in es if f(e))
        print(f"{'total' if d is None else d.id:<14}{n_topics:>7}"
              f"{count(lambda e: e.kind == taxonomy.HANDS_ON):>10}{count(lambda e: e.kind == taxonomy.READING):>9}"
              f"{count(lambda e: e.level == taxonomy.CORE):>6}{count(lambda e: e.level == taxonomy.COMMON):>8}"
              f"{count(lambda e: e.level == taxonomy.EXTENDED):>10}")

    if args.links:
        problems += taxonomy.check_links(domains)
    if problems:
        print("\nProblems:")
        print("\n".join(f"  {p}" for p in problems))
        return 1
    print("\nNo problems found." + ("" if args.links else " (Run with --links to check doc links.)"))
    return 0


NODES_HELP = """\
Nodes are named after their cluster and number:
  a1, a2, a3        Elasticsearch nodes of cluster A
  b1, b2, b3        Elasticsearch nodes of cluster B
  kibana-a, kibana-b
The `es-` prefix is optional (es-a2 and a2 are the same node)."""

TASK_ID_HELP = "task ID, e.g. 7a1f (default: your most recent task)"


@dataclass
class Command:
    name: str
    func: object
    summary: str
    details: str
    examples: list
    arguments: list = field(default_factory=list)   # [(args, kwargs)] for add_argument


def arg(*args, **kwargs):
    return (args, kwargs)


YES = arg("-y", "--yes", action="store_true", help="don't ask for confirmation")
NODE = arg("node", help="node name, e.g. a2 (see above)")
TASK = arg("task", nargs="?", help=TASK_ID_HELP)

COMMANDS = [
    ("Tasks", [
        Command("next", taskcli.cmd_next, "start a task you haven't passed yet",
                "Picks a template you haven't passed (core topics first), creates a task\n"
                "from it and prints it. Tasks get a short ID like 7a1f; their resources\n"
                "(indices, pipelines, ...) carry that ID in their names.",
                ["./ece next", "./ece next --domain search"],
                [arg("--domain", help="only templates of this domain (data, ingest, search, ...)")]),
        Command("new", taskcli.cmd_new, "start a task from a specific template",
                "Creates a task from a template (see `./ece list`). The seed decides the\n"
                "task's details; the same template and seed give the same task.",
                ["./ece new search-ecommerce-bool", "./ece new search-ecommerce-bool --seed 42"],
                [arg("template", help="template ID from `./ece list`"),
                 arg("--seed", type=int, help="reproduce a specific variant")]),
        Command("list", taskcli.cmd_list, "list the task templates and what you've passed",
                "Lists all task templates by domain: size (drill or exam), how it's graded\n"
                "(state: by inspecting the cluster; query: by running your answer), title.",
                ["./ece list", "./ece list --todo", "./ece list --domain ingest"],
                [arg("--todo", action="store_true", help="hide templates you've passed"),
                 arg("--domain", help="only this domain")]),
        Command("tasks", taskcli.cmd_tasks, "list your open tasks",
                "Lists the tasks you've started and not dropped, with their status.",
                ["./ece tasks"]),
        Command("show", taskcli.cmd_show, "print a task again, with its doc links",
                "Prints the task, links to the documentation pages that cover it, and how\n"
                "to hand it in.",
                ["./ece show", "./ece show 7a1f"], [TASK]),
        Command("answer", taskcli.cmd_answer, "hand in your request for a query task",
                "Query tasks are graded by running your request. Write it in Kibana Dev\n"
                "Tools, then hand it in exactly as it appears there: this opens it in vim\n"
                "($EDITOR if set), or with --paste reads it from the terminal. The answer\n"
                "may contain several requests; the response of the last one is graded.",
                ["./ece answer", "./ece answer 7a1f", "./ece answer 7a1f --paste"],
                [TASK, arg("--paste", action="store_true", help="read the answer from the terminal")]),
        Command("check", taskcli.cmd_check, "grade a task",
                "State tasks are graded by inspecting the cluster; query tasks by running\n"
                "your answer and comparing its results with the reference solution's.\n"
                "Prints each check, and records the result in your progress.",
                ["./ece check", "./ece check 7a1f"], [TASK]),
        Command("solution", taskcli.cmd_solution, "show the reference solution",
                "Prints the reference solution in Kibana console syntax. The task is marked\n"
                "as 'solution viewed' in your progress.",
                ["./ece solution 7a1f"], [TASK]),
        Command("drop", taskcli.cmd_drop, "remove a task and everything it created",
                "Deletes the task's indices, pipelines, templates, policies, roles and so on\n"
                "from both clusters. Results already recorded stay in your progress.",
                ["./ece drop 7a1f"], [TASK]),
    ]),
    ("Exam", [
        Command("exam", taskcli.cmd_exam, "a timed practice exam, graded at the end",
                "Like the real exam: about 10 tasks across all domains in 3 hours. During the\n"
                "exam there is no grading, no solutions and no doc links (finding the docs is\n"
                "part of the exam); answers can be handed in until the time is up. Exam-size\n"
                "tasks count double. A task counts only when all its checks pass.\n\n"
                "  (no action)   show the tasks and the time left\n"
                "  start         start an exam (--count, --minutes)\n"
                "  finish        grade everything and show the score\n"
                "  results       show the score of the last exam again\n"
                "  clean         remove the finished exam's tasks\n"
                "  abort         cancel the running exam without grading",
                ["./ece exam start", "./ece exam", "./ece exam finish", "./ece exam start --count 5 --minutes 90"],
                [arg("action", nargs="?", choices=["status", "start", "finish", "results", "clean", "abort"]),
                 arg("--count", type=int, default=10, help="number of tasks (default 10)"),
                 arg("--minutes", type=int, default=180, help="time limit (default 180)")]),
    ]),
    ("Progress", [
        Command("progress", taskcli.cmd_progress, "show what you've done per exam topic",
                "Rolls your results up by exam topic. Hands-on entries count as done when\n"
                "you've passed a task that covers them; reading items when you've ticked\n"
                "them off with `./ece done`. Entries without tasks yet are not counted.",
                ["./ece progress", "./ece progress --detail", "./ece progress --md"],
                [arg("--detail", action="store_true", help="list every entry"),
                 arg("--md", action="store_true", help="write a Markdown checklist to .state/progress.md")]),
        Command("done", taskcli.cmd_done, "tick off a reading item",
                "Marks a reading (conceptual) entry as read. Entry IDs are shown by\n"
                "`./ece progress --detail`.",
                ["./ece done architecture.stack.elastic-stack",
                 "./ece done architecture.stack.elastic-stack --undo"],
                [arg("entry", help="taxonomy entry ID"),
                 arg("--undo", action="store_true", help="unmark it")]),
    ]),
    ("Troubleshooting", [
        Command("scenario", taskcli.cmd_scenario, "break a cluster on purpose and fix it",
                "Scenarios put a cluster into a broken state without telling you why.\n"
                "Diagnose it with the cluster APIs (_cluster/health, _cat/shards,\n"
                "_cluster/allocation/explain, ...), fix it, then check. One scenario is\n"
                "active at a time.\n\n"
                "  list            available scenarios\n"
                "  start [<id>]    start one (random if no ID)\n"
                "  show            print the active scenario's symptoms again\n"
                "  check           check whether it's fixed (cleans up when it is)\n"
                "  explain         the cause and the fix\n"
                "  reset           undo the scenario without fixing it",
                ["./ece scenario list", "./ece scenario start", "./ece scenario check"],
                [arg("action", choices=["list", "start", "show", "check", "explain", "reset"]),
                 arg("id", nargs="?", help="scenario ID (start only)")]),
    ]),
    ("Lab", [
        Command("install", cmd_install, "check prerequisites, build and start the lab",
                "Checks Docker, vm.max_map_count, memory and free ports, then builds the image,\n"
                "generates certificates, starts both clusters and both Kibanas, and loads the\n"
                "Kibana sample data. Safe to run again on a running lab: nothing is lost.\n"
                "./install.sh runs this command.",
                ["./ece install"], [YES]),
        Command("status", cmd_status, "show cluster health, URLs and credentials",
                "Shows each cluster's health, unassigned shards, trial days left, which\n"
                "containers are running, the Elasticsearch and Kibana URLs, and the login.",
                ["./ece status"]),
        Command("reset", cmd_reset, "wipe both clusters and rebuild them from scratch",
                "Deletes all containers and volumes (data, settings, certificates, snapshots,\n"
                "node config edits) and rebuilds the lab as after a fresh install, including a\n"
                "new 30-day trial. Takes about 3 minutes. Your progress is kept; open tasks\n"
                "are dropped, since their resources are gone.",
                ["./ece reset", "./ece reset --yes"], [YES]),
        Command("uninstall", cmd_uninstall, "remove containers, volumes and images",
                "Removes everything the lab created in Docker. Your progress in .state/ is\n"
                "kept; delete that folder to remove it too. ./uninstall.sh runs this command.",
                ["./ece uninstall"], [YES]),
    ]),
    ("Machine learning", [
        Command("ml-setup", lambda args: lab.ml_setup(), "prepare ELSER for semantic search tasks",
                "Downloads (once, ~270 MB) and starts the ELSER model on both clusters through\n"
                "its default inference endpoint, and waits until it answers. Semantic search\n"
                "tasks (semantic_text, the semantic query) need it. It uses about 2 GB of\n"
                "memory while active and scales down by itself when idle.",
                ["./ece ml-setup"]),
    ]),
    ("Nodes", [
        Command("shell", cmd_shell, "open a shell in a node",
                "Opens bash inside a node, e.g. to edit config/elasticsearch.yml with vim.\n"
                "Edits survive restarts; `./ece reset` restores the original config.\n\n" + NODES_HELP,
                ["./ece shell a2", "./ece shell kibana-a"], [NODE]),
        Command("config", cmd_config, "edit a node's elasticsearch.yml (also when it's stopped)",
                "Copies the node's config/elasticsearch.yml out of its container, opens it in vim\n"
                "($EDITOR if set) and copies it back. Works when the node is stopped too, e.g.\n"
                "when a config error keeps it from starting. Changes take effect after\n"
                "`./ece restart <node>` (or `./ece start <node>`). `./ece reset` restores the\n"
                "original configs.\n\n" + NODES_HELP,
                ["./ece config a2", "./ece restart a2"], [NODE]),
        Command("restart", cmd_restart, "restart a node",
                "Restarts a node, e.g. after editing its elasticsearch.yml.\n\n" + NODES_HELP,
                ["./ece restart a2"], [NODE]),
        Command("stop", cmd_stop, "stop a node",
                "Stops a node, simulating a node failure. Bring it back with `./ece start`.\n\n" + NODES_HELP,
                ["./ece stop b3"], [NODE]),
        Command("start", cmd_start, "start a stopped node",
                "Starts a node that was stopped with `./ece stop`.\n\n" + NODES_HELP,
                ["./ece start b3"], [NODE]),
    ]),
    ("Development", [
        Command("selftest", taskcli.cmd_selftest, "check that task templates and scenarios work",
                "For every template: creates an instance, checks that grading fails before\n"
                "the reference solution and passes after it, then cleans up. For every\n"
                "scenario: breaks, checks, applies the fix, checks again, resets. Doesn't\n"
                "touch your tasks or progress.",
                ["./ece selftest", "./ece selftest search-ecommerce-bool", "./ece selftest search --sweep 20"],
                [arg("only", nargs="*", help="template or scenario IDs (or ID prefixes)"),
                 arg("--sweep", type=int, metavar="N",
                     help="also run each query task's reference for N random variants and report "
                          "empty or truncated results")]),
        Command("taxonomy", cmd_taxonomy, "validate and summarize the exam taxonomy",
                "Loads taxonomy/*.py, checks it for problems (duplicate IDs, missing doc\n"
                "links, unknown levels) and prints entry counts per domain.",
                ["./ece taxonomy", "./ece taxonomy --tree", "./ece taxonomy --links"],
                [arg("--tree", action="store_true", help="print every entry"),
                 arg("--links", action="store_true", help="check that every doc link resolves (needs internet)")]),
    ]),
]

NO_DOCKER_NEEDED = {"install", "taxonomy", "list", "progress", "done", "help"}


def overview():
    width = max(len(c.name) for _, cmds in COMMANDS for c in cmds)
    lines = ["Elastic Certified Engineer practice lab", "",
             "Usage: ./ece <command> [options]", ""]
    for group, cmds in COMMANDS:
        lines.append(f"{group}:")
        lines += [f"  {c.name:<{width}}  {c.summary}" for c in cmds]
        lines.append("")
    lines += [
        "Run `./ece help <command>` for details and examples.",
        "",
        "Getting started:",
        "  ./install.sh       install and start the lab",
        "  ./ece status       URLs and login; open Kibana A and use Dev Tools",
        "  ./ece next         get a task; then `./ece check` to grade it",
    ]
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(prog="ece", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    sub = parser.add_subparsers(dest="command")
    subparsers = {}
    for _, cmds in COMMANDS:
        for c in cmds:
            epilog = "Examples:\n" + "\n".join(f"  {e}" for e in c.examples)
            p = sub.add_parser(c.name, description=f"{c.summary[0].upper()}{c.summary[1:]}.\n\n{c.details}",
                               epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
            p.set_defaults(func=c.func)
            for args, kwargs in c.arguments:
                p.add_argument(*args, **kwargs)
            subparsers[c.name] = p
    p = sub.add_parser("help")
    p.add_argument("topic", nargs="?")
    return parser, subparsers


def main():
    parser, subparsers = build_parser()
    args = parser.parse_args()

    if args.command is None or args.command == "help" and not args.topic:
        print(overview())
        return 0
    if args.command == "help":
        if args.topic not in subparsers:
            raise SystemExit(f"Unknown command '{args.topic}'. Run `./ece help` for the list.")
        subparsers[args.topic].print_help()
        return 0

    if shutil.which("docker") is None and args.command not in NO_DOCKER_NEEDED:
        raise SystemExit("Docker is not installed.")
    return args.func(args) or 0
