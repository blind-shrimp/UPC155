"""Calibrate Arm C density regions on validation and score the frozen P0 flights."""
import argparse
import hashlib
import math
from pathlib import Path

import numpy as np
import torch

import ablation as p0
from common import build_mdn, make_inputs


FROZEN_SHA256 = 'ba44252bea01885d2b4bbc76b294ab4f2fcebfbfcf2c4fca2904d64616583a27'
LEVELS = (.50, .95)


def frozen_part(path, canonical_test):
    # Git may normalize the exporter CRLF endings to LF.
    raw = path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA256:
        raise ValueError('Frozen CSV differs from the P0 manifest')
    data = np.genfromtxt(path, delimiter=',', names=True)
    names = ['obs'+time+'_'+axis for time in ('005', '010') for axis in 'xyz']
    obs = np.column_stack([data[name] for name in names]).reshape(-1, 2, 3)
    endpoint = np.column_stack([data['endpoint_y'], data['endpoint_z']])
    if (not np.array_equal(data['source_index'], canonical_test['idx'])
            or not np.allclose(obs, canonical_test['obs'], atol=5.01e-10, rtol=0)
            or not np.allclose(endpoint, canonical_test['y'], atol=5.01e-10, rtol=0)):
        raise ValueError('Frozen CSV and canonical NPZ split do not match')
    return dict(obs=obs, y=endpoint)


def batches(model, stats, part, sigma, noise_seed, mc_seed, draws, feature_kind):
    rng = np.random.default_rng(noise_seed)
    noisy = part['obs'] + sigma*rng.standard_normal(part['obs'].shape)
    torch.manual_seed(mc_seed)
    for start in range(0, len(noisy), 256):
        sl = slice(start, start+256)
        x = (make_inputs(feature_kind, noisy[sl], sigma)-stats['xm'])/stats['xs']
        x = torch.as_tensor(np.nan_to_num(x, nan=0., posinf=0., neginf=0.), dtype=torch.float32)
        y = torch.as_tensor((part['y'][sl]-stats['ym'])/stats['ys'], dtype=torch.float32)
        distribution = model(x)
        truth_lp = distribution.log_prob(y)
        draw_lp = distribution.log_prob(distribution.sample((draws,)))
        rank = (draw_lp > truth_lp).sum(dim=0).numpy()
        yield distribution, truth_lp, draw_lp, rank, sl


@torch.no_grad()
def evaluate(model, stats, validation, test, sigma, draws, feature_kind='phys'):
    base_seed = int(sigma*1e6)
    val_ranks = np.concatenate([rank for _, _, _, rank, _ in
                                batches(model, stats, validation, sigma, 19100+base_seed, 38100+base_seed, draws,
                                        feature_kind)])
    adjusted = {}
    for level in LEVELS:
        order = math.ceil((len(val_ranks)+1)*level)
        adjusted[level] = int(np.partition(val_ranks, order-1)[order-1])
    regions = {'nominal': {level: math.floor(level*draws) for level in LEVELS},
               'calibrated': adjusted}
    results = {label: {level: {'count': 0, 'area': 0.} for level in LEVELS} for label in regions}
    errors, nll = [], []
    jacobian = float(np.prod(stats['ys']))
    for distribution, truth_lp, draw_lp, rank, sl in batches(
            model, stats, test, sigma, 9100+base_seed, 48100+base_seed, draws, feature_kind):
        sorted_lp = torch.sort(draw_lp, descending=True, dim=0).values
        area_lp = distribution.log_prob(distribution.sample((draws,)))
        pred = distribution.mean.numpy()*stats['ys']+stats['ym']
        errors.extend(np.linalg.norm(pred-test['y'][sl], axis=1))
        nll.extend((-truth_lp + np.log(jacobian)).numpy())
        for label, cutoffs in regions.items():
            for level, cutoff in cutoffs.items():
                acc = results[label][level]
                acc['count'] += int(np.sum(rank <= cutoff))
                if cutoff == draws:
                    acc['area'] = math.inf
                else:
                    area = torch.where(area_lp >= sorted_lp[cutoff], torch.exp(-area_lp), 0.).mean(dim=0)
                    acc['area'] += float(area.sum())*jacobian
    scores = {label: {str(level): dict(coverage=values['count']/len(errors),
                                       area_m2=values['area']/len(errors),
                                       mass_cutoff=regions[label][level]/draws)
                      for level, values in metrics.items()} for label, metrics in results.items()}
    return dict(sigma_m=sigma, median_error_m=float(np.median(errors)),
                rmse_m=float(np.sqrt(np.mean(np.square(errors)))),
                mean_nll=float(np.mean(nll)), **scores)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=p0.DATA)
    parser.add_argument('--frozen', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=p0.SB/'runs/p1_calibration')
    parser.add_argument('--seeds', type=int, nargs='+', choices=p0.SEEDS, default=p0.SEEDS)
    parser.add_argument('--draws', type=int, default=512)
    args = parser.parse_args()
    if args.draws < 100:
        parser.error('Use at least 100 draws')
    torch.set_num_threads(4)
    p0.DATA = args.data
    _, parts = p0.load()
    test = frozen_part(args.frozen, parts['te'])
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in args.seeds:
        checkpoint = args.out/f'arm_c_seed{seed}.pt'
        if checkpoint.exists():
            saved = torch.load(checkpoint, weights_only=True)
            stats = {key: value.numpy() for key, value in saved['stats'].items()}
            model = build_mdn(len(stats['xm']), k=p0.K, hidden=p0.HIDDEN, depth=p0.DEPTH)
            model.load_state_dict(saved['state'])
        else:
            model, stats, history, seconds, n_params = p0.train_one('C', seed, parts)
            torch.save(dict(state=model.state_dict(), stats={k: torch.as_tensor(v) for k, v in stats.items()},
                            history=history, seconds=seconds, n_params=n_params), checkpoint)
        model.eval()
        for sigma in p0.LEVELS:
            row = dict(seed=seed, **evaluate(model, stats, parts['va'], test, sigma, args.draws))
            rows.append(row)
            print(seed, sigma, f"median={row['median_error_m']:.3f}",
                  *[f"{name} {row[name]['0.5']['coverage']:.3f}/{row[name]['0.95']['coverage']:.3f}"
                    for name in ('nominal', 'calibrated')], flush=True)
        p0.dump(args.out/('scores_'+'_'.join(map(str, args.seeds))+'.json'),
                dict(frozen_sha256=FROZEN_SHA256, test_flights=len(test['y']),
                     calibration_flights=len(parts['va']['y']), draws=args.draws, records=rows))


if __name__ == '__main__':
    main()
