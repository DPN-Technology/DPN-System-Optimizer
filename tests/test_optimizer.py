"""Safety and behavior regression tests. Run: python -m unittest discover -s tests -v"""
from __future__ import annotations

import os
import json
import io
from types import SimpleNamespace
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from dpn_optimizer.cleaner import (Root, _safe_root, clean_root, human_bytes,
                                   run_cleanup, roots_for, file_age)
from dpn_optimizer import diagnostics
from dpn_optimizer.diagnostics import (
    ProcessActionError,
    performance_advice,
    performance_health_score,
    terminate_user_process,
)
from dpn_optimizer.cli import make_parser, main
from dpn_optimizer import scheduler
from dpn_optimizer.startup import assess_startup_item
from dpn_optimizer.diskmap import scan_disk_usage, scan_file_insights


class DiskMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'big').mkdir()
        (self.root / 'big' / 'a.bin').write_bytes(b'x' * 300)
        (self.root / 'small').mkdir()
        (self.root / 'small' / 'b.bin').write_bytes(b'x' * 100)
        (self.root / 'loose.bin').write_bytes(b'x' * 50)

    def test_groups_sizes_and_ranks_files(self):
        result = scan_disk_usage(self.root)
        self.assertEqual(result['total_bytes'], 450)
        self.assertEqual([f['name'] for f in result['folders']], ['big', 'small', '(files in root)'])
        self.assertEqual(result['largest_files'][0]['bytes'], 300)
        self.assertFalse(result['truncated'])

    def test_scan_is_read_only(self):
        scan_disk_usage(self.root)
        self.assertTrue((self.root / 'big' / 'a.bin').exists())
        self.assertEqual((self.root / 'loose.bin').stat().st_size, 50)

    def test_cancel_marks_truncated(self):
        result = scan_disk_usage(self.root, cancelled=lambda: True)
        self.assertTrue(result['truncated'])

    def test_missing_root_raises(self):
        with self.assertRaises(ValueError):
            scan_disk_usage(self.root / 'nope')

    def test_symlinked_folder_not_followed(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(outside, ignore_errors=True))
        (outside / 'secret.bin').write_bytes(b'x' * 999)
        try:
            (self.root / 'link').symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Cannot create symlinks')
        self.assertEqual(scan_disk_usage(self.root)['total_bytes'], 450)


class FileInsightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'first.bin').write_bytes(b'A' * 64)
        (self.root / 'second.bin').write_bytes(b'A' * 64)
        (self.root / 'different.bin').write_bytes(b'B' * 64)
        (self.root / 'small.bin').write_bytes(b'A' * 8)

    def test_finds_exact_duplicates_and_reclaimable_size(self):
        result = scan_file_insights(self.root, min_size=32)
        self.assertEqual(result['duplicate_groups'], 1)
        self.assertEqual(result['duplicates'][0]['bytes_each'], 64)
        self.assertEqual(result['duplicates'][0]['reclaimable_bytes'], 64)
        self.assertEqual(len(result['duplicates'][0]['paths']), 2)
        self.assertEqual(result['reclaimable_bytes'], 64)

    def test_same_size_different_content_is_not_duplicate(self):
        result = scan_file_insights(self.root, min_size=32)
        self.assertEqual(result['duplicate_groups'], 1)
        self.assertNotIn('different.bin', result['duplicates'][0]['paths'])

    def test_minimum_size_filters_duplicate_candidates(self):
        result = scan_file_insights(self.root, min_size=65)
        self.assertEqual(result['duplicate_groups'], 0)
        self.assertEqual(result['files_seen'], 4)

    def test_scan_never_modifies_files(self):
        original = (self.root / 'first.bin').read_bytes()
        scan_file_insights(self.root, min_size=1)
        self.assertEqual((self.root / 'first.bin').read_bytes(), original)

    def test_cancelled_scan_is_marked_partial(self):
        result = scan_file_insights(self.root, min_size=1, cancelled=lambda: True)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['files_seen'], 0)

    def test_candidate_limit_marks_partial(self):
        result = scan_file_insights(self.root, min_size=1, max_candidates=1)
        self.assertTrue(result['truncated'])

    def test_symlinked_files_are_skipped(self):
        outside = self.root.parent / (self.root.name + '-outside.bin')
        outside.write_bytes(b'A' * 64)
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        link = self.root / 'linked.bin'
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest('Cannot create symlinks')
        result = scan_file_insights(self.root, min_size=1)
        self.assertFalse(any(item['path'] == str(link) for item in result['largest_files']))
        self.assertEqual(result['files_seen'], 4)

    def test_invalid_minimum_size_rejected(self):
        with self.assertRaises(ValueError):
            scan_file_insights(self.root, min_size=-1)

    def test_hardlinks_do_not_overstate_reclaimable_bytes(self):
        hardlink = self.root / 'hardlink.bin'
        try:
            os.link(self.root / 'first.bin', hardlink)
        except OSError:
            self.skipTest('Cannot create hardlinks')
        result = scan_file_insights(self.root, min_size=32)
        group = result['duplicates'][0]
        self.assertEqual(len(group['paths']), 3)
        self.assertEqual(group['reclaimable_bytes'], 64)


class CleanerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Temp'
        self.root.mkdir()
        self.old = self.root / 'old.tmp'
        self.old.write_bytes(b'A' * 64)
        os.utime(self.old, (time.time() - 200000, time.time() - 200000))
        self.cutoff = time.time() - 48 * 3600
        self.folder = Root('user_temp', 'Test Temp', self.root)
        # Windows st_ctime is file creation time; fresh test fixtures must
        # simulate an existing old file to exercise deletion deterministically.
        mtime_only = patch('dpn_optimizer.cleaner.file_age', side_effect=lambda st: st.st_mtime)
        mtime_only.start()
        self.addCleanup(mtime_only.stop)

    def test_preview_does_not_delete(self):
        result = clean_root(self.folder, cutoff=self.cutoff, apply=False)
        self.assertEqual(result['eligible_files'], 1)
        self.assertEqual(result['deleted_files'], 0)
        self.assertTrue(self.old.exists())

    def test_apply_removes_old_files(self):
        result = clean_root(self.folder, cutoff=self.cutoff, apply=True)
        self.assertEqual(result['deleted_files'], 1)
        self.assertEqual(result['deleted_bytes'], 64)
        self.assertFalse(self.old.exists())
        self.assertTrue(self.root.exists())

    def test_recent_files_preserved(self):
        new = self.root / 'recent.tmp'
        new.write_bytes(b'new')
        result = clean_root(self.folder, cutoff=self.cutoff, apply=True)
        self.assertTrue(new.exists())
        self.assertEqual(result['skipped_recent'], 1)

    def test_nested_dirs_remove_only_when_empty(self):
        child = self.root / 'nested'
        child.mkdir()
        old_nested = child / 'old.log'
        old_nested.write_bytes(b'X')
        os.utime(old_nested, (time.time() - 200000, time.time() - 200000))
        result = clean_root(self.folder, cutoff=self.cutoff, apply=True)
        self.assertEqual(result['deleted_files'], 2)
        self.assertFalse(child.exists())
        self.assertTrue(self.root.exists())

    def test_symlink_file_skipped_and_target_preserved(self):
        target = Path(self.temp.name) / 'private.log'
        target.write_text('Do not erase')
        link = self.root / 'old_link.log'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Cannot create symlinks')
        result = clean_root(self.folder, cutoff=self.cutoff, apply=True)
        self.assertTrue(target.exists())
        self.assertTrue(link.is_symlink())
        self.assertEqual(result['skipped_links'], 1)

    def test_symlink_directory_never_traversed(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        secret = outside / 'secret.tmp'
        secret.write_text('Keep')
        os.utime(secret, (time.time() - 200000, time.time() - 200000))
        link = self.root / 'fake_dir'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Cannot create symlinks')
        clean_root(self.folder, cutoff=self.cutoff, apply=True)
        self.assertTrue(secret.exists())
        self.assertTrue(link.is_symlink())

    def test_root_link_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        linked = Path(self.temp.name) / 'link'
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Cannot create symlinks')
        res = clean_root(Root('user_temp', 'linked', linked), self.cutoff, True)
        self.assertEqual(res['deleted_files'], 0)
        self.assertTrue(self.old.exists())

    def test_cancel_stops_before_deletion(self):
        res = clean_root(self.folder, self.cutoff, True, cancelled=lambda: True)
        self.assertEqual(res['deleted_files'], 0)
        self.assertTrue(self.old.exists())

    def test_unknown_categories_rejected(self):
        with self.assertRaises(ValueError):
            roots_for(['user_temp', 'Documents'])

    def test_age_out_of_range(self):
        with self.assertRaises(ValueError):
            run_cleanup(['user_temp'], age_hours=0.5)

    def test_empty_categories_rejected(self):
        with self.assertRaises(ValueError):
            run_cleanup([], age_hours=48)

    def test_path_outside_base_rejected(self):
        outside = Path(self.temp.name).parent
        self.assertIsNone(_safe_root(outside, self.root))

    def test_safe_child_root(self):
        self.assertEqual(_safe_root(self.root, Path(self.temp.name)), self.root.resolve())

    def test_linked_subfolder_of_allowed_base_rejected(self):
        linked = Path(self.temp.name) / 'linked'
        try:
            linked.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Cannot create symlinks')
        self.assertIsNone(_safe_root(linked, Path(self.temp.name)))

    def test_run_report_and_no_deletion_preview(self):
        with patch('dpn_optimizer.cleaner.roots_for', return_value=([self.folder], [])), \
             patch('dpn_optimizer.cleaner.save_report', return_value=Path('fake')):
            report = run_cleanup(['user_temp'], age_hours=48, apply=False)
        self.assertEqual(report['totals']['eligible_bytes'], 64)
        self.assertEqual(report['totals']['deleted_files'], 0)
        self.assertTrue(self.old.exists())

    def test_run_report_apply(self):
        with patch('dpn_optimizer.cleaner.roots_for', return_value=([self.folder], [])), \
             patch('dpn_optimizer.cleaner.save_report', return_value=Path('fake')):
            report = run_cleanup(['user_temp'], age_hours=48, apply=True)
        self.assertEqual(report['totals']['deleted_bytes'], 64)
        self.assertFalse(self.old.exists())

    def test_browser_guard(self):
        self.folder = Root('browser_cache', 'browser', self.root)
        with patch('dpn_optimizer.cleaner.roots_for', return_value=([self.folder], [])), \
             patch('dpn_optimizer.cleaner.browsers_running', return_value=(True, 'chrome.exe')), \
             patch('dpn_optimizer.cleaner.save_report', return_value=Path('fake')):
            report = run_cleanup(['browser_cache'], age_hours=48, apply=True)
        self.assertEqual(report['roots_scanned'], 0)
        self.assertTrue(self.old.exists())
        self.assertIn('chrome.exe', report['skipped'][0])

    def test_recent_mtime_even_when_old_file(self):
        os.utime(self.old, None)
        result = clean_root(self.folder, self.cutoff, True)
        self.assertEqual(result['deleted_files'], 0)


class AuxiliaryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows creation-time safeguard')
    def test_windows_ctime_guard(self):
        from types import SimpleNamespace
        self.assertEqual(file_age(SimpleNamespace(st_ctime=200, st_mtime=100)), 200)

    def test_human_bytes(self):
        self.assertEqual(human_bytes(1024), '1.0 KB')

    def test_low_disk_advice(self):
        s = {'disk': {'free': 2, 'percent': 99}, 'ram': None,
             'cpu': None, 'monitoring_available': True}
        self.assertIn('Disk space is low', performance_advice(s)[0])

    def test_missing_monitoring_advice(self):
        s = {'disk': None, 'ram': None, 'cpu': None, 'monitoring_available': False}
        self.assertIn('psutil', performance_advice(s)[0])

    def test_performance_health_score_averages_available_headroom(self):
        snapshot = {'cpu': 20, 'ram': {'percent': 40},
                    'disk': {'percent': 60}}
        self.assertEqual(performance_health_score(snapshot), 60)

    def test_performance_health_score_handles_missing_metrics(self):
        self.assertEqual(performance_health_score({'cpu': 25, 'ram': None, 'disk': None}), 75)
        self.assertIsNone(performance_health_score({'cpu': None, 'ram': None, 'disk': None}))

    def test_startup_assessment_flags_known_heavier_app_categories(self):
        result = assess_startup_item('Cloud Sync', r'C:\Apps\OneDrive\OneDrive.exe')
        self.assertEqual(result['impact'], 'Potentially high')
        self.assertEqual(result['publisher'], 'Unknown (not verified)')

    def test_startup_assessment_does_not_invent_impact_for_unknown_apps(self):
        result = assess_startup_item('Local Utility', r'C:\Tools\utility.exe')
        self.assertEqual(result['impact'], 'Unrated')

    def test_cli_preview_is_default_no_apply(self):
        args = make_parser().parse_args(['clean'])
        self.assertFalse(args.apply)
        self.assertEqual(args.categories, ['user_temp'])

    def test_diagnose_json_for_automation(self):
        snapshot = {"os": "Test OS", "hostname": "test-machine", "disk": None,
                    "cpu": None, "ram": None, "top_processes": [],
                    "monitoring_available": False}
        output = io.StringIO()
        with patch('dpn_optimizer.cli.performance_snapshot', return_value=snapshot), \
             redirect_stdout(output):
            exit_code = main(['diagnose', '--json'])
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload['snapshot'], snapshot)
        self.assertTrue(payload['recommendations'])

    def test_default_diagnose_stays_human_readable(self):
        args = make_parser().parse_args(['diagnose'])
        self.assertFalse(args.json)

    def test_scheduler_rejects_bad_time(self):
        missing_path = Path('not-present')
        with patch('dpn_optimizer.scheduler.os.name', 'nt'):
            with self.assertRaises(ValueError):
                scheduler.install_daily(missing_path, '25:80')

    def test_scheduler_command_limited_scope(self):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / 'dpn_system_optimizer.py'
            script.touch()
            with patch('dpn_optimizer.scheduler.os.name', 'nt'), \
                 patch('dpn_optimizer.scheduler.subprocess.run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = 'SUCCESS'
                scheduler.install_daily(script, '09:00')
                command = run.call_args.args[0]
                self.assertEqual(command[0], 'schtasks.exe')
                self.assertIn('/RL', command)
                self.assertIn('LIMITED', command)
                action = command[command.index('/TR') + 1]
                self.assertIn('user_temp', action)
                self.assertNotIn('system_temp', action)
                self.assertIn('--age-hours 48', action)


class ProcessExplorerTests(unittest.TestCase):
    class FakePsutilError(Exception):
        pass

    class FakeProcess:
        def __init__(self, info):
            self.info = info
            self.terminated = False

        def cpu_percent(self, interval=None):
            return self.info.get("cpu_percent", 0)

        def name(self):
            return self.info["name"]

        def username(self):
            return self.info["username"]

        def exe(self):
            return self.info["exe"]

        def create_time(self):
            return self.info["create_time"]

        def is_running(self):
            return True

        def terminate(self):
            self.terminated = True

    def make_psutil(self, process):
        return SimpleNamespace(
            Error=self.FakePsutilError,
            NoSuchProcess=type("NoSuchProcess", (self.FakePsutilError,), {}),
            AccessDenied=type("AccessDenied", (self.FakePsutilError,), {}),
            process_iter=lambda _attrs: [process],
            Process=lambda _pid: process,
        )

    def make_process(self, pid=12345, name="sample.exe",
                     username="WORKSTATION\\Alice",
                     exe=r"C:\Users\Alice\AppData\Local\sample.exe",
                     create_time=123.0, cpu_percent=8.0):
        return self.FakeProcess({
            "pid": pid, "name": name, "username": username, "exe": exe,
            "create_time": create_time, "cpu_percent": cpu_percent,
            "memory_info": SimpleNamespace(rss=1024 * 1024),
            "memory_percent": 1.0, "status": "running",
        })

    def test_process_snapshot_marks_only_verified_user_app_eligible(self):
        process = self.make_process()
        with patch.object(diagnostics, "psutil", self.make_psutil(process)), \
             patch("dpn_optimizer.diagnostics.getpass.getuser", return_value="Alice"):
            result = diagnostics.list_process_details()
        self.assertEqual(result[0]["pid"], 12345)
        self.assertEqual(result[0]["ram_bytes"], 1024 * 1024)
        self.assertTrue(result[0]["can_end"])

    def test_termination_requires_matching_process_identity(self):
        process = self.make_process()
        with patch.object(diagnostics, "psutil", self.make_psutil(process)), \
             patch("dpn_optimizer.diagnostics.getpass.getuser", return_value="Alice"), \
             patch("dpn_optimizer.diagnostics.os.getpid", return_value=99999):
            terminate_user_process(12345, "sample.exe", 123.0, "Alice")
        self.assertTrue(process.terminated)

    def test_termination_rejects_windows_components(self):
        process = self.make_process(
            name="svchost.exe", exe=r"C:\Windows\System32\svchost.exe"
        )
        with patch.object(diagnostics, "psutil", self.make_psutil(process)), \
             patch("dpn_optimizer.diagnostics.getpass.getuser", return_value="Alice"), \
             patch("dpn_optimizer.diagnostics.os.getpid", return_value=99999):
            with self.assertRaises(ProcessActionError):
                terminate_user_process(12345, "svchost.exe", 123.0, "Alice")
        self.assertFalse(process.terminated)

    def test_termination_rejects_changed_process(self):
        process = self.make_process(username="WORKSTATION\\Bob")
        with patch.object(diagnostics, "psutil", self.make_psutil(process)), \
             patch("dpn_optimizer.diagnostics.getpass.getuser", return_value="Alice"), \
             patch("dpn_optimizer.diagnostics.os.getpid", return_value=99999):
            with self.assertRaises(ProcessActionError):
                terminate_user_process(12345, "sample.exe", 123.0, "Alice")
        self.assertFalse(process.terminated)


if __name__ == '__main__':
    unittest.main()
