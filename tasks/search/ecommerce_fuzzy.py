from lib.sampledata import ECOMMERCE, LAST_NAMES
from lib.tasklib import Task


def typo(rnd, word):
    """One edit: drop, double or swap a letter after the first."""
    i = rnd.randrange(1, len(word) - 1)
    kind = rnd.choice(["drop", "double", "swap"])
    if kind == "drop":
        return word[:i] + word[i + 1:]
    if kind == "double":
        return word[:i] + word[i] + word[i:]
    return word[:i] + word[i + 1] + word[i] + word[i + 2:]


class EcommerceFuzzy(Task):
    id = "search-ecommerce-fuzzy"
    title = "Tolerate typos with fuzzy matching"
    covers = ["search.term.fuzzy", "search.fulltext.match"]
    answer = "query"
    compare = "hits"

    def params(self, rnd, iid):
        name = rnd.choice(LAST_NAMES)
        misspelled = typo(rnd, name)
        while misspelled == name:
            misspelled = typo(rnd, name)
        return {"name": misspelled, "edits": 1 if len(misspelled) <= 5 else 2}

    def prompt(self, ctx):
        p = ctx.p
        return f"""
A support agent typed the customer's last name as "{p['name']}". In `{ECOMMERCE}`, find all orders
of customers whose last name (customer_last_name) differs from "{p['name']}" by at most
{p['edits']} edit(s) (a changed, added, removed or swapped letter), ignoring upper and lower case.

Return all of them in one response; there are fewer than 500.
"""

    def solution(self, ctx):
        p = ctx.p
        return f"""
GET {ECOMMERCE}/_search
{{
  "size": 500,
  "query": {{
    "match": {{
      "customer_last_name": {{
        "query": "{p['name']}",
        "fuzziness": {p['edits']}
      }}
    }}
  }}
}}
"""

    def wrong_answer(self, ctx):
        return self.solution(ctx).replace(f'"fuzziness": {ctx.p["edits"]}', '"fuzziness": 0')
