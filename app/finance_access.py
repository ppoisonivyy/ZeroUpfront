"""Per-hospital assignments and a read-only projection for finance staff."""
import psycopg
from psycopg.rows import dict_row


def assign_case(dsn, username, case_id, *, remove=False):
    with psycopg.connect(dsn) as db:
        if not db.execute("""
            SELECT 1 FROM zeroupfront_demo.staff_accounts
            WHERE username=%s AND role='finance' AND active FOR UPDATE
        """, (username,)).fetchone():
            raise ValueError("Choose an active finance account in this hospital.")
        if remove:
            db.execute("DELETE FROM zeroupfront_demo.finance_assignments WHERE username=%s AND case_id=%s",
                       (username, case_id))
            return
        if not db.execute("SELECT 1 FROM zeroupfront_demo.discharge_cases WHERE id=%s", (case_id,)).fetchone():
            raise ValueError("Choose an existing discharge case in this hospital.")
        db.execute("""
            INSERT INTO zeroupfront_demo.finance_assignments (username,case_id) VALUES (%s,%s)
            ON CONFLICT DO NOTHING
        """, (username, case_id))


def _balance(row):
    amount = row["approved_minor"]
    paid = row["credited_minor"]
    matched_currency = row.pop("matched_currency")
    if row["receipt_count"] and matched_currency is not True:
        row["credited_minor"] = None
        status = "reconciliation_required"
    elif amount is None:
        if row["receipt_count"]:
            status = "reconciliation_required"
        elif row["payer_outcome"] in {"declined", "query"}:
            status = row["payer_outcome"]
        else:
            status = "awaiting_decision"
    elif paid > amount:
        status = "reconciliation_required"
    else:
        row["outstanding_minor"] = amount - paid
        status = "settled" if paid == amount else "outstanding"
    row.setdefault("outstanding_minor", None)
    row["status"] = status
    return row


def reconciliation(dsn, username, page):
    page_size = 25
    # Filter assigned revisions before resolving their latest written decision and credits.
    # Only typed accounting fields cross this boundary; letters, notes and names stay in the case workspace.
    with psycopg.connect(dsn, row_factory=dict_row) as db:
        rows = db.execute("""
            WITH selected AS MATERIALIZED (
                SELECT c.id AS case_id,r.revision,c.head=r.revision AS current
                FROM zeroupfront_demo.finance_assignments a
                JOIN zeroupfront_demo.discharge_cases c ON c.id=a.case_id
                JOIN zeroupfront_demo.discharge_revisions r ON r.case_id=c.id
                WHERE a.username=%s AND (c.head=r.revision OR EXISTS (
                    SELECT 1 FROM zeroupfront_demo.discharge_events e
                    WHERE e.case_id=c.id AND e.revision=r.revision AND e.kind IN ('reply','payment')))
                ORDER BY c.id,r.revision DESC LIMIT %s OFFSET %s
            )
            SELECT s.*,decision.payer_outcome,decision.currency,decision.approved_minor,credits.receipt_count,credits.last_receipt_id,
                   credits.credited_minor, credits.matched_currency
            FROM selected s
            LEFT JOIN LATERAL (
                SELECT CASE WHEN data->>'outcome' IN ('confirmed','partial','declined','query')
                            THEN data->>'outcome' END AS payer_outcome,
                       data->>'currency' AS currency,
                       CASE WHEN data->>'outcome' IN ('partial','confirmed')
                            THEN (data->>'amount_minor')::bigint END AS approved_minor
                FROM zeroupfront_demo.discharge_events
                WHERE case_id=s.case_id AND revision=s.revision AND kind='reply'
                ORDER BY version DESC LIMIT 1
            ) decision ON true
            CROSS JOIN LATERAL (
                SELECT count(*) AS receipt_count,max(id) AS last_receipt_id,
                       coalesce(sum((data->>'amount_minor')::bigint),0)::bigint AS credited_minor,
                       bool_and((data->>'currency') IS NOT DISTINCT FROM decision.currency) AS matched_currency
                FROM zeroupfront_demo.discharge_events
                WHERE case_id=s.case_id AND revision=s.revision AND kind='payment'
            ) credits
            ORDER BY s.case_id,s.revision DESC
        """, (username, page_size + 1, (page - 1) * page_size)).fetchall()
        items = [_balance(row) for row in rows[:page_size]]
        with db.cursor() as cursor:
            cursor.executemany("""
                INSERT INTO zeroupfront_demo.access_audit (username,capability,outcome,case_id,revision)
                VALUES (%s,'finance_reconciliation','allowed',%s,%s)
            """, [(username, row["case_id"], row["revision"]) for row in items] or [(username, None, None)])
        return {"items": items, "page": page, "has_more": len(rows) > page_size}
