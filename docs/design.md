# Design decisions

## Business purpose

Help a reviewer compare sales revenue and advertising efficiency while exposing the cleaning and reconciliation needed to interpret the results. The project demonstrates analytics engineering, not statistical proof of advertising impact.

## 1. Standard-library Python and SQLite

The runtime uses Python's CSV parser, Decimal, SQLite, and a loopback HTTP server. A reviewer can run the app without a dependency install or external service. The cost is a limited local-server feature set: no authentication, tenant boundaries, production worker management, or operational monitoring. Production deployment should use a maintained application server, authentication, access policies, and deployment-specific hardening.

SQLite provides transactional imports and consistent report snapshots. Integer cents preserve monetary sums. Final displayed ratios are rounded to four decimals by the API and fewer decimals in the UI; exact base totals remain in the response.

## 2. Immutable accepted records

Sales keys are global order IDs. Advertising keys are date/channel/campaign. Exact reimports are ignored; changed values under an existing key are flagged as conflicts. This prevents double-counting and accidental historical rewrites, but does not implement corrections, late refunds, upserts, source versioning, or tenant-scoped identity. A production design should define those semantics explicitly rather than treating every conflicting row as an update.

Import auditing records a SHA-256 hash of the two source strings, a timestamp, and counts. Hashes identify input content; they do not replace source storage or provide encryption. Quarantined records retain only metadata, not the raw row. Normalization counts apply to valid parsed rows, including duplicates and conflicts, and overlap outcome categories.

## 3. Parse first, commit once

Both CSV files are structurally parsed before a write transaction. Invalid headers and malformed quoting fail the request. Row-level validation errors are recorded while other valid rows can commit. The accepted data and import/issue history commit atomically. A failure in database writes rolls back the transaction.

This is deliberately partial acceptance at row level, not all-or-nothing validation. The dashboard reports rejected rows so users can reconcile before interpreting metrics. It does not suppress all results when quality problems exist.

## 4. Explicit grain prevents join multiplication

The SQL first aggregates sales and advertising independently to date/channel/campaign. It unions their keys, then left-joins the aggregates. This preserves records present in only one source and prevents the classic error of repeating daily ad spend for every individual order.

Report filters are applied consistently to both source aggregates. A read transaction keeps the metrics and quality history consistent with one database snapshot. Dates are inclusive, calendar-valid ISO dates. Campaign matching is exact after trimming; no fuzzy mapping is implied.

## 5. Ratios have named denominators

The code calculates ratios from summed inputs. A zero denominator yields null, not invented zero or infinity. Paid ROAS uses paid-channel sales; MER uses all selected sales. Platform conversions stay distinct from orders and customers. Cost per platform conversion is never labeled customer acquisition cost.

Revenue without advertising coverage can overstate ROAS. Advertising-only days can be real zero-sales outcomes or absent sales data. The dashboard flags both and does not guess which explanation is correct. Reports remain observational: a high ROAS is not evidence that increasing budget will produce proportional returns.

## 6. Transparent observations

Business observations are deterministic, inspectable rules in `analytics.py`. They identify the leading observed paid ROAS, refunds, and coverage gaps. There is no LLM, automatic budget optimizer, forecast, experiment, or significance test. These extensions would require a different dataset and evaluation strategy.

## Browser handling

User-provided labels are rendered with `textContent`, not injected HTML. Server-generated CSV exports prefix potentially executable spreadsheet formula cells and use CSV escaping. Static paths are explicitly allowlisted. Requests are constrained by content type and byte limit; the app sends a restrictive content security policy and no permissive cross-origin headers. These measures do not make the standard-library server a production security boundary.

## Production roadmap

1. Define identity, tenant scope, source-system keys, correction behavior, and retention.
2. Add authenticated connectors and a raw-data landing area with file provenance.
3. Add dimensional campaign mappings, currency conversion, and reporting timezone contracts.
4. Move transformations to a warehouse/dbt model with scheduled quality checks.
5. Add pipeline monitoring, reconciliation alerts, incremental loads, and role-based access.
6. Add attribution/experimentation only when the source data supports those analyses.
