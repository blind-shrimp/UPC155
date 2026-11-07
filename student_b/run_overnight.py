"""Checkpointed sequential runner. Does NOT alter Windows sleep/power settings."""
import argparse,subprocess,sys,json,time
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--n',type=int,default=50000)
p.add_argument('--epochs',type=int,default=150);p.add_argument('--out',default='runs/overnight')
a=p.parse_args();out=Path(a.out).resolve();out.mkdir(parents=True,exist_ok=True)
script=Path(__file__).with_name('experiment.py'); manifest=out/'pipeline.json'
plan=[('generate',['--n',str(a.n)]),('train',['--epochs',str(a.epochs)]),('evaluate',[]),('case',['--n','30000'])]
state=json.loads(manifest.read_text()) if manifest.exists() else dict(n=a.n,epochs=a.epochs,steps={})
if state['n']!=a.n or state['epochs']!=a.epochs: raise SystemExit('Existing run has different settings; choose a new output folder.')
for name,extra in plan:
    if state['steps'].get(name,{}).get('success'):continue
    start=time.time();cmd=[sys.executable,str(script),name,'--out',str(out)]+extra
    with (out/f'{name}.log').open('a',encoding='utf-8') as log:
        result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    state['steps'][name]=dict(success=result.returncode==0,returncode=result.returncode,seconds=time.time()-start)
    manifest.write_text(json.dumps(state,indent=2),encoding='utf-8')
    print(name,state['steps'][name],flush=True)
    if result.returncode:raise SystemExit(result.returncode)
