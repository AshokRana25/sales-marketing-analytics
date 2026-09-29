"""Rebuild deterministic fictional fixtures, including deliberate data quality problems."""

import csv
from datetime import date, timedelta
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]


def main():
    rng = Random(20260929)
    sales, ads = [], []
    campaigns = [("paid search", "Search / High intent", 12, 8500),
                 ("paid social", "Social / Prospecting", 8, 7200),
                 ("email", "Email / Loyalty", 7, 9500),
                 ("organic", "Organic / Discovery", 5, 8000)]
    order = 1000
    for day in range(28):
        current = (date(2026, 8, 1) + timedelta(days=day)).isoformat()
        for channel, campaign, volume, basket in campaigns:
            count = volume + rng.randint(-2, 3)
            for _ in range(count):
                order += 1
                gross = basket + rng.randint(-1500, 2500)
                refund = gross if rng.random() < .035 else 0
                label = " Search " if channel == "paid search" and order % 7 == 0 else channel
                sales.append([f"SYN-{order}", current, label, campaign,
                              f"{gross / 100:.2f}", f"{refund / 100:.2f}", "USD"])
            if channel.startswith("paid") and not (channel == "paid social" and day == 24):
                spend = (21000 if channel == "paid search" else 29000) + rng.randint(-2000, 4000)
                clicks = rng.randint(140, 260)
                ads.append([current, channel, campaign, f"{spend / 100:.2f}",
                            clicks * rng.randint(30, 50), clicks, max(0, count + rng.randint(-2, 2)), "USD"])
    sales.append(sales[0].copy())
    sales.append(["SYN-BAD1", "2026-02-30", "email", "Email / Loyalty", "50", "0", "USD"])
    sales.append(["SYN-BAD2", "2026-08-01", "email", "Email / Loyalty", "-50", "0", "USD"])
    ads.append(["2026-08-28", "paid social", "Social / Awareness test", "150.00", 10000, 120, 0, "USD"])
    headers = {"sales": ["order_id", "date", "channel", "campaign", "gross_revenue", "refund_amount", "currency"],
               "ads": ["date", "channel", "campaign", "spend", "impressions", "clicks", "conversions", "currency"]}
    (ROOT / "samples").mkdir(exist_ok=True)
    for name, rows in (("sales", sales), ("ads", ads)):
        with (ROOT / "samples" / f"{name}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(headers[name])
            writer.writerows(rows)


if __name__ == "__main__":
    main()
