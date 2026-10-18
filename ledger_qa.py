"""Plain-English question answering over the Acme order ledger."""
import json, os, re, calendar
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
IST = timezone(timedelta(hours=5, minutes=30))
CENT = Decimal("0.01")

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Ledger:
    def __init__(self, ndjson_path=None, rates_path=None):
        ndjson_path = ndjson_path or os.path.join(HERE, "ledger_export.ndjson")
        rates_path = rates_path or os.path.join(HERE, "rates.json")
        self.rates = {k: Decimal(str(v)) for k, v in
                      json.load(open(rates_path))["usd_per_unit"].items()}
        latest = {}
        with open(ndjson_path) as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                r["_upd"] = _dt(r["updated_at"])
                cur = latest.get(r["id"])
                if cur is None or r["_upd"] > cur["_upd"]:
                    latest[r["id"]] = r
        self.rows = []
        for r in latest.values():
            r["_day"] = _dt(r["created_at"]).astimezone(IST).date()
            r["_usd"] = Decimal(str(r["amount"])) * self.rates[r["currency"]]
            self.rows.append(r)
        self.regions = sorted({r["region"] for r in self.rows})
        self.products = sorted({r["product"] for r in self.rows}, key=len, reverse=True)
        self.customers = {r["customer"] for r in self.rows}


# ---------------------------------------------------------------- parsing
def _singular(w):
    return w[:-1] if w.endswith("s") and not w.endswith("ss") else w


