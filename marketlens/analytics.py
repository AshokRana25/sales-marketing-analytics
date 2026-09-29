"""SQL-grain reconciliation and explicitly defined, ratio-of-sums metrics."""

import csv
import io
from collections import defaultdict
from pathlib import Path

from .pipeline import CHANNELS, connect, valid_date

SUM_FIELDS = ("orders", "gross_cents", "refund_cents", "revenue_cents", "spend_cents",
              "impressions", "clicks", "conversions", "missing_ad_days", "ad_only_days")


def export_csv(data):
    fields = ("campaign", "channel", "net_revenue", "spend", "roas", "orders",
              "conversions", "ctr", "cpc", "cpa")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(fields)
    for campaign in data["campaigns"]:
        row = []
        for key in fields:
            value = campaign[key]
            if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@"))
                                           or value.startswith(("\t", "\r", "\n"))):
                value = "'" + value
            row.append(value)
        writer.writerow(row)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def ratio(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def summarize(rows):
    totals = {k: sum(r[k] for r in rows) for k in SUM_FIELDS}
    paid = sum(r["revenue_cents"] for r in rows if r["channel"] in {"paid search", "paid social"})
    return {**totals, "net_revenue": totals["revenue_cents"] / 100,
            "spend": totals["spend_cents"] / 100, "refunds": totals["refund_cents"] / 100,
            "roas": ratio(paid, totals["spend_cents"]),
            "mer": ratio(totals["revenue_cents"], totals["spend_cents"]),
            "aov": ratio(totals["revenue_cents"] / 100, totals["orders"]),
            "ctr": ratio(totals["clicks"] * 100, totals["impressions"]),
            "cpc": ratio(totals["spend_cents"] / 100, totals["clicks"]),
            "cpa": ratio(totals["spend_cents"] / 100, totals["conversions"])}


def report(path, start=None, end=None, channel=""):
    if channel and channel not in CHANNELS:
        raise ValueError("Unsupported channel filter")
    with connect(path) as db:
        db.execute("BEGIN")  # All report sections use one consistent read snapshot.
        bounds = db.execute("SELECT MIN(date),MAX(date) FROM (SELECT date FROM sales UNION SELECT date FROM ads)").fetchone()
        start = valid_date(start or bounds[0] or "2026-08-01")
        end = valid_date(end or bounds[1] or start)
        if start > end:
            raise ValueError("Start date must be on or before end date")
        rows = [dict(r) for r in db.execute(Path(__file__).with_name("queries.sql").read_text(),
                                           {"start": start, "end": end, "channel": channel})]
        history = [dict(r) for r in db.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 5")]
        issues = [dict(r) for r in db.execute("SELECT dataset,line,reason FROM issues WHERE import_id=(SELECT MAX(id) FROM imports) ORDER BY id LIMIT 50")]
    groups = defaultdict(list)
    days = defaultdict(list)
    for row in rows:
        groups[(row["channel"], row["campaign"])].append(row)
        days[row["date"]].append(row)
    campaigns = [{"channel": key[0], "campaign": key[1], **summarize(value)}
                 for key, value in groups.items()]
    campaigns.sort(key=lambda x: x["net_revenue"], reverse=True)
    summary = summarize(rows)
    insights = []
    eligible = [c for c in campaigns if c["spend"] > 0]
    if eligible:
        best = max(eligible, key=lambda c: c["roas"])
        insights.append(f'{best["campaign"]} has the highest observed paid ROAS ({best["roas"]:.2f}x) '
                        "in this selection. Review volume and attribution before changing budgets.")
    if summary["missing_ad_days"]:
        insights.append(f'{summary["missing_ad_days"]} paid campaign-day(s) have sales but no ad row. '
                        "ROAS may be overstated; reconcile source coverage.")
    if summary["ad_only_days"]:
        insights.append(f'{summary["ad_only_days"]} campaign-day(s) have advertising but no sales row. '
                        "This may reflect zero orders or incomplete sales coverage.")
    if summary["refunds"]:
        insights.append(f'Net revenue deducts ${summary["refunds"]:,.2f} in refunds. '
                        "Gross revenue alone would overstate performance.")
    if not rows:
        insights.append("No records match this selection. Import data or adjust the filters.")
    return {"filters": {"start": start, "end": end, "channel": channel},
            "bounds": {"start": bounds[0], "end": bounds[1]}, "summary": summary,
            "campaigns": campaigns, "daily": [{"date": d, **summarize(v)} for d, v in days.items()],
            "insights": insights, "imports": history, "issues": issues,
            "attribution": "Single campaign recorded per sales order; observational, not causal."}
