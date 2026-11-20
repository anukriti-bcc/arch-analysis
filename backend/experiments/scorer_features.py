"""Per-finding evidence features for the scored-escalation study (`experiments/scorer_study.py`).

  python -m experiments.scorer_features <benchmark_root> <tag> <out_csv>
"""
import sys, json, re
import pandas as pd
from datetime import datetime
from experiments import pipeline
from analysis.intent.readability import assess, governing_adr, scope_of, _STRONG_PERMIT, GATES
from analysis.intent.reader import introduction_date, decision_section, sentences
def main(root, tag, out):
    man=json.load(open(root+"/manifest.json")); rows=[]
    for e in man["cases"]:
        ctx=pipeline.CaseContext(root,e)
        for f in ctx.violations:
            b=ctx.bundle(f); ev=b.evolution or {}; sig=ev.get("message_signals",{}) if ev.get("available") else {}
            scopes=[scope_of(m,b.source_path,b.target_path) for m in b.adrs if m.adr.is_active]
            gov,oth=governing_adr(b.adrs,b.source_path,b.target_path)
            intro=introduction_date(b.evolution)
            r=dict(tag=tag,case=e["case_id"],scenario=e["scenario"][0],truth=ctx.truth[ctx.edge(f)],
              n_inactive=sum(not m.adr.is_active for m in b.adrs),n_active=len(scopes),
              s_strong=scopes.count("strong"),s_desc=scopes.count("described"),s_weak=scopes.count("weak"),
              temp=int(bool(sig.get("temporary_language"))),migr=int(bool(sig.get("migration_language"))),
              adr_ref=int(bool(sig.get("adr_references"))),reintro=int(bool(ev.get("reintroduced"))),
              born=int(bool(ev.get("introduced_with_file_creation"))),age=ev.get("age_days") or 0,
              since=ev.get("commits_since_introduction") or 0,code_temp=int(bool(re.search(r"todo|temporary|hack|remove later|fixme",b.code_snippet or "",re.I))))
            if gov:
                a=assess(gov.adr,introduced=intro,source_path=b.source_path,target_path=b.target_path,other_strong_active=oth)
                sec=sentences(decision_section(gov.adr.text)[0])
                r.update(stance={"permits":1,"prohibits":-1}.get(a.reading.stance,0),permit_cue=int(any(_STRONG_PERMIT.search(x) for x in sec)),
                  adr_gap=((gov.adr.date-intro).days if gov.adr.date and intro else 0),nfail=len(a.failed),**{g:int(g in a.failed) for g in GATES})
            else:
                r.update(stance=0,permit_cue=0,adr_gap=0,nfail=0,**{g:0 for g in GATES})
            r["old_candidate"]=int(any(m.adr.is_active for m in b.adrs) or bool(sig.get("temporary_language") or sig.get("migration_language") or ev.get("reintroduced")))
            rows.append(r)
    pd.DataFrame(rows).to_csv(out,index=False); print(tag,len(rows),flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:4])
