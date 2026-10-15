#!/usr/bin/env python3
"""Generate a design-panel winner the same way daily_experiment.py generates its own pick, and log it
to the same ledger so Cole's rating feeds the same learning loop. Usage: run_panel_winner.py <winner.json>"""
import datetime as dt, json, sys
import requests
import daily_experiment as d

exp = json.load(open(sys.argv[1]))
d.load_env()
for attempt in (1, 2):
    jid, status = d.generate(exp["prompt"])
    secs = d.generated_seconds(jid)
    d.log(f"attempt {attempt}: job {jid} {status}, {secs:.0f} s")
    if status == "complete" and secs >= 480:
        break
requests.post(f"{d.BASE}/api/job/{jid}/meta", json={"title": f"Daily · {exp['title']}", "world": exp["world"]}, timeout=30)
rec = {"date": dt.date.today().isoformat(), "job_id": jid, "world": exp["world"], "title": exp["title"],
       "testing": exp["testing"], "mode": exp["mode"], "parent_job_id": exp.get("parent_job_id", ""),
       "prompt": exp["prompt"], "seconds": round(secs), "source": "design-panel"}
with d.LEDGER.open("a") as fh:
    fh.write(json.dumps(rec) + "\n")
d.write_report(d.ledger())
print(json.dumps({"job_id": jid, "seconds": round(secs), "title": f"{exp['world']} · Daily · {exp['title']}"}))
