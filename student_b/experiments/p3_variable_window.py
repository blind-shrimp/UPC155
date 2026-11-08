"""Train a timing-aware conditional goal-plane MDN and evaluate DFL penalties."""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

SB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SB))
from common import build_mdn, standardize_fit
from physics import sample_prior, simulate
from validate_real_penalties import CASES, coordinates, read_csv, save_json


WINDOWS = (.04, .05)
SIGMAS = (.015, .030)


def generate(count, seed, step):
    rng = np.random.default_rng(seed)
    blocks = []
    for start in range(0, count, 2000):
        n = min(count-start, 2000)
        theta = sample_prior(n, rng)
        height = rng.uniform(.11, .35, n)
        goal = rng.uniform(9., 11.5, n)
        result = simulate(theta, observation_times=(step, 2*step), initial_z=height, goal_x=goal)
        keep = (result['status'] == 1) & np.isfinite(result['observations']).all(axis=(1, 2))
        origin = np.column_stack((np.zeros(n), np.zeros(n), height))
        points = np.concatenate((origin[:, None], result['observations']), axis=1)
        blocks.append((points[keep], result['endpoint'][keep], goal[keep], np.full(keep.sum(), step)))
    return tuple(np.concatenate(columns) for columns in zip(*blocks))


def features(points, goal, step, sigma):
    delta = points[:, 2]-points[:, 0]
    velocity = delta/(2*step[:, None])
    curvature = (delta-2*(points[:, 1]-points[:, 0]))/step[:, None]**2
    return np.column_stack((velocity, curvature, points[:, 0, 2],
                            goal-points[:, 0, 0], step, sigma))


def noisy_batch(part, rng, sigma, indices=slice(None)):
    points, endpoint, goal, step = (x[indices] for x in part)
    noisy = points+rng.normal(size=points.shape)*sigma[:, None, None]
    target = endpoint.copy()
    target[:, 0] -= noisy[:, 0, 1]
    return features(noisy, goal, step, sigma), target


def inputs(x, stats):
    return torch.as_tensor((x-stats['xm'])/stats['xs'], dtype=torch.float32)


def targets(y, stats):
    return torch.as_tensor((y-stats['ym'])/stats['ys'], dtype=torch.float32)


