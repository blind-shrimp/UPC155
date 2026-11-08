"""Controlled Arm C continuation and reflection augmentation experiments."""
import argparse
from pathlib import Path

import numpy as np
import torch

import ablation as p0
from common import build_mdn
from p1_calibrate_arm_c import evaluate, frozen_part
from physics import sample_prior, simulate


VARIANTS = {
    'baseline': dict(input='phys', target='abs'),
    'continued': dict(input='phys', target='abs'),
    'mirror_reduced': dict(input='phys_reduced13', target='abs'),
}


def calibration_part():
    rng = np.random.default_rng(46023)
    observations, endpoints = [], []
    for _ in range(3):
        trajectories = simulate(sample_prior(2000, rng))
        valid = (trajectories['status'] == 1) & np.isfinite(trajectories['observations']).all(axis=(1, 2))
        observations.append(trajectories['observations'][valid])
        endpoints.append(trajectories['endpoint'][valid])
    return dict(obs=np.concatenate(observations), y=np.concatenate(endpoints))


def load_checkpoint(path):
    saved = torch.load(path, weights_only=True, map_location='cpu')
    saved['stats'] = {key: value.numpy() for key, value in saved['stats'].items()}
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--frozen', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, default=p0.SB/'runs/p1_calibration')
    parser.add_argument('--out', type=Path, default=p0.SB/'runs/p2_training')
    parser.add_argument('--seeds', type=int, nargs='+', choices=p0.SEEDS, default=p0.SEEDS)
    parser.add_argument('--variant', choices=VARIANTS, required=True)
    parser.add_argument('--threads', type=int, default=3)
    args = parser.parse_args()
    torch.set_num_threads(args.threads)
    p0.DATA = args.data
    _, parts = p0.load()
    args.out.mkdir(parents=True, exist_ok=True)
    spec = VARIANTS[args.variant]
    paths = {}
    for seed in args.seeds:
        if args.variant == 'baseline':
            paths[seed] = args.baseline/f'arm_c_seed{seed}.pt'
            continue
        checkpoint = args.out/f'{args.variant}_{seed}.pt'
        paths[seed] = checkpoint
        if checkpoint.exists():
            continue
        warm = (load_checkpoint(args.baseline/f'arm_c_seed{seed}.pt')
                if args.variant == 'continued' else None)
        model, stats, history, seconds, n_params = p0.train_one(
            args.variant, seed, parts, spec=spec, warm_start=warm,
            mirror=args.variant == 'mirror_reduced', select_validation=True)
        torch.save(dict(state=model.state_dict(), stats={k: torch.as_tensor(v) for k, v in stats.items()},
                        history=history, seconds=seconds, n_params=n_params), checkpoint)
        print(args.variant, seed, 'selected epoch', history[-1]['selected_epoch'], flush=True)

    test = frozen_part(args.frozen, parts['te'])
    calibration = calibration_part()
    rows = []
    for seed, checkpoint in paths.items():
        saved = load_checkpoint(checkpoint)
        stats = saved['stats']
        model = build_mdn(len(stats['xm']), k=p0.K, hidden=p0.HIDDEN, depth=p0.DEPTH)
        model.load_state_dict(saved['state'])
        model.eval()
        for sigma in p0.LEVELS:
            row = dict(seed=seed, variant=args.variant, **evaluate(
                model, stats, calibration, test, sigma, 512, spec['input']))
            rows.append(row)
            print(args.variant, seed, sigma, f"median={row['median_error_m']:.3f}",
                  f"NLL={row['mean_nll']:.3f}", flush=True)
        p0.dump(args.out/f'{args.variant}_scores.json', dict(
            records=rows, test_flights=len(test['y']), calibration_flights=len(calibration['y']),
            calibration_seed=46023))


if __name__ == '__main__':
    main()
