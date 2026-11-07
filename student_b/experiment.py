"""CLI: generate, train, evaluate, case, smoke. Run --help for arguments."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from dataclasses import asdict
from physics import Config, sample_prior, simulate, quadratic_baseline, CASE, LOW, HIGH, NOMINAL_CD


def dump(path, obj):
    def clean(x):
        if isinstance(x,dict): return {k:clean(v) for k,v in x.items()}
        if isinstance(x,list): return [clean(v) for v in x]
        if isinstance(x,float) and not np.isfinite(x): return None
        return x
    Path(path).write_text(json.dumps(clean(obj),indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')


def generate(out,n,seed):
    rng=np.random.default_rng(seed); cfg=Config(); pieces=[]
    for start in range(0,n,2000):
        theta=sample_prior(min(2000,n-start),rng)
        sim=simulate(theta,cfg)
        pieces.append((theta,sim))
        print(f'generated {start+len(theta)}/{n}',flush=True)
    theta=np.concatenate([p[0] for p in pieces])
    sim={k:np.concatenate([p[1][k] for p in pieces]) for k in pieces[0][1]}
    # Split IDs before adding observation noise.
    perm=rng.permutation(n); split=np.empty(n,dtype=np.int8)
    split[perm[:int(.8*n)]]=0; split[perm[int(.8*n):int(.9*n)]]=1; split[perm[int(.9*n):]]=2
    np.savez_compressed(out/'data.npz',theta=theta,split=split,**sim)
    dump(out/'data_manifest.json',dict(n=n,seed=seed,config=asdict(cfg),
        prior_low=LOW.tolist(),prior_high=HIGH.tolist(),
        status_counts={str(k):int((sim['status']==k).sum()) for k in [0,1,2]},
        lift_law='CL=min(1.4*R*omega_transverse/U, 0.30)',
        nominal_cd=NOMINAL_CD,
        disclaimer='Literature-informed sensitivity prior; no real-trajectory calibration or validation. '
                   'MDN is conditional on airborne crossing, not all kicks.'))


def torch_parts():
    import torch
    from torch import nn
    class MDN(nn.Module):
        def __init__(self,k=3):
            super().__init__(); self.k=k
            # Six coordinates plus known noise sigma. No privileged latent inputs.
            self.net=nn.Sequential(nn.Linear(7,64),nn.SiLU(),nn.Linear(64,64),nn.SiLU(),nn.Linear(64,6*k))
        def forward(self,x):
            raw=self.net(x).reshape(-1,self.k,6)
            logits=raw[:,:,0]; mu=raw[:,:,1:3]
            scale=torch.nn.functional.softplus(raw[:,:,3:5])+1e-3
            corr=.995*torch.tanh(raw[:,:,5])
            L=torch.zeros((*mu.shape,2),device=x.device)
            L[:,:,0,0]=scale[:,:,0]
            L[:,:,1,0]=corr*scale[:,:,1]
            L[:,:,1,1]=scale[:,:,1]*torch.sqrt(1-corr**2)
            components=torch.distributions.MultivariateNormal(mu,scale_tril=L)
            return torch.distributions.MixtureSameFamily(torch.distributions.Categorical(logits=logits),components)
    return torch,MDN


def train(out,epochs,k,seed):
    torch,MDN=torch_parts(); torch.manual_seed(seed); torch.set_num_threads(4)
    rng=np.random.default_rng(seed); d=np.load(out/'data.npz')
    valid=(d['status']==1)&np.isfinite(d['observations']).all(axis=(1,2))
    tr=valid&(d['split']==0); va=valid&(d['split']==1)
    if min(tr.sum(),va.sum())<10: raise ValueError('Too few valid training/validation flights')
    trainx=d['observations'][tr].reshape(-1,6); trainy=d['endpoint'][tr]
    # Fixed validation noise; fresh training noise each epoch.
    levels=np.array([.002,.005,.015])
    vs=rng.choice(levels,va.sum()); vx=d['observations'][va].reshape(-1,6)+rng.normal(size=(va.sum(),6))*vs[:,None]
    vx=np.column_stack([vx,vs]); vy=d['endpoint'][va]
    xm=np.r_[trainx.mean(0),levels.mean()]; xs=np.r_[trainx.std(0),levels.std()]; xs=np.maximum(xs,1e-6)
    ym=trainy.mean(0); ys=np.maximum(trainy.std(0),1e-6)
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=MDN(k).to(device); opt=torch.optim.Adam(model.parameters(),lr=.001)
    def tensor(x): return torch.as_tensor(x,dtype=torch.float32,device=device)
    valx=tensor((vx-xm)/xs); valy=tensor((vy-ym)/ys)
    best=float('inf'); stale=0; history=[]; start=time.perf_counter()
    for epoch in range(epochs):
        sig=rng.choice(levels,len(trainx)); noisy=trainx+rng.normal(size=trainx.shape)*sig[:,None]
        x=tensor((np.column_stack([noisy,sig])-xm)/xs); y=tensor((trainy-ym)/ys)
        order=torch.randperm(len(x),device=device); model.train(); total=0.
        for ids in order.split(256):
            opt.zero_grad(); loss=-model(x[ids]).log_prob(y[ids]).mean()
            if not torch.isfinite(loss): raise RuntimeError('Nonfinite loss')
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),10); opt.step()
            total+=float(loss.detach())*len(ids)
        model.eval()
        with torch.no_grad(): val=float(-model(valx).log_prob(valy).mean())
        history.append(dict(epoch=epoch,train_nll=total/len(x),val_nll_standardized=val))
        if val<best:
            best=val;stale=0
            torch.save(dict(state=model.state_dict(),k=k,xm=xm.tolist(),xs=xs.tolist(),ym=ym.tolist(),ys=ys.tolist(),seed=seed),out/'mdn.pt')
        else: stale+=1
        dump(out/'training.json',dict(device=device,seconds=time.perf_counter()-start,history=history))
        print(f'epoch {epoch+1}: val NLL {val:.4f}',flush=True)
        if stale>=12: break


def evaluate(out,seed):
    torch,MDN=torch_parts(); torch.manual_seed(seed); torch.set_num_threads(4)
    ck=torch.load(out/'mdn.pt',map_location='cpu',weights_only=True)
    model=MDN(ck['k']); model.load_state_dict(ck['state']); model.eval()
    xm,xs,ym,ys=[np.array(ck[k]) for k in ['xm','xs','ym','ys']]
    d=np.load(out/'data.npz'); keep=(d['split']==2)&(d['status']==1)&np.isfinite(d['observations']).all(axis=(1,2))
    clean=d['observations'][keep].reshape(-1,6); y=d['endpoint'][keep]
    rng=np.random.default_rng(seed); reports=[]
    for sigma in [.002,.005,.015]:
        noisy=clean+rng.normal(size=clean.shape)*sigma
        x=np.column_stack([noisy,np.full(len(y),sigma)])
        errors=[];baseline=[];coverage={.5:[],.95:[]}; areas={.5:[],.95:[]}; nll=[]
        start=time.perf_counter()
        with torch.no_grad():
            for j in range(0,len(x),128):
                xx=torch.tensor((x[j:j+128]-xm)/xs,dtype=torch.float32)
                yy=torch.tensor((y[j:j+128]-ym)/ys,dtype=torch.float32)
                dist=model(xx); pred=dist.mean.numpy()*ys+ym
                errors.extend(np.linalg.norm(pred-y[j:j+128],axis=1).tolist())
                truthlp=dist.log_prob(yy); nll.extend((-truthlp+np.log(ys).sum()).tolist())
                samples=dist.sample((512,)); samplelp=dist.log_prob(samples)
                area_samples=dist.sample((1024,)); area_lp=dist.log_prob(area_samples)
                for alpha in coverage:
                    threshold=torch.quantile(samplelp,1-alpha,dim=0)
                    coverage[alpha].extend((truthlp>=threshold).tolist())
                    area=(torch.where(area_lp>=threshold,torch.exp(-area_lp),0.).mean(0)*np.prod(ys))
                    areas[alpha].extend(area.tolist())
        for obs in noisy.reshape(-1,2,3):
            baseline.append(quadratic_baseline(obs)['endpoint'])
        be=np.linalg.norm(np.array(baseline)-y,axis=1); good=np.isfinite(be)
        reports.append(dict(sigma=sigma,n=len(y),mean_prediction_median_error=float(np.median(errors)),
            mean_prediction_p90_error=float(np.quantile(errors,.9)),nll=float(np.mean(nll)),
            coverage={str(a):dict(value=float(np.mean(v)),standard_error=float(np.sqrt(np.mean(v)*(1-np.mean(v))/len(v)))) for a,v in coverage.items()},
            baseline_median_error=float(np.median(be[good])),baseline_invalid=int((~good).sum()),
            mdn_median_error_on_baseline_valid=float(np.median(np.array(errors)[good])),
            mean_HDR_area_m2={str(a):float(np.mean(v)) for a,v in areas.items()},
            evaluation_seconds=time.perf_counter()-start))
    dump(out/'evaluation.json',dict(reports=reports,notes='Synthetic development holdout only; not final publication test. Point metric uses posterior mean, not mode. HDR threshold uses 512 samples; area uses 1024 independent importance samples. Area and coverage have Monte Carlo error.'))
    # Case distribution includes off-target probability; never normalize to goal rectangle.
    sigma=.005; x=np.r_[CASE.ravel(),sigma]
    with torch.no_grad():
        dist=model(torch.tensor(((x-xm)/xs)[None,:],dtype=torch.float32))
        samples=dist.sample((20000,))[:,0,:].numpy()*ys+ym
        lo=np.quantile(samples,.0005,axis=0)-.2; hi=np.quantile(samples,.9995,axis=0)+.2
        yy,zz=np.meshgrid(np.linspace(lo[0],hi[0],240),np.linspace(lo[1],hi[1],240))
        grid=np.column_stack([yy.ravel(),zz.ravel()])
        dens=dist.log_prob(torch.tensor((grid-ym)/ys,dtype=torch.float32)).exp().numpy()/np.prod(ys)
        cell=(hi[0]-lo[0])*(hi[1]-lo[1])/239**2
        sorted_density=np.sort(dens)[::-1]; thresholds=[]
        for alpha in [.5,.95]:
            ix=np.searchsorted(np.cumsum(sorted_density)*cell,alpha)
            thresholds.append(float(sorted_density[min(ix,len(dens)-1)]))
        mode=grid[np.argmax(dens)]
        goal=(abs(samples[:,0])<3.66)&(samples[:,1]>0)&(samples[:,1]<2.44)
        dump(out/'case_mdn.json',dict(sigma=sigma,approximate_grid_mode=mode.tolist(),
            mean=samples.mean(0).tolist(),grid_probability_mass=float(dens.sum()*cell),
            center_in_rectangle_probability_conditional_airborne=float(goal.mean()),
            note='Development model only. Rectangle probability is not a physical goal/collision probability.'))
    np.save(out/'case_mdn_samples.npy',samples)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(7,5));ax.pcolormesh(yy,zz,dens.reshape(yy.shape),cmap='viridis',shading='auto')
    ax.contour(yy,zz,dens.reshape(yy.shape),levels=sorted(set(thresholds)),colors=['cyan','white'])
    ax.plot(*mode,'r+',label='approx. density mode')
    from matplotlib.patches import Rectangle
    ax.add_patch(Rectangle((-3.66,0),7.32,2.44,fill=False,color='red',lw=1.5))
    base=quadratic_baseline(CASE)['endpoint'];ax.plot(*base,'wx',label='constant acceleration')
    ax.set(xlabel='Y (m)',ylabel='Z (m)',title='Development MDN: sigma=5 mm; airborne-conditional')
    ax.legend();fig.tight_layout();fig.savefig(out/'case_mdn.png',dpi=160);plt.close(fig)


def case(out,n,seed,sigma=.005,cd=None):
    from inference import posterior
    start=time.perf_counter(); r=posterior(n=n,seed=seed,sigma=sigma,cfg=Config(fixed_cd=cd))
    np.savez_compressed(out/'case_posterior.npz',**{k:r.pop(k) for k in ['endpoints','weights','theta','parameter_weights']})
    r.update(seconds=time.perf_counter()-start,sigma=sigma,fixed_cd=cd,seed=seed,
        samples_per_stage=n,baseline=quadratic_baseline(CASE))
    dump(out/'case_posterior.json',r);print(json.dumps(r,indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['generate','train','evaluate','case','smoke'])
    p.add_argument('--out',default='runs/dev');p.add_argument('--n',type=int,default=10000)
    p.add_argument('--epochs',type=int,default=60);p.add_argument('--k',type=int,default=3);p.add_argument('--seed',type=int,default=42)
    p.add_argument('--cd',type=float,help='Fix drag coefficient for case inference')
    p.add_argument('--sigma',type=float,default=.005,help='Case position noise SD in meters')
    a=p.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    if a.command in ['generate','smoke']:generate(out,a.n,a.seed)
    if a.command in ['train','smoke']:train(out,a.epochs,a.k,a.seed)
    if a.command in ['evaluate','smoke']:evaluate(out,a.seed+1)
    if a.command=='case':case(out,a.n,a.seed,a.sigma,a.cd)
