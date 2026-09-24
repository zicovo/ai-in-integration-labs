"""Read-only pages over the in-memory state of the three systems of record.

A learner sees these systems through the API and the terminal, and some lab results are easier
to believe when they are on screen: e-03's two work orders for one connection, the dunning case
f-01's agent moved, the March that doubles in a-02. Each system serves one page at `/`, in the lab
browser, next to its API.

Three rules, all deliberate:

- **The page reads the same dictionaries the API writes**, so it is never out of date and a
  reset clears it too. There is no second copy of the data and nothing to synchronise.
- **It changes nothing and interprets nothing.** No buttons, and no "possible duplicate" flags:
  e-03 asks the learner to prove from the work order system what happened, and a page that
  pointed at the answer would do the lab for them.
- **It is not in the OpenAPI document.** c-02 generates its twenty-three tools from that
  document, so a page that appeared in it would become a twenty-fourth tool.

Every value is escaped. Case 4471 carries a note written to steer whatever reads it, and a page
that rendered it as markup would be the one reader in the stack that fell for it.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlencode

_STYLE = """
  :root { color-scheme: light dark; --fg: #1a1a1a; --dim: #5c5c5c; --line: #d8d8d8; --bg: #fdfdfc;
          --accent: #0b6b62; --soft: #f1f4f3; }
  @media (prefers-color-scheme: dark) {
    :root { --fg: #e8e8e6; --dim: #9a9a96; --line: #34343a; --bg: #17171a; --accent: #4fd1c5; --soft: #202024; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 40px 16px; background: var(--bg); color: var(--fg);
         font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  main { max-width: 1180px; margin: 0 auto; }
  h1 { font-size: 24px; margin: 0 0 4px; font-weight: 650; letter-spacing: -0.01em; }
  p.lede { color: var(--dim); margin: 0 0 20px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--dim);
       font-weight: 600; margin: 28px 0 8px; }
  nav { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; margin: 0 0 18px;
        font-size: 13.5px; color: var(--dim); }
  nav form { display: flex; gap: 6px; align-items: center; margin: 0; }
  input { font: inherit; padding: 3px 7px; border: 1px solid var(--line); border-radius: 4px;
          background: var(--bg); color: var(--fg); width: 9em; }
  button { font: inherit; padding: 3px 10px; border: 1px solid var(--line); border-radius: 4px;
           background: var(--soft); color: var(--fg); cursor: pointer; }
  a { color: var(--accent); }
  .scroll { overflow-x: auto; border-top: 1px solid var(--line); }
  table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
  th, td { text-align: left; vertical-align: top; padding: 7px 10px 7px 0; border-bottom: 1px solid var(--line); }
  th { font-weight: 600; color: var(--dim); white-space: nowrap; }
  td.num { text-align: right; font-variant-numeric: tabular-nums; }
  code, .mono { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 12.5px; }
  .dim { color: var(--dim); }
  .state { display: inline-block; padding: 0 7px; border-radius: 9px; background: var(--soft);
           border: 1px solid var(--line); font-size: 12.5px; white-space: nowrap; }
  .note { white-space: pre-wrap; background: var(--soft); border-left: 3px solid var(--line);
          padding: 6px 10px; margin: 4px 0; max-width: 62em; }
  .bar { height: 10px; background: var(--accent); border-radius: 2px; min-width: 2px; }
  footer { margin-top: 32px; padding-top: 14px; border-top: 1px solid var(--line);
           color: var(--dim); font-size: 13px; }
"""


def _e(value: object) -> str:
    """Escape one value for the page. A missing value reads "none", dimmed, not "None"."""
    if value is None or value == "":
        return '<span class="dim">none</span>'
    return escape(str(value))


def _page(title: str, lede: str, nav: str, body: str, api: str, refresh: int | None,
          keep: dict | None = None) -> str:
    """`keep` is the filter in force, so switching the refresh on or off does not drop it."""
    keep = {k: v for k, v in (keep or {}).items() if v}
    meta = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    toggle = (f'<a href="?{escape(urlencode(keep))}">stop refreshing</a>' if refresh
              else f'<a href="?{escape(urlencode(keep | {"refresh": 5}))}">refresh every five seconds</a>')
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta}
<title>{escape(title)}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
  <h1>{escape(title)}</h1>
  <p class="lede">{lede}</p>
  <nav>{nav}<span>{toggle}</span><a href="{api}">the same as JSON</a><a href="/docs">the API</a></nav>
  {body}
  <footer>Read only. This page shows the system's state as it is held right now; a restart or a
  reset puts it back to the seed. Nothing here is written by the page.</footer>
</main>
</body>
</html>"""


def _refresh_arg(refresh: int | None) -> str:
    return f'<input type="hidden" name="refresh" value="{refresh}">' if refresh else ""


def _filter(name: str, label: str, value: str | None, refresh: int | None) -> str:
    return (f'<form method="get"><label for="{name}">{label}</label>'
            f'<input id="{name}" name="{name}" value="{escape(value or "")}" inputmode="numeric">'
            f'{_refresh_arg(refresh)}<button type="submit">show</button></form>')


def _actor(created_by: dict | None) -> str:
    if not created_by or not created_by.get("subject"):
        return '<span class="dim">no token presented</span>'
    subject = escape(str(created_by["subject"]))
    actor = created_by.get("actor")
    return f"{subject}, through {escape(str(actor))}" if actor else subject


# ------------------------------------------------------------------ work order management


def work_orders(orders: list[dict], history: dict[str, list[dict]], notes: dict[str, list[dict]],
                connection_id: str | None, refresh: int | None) -> str:
    rows = [o for o in orders if not connection_id or o["connection_id"] == connection_id]
    rows.sort(key=lambda o: (o.get("created_at") or "", o["work_order_id"]), reverse=True)
    if rows:
        body_rows = []
        for o in rows:
            extra = []
            if o.get("note"):
                extra.append(f'<div class="note">{_e(o["note"])}</div>')
            for n in notes.get(o["work_order_id"], []):
                extra.append(f'<div class="note">{_e(n.get("author"))}: {_e(n.get("body"))}</div>')
            events = history.get(o["work_order_id"], [])
            if events:
                extra.append('<div class="dim">' + ", ".join(
                    f'{_e(ev["event"])} {_e(ev.get("at"))}' for ev in events) + "</div>")
            body_rows.append(
                "<tr>"
                f'<td class="mono">{_e(o["work_order_id"])}</td>'
                f'<td class="mono">{_e(o["connection_id"])}</td>'
                f"<td>{_e(o['type'])}</td>"
                f'<td><span class="state">{_e(o["state"])}</span></td>'
                f"<td>{_e(o.get('reason'))}{''.join(extra)}</td>"
                f'<td class="mono">{_e(o.get("created_at"))}</td>'
                f'<td class="mono">{_e(o.get("idempotency_key"))}</td>'
                f"<td>{_actor(o.get('created_by'))}</td>"
                f"<td>{_e(o.get('technician'))}</td>"
                "</tr>")
        table = ('<div class="scroll"><table><thead><tr><th>Work order</th><th>Connection</th>'
                 "<th>Type</th><th>State</th><th>Reason and notes</th><th>Created</th>"
                 "<th>Idempotency key</th><th>Created by</th><th>Technician</th></tr></thead>"
                 f"<tbody>{''.join(body_rows)}</tbody></table></div>")
    else:
        where = f" for connection {escape(connection_id)}" if connection_id else ""
        table = f'<p class="dim">No work orders{where}.</p>'
    count = f"{len(rows)} work order{'s' if len(rows) != 1 else ''}"
    scope = f" on connection {escape(connection_id)}" if connection_id else ""
    api = "/v4/work-orders" + (f"?{urlencode({'connection_id': connection_id})}" if connection_id else "")
    return _page(
        "Aquaflux work order management",
        f"{count}{scope}, newest first. Every work order this system holds, with the key it was "
        "created under and who asked for it.",
        _filter("connection_id", "Connection", connection_id, refresh)
        + (f'<a href="?{urlencode({"refresh": refresh}) if refresh else ""}">all connections</a>' if connection_id else ""),
        f"<h2>Work orders</h2>{table}", api, refresh, {"connection_id": connection_id})


# ---------------------------------------------------------- customer information system


_NO_NOTES = '<span class="dim">no notes</span>'


def dunning_cases(cases: list[dict], fixture: str, case_id: str | None, refresh: int | None) -> str:
    rows = [c for c in cases if not case_id or c["case_id"] == case_id]
    rows.sort(key=lambda c: c["case_id"])
    blocks = []
    for c in rows:
        notes = "".join(
            f'<div class="note">{_e(n.get("author"))}, {_e(n.get("created_at"))}:\n{_e(n.get("body"))}</div>'
            for n in c.get("notes", []))
        acts = [f'reminder by {_e(r["channel"])} at {_e(r["sent_at"])}, state after: {_e(r["state_after"])}'
                for r in c.get("reminders", [])]
        acts += [f'disconnection proposed at {_e(p["proposed_at"])} by {_e(p.get("proposed_by"))}: '
                 f'{_e(p["reason"])} ({_e(p["state"])})' for p in c.get("proposals", [])]
        activity = "<br>".join(acts) if acts else '<span class="dim">nothing since the seed</span>'
        blocks.append(
            "<tr>"
            f'<td class="mono">{_e(c["case_id"])}</td>'
            f"<td>{_e(c.get('customer'))}</td>"
            f'<td><span class="state">{_e(c["state"])}</span></td>'
            f'<td class="num">{_e(c.get("amount_outstanding_eur"))}</td>'
            f'<td class="num">{_e(c.get("days_overdue"))}</td>'
            f"<td>{notes or _NO_NOTES}</td>"
            f"<td>{activity}</td>"
            "</tr>")
    if blocks:
        table = ('<div class="scroll"><table><thead><tr><th>Case</th><th>Customer</th><th>State</th>'
                 "<th>Outstanding, EUR</th><th>Days overdue</th><th>Notes</th>"
                 "<th>What has happened to it</th></tr></thead>"
                 f"<tbody>{''.join(blocks)}</tbody></table></div>")
    else:
        table = f'<p class="dim">No dunning case for {escape(case_id or "")}: the connection is not in arrears, or does not exist.</p>'
    api = f"/dunning/{case_id}" if case_id else "/dunning/4471"
    return _page(
        "Aquaflux customer information system",
        f"Open dunning cases, {len(rows)} shown. Case 4471 carries the note loaded as "
        f"<code>{escape(fixture)}</code>. A note is shown as the text it is, never as markup.",
        _filter("case", "Case", case_id, refresh)
        + (f'<a href="?{urlencode({"refresh": refresh}) if refresh else ""}">all cases</a>' if case_id else ""),
        f"<h2>Dunning cases</h2>{table}", api, refresh, {"case": case_id})


# ------------------------------------------------------------------ meter data management


def readings(connection_id: str, customer: dict | None, rows: list[dict] | None, refresh: int | None) -> str:
    if rows is None:
        body = f'<p class="dim">No such connection: {escape(connection_id)}.</p>'
    else:
        top = max((r["volume_m3"] for r in rows), default=0) or 1
        lines = "".join(
            "<tr>"
            f"<td>{_e(r['period'])}</td>"
            f'<td class="num">{_e(r["volume_m3"])}</td>'
            f'<td style="width:50%"><div class="bar" style="width:{round(100 * r["volume_m3"] / top)}%"></div></td>'
            f"<td>{_e(r['source'])}</td>"
            f"<td>{'yes' if r.get('validated') else 'no'}</td>"
            "</tr>" for r in rows)
        who = ""
        if customer:
            who = (f'<p>Meter <span class="mono">{_e(customer.get("meter_serial"))}</span>, '
                   f'{_e(customer.get("meter_type"))}, tariff {_e(customer.get("tariff"))}.</p>')
        body = (f"<h2>Monthly consumption, connection {escape(connection_id)}</h2>{who}"
                '<div class="scroll"><table><thead><tr><th>Period</th><th>Volume, m³</th><th></th>'
                "<th>Source</th><th>Validated</th></tr></thead>"
                f"<tbody>{lines}</tbody></table></div>")
    return _page(
        "Aquaflux meter data management",
        "Monthly consumption for one connection, the figures the reading tools return.",
        _filter("connection_id", "Connection", connection_id, refresh),
        body, f"/readings?{urlencode({'connection_id': connection_id})}", refresh,
        {"connection_id": connection_id})
