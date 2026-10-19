"""Acceleration packaging, provenance and command-boundary regression checks."""
import argparse
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from bootstrap_acceleration import unpack_tar, digest, load_registry, install_methscan
from run_accelerated import build_command, main
from init_project import RUNTIME_TOOLS


class AccelerationTests(unittest.TestCase):
    def registry(self, root):
        for name in ('bismark', 'pipeline_gpu.py', 'wheel.whl'):
            (root / name).write_text('fixture')
        p = root / 'acceleration.json'
        p.write_text(json.dumps({'schema_version': 1, 'bismark': 'bismark',
            'methscan_wheel': 'wheel.whl', 'vmrseq_gpu': 'pipeline_gpu.py',
            'files': {n: digest(root/n) for n in ('bismark','pipeline_gpu.py','wheel.whl')}}))
        return p

    def test_reject_archive_escape_and_links_before_writing(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('hardlink', tarfile.LNKTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as t:
                b = io.BytesIO()
                with tarfile.open(fileobj=b, mode='w') as tar:
                    m = tarfile.TarInfo(name); m.type=kind; m.linkname='/tmp/out'; tar.addfile(m)
                b.seek(0)
                with tarfile.open(fileobj=b) as tar, self.assertRaisesRegex(ValueError,'unsafe'):
                    unpack_tar(tar, Path(t)/'output')
                self.assertFalse((Path(t)/'output').exists())

    def test_registry_detects_changed_release(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=self.registry(root); load_registry(p)
            (root/'pipeline_gpu.py').write_text('changed')
            with self.assertRaisesRegex(ValueError,'changed'): load_registry(p)

    def test_native_argument_preservation_and_gpu_csv(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=self.registry(root)
            a=argparse.Namespace(registry=p, tool='methscan', python=Path('/env/python'), device='gpu')
            cmd=build_command(a, ['--','smooth','/input with spaces','--bandwidth','1000'])
            self.assertIn('/input with spaces',cmd)
            self.assertEqual(cmd[-3:], ['--device','gpu','--write-csv'])
            cmd=build_command(a, ['matrix','regions','input','output'])
            self.assertNotIn('--device',cmd)
            with self.assertRaisesRegex(ValueError,'set --device'):
                build_command(a,['smooth','input','--device=cpu'])
            a.tool='vmrseq-gpu'; a.rscript=None; a.r_library=None
            with self.assertRaisesRegex(ValueError,'requires'): build_command(a,['pool','out'])

    def test_submit_host_cannot_execute_or_write_evidence(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=self.registry(root); evidence=root/'evidence.json'
            argv=['run','--registry',str(p),'--tool','bismark','--execute',
                  '--evidence',str(evidence),'--','align','--device','cpu']
            with mock.patch.object(sys,'argv',argv), mock.patch('run_accelerated.host_role',return_value='submit'), \
                    mock.patch('run_accelerated.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'compute'): main()
                run.assert_not_called()
            self.assertFalse(evidence.exists())

    def test_existing_environment_is_never_mutated(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=self.registry(root); prefix=root/'env'; prefix.mkdir()
            with mock.patch('bootstrap_acceleration.subprocess.check_output',return_value='[3,11]'), \
                    mock.patch('bootstrap_acceleration.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'existing environment'):
                    install_methscan(p, Path(sys.executable),prefix)
                run.assert_not_called()

    def test_standard_methscan_is_not_misreported_as_accelerated(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=self.registry(root)
            argv=['run','--registry',str(p),'--tool','methscan','--python',sys.executable,
                  '--execute','--','smooth','input']
            with mock.patch.object(sys,'argv',argv), mock.patch('run_accelerated.host_role',return_value='compute'), \
                    mock.patch('run_accelerated.subprocess.check_output',return_value='1.1.0\n'), \
                    mock.patch('run_accelerated.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'expected accelerated'): main()
                run.assert_not_called()

    def test_default_is_read_only_command_plan(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); p=self.registry(root)
            argv=['run','--registry',str(p),'--tool','bismark','--','align','--device','cpu']
            with mock.patch.object(sys,'argv',argv), mock.patch('sys.stdout',new_callable=io.StringIO) as out, \
                    mock.patch('run_accelerated.subprocess.run') as run:
                main()
                plan=json.loads(out.getvalue())
                self.assertFalse(plan['execute'])
                self.assertEqual(plan['command'][-2:],['--device','cpu'])
                run.assert_not_called()

    def test_generated_projects_include_all_adapter_dependencies(self):
        for name in ('bootstrap_acceleration.py','run_accelerated.py','run_vmrseq_cpu.R'):
            self.assertIn(name,RUNTIME_TOOLS)

if __name__ == '__main__': unittest.main()
