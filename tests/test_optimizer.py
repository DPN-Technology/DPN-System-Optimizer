"""Safety and behavior regression tests. Run: python -m unittest discover -s tests -v"""
from __future__ import annotations

import os
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from dpn_optimizer.cleaner import (Root, _safe_root, clean_root, human_bytes,
                                   run_cleanup, roots_for, file_age)
from dpn_optimizer.diagnostics import performance_advice, performance_health_score
from dpn_optimizer.cli import make_parser, main
from dpn_optimizer import scheduler
from dpn_optimizer.startup import assess_startup_item
from dpn_optimizer.diskmap import scan_disk_usage


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


if __name__ == '__main__':
    unittest.main()
