#!/usr/bin/env python3
"""Small compute-node smoke of supplied CPU backends; no study inputs."""
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from bootstrap_acceleration import load_registry
from _common import host_role, HOST_ROLE_SUBMIT


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--registry',type=Path,required=True)
    p.add_argument('--methscan-python',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--only',choices=['bismark','methscan','all'],default='all')
    a=p.parse_args()
    if host_role()==HOST_ROLE_SUBMIT: raise RuntimeError('use a compute allocation')
    root,record=load_registry(a.registry)
    a.output.mkdir(parents=True,exist_ok=False)
    output=a.output.resolve()
    os.environ['PATH']=str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')
    summary={}
    def run(cmd,name):
        with (output/(name+'.log')).open('w') as log:
            subprocess.run(list(map(str,cmd)),check=True,stdout=log,stderr=subprocess.STDOUT)
    if a.only != 'methscan':
        bacc=root/record['bismark']; package=bacc.parent
        genome=output/'genome';genome.mkdir()
        with gzip.open(package/'test/genome/chr21_25M.fa.gz','rb') as src, (genome/'chr21_25M.fa').open('wb') as dst:
            shutil.copyfileobj(src,dst)
        run([bacc,'prepare',genome,'--threads','4','--no-gpu-cache'],'bismark-prepare')
        expected={}
        with (package/'test/expected.tsv').open() as f:
            for line in f:
                fields=line.split()
                if fields and fields[0]=='cpu': expected[fields[1]]=fields
        for mode,arguments in (
            ('se_r1_pbat',['--pbat',package/'test/reads_R1.fastq.gz']),
            ('se_r2_dir',[package/'test/reads_R2.fastq.gz']),
            ('pe_pbat',['--pbat','--maxins','2000','-1',package/'test/reads_R1.fastq.gz','-2',package/'test/reads_R2.fastq.gz'])):
            target=output/mode
            run([bacc,'align','--device','cpu','--threads','2','--genome',genome,*arguments,'-o',target],mode)
            bg=next(target.glob('*.bedGraph'))
            observed=hashlib.md5(bg.read_bytes()).hexdigest()[:12]
            assert observed==expected[mode][3],(mode,observed,expected[mode][3])
            bams=list(target.glob('*.bam'))
            assert bams and all(p.stat().st_size>0 for p in bams)
            report=next(target.glob('*_report.txt')).read_text()
            unique=int(re.search(r'unique best hit[^:]*:\s*(\d+)',report).group(1))
            assert unique==int(expected[mode][2])
            summary[mode]={'bedgraph_md5_prefix':observed,'matches_package_reference':True,
                           'unique_alignments':unique,'bam_nonempty':True}
        (output/'bismark-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    if a.only != 'bismark':
        native=a.methscan_python.parent/'methscan'
        inputs=output/'coverage';inputs.mkdir()
        files=[]
        for cell in range(8):
            path=inputs/('cell%d.cov'%cell);files.append(path)
            with path.open('w') as f:
                for pos in range(100,40100,100):
                    m=int(cell>=4) if 10000<=pos<30000 else int(pos//100%31==cell)
                    f.write('chr1\t%d\t%d\t%d\t%d\t%d\n'%(pos,pos,100*m,m,1-m))
        data=output/'prepared'
        run([native,'prepare','--input-format','bismark',*files,data],'methscan-prepare')
        assert len((data/'column_header.txt').read_text().splitlines())==8
        run([native,'smooth',data,'--bandwidth','1000'],'methscan-smooth')
        regions=output/'regions.bed';regions.write_text('chr1\t0\t19999\nchr1\t20000\t40100\n')
        matrix=output/'matrix'
        run([native,'matrix',regions,data,matrix,'--threads','2'],'methscan-matrix')
        with gzip.open(matrix/'total_sites.csv.gz','rt') as f:
            counts=list(csv.reader(f))
        assert len(counts)==9, len(counts)
        for row in counts[1:]:
            values=[float(x) for x in row[1:]]
            assert len(values)==2 and sum(values)==400, row
        run([native,'scan',data,output/'vmr.bed','--bandwidth','2000','--stepsize','100',
             '--var-threshold','0.1','--min-cells','2','--threads','2'],'methscan-scan')
        summary['methscan']={'cells':8,'sites_per_cell':400,'regions':2,'total_site_counts_verified':True,
                             'scan_exited_successfully':True}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
