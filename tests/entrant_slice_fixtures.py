"""Synthetic identities and an empty local SQLite sandbox for Slice 1 tests."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Concatenate, ParamSpec, Sequence, TypeVar

from entrant_slice import registration, sandbox, storage

REGISTRATION_TIME = 1_790_000_000
DEADLINE = REGISTRATION_TIME + 600
ORGANIZER_ID = 701
SECOND_ORGANIZER_ID = 702
CommandArgs = ParamSpec("CommandArgs")
CommandResult = TypeVar("CommandResult")
_CHILD_FLAG = "--entrant-case-child"
_CASE_RUNNER = """
import sys
import unittest
from unittest.mock import patch

import dotenv

with patch.object(dotenv, 'load_dotenv', return_value=False):
    suite = unittest.defaultTestLoader.loadTestsFromName(sys.argv[1])
    result = unittest.TextTestRunner(verbosity=0).run(suite)
passed = result.wasSuccessful() and result.testsRun == 1 and not result.skipped and not result.expectedFailures
raise SystemExit(0 if passed else 1)
"""


@dataclass(frozen=True)
class Registrant:
    account_id: int
    player_id: int
    steam_id: str


def seed_registrants(
    conn: sqlite3.Connection, minutes: Sequence[int | None], *, club_id: int | None = None
) -> list[Registrant]:
    next_account_id = conn.execute("SELECT MAX(id) FROM users").fetchone()[0] or 1_000
    people = []
    for offset, playtime in enumerate(minutes, start=1):
        account_id = next_account_id + offset
        player_id = 10_000 + account_id
        steam_id = str(76561198001000000 + account_id)
        display_name = f"Slice registrant {account_id}"
        conn.execute(
            """INSERT INTO users
               (id, username, password_hash, email, email_verified_at, steam_id64, approval_status)
               VALUES (?, ?, 'not-a-login-hash', ?, '2026-01-01', ?, 'approved')""",
            (account_id, display_name, f"slice-{account_id}@example.invalid", steam_id),
        )
        conn.execute(
            """INSERT INTO players
               (id, nickname, steam_id, team_id, cs2_playtime_minutes, playtime_status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                display_name,
                steam_id,
                club_id,
                playtime,
                "public" if playtime is not None else "unknown",
            ),
        )
        people.append(Registrant(account_id, player_id, steam_id))
    conn.commit()
    return people


class EntrantSandboxCase(unittest.TestCase):
    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult | None:
        # Mixed discovery can load the old site before setUp; leave that site's config untouched.
        if (
            sandbox._configured
            or _CHILD_FLAG in sys.argv
            or not any(
                name in sys.modules for name in ("config", "models", "web_app", "app", "wsgi")
            )
        ):
            return super().run(result)

        own_result = result is None
        if result is None:
            result = self.defaultTestResult()
            result.startTestRun()
        result.startTest(self)
        try:
            environment = {
                name: value
                for name, value in os.environ.items()
                if name.upper()
                in {
                    "PATH",
                    "SYSTEMROOT",
                    "WINDIR",
                    "COMSPEC",
                    "PATHEXT",
                    "USERPROFILE",
                    "HOME",
                    "APPDATA",
                    "LOCALAPPDATA",
                    "SYSTEMDRIVE",
                    "TEMP",
                    "TMP",
                    "TMPDIR",
                }
            }
            environment["PYTHONIOENCODING"] = "utf-8"
            child = subprocess.run(
                [sys.executable, "-B", "-c", _CASE_RUNNER, self.id(), _CHILD_FLAG],
                cwd=sandbox.ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=45,
                check=False,
            )
            self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
        except AssertionError:
            result.addFailure(self, sys.exc_info())
        except (OSError, subprocess.TimeoutExpired):
            result.addError(self, sys.exc_info())
        else:
            result.addSuccess(self)
        finally:
            result.stopTest(self)
            if own_result:
                result.stopTestRun()
        return result

    def setUp(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="80gotv-entrant-test-"))
        self.workspace = Path(directory) / "sandbox"
        sandbox.initialize(self.workspace)
        self.conn = self.enterContext(closing(sandbox.connect(self.workspace)))
        self.conn.executemany(
            "INSERT INTO admins(id, username, password_hash) VALUES (?, ?, 'not-a-login-hash')",
            ((ORGANIZER_ID, "slice-organizer"), (SECOND_ORGANIZER_ID, "slice-second-organizer")),
        )
        self.conn.commit()

    def create_event(self, slug: str = "slice-cup") -> int:
        return self.command(
            registration.create_event,
            slug.replace("-", " "),
            slug,
            DEADLINE,
            admin_id=ORGANIZER_ID,
            now=REGISTRATION_TIME,
        )

    def register_group(self, event_id: int, name: str, people: Sequence[Registrant]) -> int:
        group_id = self.command(
            registration.create_group,
            event_id,
            people[0].account_id,
            name,
            now=REGISTRATION_TIME,
        )
        for slot, member in enumerate(people[1:], start=1):
            self.command(
                registration.join_group,
                event_id,
                group_id,
                member.account_id,
                slot,
                now=REGISTRATION_TIME,
            )
        return group_id

    def enroll_individuals(self, event_id: int, people: Sequence[Registrant]) -> None:
        for offset, member in enumerate(people):
            self.command(
                registration.enroll,
                event_id,
                member.account_id,
                "individual",
                now=REGISTRATION_TIME + offset,
            )

    def command(
        self,
        fn: Callable[Concatenate[sqlite3.Connection, CommandArgs], CommandResult],
        /,
        *args: CommandArgs.args,
        **kwargs: CommandArgs.kwargs,
    ) -> CommandResult:
        with storage.write(self.conn):
            return fn(self.conn, *args, **kwargs)
