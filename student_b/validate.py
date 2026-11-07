"""Fresh simulator benchmark and joint prediction regions for the posed case."""
import argparse
from pathlib import Path
import time

import numpy as np
from scipy.stats import gaussian_kde

from experiment import dump, torch_parts
from inference import posterior
from physics import CASE, Config, quadratic_baseline, sample_prior, simulate


def sample_metrics(draws, truth):
    n = len(draws)//2
    return dict(error=float(np.linalg.norm(draws.mean(0)-truth)),
        energy=float(np.linalg.norm(draws-truth,axis=1).mean()
        - .5*np.linalg.norm(draws[:n]-draws[n:2*n],axis=1).mean()))


def benchmark(output, checkpoint, size, n, seed):
    torch, MDN = torch_parts()
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    ck = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model = MDN(ck["k"])
    model.load_state_dict(ck["state"])
    model.eval()
    xm, xs, ym, ys = [np.asarray(ck[key]) for key in ("xm", "xs", "ym", "ys")]
    rng = np.random.default_rng(seed)
    sigma = .005
    records = []
    for label, truth_cfg in [("nominal", Config()), ("crosswind", Config(wind_y=3))]:
        simulated = simulate(sample_prior(max(200, size*4), rng), truth_cfg)
        eligible = np.flatnonzero((simulated["status"]==1) &
            np.isfinite(simulated["observations"]).all(axis=(1,2)))
        selected = rng.choice(eligible, size, replace=False)
        for index in selected:
            truth = simulated["endpoint"][index]
            obs = simulated["observations"][index] + rng.normal(0,sigma,(2,3))
            x = (np.r_[obs.ravel(),sigma]-xm)/xs
            start = time.perf_counter()
            with torch.no_grad():
                dist = model(torch.tensor(x[None],dtype=torch.float32))
                point = dist.mean.numpy()[0]*ys+ym
                elapsed = time.perf_counter()-start
                draws = dist.sample((4096,))[:,0].numpy()*ys+ym
            mdn = sample_metrics(draws, truth)
            mdn.update(error=float(np.linalg.norm(point-truth)), seconds=elapsed)
            start = time.perf_counter()
            draw_seed = int(rng.integers(2**31))
            base = quadratic_baseline(obs)["endpoint"]
            row = dict(scenario=label, sigma_m=sigma, observation=obs.tolist(),
                truth=truth.tolist(), mdn=mdn, baseline_error=float(np.linalg.norm(base-truth)))
            try:
                physics = posterior(n=n,sigma=sigma,seed=draw_seed,observations=obs)
                if physics["conditional_ess"] < 100:
                    physics = posterior(n=3*n,sigma=sigma,seed=draw_seed+1,observations=obs)
                elapsed = time.perf_counter()-start
                samples = physics["endpoints"][rng.choice(len(physics["weights"]),4096,p=physics["weights"])]
                row["physics"] = sample_metrics(samples, truth)
                row["physics"].update(error=float(np.linalg.norm(physics["conditional_mean"]-truth)),
                    ess=physics["conditional_ess"],seconds=elapsed)
            except RuntimeError as error:
                row["physics_error"] = str(error)
            records.append(row)
            dump(output/"benchmark_rows.json", records)
            print(label,len(records),round(mdn["error"],3),row.get("physics"),flush=True)
    summaries = {}
    for label in ("nominal", "crosswind"):
        group = [row for row in records if row["scenario"] == label]
        paired = [row for row in group if row.get("physics",{}).get("ess",0) >= 100]
        result = dict(total=len(group), paired=len(paired))
        for method in ("mdn","physics"):
            result[method] = {f"median_{key}":float(np.median([row[method][key] for row in paired]))
                for key in ("error","energy","seconds")} if paired else {}
        result["baseline_median_error"] = float(np.nanmedian([row["baseline_error"] for row in paired])) if paired else None
        summaries[label] = result
    dump(output/"benchmark.json",dict(seed=seed, physics_samples_per_stage=n, scenarios=summaries))


def case_regions(output, n, seed):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rng = np.random.default_rng(seed)
    fig, axes = plt.subplots(1,3,figsize=(12,4),layout="constrained")
    reports = []
    for ax, sigma in zip(axes,(.002,.005,.015)):
        result = posterior(n=n,sigma=sigma,seed=seed,observations=CASE)
        points, weights = result["endpoints"], result["weights"]
        keep = weights > weights.max()*1e-10
        kde = gaussian_kde(points[keep].T, weights=weights[keep])
        draws = kde.resample(6000,seed=rng)
        lo, hi = np.quantile(draws,[.0005,.9995],axis=1)
        lo -= .2*(hi-lo)
        hi += .2*(hi-lo)
        y, z = np.meshgrid(np.linspace(lo[0],hi[0],160),np.linspace(lo[1],hi[1],160))
        cell = (hi[0]-lo[0])*(hi[1]-lo[1])/159**2
        grid = np.stack((y.ravel(),z.ravel()))
        density = kde(grid)
        order = np.argsort(density)[::-1]
        masses = np.cumsum(density[order])*cell
        thresholds = [float(density[order[min(np.searchsorted(masses,p),len(order)-1)]]) for p in (.5,.95)]
        mode = grid[:,order[0]]
        reports.append(dict(sigma_m=sigma, mode_yz_m=mode.tolist(), mean_yz_m=result["conditional_mean"],
            ess=result["conditional_ess"], airborne_probability=result["airborne_probability"],
            grid_mass=float(masses[-1]), hdr_area_m2=[float(np.sum(density>=q)*cell) for q in thresholds]))
        ax.pcolormesh(y,z,density.reshape(y.shape),shading="auto")
        contours = ax.contour(y,z,density.reshape(y.shape),levels=thresholds[::-1],colors=["cyan","white"])
        ax.clabel(contours,fmt=dict(zip(thresholds[::-1],["95%","50%"])))
        ax.plot(*mode, "r+")
        ax.set(xlabel="Y (m)", ylabel="Z (m)", title=f"Position SD = {sigma*1000:g} mm")
        print(reports[-1],flush=True)
    fig.savefig(output/"case_regions.png",dpi=180)
    plt.close(fig)
    dump(output/"case_regions.json",dict(regions=reports, seed=seed, samples_per_stage=n,
        note="Weighted KDE and grid HDRs, conditional on airborne crossing. Area order is 50%, 95%."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task",choices=["benchmark","case"])
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--checkpoint",type=Path,default=Path("student_b/runs/literature50k/mdn.pt"))
    parser.add_argument("--size",type=int,default=12)
    parser.add_argument("--n",type=int,default=8000)
    parser.add_argument("--seed",type=int,default=8047)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if args.task == "benchmark":
        benchmark(args.output,args.checkpoint,args.size,args.n,args.seed)
    else:
        case_regions(args.output,args.n,args.seed)
