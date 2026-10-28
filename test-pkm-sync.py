#!/usr/bin/env python3
"""Local mock filesystem tests. Does not access the user's phone or Drive."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("pkm_sync", Path(__file__).with_name("pkm-sync.py"))
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.master = self.root / "master"
        self.phone = self.root / "phone"
        self.muse = self.root / "muse"
        self.state = self.root / "state/state.json"
        self.state.parent.mkdir()
        for p in [self.master / "External/Journal", self.master / "External/Google_Drive",
                  self.phone / "External/Journal", self.muse]:
            p.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, root, rel, text, stamp=1000):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        os.utime(path, (stamp, stamp))
        return path

    def job(self, initial=True, mirror=True):
        job = sync.Job(self.master, self.phone, self.muse, self.state, initial, mirror)
        job.plan()
        return job

    def test_preview_changes_no_content(self):
        self.write(self.muse, "news.md", "news")
        self.write(self.phone, "old.md", "phone")
        job = self.job()
        self.assertEqual(len(job.imports), 1)
        self.assertEqual(job.deletes, ["old.md"])
        self.assertFalse((self.master / "External/Google_Drive/news.md").exists())
        self.assertTrue((self.phone / "old.md").exists())
        self.assertFalse(self.state.exists())

    def test_initial_skips_phone_import_and_backs_up_replacement_and_deletion(self):
        self.write(self.master, "note.md", "master")
        self.write(self.phone, "note.md", "old phone")
        self.write(self.phone, "Journal/unwanted.md", "do not import")
        job = self.job()
        job.apply()
        self.assertEqual((self.phone / "note.md").read_text(), "master")
        self.assertFalse((self.phone / "Journal").exists())
        self.assertFalse((self.master / "External/Journal/unwanted.md").exists())
        self.assertEqual((job.backup / "phone/note.md").read_text(), "old phone")
        self.assertEqual((job.backup / "phone/Journal/unwanted.md").read_text(), "do not import")

    def test_protected_settings_and_desktop_directories(self):
        self.write(self.master, ".obsidian/config.json", "desktop")
        self.write(self.phone, ".obsidian/config.json", "mobile")
        self.write(self.master, ".opencode/secret", "secret")
        self.write(self.phone, ".opencode/existing", "keep excluded")
        self.job().apply()
        self.assertEqual((self.phone / ".obsidian/config.json").read_text(), "mobile")
        self.assertFalse((self.phone / ".opencode/secret").exists())
        self.assertTrue((self.phone / ".opencode/existing").exists())

    def test_newer_phone_update_and_destination_only_retention(self):
        self.write(self.master, "External/Journal/day.md", "old", 1000)
        self.write(self.master, "External/Journal/local-only.md", "local", 1000)
        self.job().apply()
        self.write(self.phone, "External/Journal/day.md", "new from phone", 2000)
        job = self.job(initial=False)
        job.apply()
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "new from phone")
        self.assertTrue((self.master / "External/Journal/local-only.md").exists())
        self.assertEqual((job.backup / "master/External/Journal/day.md").read_text(), "old")

    def test_older_source_never_overwrites_newer_master(self):
        self.write(self.master, "External/Google_Drive/news.md", "new local", 2000)
        self.write(self.muse, "news.md", "old remote", 1000)
        job = self.job()
        job.apply()
        self.assertEqual((self.master / "External/Google_Drive/news.md").read_text(), "new local")

    def test_changed_source_ambiguous_timestamps_abort(self):
        self.write(self.master, "External/Google_Drive/news.md", "local", 1000)
        self.write(self.muse, "news.md", "remote", 1001)
        with self.assertRaises(sync.SyncError):
            self.job()
        self.assertFalse(self.state.exists())

    def test_repeat_run_and_moved_import_do_not_resurrect(self):
        self.write(self.muse, "news.md", "remote")
        self.job().apply()
        self.assertEqual(len(self.job(initial=False).imports), 0)
        (self.master / "News").mkdir()
        (self.master / "External/Google_Drive/news.md").rename(self.master / "News/news.md")
        job = self.job(initial=False)
        self.assertEqual(len(job.imports), 0)
        job.apply()
        self.assertFalse((self.master / "External/Google_Drive/news.md").exists())
        self.assertFalse((self.phone / "External/Google_Drive/news.md").exists())
        self.assertTrue((self.phone / "News/news.md").exists())

    def test_source_changed_after_plan_aborts_before_writes(self):
        self.write(self.muse, "news.md", "remote")
        job = self.job()
        self.write(self.muse, "news.md", "changed", 2000)
        with self.assertRaises(sync.SyncError):
            job.apply()
        self.assertFalse((self.master / "External/Google_Drive/news.md").exists())
        self.assertFalse(self.state.exists())

    def test_without_mirror_destination_only_phone_files_survive(self):
        self.write(self.phone, "extra.md", "retain")
        self.job(mirror=False).apply()
        self.assertTrue((self.phone / "extra.md").exists())

    def test_symlink_rejected(self):
        (self.master / "link").symlink_to(self.muse, target_is_directory=True)
        with self.assertRaises(sync.SyncError):
            self.job()

    def test_regular_requires_initial_success(self):
        with self.assertRaises(sync.SyncError):
            self.job(initial=False)

    def test_file_directory_collision_aborts(self):
        self.write(self.master, "path/child.md", "child")
        self.write(self.phone, "path", "blocking file")
        with self.assertRaises(sync.SyncError):
            self.job()

    def test_do_not_repeat_initial_after_success(self):
        self.job().apply()
        with self.assertRaises(sync.SyncError):
            self.job(initial=True)

    def test_failed_import_never_pushes_or_deletes_phone_files(self):
        self.write(self.muse, "news.md", "new source")
        self.write(self.phone, "obsolete.md", "keep if import fails")
        job = self.job()
        with patch.object(sync, "copy_checked", side_effect=OSError("simulated I/O failure")):
            with self.assertRaises(OSError):
                job.apply()
        self.assertTrue((self.phone / "obsolete.md").exists())
        self.assertFalse(self.state.exists())

    def test_changed_drive_version_imported_again(self):
        self.write(self.muse, "news.md", "v1", 1000)
        self.job().apply()
        self.write(self.muse, "news.md", "v2", 2000)
        job = self.job(initial=False)
        job.apply()
        self.assertEqual((self.master / "External/Google_Drive/news.md").read_text(), "v2")
        self.assertEqual((self.phone / "External/Google_Drive/news.md").read_text(), "v2")

    def test_phone_write_never_renames_on_mtp(self):
        self.write(self.master, "note.md", "new")
        self.write(self.phone, "note.md", "old")
        real_replace = os.replace
        def checked_replace(src, dst):
            self.assertFalse(Path(src).is_relative_to(self.phone))
            self.assertFalse(Path(dst).is_relative_to(self.phone))
            return real_replace(src, dst)
        with patch.object(sync.os, "replace", side_effect=checked_replace):
            self.job().apply()
        self.assertEqual((self.phone / "note.md").read_text(), "new")

    def test_batches_resume_without_rescanning_and_finish(self):
        for i in range(7):
            self.write(self.master, f"note{i}.md", str(i))
        job = self.job()
        self.assertFalse(job.apply(batch_size=2, pause_after_batch=True))
        first_backup = job.backup
        self.assertEqual(job.progress["index"], 2)
        passes = 1
        while (self.state.parent / "active-run.json").exists():
            with patch.object(sync, "scan", side_effect=AssertionError("must not rescan")):
                resumed = sync.Job.resume(self.state)
                resumed.apply(batch_size=2, pause_after_batch=True)
            self.assertEqual(resumed.backup, first_backup)
            passes += 1
            self.assertLess(passes, 20)
        self.assertTrue(json.loads(self.state.read_text())["initialized"])
        for i in range(7):
            self.assertEqual((self.phone / f"note{i}.md").read_text(), str(i))

    def test_partial_phone_write_resumes_without_losing_original_backup(self):
        self.write(self.master, "note.md", "new complete")
        self.write(self.phone, "note.md", "precious original")
        job = self.job()
        def broken_copy(src, dst, digest):
            dst.write_text("partial")
            raise OSError(24, "Too many open files")
        with patch.object(sync, "copy_phone_checked", side_effect=broken_copy):
            with self.assertRaises(OSError):
                job.apply()
        self.assertTrue(job.progress["inflight"])
        resumed = sync.Job.resume(self.state)
        self.assertTrue(resumed.apply())
        self.assertEqual((self.phone / "note.md").read_text(), "new complete")
        self.assertEqual((job.backup / "phone/note.md").read_text(), "precious original")

    def test_missing_original_backup_refuses_partial_retry(self):
        self.write(self.master, "note.md", "new")
        self.write(self.phone, "note.md", "old")
        job = self.job()
        with patch.object(sync, "copy_phone_checked", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                job.apply()
        (job.backup / "phone/note.md").unlink()
        with self.assertRaises(sync.SyncError):
            sync.Job.resume(self.state).apply()
        self.assertEqual((self.phone / "note.md").read_text(), "old")

    def test_completed_write_with_unadvanced_cursor_retries_safely(self):
        self.write(self.master, "note.md", "new")
        self.write(self.phone, "note.md", "old")
        job = self.job()
        with patch.object(job, "end_operation", side_effect=OSError("checkpoint interrupted")):
            with self.assertRaises(OSError):
                job.apply()
        self.assertEqual((self.phone / "note.md").read_text(), "new")
        resumed = sync.Job.resume(self.state)
        resumed.apply()
        self.assertEqual((job.backup / "phone/note.md").read_text(), "old")

    def test_cursor_prevents_new_run_over_active_run(self):
        self.write(self.master, "note.md", "new")
        self.write(self.phone, "extra.md", "old")
        self.assertFalse(self.job().apply(batch_size=1, pause_after_batch=True))
        other = self.job()
        with self.assertRaises(sync.SyncError):
            other.apply()

    def test_master_change_between_batches_stops_resume(self):
        self.write(self.master, "note.md", "new")
        self.write(self.phone, "extra.md", "old")
        self.assertFalse(self.job().apply(batch_size=1, pause_after_batch=True))
        self.write(self.master, "note.md", "edited meanwhile")
        with self.assertRaises(sync.SyncError):
            sync.Job.resume(self.state).apply()
        self.assertTrue((self.phone / "extra.md").exists())

    def test_deleted_file_with_unadvanced_cursor_retries_safely(self):
        self.write(self.phone, "extra.md", "original")
        job = self.job()
        with patch.object(job, "end_operation", side_effect=OSError("checkpoint interrupted")):
            with self.assertRaises(OSError):
                job.apply()
        self.assertFalse((self.phone / "extra.md").exists())
        sync.Job.resume(self.state).apply()
        self.assertEqual((job.backup / "phone/extra.md").read_text(), "original")

    def test_partial_new_phone_file_can_resume(self):
        self.write(self.master, "new.md", "complete")
        job = self.job()
        def broken_copy(src, dst, digest):
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text("partial")
            raise OSError(24, "Too many open files")
        with patch.object(sync, "copy_phone_checked", side_effect=broken_copy):
            with self.assertRaises(OSError):
                job.apply()
        sync.Job.resume(self.state).apply()
        self.assertEqual((self.phone / "new.md").read_text(), "complete")

    def test_default_batches_continue_to_success_without_input(self):
        for i in range(5):
            self.write(self.master, f"note{i}.md", str(i))
        job = self.job()
        with patch("builtins.input", side_effect=AssertionError("no batch prompts allowed")):
            self.assertTrue(job.apply(batch_size=1))
        self.assertFalse((self.state.parent / "active-run.json").exists())
        self.assertTrue(json.loads(self.state.read_text())["initialized"])

    def test_old_paused_cursor_resumes_with_automatic_batches(self):
        for i in range(5):
            self.write(self.master, f"note{i}.md", str(i))
        job = self.job()
        self.assertFalse(job.apply(batch_size=1, pause_after_batch=True))
        resumed = sync.Job.resume(self.state)
        with patch("builtins.input", side_effect=AssertionError("no batch prompts allowed")):
            self.assertTrue(resumed.apply(batch_size=1))
        self.assertFalse((self.state.parent / "active-run.json").exists())

    def test_phone_discovery_uses_single_vault_without_embedded_username(self):
        documents = self.root / "Documents"
        (documents / "Personal Vault/.obsidian").mkdir(parents=True)
        self.assertEqual(sync.resolve_phone_vault(documents=documents),
                         documents / "Personal Vault")

    def test_phone_discovery_refuses_ambiguous_vaults(self):
        documents = self.root / "Documents"
        for name in ("Vault A", "Vault B"):
            (documents / name / ".obsidian").mkdir(parents=True)
        with self.assertRaises(sync.SyncError):
            sync.resolve_phone_vault(documents=documents)

    def test_phone_path_override(self):
        self.assertEqual(sync.resolve_phone_vault(str(self.phone)), self.phone)


if __name__ == "__main__":
    unittest.main()
