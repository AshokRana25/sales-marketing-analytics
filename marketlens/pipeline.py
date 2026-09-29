"""Repeatable CSV cleaning and atomic imports, using only the Python standard library."""

import csv
import hashlib
import io
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

CHANNELS = {"paid search", "paid social", "email", "organic"}
ALIASES = {"search": "paid search", "ppc": "paid search", "social": "paid social",
           "paid_search": "paid search", "paid_social": "paid social"}
SALES_FIELDS = {"order_id", "date", "channel", "campaign", "gross_revenue", "refund_amount", "currency"}
ADS_FIELDS = {"date", "channel", "campaign", "spend", "impressions", "clicks", "conversions", "currency"}


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS sales (
          order_id TEXT PRIMARY KEY, date TEXT NOT NULL, channel TEXT NOT NULL,
          campaign TEXT NOT NULL, gross_cents INTEGER NOT NULL, refund_cents INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS ads (
          date TEXT NOT NULL, channel TEXT NOT NULL, campaign TEXT NOT NULL,
          spend_cents INTEGER NOT NULL, impressions INTEGER NOT NULL,
          clicks INTEGER NOT NULL, conversions INTEGER NOT NULL,
          PRIMARY KEY(date,channel,campaign));
        CREATE TABLE IF NOT EXISTS imports (
          id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, source_hash TEXT NOT NULL,
          accepted INTEGER NOT NULL, duplicates INTEGER NOT NULL, rejected INTEGER NOT NULL,
          normalized INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS issues (
          id INTEGER PRIMARY KEY, import_id INTEGER NOT NULL REFERENCES imports(id),
          dataset TEXT NOT NULL, line INTEGER NOT NULL, reason TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_sales_date_channel ON sales(date,channel);
        CREATE INDEX IF NOT EXISTS ix_ads_date_channel ON ads(date,channel);
        """)


def valid_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("date is not a valid calendar date") from None


def money(value):
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError("money must be numeric") from None
    if (not number.is_finite() or number < 0 or number > 10_000_000
            or number * 100 != (number * 100).to_integral_value()):
        raise ValueError("money must be 0..10000000 with at most two decimals")
    return int(number * 100)


def integer(value):
    if not re.fullmatch(r"\d{1,9}", value):
        raise ValueError("counts must be nonnegative integers of at most 9 digits")
    return int(value)


def parse(text, dataset):
    if not text.strip():
        return [], []
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
    fields = SALES_FIELDS if dataset == "sales" else ADS_FIELDS
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError(f"{dataset}: missing or duplicate headers")
    headers = [h.strip().lower() for h in reader.fieldnames]
    if set(headers) != fields or len(headers) != len(fields):
        raise ValueError(f"{dataset}: required headers are {', '.join(sorted(fields))}")
    reader.fieldnames = headers
    cleaned, issues = [], []
    try:
        for row in reader:
            line = reader.line_num
            if line > 20001:
                raise ValueError("CSV limit is 20000 lines per file")
            try:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("row has missing or extra columns")
                values = {k: v.strip() for k, v in row.items()}
                day = valid_date(values["date"])
                channel = values["channel"].lower()
                channel = ALIASES.get(channel, channel)
                if channel not in CHANNELS:
                    raise ValueError("unsupported channel")
                campaign = values["campaign"]
                if not campaign or len(campaign) > 100:
                    raise ValueError("campaign must contain 1..100 characters")
                if values["currency"].upper() != "USD":
                    raise ValueError("only USD is supported; currency conversion is not inferred")
                changed = (any(row[k] != values[k] for k in row)
                           or values["channel"] != channel or values["currency"] != "USD")
                if dataset == "sales":
                    order = values["order_id"]
                    if not order or len(order) > 100:
                        raise ValueError("order_id must contain 1..100 characters")
                    gross, refund = money(values["gross_revenue"]), money(values["refund_amount"])
                    if refund > gross:
                        raise ValueError("refund exceeds gross revenue")
                    data = (order, day, channel, campaign, gross, refund)
                else:
                    if channel not in {"paid search", "paid social"}:
                        raise ValueError("ad rows require paid search or paid social")
                    impressions, clicks, conversions = (integer(values[k]) for k in
                                                        ("impressions", "clicks", "conversions"))
                    if not conversions <= clicks <= impressions:
                        raise ValueError("require conversions <= clicks <= impressions")
                    data = (day, channel, campaign, money(values["spend"]),
                            impressions, clicks, conversions)
                cleaned.append((line, data, changed))
            except ValueError as error:
                issues.append({"dataset": dataset, "line": line, "reason": str(error)})
    except csv.Error:
        raise ValueError(f"{dataset}: malformed CSV quoting") from None
    return cleaned, issues


def import_csv(path, sales_csv="", ads_csv=""):
    if not sales_csv.strip() and not ads_csv.strip():
        raise ValueError("Supply at least one nonempty CSV")
    # Parse both files before writing: structural errors must not leave a half-import.
    sales, sales_issues = parse(sales_csv, "sales")
    ads, ads_issues = parse(ads_csv, "ads")
    issues = sales_issues + ads_issues
    accepted = duplicates = normalized = 0
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        for dataset, records in (("sales", sales), ("ads", ads)):
            for line, data, changed in records:
                normalized += int(changed)
                if dataset == "sales":
                    old = db.execute("SELECT * FROM sales WHERE order_id=?", data[:1]).fetchone()
                else:
                    old = db.execute("SELECT * FROM ads WHERE date=? AND channel=? AND campaign=?",
                                     data[:3]).fetchone()
                if old is not None:
                    if tuple(old) == data:
                        duplicates += 1
                    else:
                        issues.append({"dataset": dataset, "line": line,
                                       "reason": "conflicting existing key; record not overwritten"})
                    continue
                placeholders = ",".join("?" for _ in data)
                # dataset is selected from constants above; values are always parameters.
                db.execute(f"INSERT INTO {dataset} VALUES ({placeholders})", data)
                accepted += 1
        digest = hashlib.sha256(json.dumps([sales_csv, ads_csv]).encode()).hexdigest()
        run_id = db.execute("""INSERT INTO imports
            (created_at,source_hash,accepted,duplicates,rejected,normalized) VALUES(?,?,?,?,?,?)""",
            (datetime.now(timezone.utc).isoformat(), digest, accepted, duplicates,
             len(issues), normalized)).lastrowid
        db.executemany("INSERT INTO issues(import_id,dataset,line,reason) VALUES(?,?,?,?)",
                       [(run_id, i["dataset"], i["line"], i["reason"]) for i in issues])
    return {"id": run_id, "accepted": accepted, "duplicates": duplicates,
            "rejected": len(issues), "normalized": normalized, "issues": issues}
