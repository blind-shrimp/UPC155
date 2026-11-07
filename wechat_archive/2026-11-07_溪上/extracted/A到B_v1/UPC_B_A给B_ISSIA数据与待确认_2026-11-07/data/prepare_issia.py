"""Normalize ISSIA-3D coordinates without filling missing or clipping noisy values."""
from pathlib import Path
import ast,csv,hashlib,json,math,statistics

BASE=Path(__file__).resolve().parent
FPS=25

def write(path,rows,fields=None):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    with (BASE/'ISSIA-3D.csv').open(encoding='utf-8-sig',newline='') as f: source=list(csv.DictReader(f))
    rows=[];valid=[];runs=[];first=min(int(r['frame']) for r in source)
    for s in source:
        frame=int(s['frame']);p=ast.literal_eval(s['ball_3D']) if s['ball_3D'].strip() else None
        if p is not None and (len(p)!=3 or not all(math.isfinite(float(v)) for v in p)):raise ValueError('Non-finite 3D source')
        errors=[float(s[f'err_cam{i}']) for i in range(1,7) if s[f'err_cam{i}'].strip()]
        r={'frame_id':frame,'t_from_first_annotation_s':round((frame-first)/FPS,6),
            'has_3d':p is not None,'num_cameras':int(s['num_cameras']),
            'x_m':p[0] if p else '', 'y_m':p[1] if p else '',
            'z_up_m':-p[2] if p else '', 'z_original_m':p[2] if p else '',
            'max_reprojection_error_px':max(errors) if errors else '',
            'below_ground_flag':(-p[2]<0) if p else '', 'continuity_run_id':''}
        if p:
            if not runs or frame!=runs[-1][-1]['frame_id']+1:runs.append([])
            r['continuity_run_id']=len(runs)
            runs[-1].append(r);valid.append(r)
        rows.append(r)
    write(BASE/'ISSIA_native_normalized.csv',rows)
    write(BASE/'ISSIA_valid_3d_only.csv',valid)
    runrows=[]
    for run in runs:
        runrows.append({'continuity_run_id':run[0]['continuity_run_id'],
            'start_frame':run[0]['frame_id'],'end_frame':run[-1]['frame_id'],
            'n_frames':len(run),'duration_s':round((len(run)-1)/FPS,6),
            'min_height_m':min(r['z_up_m'] for r in run),'max_height_m':max(r['z_up_m'] for r in run),
            'n_negative_heights':sum(r['z_up_m']<0 for r in run),
            'median_max_reprojection_error_px':statistics.median(r['max_reprojection_error_px'] for r in run),
            'continuous_flight_confirmed':False})
    write(BASE/'ISSIA_continuity_runs.csv',runrows)
    summary={'source_url':'https://github.com/mguti97/SoccerNet-v3D/releases/download/v1.0.0/ISSIA-3D.csv',
        'source_rows':len(source),'unique_frames':len(set(r['frame_id'] for r in rows)),
        'valid_3d_frames':len(valid),'fps':FPS,'continuity_runs':len(runs),
        'runs_at_least_10_frames':sum(len(r)>=10 for r in runs),
        'longest_contiguous_run_frames':max(map(len,runs)),
        'height_sign_conversion':'z_up_m = -z_original_m; SoccerNet pitch model places crossbar at z=-2.44 m.',
        'coordinate_reference_url':'https://raw.githubusercontent.com/SoccerNet/sn-calibration/main/src/soccerpitch.py',
        'height_range_m':[min(r['z_up_m'] for r in valid),max(r['z_up_m'] for r in valid)],
        'negative_heights_preserved':sum(r['z_up_m']<0 for r in valid),
        'no_interpolation':True,'no_clipping':True,
        'warning':'Continuity runs are not independent kicks and may contain contacts, rolling, or reconstruction errors. Requires further flight segmentation and quality filtering.',
        'ball_size_evidence':'Real adult soccer match context; no per-ball size/mass certificate in CSV.',
        'source_sha256':hashlib.sha256((BASE/'ISSIA-3D.csv').read_bytes()).hexdigest()}
    (BASE/'ISSIA_audit.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
