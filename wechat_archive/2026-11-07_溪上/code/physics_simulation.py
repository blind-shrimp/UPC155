"""Point-mass football simulation; SI units, vertical spin axis only.

Run: python B/physics_simulation.py --help
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp


@dataclass(frozen=True)
class Parameters:
    mass: float = 0.43
    radius: float = 0.11
    rho: float = 1.225
    gravity: float = 9.80665
    cd: float = 0.22
    cl: float = 0.10  # signed effective coefficient, NOT angular velocity
    wind: tuple[float, float, float] = (0.0, 0.0, 0.0)
    buoyancy: bool = True

    def __post_init__(self):
        values = [self.mass, self.radius, self.rho, self.gravity, self.cd, self.cl]
        if not np.all(np.isfinite(values)):
            raise ValueError("Physical parameters must be finite")
        if self.mass <= 0 or self.radius <= 0 or min(self.rho, self.gravity, self.cd) < 0:
            raise ValueError("mass/radius must be positive; rho/gravity/cd nonnegative")
        vector3(self.wind)


def vector3(value):
    result = np.asarray(value, dtype=float)
    if result.shape != (3,) or not np.all(np.isfinite(result)):
        raise ValueError("Expected a finite three-component vector")
    return result


def forces(velocity, p: Parameters):
    """Return the four forces in N. u = ball velocity - air velocity.

    At |z_hat x u| <= 1e-12 m/s the supplied formula is undefined;
    we explicitly adopt zero spin force there (a modelling convention).
    """
    u = vector3(velocity) - np.asarray(p.wind)
    speed = np.linalg.norm(u)
    area = np.pi * p.radius**2
    gravity = np.array([0., 0., -p.mass * p.gravity])
    drag = -0.5 * p.rho * p.cd * area * speed * u
    cross = np.array([-u[1], u[0], 0.])
    horizontal_speed = np.linalg.norm(cross)
    spin = np.zeros(3)
    if horizontal_speed > 1e-12:
        spin = 0.5 * p.rho * p.cl * area * speed**2 * cross / horizontal_speed
    buoyancy = np.array([0., 0., p.rho * 4 / 3 * np.pi * p.radius**3 * p.gravity])
    if not p.buoyancy:
        buoyancy[:] = 0
    return gravity, drag, spin, buoyancy


def rhs(t, state, p):
    return np.r_[state[3:], np.sum(forces(state[3:], p), axis=0) / p.mass]


@dataclass
class Flight:
    status: str  # airborne_crossing, ground, no_crossing
    time: np.ndarray
    state: np.ndarray  # columns: x,y,z,vx,vy,vz
    stop_time: float
    stop_state: np.ndarray
    observations: np.ndarray  # (2,3), NaN if flight ended before observation
    target: np.ndarray  # Y,Z, only for airborne_crossing


def simulate(v0=(30.4, 9.4, 6.9), p=None, r0=(0., 0., 0.11),
             goal_x=11., t_max=3., rtol=1e-8, atol=1e-10,
             max_step=0.02, sample_dt=0.005):
    p = Parameters() if p is None else p
    r0, v0 = vector3(r0), vector3(v0)
    controls = [goal_x, t_max, rtol, atol, max_step, sample_dt]
    if not np.all(np.isfinite(controls)) or min(controls[1:]) <= 0:
        raise ValueError("Finite goal and positive time/solver controls required")
    if r0[0] >= goal_x or r0[2] < p.radius:
        raise ValueError("Initial centre must be before goal and on/above ground")
    initial = np.r_[r0, v0]
    obs = np.full((2, 3), np.nan)
    target = np.full(2, np.nan)
    # A ball initially on the ground must actually launch upwards.
    if r0[2] == p.radius and (v0[2] < 0 or
            (v0[2] == 0 and rhs(0, initial, p)[5] <= 0)):
        return Flight("ground", np.array([0.]), initial[None, :], 0., initial, obs, target)

    def goal(t, state):
        return state[0] - goal_x

    def ground(t, state):
        return state[2] - p.radius

    goal.terminal, goal.direction = True, 1
    ground.terminal, ground.direction = True, -1
    sol = solve_ivp(lambda t, y: rhs(t, y, p), (0., t_max), initial,
                    method="DOP853", events=(goal, ground), dense_output=True,
                    rtol=rtol, atol=atol, max_step=max_step)
    if not sol.success:
        raise RuntimeError(sol.message)
    stop_time = float(sol.t[-1])
    stop = sol.y[:, -1].copy()
    status = "no_crossing"
    if len(sol.t_events[1]) or (len(sol.t_events[0]) and stop[2] <= p.radius + 1e-9):
        status = "ground"  # simultaneous contact is not an airborne label
    elif len(sol.t_events[0]):
        status = "airborne_crossing"
        target = stop[1:3].copy()
    for i, t in enumerate((0.05, 0.10)):
        if t <= stop_time:
            obs[i] = sol.sol(t)[:3]
    time = np.unique(np.r_[np.arange(0., stop_time, sample_dt), stop_time])
    return Flight(status, time, sol.sol(time).T, stop_time, stop, obs, target)


def generate_dataset(n, output, seed=2026, noise_std=0.01, pool=None):
    """Use jointly calibrated parameter rows if supplied, otherwise demo priors.

    pool columns: vx,vy,vz,cd,cl,mass,radius,rho,wind_x,wind_y,wind_z.
    Whole rows are resampled to preserve empirical parameter correlations.
    """
    if n <= 0 or not np.isfinite(noise_std) or noise_std < 0:
        raise ValueError("n must be positive and noise_std finite/nonnegative")
    rng = np.random.default_rng(seed)
    if pool is None:
        # Deliberately illustrative; these ranges are NOT calibrated priors.
        parameters = np.column_stack([
            rng.uniform(15, 40, n), rng.uniform(-12, 12, n), rng.uniform(0, 12, n),
            rng.uniform(.15, .30, n), rng.uniform(-.25, .25, n),
            np.full(n, .43), np.full(n, .11), np.full(n, 1.225), np.zeros((n, 3))])
    else:
        pool = np.asarray(pool, dtype=float)
        if pool.ndim != 2 or pool.shape[1] != 11 or not len(pool) or not np.all(np.isfinite(pool)):
            raise ValueError("Parameter pool must be finite, nonempty, shape (N,11)")
        parameters = pool[rng.integers(len(pool), size=n)].copy()
    clean = np.full((n, 6), np.nan)
    targets = np.full((n, 2), np.nan)
    statuses = np.empty(n, dtype="U20")
    stop_times = np.empty(n)
    stop_states = np.empty((n, 6))
    for i, row in enumerate(parameters):
        p = Parameters(cd=row[3], cl=row[4], mass=row[5], radius=row[6],
                       rho=row[7], wind=tuple(row[8:11]))
        f = simulate(row[:3], p)  # r0 is fixed by the experiment, not varied with R
        clean[i], targets[i], statuses[i] = f.observations.ravel(), f.target, f.status
        stop_times[i], stop_states[i] = f.stop_time, f.stop_state
    inputs = clean + rng.normal(0, noise_std, clean.shape)
    # Split trajectory IDs before filtering. Every future noise copy must inherit this split.
    order = rng.permutation(n)
    split = np.full(n, "test", dtype="U5")
    split[order[:int(.8*n)]] = "train"
    split[order[int(.8*n):int(.9*n)]] = "val"
    usable = (statuses == "airborne_crossing") & np.isfinite(inputs).all(axis=1)
    counts = {s: int(np.sum(statuses == s)) for s in
              ("airborne_crossing", "ground", "no_crossing")}
    metadata = dict(seed=seed, noise_std_m=noise_std, n=n, counts=counts,
                    usable_count=int(usable.sum()), excluded_fraction=float(1-usable.mean()),
                    prior="demo_uncalibrated" if pool is None else "user_joint_parameter_pool",
                    parameter_columns="vx vy vz cd cl mass radius rho wind_x wind_y wind_z".split(),
                    input_columns="x_005 y_005 z_005 x_010 y_010 z_010".split(),
                    r0=[0, 0, .11], goal_x=11, t_max=3, buoyancy=True,
                    numpy_version=np.__version__)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, inputs=inputs, clean_inputs=clean, targets=targets,
                        status=statuses, stop_time=stop_times, stop_state=stop_states,
                        parameters=parameters, trajectory_id=np.arange(n), split=split,
                        usable=usable, metadata=json.dumps(metadata))
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--v0", nargs=3, type=float, default=[30.4, 9.4, 6.9])
    demo.add_argument("--cd", type=float, default=.22)
    demo.add_argument("--cl", type=float, default=.10)
    demo.add_argument("--wind", nargs=3, type=float, default=[0., 0., 0.])
    demo.add_argument("--output", type=Path, default=Path("B/simulation_output/demo.npz"))
    data = sub.add_parser("dataset")
    data.add_argument("--n", type=int, default=10000)
    data.add_argument("--seed", type=int, default=2026)
    data.add_argument("--noise-std", type=float, default=.01)
    data.add_argument("--pool", type=Path, help="Joint parameter samples in an (N,11) .npy file")
    data.add_argument("--output", type=Path, default=Path("B/simulation_output/dataset.npz"))
    args = parser.parse_args()
    if args.command == "dataset":
        pool = np.load(args.pool, allow_pickle=False) if args.pool else None
        print(json.dumps(generate_dataset(args.n, args.output, args.seed, args.noise_std, pool), indent=2))
    else:
        p = Parameters(cd=args.cd, cl=args.cl, wind=tuple(args.wind))
        f = simulate(args.v0, p)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(args.output, time=f.time, state=f.state,
                            observations=f.observations, target=f.target,
                            status=f.status, parameters=json.dumps(asdict(p)))
        print(json.dumps(dict(status=f.status, stop_time=f.stop_time,
                              stop_position=f.stop_state[:3].tolist(),
                              observations=f.observations.tolist()), indent=2))


if __name__ == "__main__":
    main()
