"""Validate teammate handoff files and inventory overlaps, without fitting models."""
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np


def read_rows(text):
    return list(csv.DictReader(io.StringIO(text.lstrip('\ufeff'))))


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / 'student-a/flight_trajectory_validation_2026-11-07'
    inputs = read_rows((folder / 'inputs_only.csv').read_text(encoding='utf-8-sig'))
    held = read_rows((folder / 'held_out.csv').read_text(encoding='utf-8-sig'))
    configs = json.loads((folder / 'case_config.json').read_text(encoding='utf-8-sig'))
    sources = json.loads((folder / 'source_audit.json').read_text(encoding='utf-8-sig'))
    records = []
    assert set(configs) == {row['case_id'] for row in inputs} == {row['case_id'] for row in held}
    with zipfile.ZipFile(root / 'student-a/penalty_trajectory_handoff_2026-11-07.zip') as archive:
        assert archive.testzip() is None, 'ZIP CRC failure'
        def member(basename):
            matches = [name for name in archive.namelist() if name.endswith('/' + basename)]
            assert len(matches) == 1, basename
            return archive.read(matches[0])
        summary = read_rows(member('penalty_summary.csv').decode('utf-8-sig'))
        out = root / 'student_b/runs/data_integration'
        out.mkdir(parents=True, exist_ok=True)
        # Small portable indexes, with raw evidence retained in the original ZIP.
        for name in ('penalty_summary.csv', 'penalty_trajectories.csv'):
            (out / name).write_bytes(member(name))
        for source in sources:
            case = source['case_id']
            before = [r for r in inputs if r['case_id'] == case]
            after = [r for r in held if r['case_id'] == case]
            combined = before + after
            times = np.array([float(r['t_s']) for r in combined])
            assert len(before) == source['n_input'] and len(after) == source['n_held_out']
            assert times[0] == 0 and np.all(np.diff(times) > 0), case
            assert len({r['source_sample_id'] for r in combined}) == len(combined), case
            axes = configs[case]['score_axes']
            coordinates = np.array([[float(r[a + '_m']) for a in axes] for r in combined])
            assert np.isfinite(coordinates).all(), case
            if case == 'Barber2010_Fig5':
                assert all(r['y_m'] == '' for r in combined)
                native = np.array(source['diamond_centers_px'])
                anchors = source['axis_anchors_px']
                scale = 20 / (anchors['m0'] - anchors['m20'])
                expected = np.column_stack(((anchors['m0'] - native[:, 2]) * scale,
                                            (anchors['m0'] - native[:, 4]) * scale))
                np.testing.assert_allclose(coordinates, expected, atol=1e-6, rtol=0)
                np.testing.assert_allclose(times, native[:, 0] - source['figure_time_at_local_zero_s'], atol=1e-8)
            elif case.startswith('ISSIA'):
                native = np.array([r['native_xyz_m'] for r in source['native_frame_records']])
                np.testing.assert_allclose(coordinates, native * [1, 1, -1], atol=1e-6, rtol=0)
                assert [int(r['source_sample_id']) for r in combined] == [r['frame'] for r in source['native_frame_records']]
            else:
                raw = member(Path(source['source']).name)
                assert hashlib.sha256(raw).hexdigest() == source['source_sha256'], case
                native_rows = source['native_frame_records']
                assert [r['source_sample_id'] for r in combined] == [r['N'] for r in native_rows]
                native = np.array([[float(r[a]) for a in ('X', 'Y', 'Z')] for r in native_rows])
                expected = native - [*source['provider_x0_y0_m'], 0]
                np.testing.assert_allclose(coordinates, expected, atol=1e-6, rtol=0)
                target = configs[case]['target_local_x_m']
                i = np.flatnonzero((coordinates[:-1, 0] < target) & (coordinates[1:, 0] >= target))[0]
                fraction = (target - coordinates[i, 0]) / (coordinates[i+1, 0] - coordinates[i, 0])
                cross = coordinates[i] + fraction * (coordinates[i+1] - coordinates[i])
                reference = source['goal_crossing_reference']
                np.testing.assert_allclose([cross[1], cross[2]], [reference['local_y_m'], reference['z_m']], atol=1e-6)
                np.testing.assert_allclose(times[i] + fraction * (times[i+1] - times[i]), reference['time_s'], atol=1e-8)
            records.append({'case_id': case, 'input_rows': len(before), 'held_out_rows': len(after),
                            'input_times_s': times[:len(before)].tolist(), 'axes': axes,
                            'penalty': configs[case]['penalty'], 'coordinate_audit': 'passed'})
    result = {'validation_cases': records, 'zip_summary': summary,
              'overlapping_cases': ['J03WOH', 'J03WR9'],
              'unique_new_cases': ['J03WOH', 'J03WR9', 'J03WMX', 'PFF_3816', 'ISSIA_2972_2991', 'Barber2010_Fig5'],
              'files_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()},
              'scope': 'Data integrity and documented transforms only; no model fitted or evaluated. DFL raw XML hashes checked against ZIP. Barber source PDF and original page image are not supplied here.'}
    (out / 'audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print('PASS: four validation cases, input/held-out separation, documented coordinate transforms, DFL raw hashes and crossing references; ZIP CRC passed.')
    print('Unique new cases: 6; duplicated between packages: J03WOH, J03WR9.')


if __name__ == '__main__':
    main()
