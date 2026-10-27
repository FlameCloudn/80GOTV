import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")
if not BASH and shutil.which("git"):
    candidate = Path(shutil.which("git")).resolve().parents[1] / "bin/bash.exe"
    if candidate.is_file():
        BASH = str(candidate)


@unittest.skipUnless(BASH, "需要 Bash 检查部署脚本")
class DeploymentRollbackSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="80gotv-deploy-flow-")
        self.root = Path(self.temp.name)
        self.tools = self.root / "tools"
        self.venv = self.root / "venv"
        self.tools.mkdir()
        (self.venv / "bin").mkdir(parents=True)
        (self.root / "tests").mkdir()
        (self.root / "tests/test_example.py").write_text("", encoding="utf-8")
        self.script = self.root / "update.sh"
        self.script.write_text(
            (ROOT / "deploy/update.sh").read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
        )
        self.candidate_fixture = self.root / "candidate-fixture"
        (self.candidate_fixture / "tests").mkdir(parents=True)
        (self.candidate_fixture / "deploy").mkdir()
        (self.candidate_fixture / "tests/test_example.py").write_text("", encoding="utf-8")
        shutil.copy2(self.script, self.candidate_fixture / "deploy/update.sh")
        self.data = self.root / "data.db"
        self.data.write_text("before\n", encoding="utf-8", newline="\n")
        self.events = self.root / "events.log"
        self.events.touch()
        (self.root / "code-revision").write_text("old", encoding="utf-8")
        self.env_file = self.root / "app.env"
        self.env_file.write_text(
            f"DATABASE_PATH={self.data.as_posix()}\n", encoding="utf-8", newline="\n"
        )
        self._tool("id", 'printf "0\\n"\n')
        self._tool(
            "sudo",
            """if [[ "${1:-}" == "-u" ]]; then shift 2; fi
if [[ "${1:-}" == "--" ]]; then shift; fi
exec "$@"
""",
        )
        self._tool(
            "git",
            """case "$*" in
  *"status --porcelain"*) exit 0 ;;
  *"rev-parse HEAD"*)
    if [[ "$(cat "$APP_DIR/code-revision")" == new ]]; then printf '%040d\\n' 2; else printf '%040d\\n' 1; fi ;;
  *"rev-parse origin/main"*) printf '%040d\\n' 2 ;;
  *"fetch origin"*) echo fetch >> "$EVENTS" ;;
  *"archive "*) echo archive >> "$EVENTS"; tar -cf - -C "$CANDIDATE_FIXTURE" . ;;
  *"merge --ff-only"*) printf new > "$APP_DIR/code-revision"; echo merge >> "$EVENTS" ;;
  *"switch --detach"*) printf old > "$APP_DIR/code-revision"; echo rollback-code >> "$EVENTS" ;;
esac
""",
        )
        self._tool(
            "systemctl",
            """echo "$1" >> "$EVENTS"
if [[ "$1" == start && "$(cat "$APP_DIR/code-revision")" == new ]]; then
  echo after-start >> "$DATA_FILE"
fi
""",
        )
        self._tool(
            "curl",
            """if [[ "$FAIL_STAGE" == health && "$(cat "$APP_DIR/code-revision")" == new ]]; then
  exit 1
fi
""",
        )
        self._tool("sleep", "exit 0\n")
        self._write(
            self.venv / "bin/python",
            """if [[ "$1" == -m && "$2" == venv ]]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
  chmod +x "$3/bin/python"
  echo candidate-environment >> "$EVENTS"
  exit 0
fi
scope=candidate
[[ "$0" != "$VENV_DIR/bin/python" ]] || scope=live
if [[ "$1" == -m && "$2" == pip && "$3" == list ]]; then
  printf 'fixture-dependency==1.0\\n'
  exit 0
fi
if [[ "$1" == -m && "$2" == pip && "$3" == install ]]; then
  echo "pip-$scope" >> "$EVENTS"
  if [[ ! -e "$APP_DIR/preparation-write" ]]; then
    echo during-preparation >> "$DATA_FILE"
    touch "$APP_DIR/preparation-write"
  fi
  if [[ "$FAIL_STAGE" == pip && "$scope" == candidate ]]; then exit 1; fi
  if [[ "$FAIL_STAGE" == live-pip && "$scope" == live && "$(cat "$APP_DIR/code-revision")" == new ]]; then exit 1; fi
  exit 0
fi
if [[ "$1" == -m && "$2" == compileall ]]; then
  echo "syntax-$scope" >> "$EVENTS"
  [[ "$FAIL_STAGE" != syntax ]]
  exit $?
fi
if [[ "$1" == -m && "$2" == unittest ]]; then
  echo tests >> "$EVENTS"
  echo "tests-active-$(cat "$APP_DIR/code-revision")" >> "$EVENTS"
  [[ "$DATABASE_PATH" != "$DATA_FILE" ]] || echo unsafe-test-db >> "$EVENTS"
  [[ "$FAIL_STAGE" != tests ]]
  exit $?
fi
case "$1" in
  */backup_site.py)
    echo backup >> "$EVENTS"
    [[ "$FAIL_STAGE" != backup ]] || exit 1
    cp "$DATA_FILE" "$SNAPSHOT"
    printf '%s\\n' "$SNAPSHOT"
    ;;
  */migrate_database.py)
    echo migrate >> "$EVENTS"
    echo migration-write >> "$DATA_FILE"
    [[ "$FAIL_STAGE" != migration ]] || exit 1
    ;;
  */restore_site.py)
    echo restore-database >> "$EVENTS"
    cp "$SNAPSHOT" "$DATA_FILE"
    ;;
esac
""",
        )

    @staticmethod
    def _write(path, body):
        path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def _tool(self, name, body):
        self._write(self.tools / name, body)

    def tearDown(self):
        self.temp.cleanup()

    def _run(self, failure):
        env = dict(os.environ)
        paths = [str(self.tools)]
        if os.name == "nt":
            paths.append(str(Path(BASH).resolve().parents[1] / "usr/bin"))
        paths.append(env.get("PATH", ""))
        env.update(
            PATH=os.pathsep.join(paths),
            APP_DIR=self.root.as_posix(),
            VENV_DIR=self.venv.as_posix(),
            BACKUP_DIR=self.root.as_posix(),
            APP_USER="fixture",
            ENV_FILE=self.env_file.as_posix(),
            EVENTS=self.events.as_posix(),
            DATA_FILE=self.data.as_posix(),
            SNAPSHOT=(self.root / "snapshot.zip").as_posix(),
            FAIL_STAGE=failure,
            MSYS_NO_PATHCONV="1",
            MOCK_BIN=self.tools.as_posix(),
            MOCK_SCRIPT=self.script.as_posix(),
            CANDIDATE_FIXTURE=self.candidate_fixture.as_posix(),
            BASH_ENV="",
        )
        bootstrap = """if command -v cygpath >/dev/null 2>&1; then
  export PATH="$(cygpath -u "$MOCK_BIN"):/usr/bin:/bin"
else
  export PATH="$MOCK_BIN:$PATH"
fi
exec bash "$MOCK_SCRIPT"
"""
        result = subprocess.run(
            [BASH, "-c", bootstrap],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
        )
        events = self.events.read_text(encoding="utf-8").splitlines()
        self.assertIn("fetch", events, result.stdout + result.stderr)
        return result, events, self.data.read_text(encoding="utf-8")

    def test_dependency_failure_never_restores_a_database(self):
        result, events, data = self._run("pip")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("merge", events)
        self.assertNotIn("stop", events)
        self.assertNotIn("pip-live", events)
        self.assertNotIn("restore-database", events)
        self.assertIn("during-preparation", data)

    def test_active_code_is_not_replaced_until_independent_checks_and_stop_finish(self):
        result, events, _data = self._run("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(events.index("tests"), events.index("merge"))
        self.assertLess(events.index("stop"), events.index("merge"))
        self.assertLess(events.index("pip-candidate"), events.index("tests"))
        self.assertLess(events.index("stop"), events.index("pip-live"))
        self.assertIn("tests-active-old", events)
        self.assertNotIn("tests-active-new", events)
        self.assertNotIn("unsafe-test-db", events)

    def test_failed_candidate_checks_leave_active_code_and_services_untouched(self):
        result, events, _data = self._run("tests")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("merge", events)
        self.assertNotIn("stop", events)
        self.assertNotIn("rollback-code", events)

    def test_test_failure_never_restores_a_database(self):
        result, events, data = self._run("tests")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("merge", events)
        self.assertNotIn("stop", events)
        self.assertNotIn("pip-live", events)
        self.assertNotIn("restore-database", events)
        self.assertIn("during-preparation", data)

    def test_migration_rollback_uses_a_snapshot_after_writes_stopped(self):
        result, events, data = self._run("migration")
        self.assertNotEqual(result.returncode, 0)
        self.assertLess(events.index("stop"), events.index("backup"))
        self.assertLess(events.index("backup"), events.index("migrate"))
        self.assertIn("restore-database", events)
        self.assertIn("during-preparation", data)
        self.assertNotIn("migration-write", data)

    def test_syntax_failure_leaves_active_code_and_environment_unchanged(self):
        result, events, _data = self._run("syntax")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("stop", events)
        self.assertNotIn("merge", events)
        self.assertNotIn("pip-live", events)

    def test_live_dependency_failure_restores_old_code_without_replacing_data(self):
        result, events, data = self._run("live-pip")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(events.count("rollback-code"), 1)
        self.assertNotIn("restore-database", events)
        self.assertIn("during-preparation", data)
        self.assertNotIn("migration-write", data)

    def test_health_failure_does_not_erase_writes_after_services_started(self):
        result, events, data = self._run("health")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("restore-database", events)
        self.assertIn("during-preparation", data)
        self.assertIn("after-start", data)

    def test_success_takes_the_recovery_snapshot_after_stopping_writes(self):
        result, events, data = self._run("")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(events.index("tests"), events.index("stop"))
        self.assertLess(events.index("stop"), events.index("backup"))
        self.assertNotIn("restore-database", events)
        self.assertIn("during-preparation", data)
        self.assertIn("migration-write", data)

    def test_backup_failure_restarts_original_code_without_a_database_restore(self):
        result, events, data = self._run("backup")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("merge", events)
        self.assertNotIn("rollback-code", events)
        self.assertNotIn("pip-live", events)
        self.assertIn("start", events)
        self.assertNotIn("restore-database", events)
        self.assertIn("during-preparation", data)


if __name__ == "__main__":
    unittest.main()
