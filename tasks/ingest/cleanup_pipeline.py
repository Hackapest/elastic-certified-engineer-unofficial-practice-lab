import json
import random

from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, render_pipeline

COMMENTS = ["<p>Great&nbsp;product, <b>fast</b> delivery!</p>", "<div>Too <i>small</i> &amp; too loud</div>",
            "Works as described<br>", "<ul><li>cheap</li><li>light</li></ul>", "   <span>meh</span>  "]
COUNTRIES = ["de", " fr", "it ", "Es", " nl "]


def review(rnd):
    phone = rnd.choice(["({a}) {b}-{c}", "+{a} {b} {c}", "{a}.{b}.{c}", "{a}/{b}{c}"]).format(
        a=rnd.randint(100, 999), b=rnd.randint(100, 999), c=rnd.randint(1000, 9999))
    sku = rnd.choice(["ab_12_x", "QZ_9", "hk_77_b_2", "M_1"])
    return {"comment": rnd.choice(COMMENTS), "phone": phone, "country": rnd.choice(COUNTRIES), "sku": sku}


class CleanupPipeline(Task):
    id = "ingest-cleanup-pipeline"
    title = "Clean up text values (gsub, html_strip, uppercase, trim)"
    covers = ["ingest.pipelines.processor.gsub", "ingest.pipelines.processor.html_strip",
              "ingest.pipelines.processor.uppercase", "ingest.pipelines.processor.trim"]

    def params(self, rnd, iid):
        return {"pipeline": f"reviews-clean-{iid}", "dash": rnd.choice(["-", "."]),
                "target": rnd.choice(["comment_text", "comment_plain"]),
                "examples": [review(rnd) for _ in range(2)]}

    def processors(self, p):
        return [
            {"html_strip": {"field": "comment", "target_field": p["target"]}},
            {"trim": {"field": p["target"]}},
            {"gsub": {"field": "phone", "pattern": "[^0-9]", "replacement": ""}},
            {"trim": {"field": "country"}},
            {"uppercase": {"field": "country"}},
            {"gsub": {"field": "sku", "pattern": "_", "replacement": p["dash"]}},
            {"uppercase": {"field": "sku"}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        examples = "\n".join(f"  {json.dumps(e)}" for e in p["examples"])
        return f"""
Product reviews arrive like this:

{examples}

Create an ingest pipeline `{p['pipeline']}` that:

  1. stores the text of `comment` without its HTML tags in `{p['target']}`, with leading and
     trailing whitespace removed (keep the original `comment` field unchanged)
  2. keeps only the digits of `phone` (e.g. "(555) 123-4567" becomes "5551234567")
  3. removes surrounding spaces from `country` and uppercases it ("  fr" becomes "FR")
  4. replaces every underscore in `sku` with "{p['dash']}" and uppercases it
     ("ab_12_x" becomes "{"AB_12_X".replace("_", p['dash'])}")
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p = ctx.p
        rnd = random.Random()
        docs = [review(rnd) for _ in range(8)]
        checks = [(f"{p['target']} holds the comment without HTML", p["target"]),
                  ("comment is unchanged", "comment"),
                  ("phone keeps only digits", "phone"),
                  ("country is trimmed and uppercased", "country"),
                  ("sku is rewritten as requested", "sku")]
        check_against_reference(c, ctx.es, p["pipeline"], self.processors(p), docs, checks)
