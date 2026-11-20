"""Is a metadata score enough to decide WHICH findings need the model? (the "scored top-k escalation" proposal)

Train/evaluate scorers for "the static flag is a false positive" with leave-one-scenario-out validation, so a scorer
that merely decodes the benchmark generator is exposed. Needs feature CSVs from `scorer_features`.

  python -m experiments.scorer_study <dir with feat_<tag>.csv>
"""
import sys, warnings
import pandas as pd, numpy as np
warnings.filterwarnings("ignore")
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
D=sys.argv[1] if len(sys.argv)>1 else "."
df=pd.concat([pd.read_csv(f"{D}/feat_{t}.csv") for t in ["h11","h12","h13","h21","h22","p7","ho7"]])
df["y"]=(df.truth=="justified").astype(int); df["scen"]=df.scenario
print("all violations",len(df),"justified",df.y.sum(),"| old-policy candidates",df.old_candidate.sum(),"justified among them",df[df.old_candidate==1].y.sum())
F=["n_inactive","n_active","s_strong","s_desc","s_weak","temp","migr","adr_ref","reintro","born","age","since","code_temp","stance","permit_cue","adr_gap","nfail"]
def hand(d):  # fixed a priori from the proposal's feature list, not fitted
    return (2*(d.s_strong>0)+1*(d.s_desc>0)+0.5*(d.s_weak>0)+1*d.temp+1*d.migr+1*d.reintro+1*d.adr_ref+0.5*d.code_temp+0.5*(d.age>180)-0.5*d.born)
def auccurve(score,y,rng=None):
    o=np.argsort(-score,kind="stable") if rng is None else rng.permutation(len(y))  # ties: stable (input order); random uses permutation
    c=np.cumsum(y.values[o])/max(y.sum(),1); return c.mean()
def report(name,d,score):
    d=d.copy(); d["s"]=score
    c=d[d.old_candidate==1]
    auc=roc_auc_score(c.y,c.s) if c.y.nunique()>1 else float("nan")
    rnd=np.mean([auccurve(c.s,c.y,np.random.default_rng(i)) for i in range(200)])
    # tie-robust: average over random tie-breaks
    tb=np.mean([auccurve(pd.Series(c.s.values+np.random.default_rng(i).uniform(0,1e-6,len(c))),c.y) for i in range(200)])
    orc=auccurve(c.y.astype(float),c.y)
    print(f"{name:34s} n={len(c):3d} pos={c.y.sum():3d}  AUC={auc:.3f}  capture-AUC={tb:.3f} (random {rnd:.3f}, oracle {orc:.3f})")
dev=df[df.tag.isin(["h21","h22","p7"])]; test=df[df.tag.isin(["h11","h12","h13","ho7"])]
print("\n-- hand-weighted score (fixed a priori)"); report("dev",dev,hand(dev)); report("test hard s11-13",test[test.tag.str.startswith("h")],hand(test[test.tag.str.startswith("h")])); report("test heldout",test[test.tag=="ho7"],hand(test[test.tag=="ho7"]))
sc=StandardScaler().fit(dev[F]); lr=LogisticRegression(C=0.3,max_iter=2000).fit(sc.transform(dev[F]),dev.y)
print("\n-- logistic regression trained on dev (s21,s22,primary), candidates only? trained on ALL violations")
for nm,d in [("test hard s11-13",test[test.tag.str.startswith("h")]),("test heldout",test[test.tag=="ho7"])]:
    report(nm,d,lr.predict_proba(sc.transform(d[F]))[:,1])
print("\n-- leave-one-scenario-out (train on all other scenarios, all seeds), score the held-out scenario")
res=[]
for s in sorted(df.scen.unique()):
    tr,te=df[df.scen!=s],df[df.scen==s]
    if te.y.sum()==0 or te.old_candidate.sum()==0: continue
    sc2=StandardScaler().fit(tr[F]); m=LogisticRegression(C=0.3,max_iter=2000).fit(sc2.transform(tr[F]),tr.y)
    c=te[te.old_candidate==1]; p=m.predict_proba(sc2.transform(c[F]))[:,1]
    res.append((s,len(c),int(c.y.sum()),roc_auc_score(c.y,p) if c.y.nunique()>1 else np.nan, roc_auc_score(c.y,hand(c)) if c.y.nunique()>1 else np.nan))
print(pd.DataFrame(res,columns=["held-out scenario","cands","justified","LR AUC","hand AUC"]).round(2).to_string(index=False))
print("\n-- what separates justified from violation inside the candidate set? (means)")
c=df[df.old_candidate==1]; print(c.groupby("y")[["s_strong","s_desc","temp","migr","reintro","born","age","permit_cue","nfail","stance"]].mean().round(2).to_string())

print("\n== POOLED leave-one-scenario-out (every candidate scored by a model that never saw its scenario)")
from sklearn.ensemble import GradientBoostingClassifier
def loso(make,feats):
    out=pd.Series(index=df.index,dtype=float); out=pd.Series(np.nan,index=range(len(df))); d=df.reset_index(drop=True)
    for s in d.scen.unique():
        tr,te=d[d.scen!=s],d[d.scen==s]
        sc2=StandardScaler().fit(tr[feats]); m=make().fit(sc2.transform(tr[feats]),tr.y)
        out[te.index]=m.predict_proba(sc2.transform(te[feats]))[:,1]
    return d,out
def calls_to_capture(score,y,target):
    o=np.argsort(-(score+np.random.default_rng(0).uniform(0,1e-6,len(score))))
    cum=np.cumsum(y[o]); return int(np.argmax(cum>=target*y.sum()))+1
def summarize(name,d,p):
    c=d.old_candidate.values==1; y=d.y.values[c]; s=np.asarray(p)[c]
    n=c.sum(); P=y.sum()
    cap=lambda t:calls_to_capture(s,y,t)
    print(f"{name:30s} cands={n} justified={P} AUC={roc_auc_score(y,s):.3f}  calls to capture 90%/95%/100%: {cap(.9)}/{cap(.95)}/{cap(1.0)}")
d,p=loso(lambda:LogisticRegression(C=0.3,max_iter=2000),F); summarize("LR, all features",d,p)
d,p=loso(lambda:GradientBoostingClassifier(n_estimators=60,max_depth=2,random_state=0),F); summarize("GBM depth2, all features",d,p)
F2=[f for f in F if f not in ("nfail","stance","permit_cue","adr_gap")]
d,p=loso(lambda:LogisticRegression(C=0.3,max_iter=2000),F2); summarize("LR, metadata only (no text)",d,p)
d,p=loso(lambda:LogisticRegression(C=0.3,max_iter=2000),["nfail","stance","permit_cue","adr_gap"]); summarize("LR, text-reading features only",d,p)
summarize("hand-weighted",d,hand(d).values)
c=d.old_candidate.values==1; y=d.y.values[c]
print(f"{'oracle':30s} calls to capture 100%: {int(y.sum())};  random expectation for 95%: ~{int(0.95*len(y))}")
