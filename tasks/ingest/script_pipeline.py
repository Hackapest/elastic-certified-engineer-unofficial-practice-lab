import json
import random

from lib.tasklib import Task, get
from tasks.ingest._common import check_against_reference, field, send

TIERS = ["gold", "silver", "basic"]

SCRIPT = """
double total = 0;
int count = 0;
for (def item : ctx.items) {
  total += item.price * item.qty;
  count += item.qty;
}
ctx.total = Math.round(total * 100) / 100.0;
ctx.item_count = count;
double rate = params.rates.containsKey(ctx.customer.tier) ? params.rates[ctx.customer.tier] : 0;
ctx.discount = Math.round(ctx.total * rate * 100) / 100.0;
ctx.big_order = ctx.total >= params.big;
""".strip()


def order(rnd):
    return {"customer": {"tier": rnd.choice(TIERS)},
            "items": [{"price": round(rnd.uniform(2, 120), 2), "qty": rnd.randint(1, 5)}
                      for _ in range(rnd.randint(1, 4))]}


def rounded(path):
    def value(r):
        v = field(r["source"], path)
        return round(v, 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    return value


class ScriptPipeline(Task):
    id = "ingest-script-pipeline"
    title = "Compute order totals with a stored Painless script in a pipeline (script processor)"
    covers = ["ingest.pipelines.processor.script", "ingest.reindex.stored-scripts", "ingest.reindex.painless"]

    def params(self, rnd, iid):
        gold = rnd.choice([10, 15, 20])
        return {"pipeline": f"order-totals-{iid}", "script": f"order-totals-script-{iid}",
                "rates": {"gold": gold / 100, "silver": rnd.choice([3, 5, 8]) / 100},
                "big": rnd.choice([150, 200, 300]), "example": order(rnd)}

    def processors(self, p, inline=True):
        script = {"lang": "painless", "source": SCRIPT} if inline else {"id": p["script"]}
        return [{"script": {**script, "params": {"rates": p["rates"], "big": p["big"]}}}]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Order documents look like this:

  {json.dumps(p['example'])}

1. Store a Painless script with the id `{p['script']}` that sets these fields:

     total        sum of price * qty over all items, rounded to 2 decimals
     item_count   sum of qty over all items
     discount     total * the discount rate of the customer's tier, rounded to 2 decimals;
                  the rates come from the script parameter `rates`, an object mapping tier
                  to rate; tiers missing from it get no discount (0)
     big_order    true when total is at least the script parameter `big`, false otherwise

2. Create an ingest pipeline `{p['pipeline']}` that runs the stored script with the parameters
   rates = {json.dumps(p['rates'])} and big = {p['big']}.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
PUT _scripts/{p['script']}
{{
  "script": {{
    "lang": "painless",
    "source": \"\"\"
{SCRIPT}
\"\"\"
  }}
}}

PUT _ingest/pipeline/{p['pipeline']}
{json.dumps({"processors": self.processors(p, inline=False)}, indent=2)}
"""

    def verify(self, ctx, c):
        p, es = ctx.p, ctx.es
        status, response = send(es, "GET", f"/_scripts/{p['script']}")
        if c.check(status == 200 and get(response, "found"), f"stored script {p['script']} exists"):
            c.equal(get(response, "script.lang"), "painless", "the stored script is a Painless script")
        status, response = send(es, "GET", f"/_ingest/pipeline/{p['pipeline']}")
        if status == 200:
            text = json.dumps(response)
            c.check(f'"id": "{p["script"]}"' in text, "the pipeline runs the stored script by its id",
                    "no script processor refers to the stored script")
        rnd = random.Random()
        docs = [order(rnd) for _ in range(10)]
        docs[0]["customer"]["tier"], docs[1]["customer"]["tier"] = "gold", "silver"
        docs[2]["items"] = [{"price": p["big"] / 2, "qty": 2}]
        checks = [(f"{f} is computed as requested", rounded(f)) for f in ("total", "item_count", "discount",
                                                                          "big_order")]
        check_against_reference(c, es, p["pipeline"], self.processors(p), docs, checks)
