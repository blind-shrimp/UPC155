"""Read-only coverage audit of the existing trajectory archive (SI units)."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    with np.load(args.data, allow_pickle=False) as archive:
        theta, split, status, obs, endpoint = [archive[key] for key in
            ('theta', 'split', 'status', 'observations', 'endpoint')]
    n = len(theta)
    if theta.shape != (n, 7) or obs.shape != (n, 2, 3):
        raise ValueError('Unexpected parameter or observation shape')
    if not all(len(x) == n for x in (split, status, endpoint)):
        raise ValueError('Inconsistent sample counts')
    if not np.isin(split, [0, 1, 2]).all() or not np.isin(status, [0, 1, 2]).all():
        raise ValueError('Unknown split or event code')
    if not np.isfinite(theta).all():
        raise ValueError('Non-finite physical parameters')
    airborne = status == 1
    train = airborne & (split == 0)
    if not np.isfinite(obs[airborne]).all() or not np.isfinite(endpoint[airborne]).all():
        raise ValueError('Non-finite airborne labels')
    velocity, omega = theta[:, :3], theta[:, 3:6]
    speed = np.linalg.norm(velocity, axis=1)
    spin = np.linalg.norm(omega, axis=1)
    transverse = np.linalg.norm(np.cross(omega, velocity), axis=1) / speed
    azimuth = np.degrees(np.arctan2(velocity[:, 1], velocity[:, 0]))
    elevation = np.degrees(np.arctan2(velocity[:, 2], np.linalg.norm(velocity[:, :2], axis=1)))
    masks = {'all': np.ones(n, bool), 'airborne': airborne, 'train_airborne': train,
             'validation_airborne': airborne & (split == 1), 'test_airborne': airborne & (split == 2)}
    rows = []

    def add(group, label, selected):
        rows.append({'group': group, 'bin': label,
                     **{key: int(np.sum(selected & mask)) for key, mask in masks.items()}})

    def bins(group, values, edges):
        for low, high in zip(edges[:-1], edges[1:]):
            add(group, f'[{low:g}, {high:g})', (values >= low) & (values < high))

    bins('速率 m/s', speed, [0, 15, 20, 25, 30, 35, 40, np.inf])
    bins('总角速度 rad/s', spin, [0, 10, 30, 60, 90, 120, np.inf])
    bins('横向有效角速度 rad/s', transverse, [0, 10, 30, 60, 90, 120, np.inf])
    bins('水平发射角 deg', azimuth, [-90, -20, -10, 0, 10, 20, 90])
    bins('仰角 deg', elevation, [-90, 0, 5, 10, 20, 30, 90])
    add('特殊旋转', '严格零旋', spin == 0)
    for axis, name in enumerate(('x', 'y', 'z')):
        for sign in (-1, 1):
            add('旋转方向', f'{name} 轴 {sign:+d} 方向，轴夹角≤15°',
                (spin > 0) & (sign * omega[:, axis] >= np.cos(np.radians(15)) * spin))
    inside = airborne & (np.abs(endpoint[:, 0]) < 3.66) & (endpoint[:, 1] > 0) & (endpoint[:, 1] < 2.44)
    add('穿越结果', '球心在门框矩形内', inside)
    add('穿越结果', '球心在门框矩形外', airborne & ~inside)
    add('穿越结果', '过线时球心离接地高度不足5cm', airborne & (endpoint[:, 1] >= .11) & (endpoint[:, 1] < .16))
    joint, speed_edges, spin_edges = np.histogram2d(speed[train], spin[train],
        bins=([0, 15, 20, 25, 30, 35, 40, 100], [0, 10, 30, 60, 90, 120]))
    # Exact duplicated launch conditions cannot appear across different splits.
    _, inverse = np.unique(theta, axis=0, return_inverse=True)
    lower = np.full(inverse.max() + 1, 3)
    upper = np.full(inverse.max() + 1, -1)
    np.minimum.at(lower, inverse, split)
    np.maximum.at(upper, inverse, split)
    duplicates = int(np.sum(lower != upper))
    report = {'source': str(args.data.resolve()),
              'sha256': hashlib.sha256(args.data.read_bytes()).hexdigest(),
              'counts': {key: int(mask.sum()) for key, mask in masks.items()},
              'events': {str(code): int(np.sum(status == code)) for code in (0, 1, 2)},
              'cross_split_exact_parameter_duplicates': duplicates,
              'rows': rows, 'joint_train_speed_spin': joint.astype(int).tolist(),
              'joint_speed_edges': speed_edges.tolist(), 'joint_spin_edges': spin_edges.tolist(),
              'observation_ranges_airborne': {'min': obs[airborne].min(axis=0).tolist(),
                                               'max': obs[airborne].max(axis=0).tolist()}}
    lines = ['# 现有仿真数据覆盖审计', '',
        '审计对象为 literature50k 原始数据。直接读取现有样本，未重新仿真。', '',
        f'共 {n:,} 条。空中过线 {airborne.sum():,} 条，提前触地 {(status == 2).sum():,} 条，超时 {(status == 0).sum():,} 条。',
        f'实际用于 MDN 的训练/验证/测试样本分别为 {train.sum():,} / {masks["validation_airborne"].sum():,} / {masks["test_airborne"].sum():,} 条。',
        f'跨划分完全相同的参数向量组数为 {duplicates}。此检查仅检测精确重复。', '',
        '分箱及15°方向阈值是本次审计约定。总角速度与横向有效角速度分别统计，后者决定当前模型中的旋转升力。', '',
        '| 维度 | 范围 | 原始数 | 空中过线 | 训练 | 验证 | 测试 |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        lines.append('| ' + ' | '.join(str(row[key]) for key in ('group', 'bin', *masks)) + ' |')
    lines += ['', '## 训练集速率×总角速度联合分箱', '',
              '每行依次为角速度 [0,10)、[10,30)、[30,60)、[60,90)、[90,120) rad/s 的数量。', '']
    for index, values in enumerate(joint.astype(int)):
        lines.append(f'- 速率 [{speed_edges[index]:g}, {speed_edges[index+1]:g}) m/s：' + ', '.join(map(str, values)))
    lines += ['', '## 给数据与训练同学的下一步', '',
        '1. 优先补严格零旋、低旋和低速的诊断样本，并明确新的速率边界依据。现有初速度分量范围无法产生低于18 m/s的轨迹。',
        '2. 以旋转大小和轴方向分层抽样，保存各层采样权重。当前分量均匀先验使小角速度样本稀少；补样比例是建模假设，会影响条件概率。',
        '3. 保留触地/超时样本及事件标签。当前 MDN 的落点分布以空中到达球门平面为条件。反弹球需要单独的接触模型。',
        '4. 两次给定点从积分轨迹取得。补样后重新输出覆盖表，并检查题面附近的观测覆盖及推断诊断。坐标极值只能检查范围。',
        '5. 为新增分布建立独立开发/校准/测试划分，再让台式机使用相同数据比较新旧网络。现有已查看的留出集继续作为开发证据。',
        '6. ball3d 获批后，用独立无接触实测片段做前段拟合、后段预测。此审计衡量样本覆盖，现实可靠性需由实测外推检验。', '',
        '## 复现', '', '```powershell',
        'python student_b/audit_coverage.py --data student_b/runs/literature50k/data.npz --out student_b/runs/coverage_audit',
        '```', '', f'原始文件 SHA-256：`{report["sha256"]}`', '']
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'coverage.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (args.out / '覆盖审计.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'counts': report['counts'], 'events': report['events'], 'report': str(args.out / '覆盖审计.md')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
