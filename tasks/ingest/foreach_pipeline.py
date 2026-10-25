import json
import random

from lib.tasklib import Task
from tasks.ingest._common import check_against_reference, render_pipeline

NAMES = ["Trail Runner", "Wool Socks", "Rain Jacket", "Camp Stove", "Head Lamp", "Water Filter", "Tent Pegs",
         "Dry Bag"]
TAGS = ["outdoor", "sale", "new", "gift"]


def order(rnd):
    items = [{"name": n, "sku": f"{n.split()[0][:3].lower()}-{rnd.randint(10, 99)}", "qty": rnd.randint(1, 4)}
             for n in rnd.sample(NAMES, rnd.randint(1, 4))]
    return {"order_id": f"o-{rnd.randint(1000, 9999)}", "items": items,
            "tags": rnd.sample(TAGS, rnd.randint(0, 2))}


class ForeachPipeline(Task):
    id = "ingest-foreach-pipeline"
    title = "Process every element of an array (foreach, append, sort, join, uppercase)"
    covers = ["ingest.pipelines.processor.foreach", "ingest.pipelines.processor.append",
              "ingest.pipelines.processor.sort", "ingest.pipelines.processor.join",
              "ingest.pipelines.processor.uppercase", "ingest.pipelines.simulate"]

    def params(self, rnd, iid):
        return {"pipeline": f"orders-items-{iid}", "order": rnd.choice(["asc", "desc"]),
                "sep": rnd.choice([", ", " | ", "; "]), "tag": rnd.choice(["processed", "imported", "v2"]),
                "example": order(rnd)}

    def processors(self, p):
        return [
            {"foreach": {"field": "items", "processor": {"uppercase": {"field": "_ingest._value.sku"}}}},
            {"foreach": {"field": "items", "processor": {
                "append": {"field": "product_names", "value": "{{{_ingest._value.name}}}"}}}},
            {"sort": {"field": "product_names", "order": p["order"]}},
            {"join": {"field": "product_names", "separator": p["sep"], "target_field": "summary"}},
            {"append": {"field": "tags", "value": p["tag"], "allow_duplicates": False}},
        ]

    def prompt(self, ctx):
        p = ctx.p
        return f"""
Order documents look like this:

  {json.dumps(p['example'])}

Create an ingest pipeline `{p['pipeline']}` that:

  1. uppercases the sku of every element of `items` (the items keep their other fields)
  2. collects the names of all items into an array field `product_names`, sorted in
     {"ascending" if p['order'] == "asc" else "descending"} order
  3. stores those sorted names in the string field `summary`, joined with "{p['sep']}"
  4. adds the tag "{p['tag']}" to the `tags` array (creating it if needed), without adding it twice
     when it is already there

The pipeline must work for any number of items.
"""

    def solution(self, ctx):
        return render_pipeline(ctx.p["pipeline"], self.processors(ctx.p))

    def verify(self, ctx, c):
        p = ctx.p
        rnd = random.Random()
        docs = [order(rnd) for _ in range(8)]
        docs[0]["tags"] = [p["tag"], "sale"]
        docs[1].pop("tags")
        checks = [("the sku of every item is uppercased", "items"),
                  ("product_names holds the sorted item names", "product_names"),
                  ("summary holds the joined names", "summary"),
                  ("the tag is added once", "tags")]
        check_against_reference(c, ctx.es, p["pipeline"], self.processors(p), docs, checks)
