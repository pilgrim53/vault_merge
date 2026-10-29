#!/usr/bin/env python3
"""Local mock filesystem tests. Does not access the user's phone or Drive."""
import importlib.util
import contextlib
import io
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
watch_spec = importlib.util.spec_from_file_location("pkm_watch", Path(__file__).with_name("pkm-watch.py"))
watch = importlib.util.module_from_spec(watch_spec)
sys.modules[watch_spec.name] = watch
watch_spec.loader.exec_module(watch)


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

    def test_external_source_wins_even_with_older_timestamp(self):
        self.write(self.master, "External/Google_Drive/news.md", "new local", 2000)
        self.write(self.muse, "news.md", "old remote", 1000)
        job = self.job()
        job.apply()
        self.assertEqual((self.master / "External/Google_Drive/news.md").read_text(), "old remote")
        self.assertEqual((job.backup / "master/External/Google_Drive/news.md").read_text(), "new local")

    def test_external_source_wins_with_ambiguous_timestamps(self):
        self.write(self.master, "External/Google_Drive/news.md", "local", 1000)
        self.write(self.muse, "news.md", "remote", 1001)
        self.job().apply()
        self.assertEqual((self.master / "External/Google_Drive/news.md").read_text(), "remote")

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

    def test_case_only_master_files_stop_before_any_phone_scan(self):
        self.write(self.master, "Games/Trinity Journal.md", "one")
        self.write(self.master, "Games/trinity journal.md", "different")
        with patch.object(sync, "scan", wraps=sync.scan) as scanner:
            with self.assertRaisesRegex(sync.SyncError, "Case-colliding"):
                self.job()
        self.assertEqual(scanner.call_count, 1)
        self.assertFalse((self.state.parent / "active-run.json").exists())

    def test_case_only_master_directories_rejected(self):
        self.write(self.master, "Games/a.md", "one")
        self.write(self.master, "games/b.md", "two")
        with self.assertRaisesRegex(sync.SyncError, "Case-colliding"):
            self.job()

    def test_case_only_file_directory_pair_rejected(self):
        self.write(self.master, "Folder", "file")
        self.write(self.master, "folder/a.md", "child")
        with self.assertRaisesRegex(sync.SyncError, "Case-colliding"):
            self.job()

    def test_drive_case_collision_rejected_before_import(self):
        self.write(self.master, "External/Google_Drive/News.md", "master")
        self.write(self.muse, "news.md", "source")
        with self.assertRaisesRegex(sync.SyncError, "aggregated vault"):
            self.job()
        self.assertFalse((self.master / "External/Google_Drive/news.md").exists())

    def test_phone_journal_case_collision_rejected_before_import(self):
        self.job().apply()
        self.write(self.master, "External/Journal/Day.md", "master")
        self.write(self.phone, "External/Journal/day.md", "source")
        with self.assertRaisesRegex(sync.SyncError, "aggregated vault"):
            self.job(initial=False)
        self.assertFalse((self.master / "External/Journal/day.md").exists())

    def test_legacy_plan_case_collision_rejected_on_apply(self):
        self.write(self.master, "note.md", "one")
        job = self.job()
        other = self.write(self.master, "Note.md", "two")
        job.desired["Note.md"] = sync.inspect(other)
        with self.assertRaisesRegex(sync.SyncError, "planned vault"):
            job.apply()
        self.assertFalse((self.phone / "note.md").exists())

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

    def test_gui_approval_reviews_actual_plan(self):
        self.write(self.master, "note.md", "new")
        job = self.job()
        def approve(command, **kwargs):
            review = Path(next(a.split("=", 1)[1] for a in command if a.startswith("--filename=")))
            text = review.read_text()
            self.assertIn("PHONE ADD note.md", text)
            self.assertIn("original", text.lower())
            self.assertTrue(any(a.startswith("--checkbox=") for a in command))
            return sync.subprocess.CompletedProcess(command, 0)
        with patch.dict(os.environ, {"DISPLAY": ":test"}), \
             patch.object(sync.shutil, "which", return_value="/usr/bin/zenity"), \
             patch.object(sync.subprocess, "run", side_effect=approve):
            self.assertTrue(sync.confirm_gui(job))
        self.assertFalse(self.state.exists())
        self.assertFalse((self.phone / "note.md").exists())

    def test_gui_cancel_grants_no_approval(self):
        job = self.job()
        with patch.dict(os.environ, {"DISPLAY": ":test"}), \
             patch.object(sync.shutil, "which", return_value="/usr/bin/zenity"), \
             patch.object(sync.subprocess, "run",
                          return_value=sync.subprocess.CompletedProcess([], 1)):
            self.assertFalse(sync.confirm_gui(job))
        self.assertFalse(self.state.exists())

    def test_gui_tool_failure_is_not_approval(self):
        job = self.job()
        with patch.dict(os.environ, {"DISPLAY": ":test"}), \
             patch.object(sync.shutil, "which", return_value="/usr/bin/zenity"), \
             patch.object(sync.subprocess, "run",
                          return_value=sync.subprocess.CompletedProcess([], 255)):
            with self.assertRaises(sync.SyncError):
                sync.confirm_gui(job)

    def test_gui_refuses_missing_display(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sync.shutil, "which", return_value="/usr/bin/zenity"):
            with self.assertRaises(sync.SyncError):
                sync.confirm_gui(self.job())

    def test_mount_gate_debounces_and_suppresses_handled_mount(self):
        gate = watch.MountGate()
        self.assertFalse(gate.ready(None, None))
        self.assertFalse(gate.ready("mount-a", None))
        self.assertTrue(gate.ready("mount-a", None))
        self.assertFalse(gate.ready("mount-a", "mount-a"))
        self.assertFalse(gate.ready(None, "mount-a"))
        self.assertFalse(gate.ready("mount-b", "mount-a"))
        self.assertTrue(gate.ready("mount-b", "mount-a"))

    def test_mount_probe_rejects_non_mtp_filesystem(self):
        result = sync.subprocess.CompletedProcess([], 0, stdout="12 ext4 /dev/mock\n", stderr="")
        with patch.object(watch.subprocess, "run", return_value=result):
            self.assertIsNone(watch.mount_identity())

    def test_watcher_does_not_automate_initial_deployment(self):
        with patch.object(watch, "notify"), patch.object(watch.subprocess, "run") as runner:
            self.assertEqual(watch.run_offer(self.root, self.state.parent), "setup-required")
        runner.assert_not_called()

    def test_watcher_runs_gui_regular_sync_after_initial(self):
        self.state.write_text(json.dumps({"initialized": True}))
        result = sync.subprocess.CompletedProcess([], 0)
        with patch.object(watch, "notify") as notify, \
             patch.object(watch.subprocess, "run", return_value=result) as runner:
            self.assertEqual(watch.run_offer(self.root, self.state.parent), "success")
        self.assertIn("--mirror", runner.call_args.args[0])
        self.assertIn("--gui", runner.call_args.args[0])
        self.assertEqual(notify.call_args.args[0], "PKM Sync complete")

    def test_watcher_resumes_existing_cursor(self):
        (self.state.parent / "active-run.json").write_text("{}")
        result = sync.subprocess.CompletedProcess([], 0)
        with patch.object(watch, "notify"), \
             patch.object(watch.subprocess, "run", return_value=result) as runner:
            self.assertEqual(watch.run_offer(self.root, self.state.parent), "unfinished")
        self.assertIn("--resume", runner.call_args.args[0])
        self.assertNotIn("--mirror", runner.call_args.args[0])

    def test_watcher_cancellation_does_not_claim_success(self):
        self.state.write_text(json.dumps({"initialized": True}))
        with patch.object(watch, "notify") as notify, \
             patch.object(watch.subprocess, "run",
                          return_value=sync.subprocess.CompletedProcess([], 3)):
            self.assertEqual(watch.run_offer(self.root, self.state.parent), "cancelled")
        self.assertEqual(notify.call_args.args[0], "PKM Sync cancelled")

    def test_watcher_failure_does_not_claim_success(self):
        self.state.write_text(json.dumps({"initialized": True}))
        with patch.object(watch, "notify") as notify, \
             patch.object(watch.subprocess, "run",
                          return_value=sync.subprocess.CompletedProcess([], 1)):
            self.assertEqual(watch.run_offer(self.root, self.state.parent), "failed")
        self.assertEqual(notify.call_args.args[0], "PKM Sync stopped")
        self.assertTrue(notify.call_args.kwargs["urgent"])

    def test_watcher_remembers_handled_mount(self):
        path = self.state.parent / "watch-state.json"
        watch.remember(path, "mount-token")
        self.assertEqual(watch.read_json(path, {})["handled_mount"], "mount-token")

    def test_phone_mount_token_requires_mtp(self):
        with patch.object(Path, "read_text",
                          return_value="12 1 0:1 / /mnt/android rw - ext4 /dev/mock rw\n"):
            with self.assertRaises(sync.SyncError):
                sync.phone_mount_token()
        with patch.object(Path, "read_text",
                          return_value="13 1 0:2 / /mnt/android rw - fuse.jmtpfs jmtpfs rw\n"):
            self.assertEqual(sync.phone_mount_token(), ("13", "fuse.jmtpfs", "jmtpfs"))

    def test_disconnected_mount_stops_apply_before_content_changes(self):
        self.write(self.master, "new.md", "new")
        job = self.job()
        job.phone_mount_check = lambda: (_ for _ in ()).throw(sync.SyncError("disconnected"))
        with self.assertRaises(sync.SyncError):
            job.apply()
        self.assertFalse((self.phone / "new.md").exists())
        self.assertFalse((self.state.parent / "active-run.json").exists())

    def test_resume_display_reports_only_pending_operations(self):
        self.write(self.master, "a.md", "a")
        self.write(self.master, "b.md", "b")
        self.write(self.phone, "old.md", "old")
        job = self.job()
        job.progress = {"phase": "pushes", "index": 1, "inflight": False}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            job.display()
        text = output.getvalue()
        self.assertIn("MODE: RESUME INITIAL", text)
        self.assertIn("Remaining: 0 imports, 1 phone writes, 1 phone file deletions.", text)
        self.assertNotIn("PHONE ADD a.md", text)
        self.assertIn("PHONE ADD b.md", text)

    def test_verification_cursor_never_lists_completed_deletions(self):
        self.write(self.master, "a.md", "a")
        self.write(self.master, "b.md", "b")
        self.write(self.phone, "old.md", "old")
        job = self.job()
        job.progress = {"phase": "verify", "index": 1, "inflight": False}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            job.display()
        text = output.getvalue()
        self.assertIn("Remaining: 0 imports, 0 phone writes, 0 phone file deletions.", text)
        self.assertIn("1 verification reads", text)
        self.assertNotIn("PHONE DELETE old.md", text)

    def verification_job(self):
        rel = "External/Journal/day.md"
        self.write(self.master, rel, "original")
        self.write(self.phone, rel, "original")
        job = self.job()
        job.start_run()
        job.next_phase("verify")
        return sync.Job.resume(self.state)

    def test_reconcile_phone_edit_preserves_both_versions_and_old_cursor(self):
        old = self.verification_job()
        original_plan = (old.backup / "plan.json").read_bytes()
        self.write(self.phone, "External/Journal/day.md", "phone edit")
        job = old.reconciliation()
        self.assertEqual(len(job.imports), 1)
        self.assertFalse(self.state.exists())
        job.apply()
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "phone edit")
        self.assertEqual((job.backup / "master/External/Journal/day.md").read_text(), "original")
        self.assertEqual((job.backup / "reconciliation/phone/External/Journal/day.md").read_text(),
                         "phone edit")
        self.assertEqual(json.loads((job.backup / "superseded-active-run.json").read_text()),
                         old.progress)
        self.assertEqual((old.backup / "plan.json").read_bytes(), original_plan)
        self.assertTrue(json.loads(self.state.read_text())["initialized"])

    def test_reconcile_preview_leaves_old_cursor_and_vaults_untouched(self):
        old = self.verification_job()
        active = self.state.parent / "active-run.json"
        before = active.read_bytes()
        self.write(self.phone, "External/Journal/day.md", "phone edit")
        old.reconciliation()
        self.assertEqual(active.read_bytes(), before)
        self.assertFalse(self.state.exists())
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "original")

    def test_reconcile_phone_wins_when_both_copies_changed(self):
        old = self.verification_job()
        self.write(self.master, "External/Journal/day.md", "master edit")
        self.write(self.phone, "External/Journal/day.md", "phone edit")
        job = old.reconciliation()
        job.apply()
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "phone edit")
        self.assertEqual((job.backup / "master/External/Journal/day.md").read_text(), "master edit")

    def test_reconcile_phone_wins_even_if_only_master_was_edited(self):
        old = self.verification_job()
        self.write(self.master, "External/Journal/day.md", "master edit")
        job = old.reconciliation()
        self.assertEqual(len(job.imports), 1)
        job.apply()
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "original")
        self.assertEqual((job.backup / "master/External/Journal/day.md").read_text(), "master edit")

    def test_reconcile_same_edit_on_both_copies_needs_no_transfer(self):
        old = self.verification_job()
        self.write(self.master, "External/Journal/day.md", "same edit")
        self.write(self.phone, "External/Journal/day.md", "same edit")
        job = old.reconciliation()
        self.assertFalse(job.imports)
        self.assertFalse(job.pushes)
        job.apply()

    def test_reconcile_new_phone_entry_imported_without_timestamp_guessing(self):
        old = self.verification_job()
        self.write(self.phone, "External/Journal/new.md", "new entry", 10)
        job = old.reconciliation()
        job.apply()
        self.assertEqual((self.master / "External/Journal/new.md").read_text(), "new entry")

    def test_reconcile_missing_phone_file_is_restored_from_master(self):
        old = self.verification_job()
        (self.phone / "External/Journal/day.md").unlink()
        job = old.reconciliation()
        job.apply()
        self.assertEqual((self.phone / "External/Journal/day.md").read_text(), "original")

    def test_reconcile_master_move_not_resurrected_from_unchanged_phone(self):
        old = self.verification_job()
        (self.master / "External/Journal/day.md").rename(self.master / "moved.md")
        job = old.reconciliation()
        self.assertFalse(job.imports)
        job.apply()
        self.assertFalse((self.master / "External/Journal/day.md").exists())
        self.assertEqual((self.phone / "moved.md").read_text(), "original")

    def test_reconcile_new_phone_version_imports_after_master_move(self):
        old = self.verification_job()
        (self.master / "External/Journal/day.md").rename(self.master / "moved.md")
        self.write(self.phone, "External/Journal/day.md", "phone edit")
        old.reconciliation().apply()
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "phone edit")
        self.assertEqual((self.master / "moved.md").read_text(), "original")

    def test_phone_receipt_does_not_block_source_winning_existing_target(self):
        self.write(self.master, "External/Journal/day.md", "original")
        self.job().apply()
        self.write(self.master, "External/Journal/day.md", "master edited", 3000)
        job = self.job(initial=False)
        job.apply()
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "original")

    def test_drive_receipt_does_not_block_source_winning_existing_target(self):
        self.write(self.muse, "news.md", "source")
        self.job().apply()
        self.write(self.master, "External/Google_Drive/news.md", "master edited", 3000)
        self.job(initial=False).apply()
        self.assertEqual((self.master / "External/Google_Drive/news.md").read_text(), "source")

    def test_reconcile_rejects_nonverification_or_inflight_cursor(self):
        old = self.verification_job()
        old.progress["phase"] = "imports"
        with self.assertRaises(sync.SyncError):
            old.reconciliation()
        old.progress.update(phase="verify", inflight=True)
        with self.assertRaises(sync.SyncError):
            old.reconciliation()

    def interrupted_game_write(self, replacing=False):
        self.write(self.master, "External/Journal/day.md", "journal")
        self.write(self.phone, "External/Journal/day.md", "journal")
        self.write(self.master, "Games/note.md", "complete master")
        if replacing:
            self.write(self.phone, "Games/note.md", "original phone")
        job = self.job()
        def fail_write(source, destination, expected):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text("partial")
            raise OSError("simulated interrupted transfer")
        with patch.object(sync, "copy_phone_checked", side_effect=fail_write):
            with self.assertRaises(OSError):
                job.apply()
        self.assertEqual(job.progress["phase"], "pushes")
        self.assertTrue(job.progress["inflight"])
        return sync.Job.resume(self.state)

    def test_reconcile_interrupted_nonjournal_write_after_source_rename(self):
        old = self.interrupted_game_write()
        (self.master / "Games/note.md").rename(self.master / "Games/distinct-name.md")
        self.write(self.phone, "External/Journal/day.md", "new phone journal")
        job = old.reconciliation()
        self.assertEqual(json.loads((self.state.parent / "active-run.json").read_text()),
                         old.progress)
        job.apply()
        self.assertEqual((self.phone / "Games/distinct-name.md").read_text(), "complete master")
        self.assertFalse((self.phone / "Games/note.md").exists())
        self.assertEqual((job.backup / "phone/Games/note.md").read_text(), "partial")
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "new phone journal")
        self.assertTrue(json.loads((job.backup / "superseded-active-run.json").read_text())["inflight"])

    def test_reconcile_interrupted_replace_retains_original_old_backup(self):
        old = self.interrupted_game_write(replacing=True)
        saved = old.backup / "phone/Games/note.md"
        self.assertEqual(saved.read_text(), "original phone")
        job = old.reconciliation()
        job.apply()
        self.assertEqual(saved.read_text(), "original phone")
        self.assertEqual((job.backup / "phone/Games/note.md").read_text(), "partial")

    def test_reconcile_interrupted_journal_write_rejected(self):
        old = self.interrupted_game_write()
        rel = "External/Journal/day.md"
        old.pushes = [(rel, sync.inspect(self.master / rel), None)]
        with self.assertRaisesRegex(sync.SyncError, "interrupted Journal write"):
            old.reconciliation()

    def test_reconcile_push_phase_without_inflight_allowed(self):
        old = self.verification_job()
        old.progress.update(phase="pushes", index=0)
        old.checkpoint()
        old.reconciliation().apply()
        self.assertTrue(json.loads(self.state.read_text())["initialized"])

    def test_reconcile_invalid_inflight_cursor_rejected(self):
        old = self.verification_job()
        old.progress.update(phase="pushes", index=len(old.pushes), inflight=True)
        with self.assertRaisesRegex(sync.SyncError, "Invalid in-flight"):
            old.reconciliation()

    def abandoned_alias_job(self, replacing=False):
        old = self.interrupted_game_write(replacing=replacing)
        (self.master / "Games/note.md").unlink()
        self.write(self.master, "Games/Note.md", "wanted distinct contents")
        self.write(self.phone, "Games/Note.md", "wanted distinct contents")
        return old

    def alias_inspector(self, extra_bad=()):
        original = sync.inspect
        bad = {self.phone / "Games/note.md", *extra_bad}
        def checked(path):
            if Path(path) in bad:
                raise OSError(5, "simulated unreadable MTP entry", str(path))
            return original(path)
        return checked

    def test_abandoned_create_alias_recovers_without_reading_or_deleting_it(self):
        old = self.abandoned_alias_job()
        active = self.state.parent / "active-run.json"
        prior = active.read_bytes()
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            job = old.reconciliation()
            self.assertEqual(active.read_bytes(), prior)
            self.assertFalse(self.state.exists())
            self.assertNotIn("Games/note.md", job.deletes)
            job.apply()
        self.assertEqual((self.phone / "Games/note.md").read_text(), "partial")
        self.assertEqual((self.phone / "Games/Note.md").read_text(), "wanted distinct contents")
        state = json.loads(self.state.read_text())
        self.assertEqual(state["abandoned_phone_aliases"]["Games/note.md"]["kept"], "Games/Note.md")
        self.assertEqual(json.loads((job.backup / "superseded-active-run.json").read_text()),
                         old.progress)

    def test_recorded_alias_exception_works_on_next_regular_sync(self):
        old = self.abandoned_alias_job()
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            old.reconciliation().apply()
            normal = self.job(initial=False)
            self.assertFalse(normal.pushes)
            self.assertFalse(normal.deletes)
            normal.apply()

    def test_abandoned_alias_preview_and_success_disclose_mirror_exception(self):
        old = self.abandoned_alias_job()
        output = io.StringIO()
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            job = old.reconciliation()
            with contextlib.redirect_stdout(output):
                job.display()
                job.apply()
        self.assertIn("PHONE ALIAS EXCEPTION", output.getvalue())
        self.assertIn("strict mirror has recorded abandoned-name exceptions", output.getvalue())

    def test_abandoned_replacement_not_eligible_for_alias_exception(self):
        old = self.abandoned_alias_job(replacing=True)
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            with self.assertRaises(OSError):
                old.reconciliation()

    def test_source_still_wanted_does_not_get_alias_exception(self):
        old = self.interrupted_game_write()
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            with self.assertRaises(OSError):
                old.reconciliation()

    def test_unrelated_unreadable_file_still_stops_reconciliation(self):
        old = self.abandoned_alias_job()
        bad = self.write(self.phone, "Games/unrelated.md", "important")
        with patch.object(sync, "inspect", side_effect=self.alias_inspector({bad})):
            with self.assertRaises(OSError):
                old.reconciliation()
        self.assertEqual(json.loads((self.state.parent / "active-run.json").read_text()), old.progress)

    def test_unreadable_retained_alias_still_stops_reconciliation(self):
        old = self.abandoned_alias_job()
        with patch.object(sync, "inspect", side_effect=self.alias_inspector({self.phone / "Games/Note.md"})):
            with self.assertRaises(OSError):
                old.reconciliation()

    def test_alias_canonical_path_is_inspected_when_only_old_name_is_listed(self):
        old = self.abandoned_alias_job()
        (self.phone / "Games/Note.md").unlink()
        source = sync.inspect(self.master / "Games/Note.md")
        original = self.alias_inspector()
        def checked(path):
            if Path(path) == self.phone / "Games/Note.md":
                return sync.Item(Path(path), source.digest, source.size, source.mtime)
            return original(path)
        with patch.object(sync, "inspect", side_effect=checked):
            job = old.reconciliation()
        self.assertEqual(job.phone_files["Games/Note.md"].digest, source.digest)

    def test_alias_exception_does_not_hide_ordinary_mirror_deletions(self):
        old = self.abandoned_alias_job()
        self.write(self.phone, "Games/extra.md", "old extra")
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            job = old.reconciliation()
            self.assertIn("Games/extra.md", job.deletes)
            job.apply()
        self.assertEqual((job.backup / "phone/Games/extra.md").read_text(), "old extra")

    def test_recorded_exception_never_applies_to_external_files(self):
        self.write(self.master, "External/Journal/Day.md", "journal")
        bad = self.write(self.phone, "External/Journal/day.md", "unreadable journal")
        state = {
            "initialized": True, "receipts": {}, "abandoned_phone_aliases": {
                "External/Journal/day.md": {"kept": "External/Journal/Day.md", "origin_run": "old"}
            }
        }
        self.state.write_text(json.dumps(state))
        with patch.object(sync, "inspect", side_effect=self.alias_inspector({bad})):
            with self.assertRaises(OSError):
                self.job(initial=False)

    def test_recorded_exception_cannot_bypass_reintroduced_source_collision(self):
        old = self.abandoned_alias_job()
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            old.reconciliation().apply()
        self.write(self.master, "Games/note.md", "new content")
        with self.assertRaisesRegex(sync.SyncError, "Case-colliding"):
            self.job(initial=False)

    def test_abandoned_alias_recovery_can_resume_with_exception_preserved(self):
        old = self.abandoned_alias_job()
        self.write(self.master, "new.md", "new")
        with patch.object(sync, "inspect", side_effect=self.alias_inspector()):
            job = old.reconciliation()
            self.assertFalse(job.apply(batch_size=1, pause_after_batch=True))
            resumed = sync.Job.resume(self.state)
            resumed.apply()
        self.assertIn("Games/note.md", json.loads(self.state.read_text())["abandoned_phone_aliases"])

    def test_reconcile_cursor_changed_since_preview_stops_before_mutation(self):
        old = self.verification_job()
        self.write(self.phone, "External/Journal/day.md", "phone edit")
        job = old.reconciliation()
        old.progress["index"] = 1
        old.checkpoint()
        with self.assertRaisesRegex(sync.SyncError, "cursor changed"):
            job.apply()
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "original")

    def test_reconcile_journal_backup_failure_retains_original_cursor(self):
        old = self.verification_job()
        self.write(self.phone, "External/Journal/day.md", "phone edit")
        job = old.reconciliation()
        with patch.object(sync, "copy_checked", side_effect=OSError("backup failed")):
            with self.assertRaisesRegex(OSError, "backup failed"):
                job.apply()
        self.assertEqual(json.loads((self.state.parent / "active-run.json").read_text()),
                         old.progress)
        self.assertEqual((self.master / "External/Journal/day.md").read_text(), "original")

    def test_reconcile_run_can_resume_after_a_batch_pause(self):
        old = self.verification_job()
        self.write(self.phone, "External/Journal/day.md", "phone edit")
        self.write(self.master, "new.md", "new master file")
        job = old.reconciliation()
        self.assertFalse(job.apply(batch_size=1, pause_after_batch=True))
        resumed = sync.Job.resume(self.state)
        self.assertEqual(resumed.reconcile_cursor, old.progress)
        resumed.apply()
        self.assertEqual((self.phone / "new.md").read_text(), "new master file")
        self.assertTrue(json.loads(self.state.read_text())["initialized"])


if __name__ == "__main__":
    unittest.main()