def _find_dates(q):
    """Return list of date intervals (start, end) inclusive, or None."""
    ivs = []
    # explicit ISO dates
    iso = [date.fromisoformat(m) for m in re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", q)]
    mon = "|".join(sorted(MONTHS, key=len, reverse=True))
    md = re.findall(rf"\b({mon})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", q)
    dm = re.findall(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({mon})\.?(?:,?\s+(\d{{4}}))?\b", q)
    days = list(iso)
    for m, d, y in md:
        days.append(date(int(y) if y else 2026, MONTHS[m], int(d)))
    for d, m, y in dm:
        days.append(date(int(y) if y else 2026, MONTHS[m], int(d)))
    if days:
        days.sort()
        if re.search(r"\b(between|from)\b", q) and len(days) >= 2 or re.search(r"\bto\b|\bthrough\b|\buntil\b|\band\b", q) and len(days) >= 2:
            return [(days[0], days[-1])]
        if re.search(r"\b(before|prior to|earlier than)\b", q):
            return [(date(1900, 1, 1), days[0] - timedelta(days=1))]
        if re.search(r"\b(after|since|later than)\b", q):
            nxt = days[0] + (timedelta(days=0) if "since" in q else timedelta(days=1))
            return [(nxt, date(2999, 12, 31))]
        return [(days[0], days[0])]
    year_m = re.search(r"\b(20\d{2})\b", q)
    year = int(year_m.group(1)) if year_m else 2026
    # quarters / halves
    for qn in re.findall(r"\bq([1-4])\b", q):
        s = date(year, 3 * int(qn) - 2, 1)
        e = date(year, 3 * int(qn), calendar.monthrange(year, 3 * int(qn))[1])
        ivs.append((s, e))
    for word, qn in (("first", 1), ("second", 2), ("third", 3), ("fourth", 4)):
        if re.search(rf"\b{word} quarter\b", q):
            ivs.append((date(year, 3 * qn - 2, 1),
                        date(year, 3 * qn, calendar.monthrange(year, 3 * qn)[1])))
    if re.search(r"\b(h1|first half)\b", q):
        ivs.append((date(year, 1, 1), date(year, 6, 30)))
    if re.search(r"\b(h2|second half)\b", q):
        ivs.append((date(year, 7, 1), date(year, 12, 31)))
    if ivs:
        return ivs
    # month names (possibly several, possibly a range "January to March")
    mm = re.findall(rf"\b({mon})\b(?!\s*\d{{1,2}}\b)", q)
    mm = [m for m in mm if not (m == "may" and not re.search(r"\bin may\b|\bmay\b\s+20\d\d|\bfor may\b|\bof may\b|\bduring may\b|\bmay\b$|\bmay\b[?.!,]", q))]
    if mm:
        nums = [MONTHS[m] for m in mm]
        rng = re.search(rf"\b({mon})\b\s*(?:to|through|thru|-|–)\s*\b({mon})\b", q)
        if rng:
            a, b = MONTHS[rng.group(1)], MONTHS[rng.group(2)]
            return [(date(year, a, 1), date(year, b, calendar.monthrange(year, b)[1]))]
        return [(date(year, n, 1), date(year, n, calendar.monthrange(year, n)[1]))
                for n in sorted(set(nums))]
    if year_m or re.search(r"\bthis year\b", q):
        return [(date(year, 1, 1), date(year, 12, 31))]
    return None


DIMS = {"region": "region", "product": "product", "item": "product", "appliance": "product",
        "customer": "customer", "client": "customer", "buyer": "customer",
        "month": "month", "currency": "currency", "status": "status"}
DESC = r"highest|most|largest|biggest|top|best|max(?:imum)?|greatest|leading|higher|more"
ASC = r"lowest|least|smallest|fewest|worst|min(?:imum)?|bottom|lower|less"


def plan(ledger, question):
    q = " " + question.lower().strip() + " "
    q = q.replace("’", "'").replace("–", "-")
    p = {"status": None, "region": None, "product": None, "customer": None,
         "currency": None, "dates": _find_dates(q.strip()), "group": None,
         "order": None, "topn": None, "metric": None}

    # entities
    for r in ledger.regions:
        if re.search(rf"\b{r.lower()}(?:ern)?\b(?!\s+(?:region|regions)\b.*\bvs\b)", q) and \
                re.search(rf"\b{r.lower()}\b", q):
            p["region"] = r
    for prod in ledger.products:
        pl = prod.lower()
        if re.search(rf"\b{re.escape(pl)}s?\b", q) or \
                re.search(rf"\b{re.escape(pl.replace(' ', '-'))}s?\b", q) or \
                re.search(rf"\b{re.escape(pl.replace(' ', ''))}s?\b", q):
            p["product"] = prod
            break
    m = re.search(r"\bc\d{4}\b", q)
    if m and m.group(0).upper() in ledger.customers:
        p["customer"] = m.group(0).upper()
    elif m:
        p["customer"] = m.group(0).upper()
    if re.search(r"\b(eur|euros?)\b", q):
        p["currency"] = "EUR"
    elif re.search(r"\b(inr|rupees?)\b", q):
        p["currency"] = "INR"
    elif re.search(r"\busd[- ](?:denominated |priced )?(?:orders?|transactions?|purchases?)\b|\b(?:orders?|transactions?|purchases?)\s+(?:placed |paid |made |priced |denominated )?in usd\b|\bdenominated in usd\b|\bpaid in usd\b", q):
        p["currency"] = "USD"

    # status
    if re.search(r"\brefund|\breturned\b", q):
        p["status"] = "refunded"
    elif re.search(r"\bvoid(?:ed)?\b|\bcancel", q):
        p["status"] = "void"
    elif re.search(r"\bpaid\s+(?:orders?|transactions?|purchases?|sales)\b|\bcompleted\s+(?:orders?|sales|purchases)\b|\bsuccessful\s+orders?\b|\borders?\s+with\s+(?:status\s+)?paid\b|\bstatus (?:of )?paid\b|\b(?:were|was|are|got|been|that were|which were)\s+paid\b(?!\s+(?:in|with|by|using)\s+(?:usd|eur|inr|euros?|rupees?|dollars?)\b)", q):
        p["status"] = "paid"

    # grouping / superlatives
    sup_desc = re.search(rf"\b({DESC})\b", q)
    sup_asc = re.search(rf"\b({ASC})\b", q)
    gdim = None
    for pat in (rf"\b(?:which|what|who)\s+(?:single\s+|individual\s+)?({'|'.join(DIMS)})s?\b",
                rf"\btop\s+(?:\d+\s+|three\s+|five\s+|ten\s+|two\s+)?({'|'.join(DIMS)})s?\b",
                rf"\b({'|'.join(DIMS)})s?\s+(?:with|that|had|has|having|generat|brought|made|earn)",
                rf"\b(?:by|per|for each|each|every|across)\s+({'|'.join(DIMS)})s?\b",
                rf"\b({'|'.join(DIMS)})s?\s+(?:ranked|breakdown|wise)\b",
                rf"\b(?:rank|ranking|breakdown of|split by|grouped by)\s+(?:the\s+)?({'|'.join(DIMS)})s?\b"):
        m = re.search(pat, q)
        if m:
            gdim = DIMS[m.group(1)]
            break
    if re.search(r"\bwho\b", q) and not gdim and re.search(rf"\b({DESC}|{ASC})\b", q):
        gdim = "customer"
    nwords = {"two": 2, "three": 3, "four": 4, "five": 5, "ten": 10}
    m = re.search(r"\btop\s+(\d+|two|three|four|five|ten)\b", q)
    if m:
        p["topn"] = int(m.group(1)) if m.group(1).isdigit() else nwords[m.group(1)]
    if gdim:
        # entity filter on the same dim would be contradictory; keep it as filter only if a different word
        p["group"] = gdim
        if sup_asc and not sup_desc:
            p["order"] = "asc"
        elif sup_desc or p["topn"]:
            p["order"] = "desc"
        else:
            p["order"] = "all"
        if gdim == "region" and not re.search(r"\bregions?\b", q):
            pass
    # metric
    if re.search(r"\b(unique|distinct|different)\s+customers?\b|\bhow many customers?\b|\bnumber of customers?\b|\bcustomers? count\b", q) and not p["group"]:
        p["metric"] = "n_customers"
    elif re.search(r"\b(unique|distinct|different)\s+products?\b|\bhow many products?\b|\bnumber of products?\b", q) and not p["group"]:
        p["metric"] = "n_products"
    elif re.search(r"\baverage\b|\bavg\b|\bmean\b|\baov\b", q):
        p["metric"] = "avg"
    elif re.search(r"\b(units?|quantity|quantities|pieces|items?)\b.*\b(sold|ordered|purchased|bought|total)|\bhow many (units?|items?|pieces)\b|\btotal (units?|quantity|items?)\b|\bunits?\b", q):
        p["metric"] = "units"
    elif re.search(r"\brefund(?:ed|s)?\s+rate\b|\brate of refunds?\b|\bpercent(?:age)? of orders .*refund|\brefund percentage\b|\bshare of .*refund", q):
        p["metric"] = "refund_rate"
    elif re.search(r"\bhow many\b|\bnumber of\b|\bcount\b|\btotal orders\b|\borders? (?:were|was|did)\b|\bhow often\b", q) and not re.search(r"\bhow much\b|\brevenue\b|\bvalue\b|\bamount\b", q):
        p["metric"] = "count"
    elif p["status"] == "refunded" and not re.search(r"\b(amount|value|worth|total|sum|usd|dollars?|money|much)\b", q) and re.search(r"\bwhich|\bwho\b", q) and not p["group"]:
        p["metric"] = "count"
    else:
        p["metric"] = "revenue"
    if p["metric"] == "refund_rate":
        p["status"] = None
    if p["group"] and p["metric"] == "revenue" and p["status"] == "refunded":
        if re.search(r"\bmost refunds\b|\bfewest refunds\b|\bmost refunded\b|\bhighest (number|count)\b|\bnumber of refunds\b|\bhow many\b", q):
            p["metric"] = "count"
    if p["group"] and re.search(r"\b(most|fewest|highest|lowest) (orders|purchases|refunds|returns)\b|\bnumber of (orders|refunds)\b|\bmost frequent|\bmost orders\b", q):
        p["metric"] = "count"
    if p["group"] and re.search(r"\b(most|fewest|largest|highest|lowest) (units|quantity)\b|\bbest[- ]selling\b|\bmost (sold|popular)\b|\bunits? sold\b|\bmost units\b", q):
        p["metric"] = "units"
    if p["group"] and re.search(r"\bhighest[- ]grossing\b|\bbest[- ]performing\b|\btop earner\b|\btop[- ]selling\b", q) and p["metric"] != "units" and not re.search(r"\bunits?\b", q):
        p["metric"] = "revenue"
    return p


# -------------------------------------------------------------- execution
def _in_dates(d, ivs):
    return ivs is None or any(a <= d <= b for a, b in ivs)


def _money(x):
    return float(x.quantize(CENT, rounding=ROUND_HALF_UP))


def run(ledger, p):
    metric = p["metric"]
    # which statuses count
    if p["status"]:
        statuses = {p["status"]}
    elif metric in ("revenue", "units", "avg"):
        statuses = {"paid"}
    elif metric == "refund_rate":
        statuses = {"paid", "refunded", "void"}
    else:
        statuses = {"paid", "refunded", "void"}
    if metric in ("n_customers", "n_products") and not p["status"]:
        statuses = {"paid"} if False else {"paid", "refunded", "void"}

    def match(r):
        if p["region"] and p["group"] != "region" and r["region"] != p["region"]:
            return False
        if p["product"] and p["group"] != "product" and r["product"] != p["product"]:
            return False
        if p["customer"] and p["group"] != "customer" and r["customer"] != p["customer"]:
            return False
        if p["currency"] and r["currency"] != p["currency"]:
            return False
        return _in_dates(r["_day"], p["dates"])

    base = [r for r in ledger.rows if match(r)]
    sel = [r for r in base if r["status"] in statuses]

    def value(rows):
        if metric == "revenue":
            return _money(sum((r["_usd"] for r in rows), Decimal(0)))
        if metric == "count":
            return len(rows)
        if metric == "units":
            return sum(r["qty"] for r in rows)
        if metric == "avg":
            return _money(sum((r["_usd"] for r in rows), Decimal(0)) / len(rows)) if rows else 0
        if metric == "n_customers":
            return len({r["customer"] for r in rows})
        if metric == "n_products":
            return len({r["product"] for r in rows})
        if metric == "refund_rate":
            tot = len(rows)
            return round(100.0 * sum(1 for r in rows if r["status"] == "refunded") / tot, 2) if tot else 0
        raise ValueError(metric)

    if not p["group"]:
        return value(sel)

    keyf = {"region": lambda r: r["region"], "product": lambda r: r["product"],
            "customer": lambda r: r["customer"], "currency": lambda r: r["currency"],
            "status": lambda r: r["status"],
            "month": lambda r: r["_day"].strftime("%Y-%m")}[p["group"]]
    groups = defaultdict(list)
    for r in sel:
        groups[keyf(r)].append(r)
    scores = {k: value(v) for k, v in groups.items()}
    if not scores:
        return None
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]) if p["order"] != "asc" else (kv[1], kv[0]))
    if p["order"] == "all":
        return {k: v for k, v in sorted(scores.items())}
    n = p["topn"] or 1
    names = [k for k, _ in ordered[:n]]
    return names[0] if n == 1 else names


_LEDGER = None


def answer(question: str):
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = Ledger()
    return run(_LEDGER, plan(_LEDGER, question))