def fit(train, validation, seed, epochs):
    rng = np.random.default_rng(seed)
    torch.manual_seed(seed)
    n = len(train[0])
    reference = rng.choice(n, 5000, replace=False)
    x, y = noisy_batch(train, rng, rng.uniform(.003, .035, len(reference)), reference)
    stats = standardize_fit(x, y)
    xv, yv = noisy_batch(validation, rng, rng.uniform(.003, .035, len(validation[0])))
    xv, yv = inputs(xv, stats), targets(yv, stats)
    model = build_mdn(x.shape[1])
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, epochs)
    best = (float('inf'), None, None)
    for epoch in range(1, epochs+1):
        model.train()
        for indices in np.array_split(rng.permutation(n), (n+255)//256):
            x, y = noisy_batch(train, rng, rng.uniform(.003, .035, len(indices)), indices)
            optimizer.zero_grad()
            loss = -model(inputs(x, stats)).log_prob(targets(y, stats)).mean()
            if not torch.isfinite(loss):
                raise RuntimeError('Nonfinite training loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.)
            optimizer.step()
        scheduler.step()
        model.eval()
        with torch.no_grad():
            score = float(-model(xv).log_prob(yv).mean())
        if score < best[0]:
            best = (score, epoch, {key: val.clone() for key, val in model.state_dict().items()})
        if epoch % 15 == 0 or epoch == epochs:
            print('seed', seed, 'epoch', epoch, 'validation NLL standardized', round(score, 3), flush=True)
    model.load_state_dict(best[2])
    return model, stats, best[1]


@torch.no_grad()
def summarize(model, stats, x, y, cutoff):
    errors, log_prob, ranks = [], [], []
    for j in range(0, len(x), 256):
        sl = slice(j, j+256)
        dist = model(inputs(x[sl], stats))
        lp = dist.log_prob(targets(y[sl], stats))
        draws = dist.log_prob(dist.sample((512,)))
        rank = (draws > lp).sum(dim=0).numpy()
        mean = dist.mean.numpy()*stats['ys']+stats['ym']
        errors.extend(np.linalg.norm(mean-y[sl], axis=1))
        log_prob.extend(lp.numpy())
        ranks.extend(rank)
    ranks = np.array(ranks)
    return dict(median_error_m=float(np.median(errors)), rmse_m=float(np.sqrt(np.mean(np.square(errors)))),
                nll=float(-np.mean(log_prob)+np.log(stats['ys']).sum()),
                coverage95=float(np.mean(ranks <= cutoff))), ranks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, default=11)
    parser.add_argument('--epochs', type=int, default=75)
    parser.add_argument('--out', type=Path, default=SB/'runs/p3_variable_window')
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error('epochs must be positive')
    torch.set_num_threads(2)
    args.out.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out/f'model_{args.seed}.pt'
    if checkpoint.exists():
        saved = torch.load(checkpoint, weights_only=True)
        if saved['epochs'] != args.epochs:
            raise ValueError('Checkpoint epoch budget differs. Select another output directory.')
        stats = {key: val.numpy() for key, val in saved['stats'].items()}
        model = build_mdn(len(stats['xm']))
        model.load_state_dict(saved['state'])
        best_epoch = saved['selected_epoch']
    else:
        train_blocks = [generate(22000, 901+i, step) for i, step in enumerate(WINDOWS)]
        val_blocks = [generate(2200, 1201+i, step) for i, step in enumerate(WINDOWS)]
        train, val = [tuple(np.concatenate(columns) for columns in zip(*blocks))
                      for blocks in (train_blocks, val_blocks)]
        print('conditional training/validation rows', len(train[0]), len(val[0]), flush=True)
        model, stats, best_epoch = fit(train, val, args.seed, args.epochs)
        torch.save(dict(state=model.state_dict(), stats={k: torch.as_tensor(v) for k, v in stats.items()},
                        selected_epoch=best_epoch, epochs=args.epochs), checkpoint)
    model.eval()
    torch.manual_seed(8177)
    synthetic = []
    cutoffs = {}
    for i, step in enumerate(WINDOWS):
        calibration = generate(2300, 3301+i, step)
        test = generate(2600, 4401+i, step)
        for j, sigma in enumerate(SIGMAS):
            xc, yc = noisy_batch(calibration, np.random.default_rng(8000+j), np.full(len(calibration[0]), sigma))
            _, rank = summarize(model, stats, xc, yc, 486)
            order = int(np.ceil((len(rank)+1)*.95))-1
            cutoff = int(np.partition(rank, order)[order])
            cutoffs[step, sigma] = cutoff
            xt, yt = noisy_batch(test, np.random.default_rng(9000+j), np.full(len(test[0]), sigma))
            score, _ = summarize(model, stats, xt, yt, cutoff)
            synthetic.append(dict(step_s=step, sigma_m=sigma, count=len(yt), cutoff=cutoff, **score))
    real = []
    data = SB.parent/'student-a/flight_trajectory_validation_2026-11-07'
    config = json.loads((data/'case_config.json').read_text(encoding='utf-8-sig'))
    prefix = read_csv(data/'inputs_only.csv')
    with torch.no_grad():
        for case in CASES:
            times, points = coordinates([row for row in prefix if row['case_id'] == case])
            if not np.allclose(times, [0., .04, .08]):
                raise ValueError(f'{case}: expected 0/40/80 ms input frames')
            goal = config[case]['target_local_x_m']
            centre = config[case]['target_local_center_y_m']
            for sigma in SIGMAS:
                x = features(points[None], np.array([goal]), np.array([.04]), np.array([sigma]))
                dist = model(inputs(x, stats))
                mean = dist.mean.numpy()[0]*stats['ys']+stats['ym']
                origin_y = points[0, 1]-centre
                mean[0] += origin_y
                samples = dist.sample((4096,))
                draw_lp = dist.log_prob(samples).reshape(-1)
                mass = cutoffs[.04, sigma]/512
                threshold = float(torch.quantile(draw_lp, 1-mass))
                real.append((dict(case=case, sigma_m=sigma, prediction_yz_m=mean.tolist()),
                             dist, threshold, origin_y))
        held = read_csv(data/'held_out.csv')
        for row, dist, threshold, origin_y in real:
            case = row['case']
            _, positions = coordinates([r for r in held if r['case_id'] == case])
            goal = config[case]['target_local_x_m']
            index, = np.flatnonzero((positions[:-1, 0] < goal) & (positions[1:, 0] >= goal))
            a = (goal-positions[index, 0])/(positions[index+1, 0]-positions[index, 0])
            reference = ((1-a)*positions[index]+a*positions[index+1])[1:]
            reference[0] -= config[case]['target_local_center_y_m']
            lp = float(dist.log_prob(targets((reference-[origin_y, 0.])[None], stats))[0])
            offset = np.asarray(row['prediction_yz_m'])-reference
            row.update(reference_yz_m=reference.tolist(), offset_yz_m=offset.tolist(),
                       error_m=float(np.linalg.norm(offset)), covered95=bool(lp >= threshold))
    save_json(args.out/f'scores_{args.seed}.json', dict(seed=args.seed, selected_epoch=best_epoch,
        synthetic=synthetic, real=[row for row, _, _, _ in real]))
    print('selected epoch', best_epoch, 'real results', [row for row, _, _, _ in real], flush=True)


if __name__ == '__main__':
    main()
