"""Exercise the shipped clock and the complete isolated database lifecycle in new processes."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from queue import Queue

from entrant_slice.sandbox import MIGRATION, ROOT, connect


class EntrantLocalCommands(unittest.TestCase):
    def test_rebuild_and_unattended_clock_recover_after_a_real_busy_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "entrant-commands"
            command = [sys.executable, "-B", "-m", "entrant_slice", "--workspace", str(workspace)]
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

            def invoke(*args):
                result = subprocess.run(
                    command + list(args),
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    encoding="utf-8",
                    timeout=35,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout

            def migration_state():
                with closing(connect(workspace)) as conn:
                    return (
                        [
                            tuple(r)
                            for r in conn.execute(
                                "SELECT name,applied_at FROM entrant_schema_migration"
                            )
                        ],
                        conn.execute("SELECT COUNT(*) FROM entrant_event").fetchone()[0],
                    )

            invoke("init")
            version, event_count = migration_state()
            self.assertEqual(([r[0] for r in version], event_count), ([MIGRATION], 0))
            invoke("init")
            self.assertEqual(migration_state(), (version, 0))
            invoke("demo", "--seconds", "1")
            with closing(connect(workspace)) as locker:
                event_id = locker.execute("SELECT event_id FROM entrant_event").fetchone()[0]
                locker.execute("BEGIN IMMEDIATE")
                clock = subprocess.Popen(
                    command + ["watch", "--interval", "0.12"],
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                )
                assert clock.stdout is not None
                output = clock.stdout
                messages: Queue[str] = Queue()

                def read_clock():
                    for line in output:
                        messages.put(line)

                reader = threading.Thread(target=read_clock, daemon=True)
                reader.start()
                try:
                    self.assertIn("留待下次到期检查", messages.get(timeout=30))
                    self.assertIsNone(clock.poll())
                    self.assertEqual(
                        locker.execute("SELECT COUNT(*) FROM formation_batch").fetchone()[0], 0
                    )
                    locker.rollback()
                    self.assertIn("已完成 1 届分队", messages.get(timeout=12))
                finally:
                    clock.terminate()
                    clock.wait(timeout=10)
                    reader.join(timeout=5)
                    output.close()

            status = json.loads(invoke("status", "--event", str(event_id)))
            self.assertEqual(len(status["参赛名单"]), 2)
            self.assertTrue(
                all(
                    len(r["current_player_ids"]) == 5 and not r["initial_player_ids"]
                    for r in status["参赛名单"]
                )
            )
            self.assertIn("已完成 0 届分队", invoke("due"))
            invoke("init")
            self.assertEqual(migration_state(), (version, 1))
            invoke("remove")
            self.assertFalse(workspace.exists())
            invoke("init")
            rebuilt, event_count = migration_state()
            self.assertEqual(([r[0] for r in rebuilt], event_count), ([MIGRATION], 0))
            invoke("remove")
            self.assertFalse(workspace.exists())
