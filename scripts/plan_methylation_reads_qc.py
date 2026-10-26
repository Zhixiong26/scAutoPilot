#!/usr/bin/env python3
"""Freeze, validate and submit an opt-in read-depth diagnostic DAG for an idle project."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
from result_paths import require_unused_result
from audit_runtime import require_contract

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, required=True); p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--run-id', required=True); p.add_argument('--partition'); p.add_argument('--smoke-test', type=Path)
    a=p.parse_args(); root=a.project.resolve(); run=a.run_id
    require_contract(root)
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,90}', run): p.error('Invalid run ID')
    result_dir = require_unused_result(root, run, 'methylation_qc')
    spec=json.loads(a.spec.read_text())
    # Relative source paths are anchored to the original specification, not its frozen copy.
    for key in ['metadata', 'palette']:
        if spec.get(key): spec[key]=str((a.spec.resolve().parent/Path(spec[key])).resolve())
    for entry in spec['samples']:
        for key in ['reads_file', 'id_mapping']:
            if entry.get(key): entry[key]=str((a.spec.resolve().parent/Path(entry[key])).resolve())
    for entry in spec.get('embeddings', []): entry['path']=str((a.spec.resolve().parent/Path(entry['path'])).resolve())
    for path in [root/'.workflow/run_projects'/run,root/'.workflow/runs'/run,root/'Results/runs'/run]:
        if path.exists(): raise FileExistsError(path)
    dest=root/'.workflow/run_projects'/run; dest.mkdir(parents=True)
    for name in ['config','tools','Scripts','environment-specs']:
        shutil.copytree(root/name,dest/name,symlinks=True,ignore=shutil.ignore_patterns('__pycache__','logs'))
    for name in ['Data','Results','Supplementary','.workflow']: (dest/name).symlink_to(root/name,target_is_directory=True)
    shutil.copy2(root/'workflow.py',dest/'workflow.py')
    (dest/'config/methylation_reads_qc.json').write_text(json.dumps(spec,indent=2))
    cfg=json.loads((dest/'config/analysis.yaml').read_text())
    cfg['analysis']['task_commands']={'methylation_reads_qc':[
        '{python}','{project}/tools/run_methylation_reads_qc.py','--spec','{project}/config/methylation_reads_qc.json',
        '--output','{result_dir}/methylation_reads_qc','--task-dir','{task_dir}']}
    if a.smoke_test:
        shutil.copy2(a.smoke_test,dest/'tools/methylation_reads_qc_smoke.py')
        cfg['analysis']['task_commands']['reads_qc_smoke']=['{python}','{project}/tools/methylation_reads_qc_smoke.py','--task-dir','{task_dir}']
    (dest/'config/analysis.yaml').write_text(json.dumps(cfg,indent=2))
    scheduler=json.loads((dest/'config/scheduler.yaml').read_text())
    if a.partition: scheduler['partitions']=[a.partition]
    scheduler['profiles']['reads_qc']={'floor':{'cpus':2,'memory':'8G'},'target':{'cpus':2,'memory':'8G','time':'00:30:00'},'ceiling':{'cpus':2,'memory':'8G'}}
    (dest/'config/scheduler.yaml').write_text(json.dumps(scheduler,indent=2))
    sys.path.insert(0,str(dest/'tools'))
    from _common import runtime_identity,write_json
    from validate_project import validate
    from plan_workflow import task,validate_dag
    from submit_workflow import submit
    for mode in ['quick','full']:
        pre=validate(dest,mode=mode,required_stages={'orchestrator','scanpy_allcools'},selected_routes=set())
        if pre['status']!='valid': raise RuntimeError(pre['errors'])
        write_json(dest/'.workflow/validations'/(pre['input_signature']+'.'+mode+'.json'),pre)
    tasks=[]
    if a.smoke_test: tasks.append(task('reads_qc_smoke','reads_qc',environment='scanpy_allcools'))
    tasks.append(task('methylation_reads_qc','reads_qc',['reads_qc_smoke'] if a.smoke_test else [],environment='scanpy_allcools'))
    tasks.append(task('workflow_summary','summary',['methylation_reads_qc'])); validate_dag(tasks)
    plan={'schema_version':1,'run_id':run,'project':str(dest),'created_at':datetime.now(timezone.utc).isoformat(),
        'status':'planned','routes':{x:False for x in ['scanpy','allcools','methscan_vmr','methscan_dmr','methylvi_allcools','methylvi_vmr','methylvi_vmr_dmr']},
        'input_signature':pre['input_signature'],'code_signature':pre['code_signature'],'runtime_identity':runtime_identity(dest),
        'plan_identity_version':2,'result_layout_version':2,'result_category':'methylation_qc','result_dir':str(result_dir),'tasks':tasks,
        'custom_scope':'Opt-in SeekGene method 2 read-count diagnostics; pinned sources, explicit IDs, no detector calls or cell filtering.'}
    write_json(dest/'.workflow/runs'/run/'preflight.json',pre); write_json(dest/'.workflow/runs'/run/'plan.json',plan)
    print(json.dumps(submit(dest,run),indent=2),flush=True)
if __name__=='__main__': main()
