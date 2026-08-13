"""The process trace store (docs/process-trace-store.md).

Every test here pins HOME to a temp directory, which is what makes the suite
hermetic: the store path is the literal ``~/.local/share/strictcli/trace/``,
expanded from HOME and nothing else, so a poisoned HOME is a private store.

The reader used below is a TEST-side reader on purpose. The framework exposes
no accessor for ancestry (effects contract §20.2) and no code path branches on
the store's content -- a consumer that wants the chain parses the environment
variable and reads the store itself, exactly as this file does.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import stat
import sys
import time
from pathlib import Path

import pytest

import strictcli as sc

PY = sys.executable
TRACE_PARENT = "STRICTCLI_TRACE_PARENT"


# --- the test-side reader --------------------------------------------------


def store_dir(home: Path) -> Path:
    return home / ".local" / "share" / "strictcli" / "trace"


def partitions(home: Path) -> list[Path]:
    """Partition files, in name order. Anything else in the directory -- the
    failure marker included -- is ignored, per the spec's reader rule."""
    d = store_dir(home)
    if not d.is_dir():
        return []
    return sorted(
        p for p in d.iterdir() if sc._TRACE_PARTITION_RE.match(p.name)
    )


def entries_in(path: Path) -> tuple[list[dict], list[str]]:
    """One partition's (entries, anomalies)."""
    entries: list[dict] = []
    anomalies: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        if line == "":
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            anomalies.append(line)
            continue
        if not isinstance(obj, dict) or set(obj) != set(ENTRY_KEYS):
            anomalies.append(line)
            continue
        entries.append(obj)
    return entries, anomalies


def read_entries(home: Path) -> tuple[list[dict], list[str]]:
    """Return (entries, anomalies). A torn or malformed line is recorded
    verbatim as an anomaly and skipped -- never discarded silently."""
    entries: list[dict] = []
    anomalies: list[str] = []
    for path in partitions(home):
        found, bad = entries_in(path)
        entries.extend(found)
        anomalies.extend(bad)
    return entries, anomalies


def resolve_entry(
    home: Path, entry_id: str, *, walk_back: bool = True
) -> dict | None:
    """The spec's lookup rule (docs/process-trace-store.md, Partitions).

    Binary-search the sorted labels for the greatest label NOT AFTER the
    identifier's embedded timestamp, read that partition, and on a miss walk
    backward through older partitions until the entry is found or the
    partitions are exhausted. The backward walk is required for correctness:
    the clamp invariant is one-sided, so a file that has not rolled keeps
    taking entries after a newer-labelled partition exists.

    ``walk_back=False`` is the pre-amendment rule -- one binary search and
    nothing else -- kept so a test can pin what it misses.
    """
    if not sc._ulid_valid(entry_id):
        return None
    parts = partitions(home)
    labels = [p.name[: -len(".jsonl")] for p in parts]
    target = sc._trace_label(sc._ulid_timestamp(entry_id))
    index = bisect.bisect_right(labels, target) - 1
    while index >= 0:
        for entry in entries_in(parts[index])[0]:
            if entry["id"] == entry_id:
                return entry
        if not walk_back:
            return None
        index -= 1
    return None


def flatten_ancestry(home: Path, leaf_id: str) -> list[str]:
    """Walk parent_id to the root, resolving each link through the store's own
    lookup rule; a dangling reference ends the walk."""
    chain: list[str] = []
    current: str | None = leaf_id
    while current is not None:
        entry = resolve_entry(home, current)
        if entry is None:
            break
        chain.append(current)
        current = entry["parent_id"]
    return chain


ENTRY_KEYS = [
    "id", "parent_id", "app", "version", "command", "dry_run", "machine_mode",
    "quiet", "verbose", "approve_consequential", "effect", "pid", "spawned_at",
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A private HOME, and no inherited ancestry unless a test sets one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv(TRACE_PARENT, raising=False)
    return tmp_path


def _app(**kwargs):
    return sc.App(name="app", version="1.2.3", help="app", **kwargs)


# --- the store's location and shape ---------------------------------------


class TestLocation:
    def test_path_is_the_literal_one(self, home):
        assert sc._trace_store_dir() == str(
            home / ".local" / "share" / "strictcli" / "trace"
        )

    def test_xdg_data_home_is_never_consulted(self, home, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(home / "elsewhere"))
        assert sc._trace_store_dir() == str(
            home / ".local" / "share" / "strictcli" / "trace"
        )

    def test_directory_is_created_on_write_with_mode_0700(self, home):
        assert sc._trace_write_entry(_identity()) is not None
        d = store_dir(home)
        assert d.is_dir()
        assert stat.S_IMODE(d.stat().st_mode) == 0o700

    def test_partition_file_mode_is_0600(self, home):
        sc._trace_write_entry(_identity())
        assert stat.S_IMODE(partitions(home)[0].stat().st_mode) == 0o600

    def test_a_deleted_store_resumes_from_empty(self, home):
        sc._trace_write_entry(_identity())
        for p in partitions(home):
            p.unlink()
        store_dir(home).rmdir()
        assert sc._trace_write_entry(_identity()) is not None
        assert len(read_entries(home)[0]) == 1


def _identity(**overrides):
    fields = dict(
        app="app", version="1.2.3", command="build.run", dry_run=False,
        machine_mode=False, quiet=False, verbose=False,
        approve_consequential=False, effect="mutating",
    )
    fields.update(overrides)
    return sc._TraceIdentity(**fields)


class TestEntry:
    def test_every_key_is_present_with_its_pinned_type(self, home):
        entry_id = sc._trace_write_entry(
            _identity(quiet=True, verbose=True, approve_consequential=True,
                      machine_mode=True)
        )
        (entry,), anomalies = read_entries(home)
        assert anomalies == []
        assert list(entry) == ENTRY_KEYS
        assert entry["id"] == entry_id
        assert entry["parent_id"] is None
        assert entry["app"] == "app"
        assert entry["version"] == "1.2.3"
        assert entry["command"] == "build.run"
        assert entry["dry_run"] is False
        assert entry["machine_mode"] is True
        assert entry["quiet"] is True
        assert entry["verbose"] is True
        assert entry["approve_consequential"] is True
        assert entry["effect"] == "mutating"
        assert entry["pid"] == os.getpid()
        assert entry["spawned_at"].endswith("Z")

    def test_command_may_be_null(self, home):
        sc._trace_write_entry(_identity(command=None))
        (entry,), _ = read_entries(home)
        assert entry["command"] is None

    def test_one_line_per_entry_terminated_by_exactly_one_newline(self, home):
        for _ in range(3):
            sc._trace_write_entry(_identity())
        text = partitions(home)[0].read_text()
        assert text.count("\n") == 3
        assert text.endswith("\n")
        assert not text.endswith("\n\n")

    def test_the_line_is_compact_json(self, home):
        sc._trace_write_entry(_identity())
        line = partitions(home)[0].read_text().rstrip("\n")
        assert ", " not in line
        assert '": ' not in line

    def test_spawned_at_is_the_millisecond_embedded_in_the_id(self, home):
        entry_id = sc._trace_write_entry(_identity())
        (entry,), _ = read_entries(home)
        ms = sc._ulid_timestamp(entry_id)
        assert entry["spawned_at"] == sc._trace_timestamp(ms)
        assert len(entry["spawned_at"]) == len("2026-08-13T04:17:52.913Z")

    def test_the_id_is_canonical_under_the_strict_profile(self, home):
        entry_id = sc._trace_write_entry(_identity())
        assert sc._ulid_valid(entry_id)

    def test_ids_are_distinct_per_entry(self, home):
        ids = {sc._trace_write_entry(_identity()) for _ in range(20)}
        assert len(ids) == 20


class TestTimestampFormat:
    def test_three_fractional_digits_always(self):
        assert sc._trace_timestamp(0) == "1970-01-01T00:00:00.000Z"
        assert sc._trace_timestamp(1) == "1970-01-01T00:00:00.001Z"
        assert sc._trace_timestamp(1786594672913) == "2026-08-13T04:17:52.913Z"

    def test_label_is_the_range_start_in_utc(self):
        assert sc._trace_label(1786594672913) == "2026-08-13T04"
        assert sc._trace_label(0) == "1970-01-01T00"

    def test_label_start_is_the_exact_inverse(self):
        for ms in (0, 1786594672913, 1234567890123):
            label = sc._trace_label(ms)
            start = sc._trace_label_start_ms(label)
            assert start <= ms
            assert ms - start < 3_600_000
            assert sc._trace_label(start) == label


# --- partitions ------------------------------------------------------------


class TestPartitions:
    def test_first_write_creates_the_current_hour(self, home):
        sc._trace_write_entry(_identity())
        names = [p.name for p in partitions(home)]
        assert names == [sc._trace_label(int(time.time() * 1000)) + ".jsonl"]

    def test_writers_append_to_the_greatest_named_file(self, home):
        d = store_dir(home)
        d.mkdir(parents=True)
        (d / "2020-01-01T00.jsonl").write_text("")
        (d / "2020-01-01T05.jsonl").write_text("")
        sc._trace_write_entry(_identity())
        assert (d / "2020-01-01T05.jsonl").read_text() != ""
        assert (d / "2020-01-01T00.jsonl").read_text() == ""
        assert len(partitions(home)) == 2

    def test_no_roll_when_the_hour_advanced_but_the_file_is_small(self, home):
        d = store_dir(home)
        d.mkdir(parents=True)
        old = d / "2020-01-01T00.jsonl"
        old.write_text("x" * 1024)
        sc._trace_write_entry(_identity())
        assert [p.name for p in partitions(home)] == ["2020-01-01T00.jsonl"]

    def test_no_roll_when_the_file_is_large_but_the_hour_has_not_advanced(
        self, home
    ):
        d = store_dir(home)
        d.mkdir(parents=True)
        now_label = sc._trace_label(int(time.time() * 1000))
        big = d / f"{now_label}.jsonl"
        big.write_bytes(b"x" * (8 * 1024 * 1024))
        sc._trace_write_entry(_identity())
        assert [p.name for p in partitions(home)] == [f"{now_label}.jsonl"]

    def test_roll_when_both_conditions_hold(self, home):
        d = store_dir(home)
        d.mkdir(parents=True)
        old = d / "2020-01-01T00.jsonl"
        old.write_bytes(b"x" * (8 * 1024 * 1024))
        sc._trace_write_entry(_identity())
        now_label = sc._trace_label(int(time.time() * 1000))
        assert [p.name for p in partitions(home)] == [
            "2020-01-01T00.jsonl", f"{now_label}.jsonl",
        ]
        assert (d / f"{now_label}.jsonl").read_text().endswith("\n")

    def test_the_clamp_keeps_every_entry_inside_its_files_range(self, home):
        # A partition labelled in the future stands for a clock that jumped
        # backwards. The minted timestamp clamps up to the range start.
        d = store_dir(home)
        d.mkdir(parents=True)
        future_ms = int(time.time() * 1000) + 5 * 3_600_000
        label = sc._trace_label(future_ms)
        (d / f"{label}.jsonl").write_text("")
        entry_id = sc._trace_write_entry(_identity())
        (entry,), _ = read_entries(home)
        start = sc._trace_label_start_ms(label)
        assert sc._ulid_timestamp(entry_id) == start
        assert entry["spawned_at"] == sc._trace_timestamp(start)

    def test_every_entry_is_at_or_after_its_partitions_label(self, home):
        # The clamp invariant is ONE-SIDED (spec page, amended at the
        # lookup-rule audit): nothing bounds an entry from above.
        for _ in range(5):
            sc._trace_write_entry(_identity())
        for path in partitions(home):
            label = path.name[: -len(".jsonl")]
            start = sc._trace_label_start_ms(label)
            for line in path.read_text().splitlines():
                entry = json.loads(line)
                assert sc._ulid_timestamp(entry["id"]) >= start

    def test_non_partition_files_are_ignored_by_readers(self, home):
        sc._trace_write_entry(_identity())
        d = store_dir(home)
        (d / "write-failure.marker").write_text("2020-01-01T00:00:00.000Z\n")
        (d / "notes.txt").write_text("not a partition\n")
        (d / "2020-01-01T00.jsonl.bak").write_text("junk\n")
        entries, anomalies = read_entries(home)
        assert len(entries) == 1
        assert anomalies == []


# --- the lookup rule -------------------------------------------------------


def _stranded_store(home: Path, monkeypatch=None) -> tuple[str, str]:
    """Build the store the lookup-rule audit constructed, using the real writer.

    1. A partition labelled for the PREVIOUS hour is the greatest-named file,
       so the writer appends to it and mints a timestamp in the CURRENT hour:
       that entry is stranded above its own file's label.
    2. Padding that file past the 8 MB threshold makes the next write roll, and
       the new partition is labelled for the current hour -- the very label the
       stranded entry's timestamp points at.

    Returns (stranded_id, rolled_id). When ``monkeypatch`` is given, the rolled
    entry inherits the stranded one as its parent, so the pair is a chain that
    crosses the strand.
    """
    d = store_dir(home)
    d.mkdir(parents=True)
    prev_label = sc._trace_label(int(time.time() * 1000) - 3_600_000)
    prev = d / f"{prev_label}.jsonl"
    prev.write_text("")
    stranded = sc._trace_write_entry(_identity())
    assert stranded is not None
    # Padding past the roll threshold. It is one anomalous line, which every
    # reader here skips.
    with open(prev, "a", encoding="utf-8") as fh:
        fh.write("x" * (8 * 1024 * 1024) + "\n")
    if monkeypatch is not None:
        monkeypatch.setenv(TRACE_PARENT, stranded)
    rolled = sc._trace_write_entry(_identity())
    assert rolled is not None
    assert len(partitions(home)) == 2
    return stranded, rolled


class TestLookupRule:
    """The spec's amended lookup rule: binary search, then walk backward."""

    def test_the_range_is_not_bounded_at_the_top(self, home):
        # The falsifying store: an entry whose timestamp is at or beyond the
        # NEXT partition's label, living in the older file. The clamp bounds
        # the bottom only.
        stranded, _ = _stranded_store(home)
        older, newer = partitions(home)
        assert entries_in(older)[0][0]["id"] == stranded
        newer_label = newer.name[: -len(".jsonl")]
        assert sc._ulid_timestamp(stranded) >= sc._trace_label_start_ms(newer_label)

    def test_a_stranded_entry_is_found_by_walking_backward(self, home):
        stranded, _ = _stranded_store(home)
        entry = resolve_entry(home, stranded)
        assert entry is not None
        assert entry["id"] == stranded

    def test_one_binary_search_alone_misses_the_stranded_entry(self, home):
        # The rule this page carried until the lookup-rule audit: search the
        # partition the timestamp points at and stop. It reports a live entry
        # as missing, which a consumer records as a dangling parent.
        stranded, _ = _stranded_store(home)
        assert resolve_entry(home, stranded, walk_back=False) is None

    def test_the_unstranded_entry_is_found_by_the_first_search(self, home):
        _, rolled = _stranded_store(home)
        assert resolve_entry(home, rolled, walk_back=False) is not None

    def test_a_chain_across_the_strand_still_flattens(self, home, monkeypatch):
        stranded, rolled = _stranded_store(home, monkeypatch)
        assert flatten_ancestry(home, rolled) == [rolled, stranded]

    def test_an_identifier_no_store_holds_resolves_to_nothing(self, home):
        sc._trace_write_entry(_identity())
        assert resolve_entry(home, "01JZ8X4M6N7QK2WVBD3F5RTYAC") is None

    def test_an_unparseable_identifier_resolves_to_nothing(self, home):
        sc._trace_write_entry(_identity())
        assert resolve_entry(home, "not-a-ulid") is None


# --- propagation -----------------------------------------------------------


class TestPropagation:
    def test_parent_id_is_the_inherited_identifier(self, home, monkeypatch):
        parent = sc._ulid_mint(1786594672913)
        monkeypatch.setenv(TRACE_PARENT, parent)
        sc._trace_write_entry(_identity())
        (entry,), _ = read_entries(home)
        assert entry["parent_id"] == parent

    def test_absent_variable_makes_a_root(self, home):
        sc._trace_write_entry(_identity())
        (entry,), _ = read_entries(home)
        assert entry["parent_id"] is None

    @pytest.mark.parametrize(
        "polluted",
        ["", "not-a-ulid", "01jz8x4m6n7qk2wvbd3f5rtyac",
         "ZZZZZZZZZZZZZZZZZZZZZZZZZZ", "01JZ8X4M6N7QK2WVBD3F5RTYA"],
    )
    def test_a_malformed_inherited_value_records_a_null_parent(
        self, home, monkeypatch, polluted
    ):
        monkeypatch.setenv(TRACE_PARENT, polluted)
        entry_id = sc._trace_write_entry(_identity())
        assert entry_id is not None  # never bricks the run
        (entry,), anomalies = read_entries(home)
        assert entry["parent_id"] is None
        assert anomalies == []

    def test_the_dangling_parent_is_legal_by_design(self, home, monkeypatch):
        foreign = "01JZ8X4M6N7QK2WVBD3F5RTYAC"
        monkeypatch.setenv(TRACE_PARENT, foreign)
        entry_id = sc._trace_write_entry(_identity())
        assert flatten_ancestry(home, entry_id) == [entry_id]


class TestChildEnvironment:
    """The composition happens at the seam, on the CHILD's environment only."""

    def _echo_parent(self, app_kwargs=None, env=None):
        app = _app(**(app_kwargs or {}))
        holder = {}

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            out = ctx.effects.run(
                [PY, "-c",
                 "import os,sys;sys.stdout.write(os.environ.get("
                 "'STRICTCLI_TRACE_PARENT','<unset>'))"],
                **({"env": env} if env is not None else {}),
            )
            holder["seen"] = out.stdout
            return 0

        return app, holder

    def test_the_child_receives_this_entrys_identifier(self, home):
        app, holder = self._echo_parent()
        assert app.test(["go"]).exit_code == 0
        entries, _ = read_entries(home)
        assert len(entries) == 1
        assert holder["seen"] == entries[0]["id"]

    def test_the_spawning_process_environment_is_never_mutated(self, home):
        app, _ = self._echo_parent()
        app.test(["go"])
        assert TRACE_PARENT not in os.environ

    def test_the_framework_wins_over_a_handler_supplied_value(self, home):
        app, holder = self._echo_parent(env={TRACE_PARENT: "01JZ8X4M6N7QK2WVBD3F5RTYAC"})
        app.test(["go"])
        entries, _ = read_entries(home)
        assert holder["seen"] == entries[0]["id"]
        assert holder["seen"] != "01JZ8X4M6N7QK2WVBD3F5RTYAC"

    def test_a_handler_cannot_sever_the_chain_by_clearing_it(self, home):
        app, holder = self._echo_parent(env={TRACE_PARENT: ""})
        app.test(["go"])
        entries, _ = read_entries(home)
        assert holder["seen"] == entries[0]["id"]

    def test_other_handler_env_keys_still_win(self, home):
        app = _app()
        holder = {}

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            out = ctx.effects.run(
                [PY, "-c",
                 "import os,sys;sys.stdout.write(os.environ['MY_KEY'])"],
                env={"MY_KEY": "mine"},
            )
            holder["seen"] = out.stdout
            return 0

        app.test(["go"])
        assert holder["seen"] == "mine"

    def test_the_child_inherits_the_rest_of_the_environment(self, home, monkeypatch):
        monkeypatch.setenv("SOME_INHERITED", "yes")
        app = _app()
        holder = {}

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            out = ctx.effects.run(
                [PY, "-c",
                 "import os,sys;sys.stdout.write(os.environ['SOME_INHERITED'])"],
            )
            holder["seen"] = out.stdout
            return 0

        app.test(["go"])
        assert holder["seen"] == "yes"

    def test_a_broken_store_removes_the_variable_from_the_child(self, home):
        # A lost record must not silently re-attribute the child to its
        # grandparent, so the inherited value is dropped rather than passed on.
        os.environ[TRACE_PARENT] = "01JZ8X4M6N7QK2WVBD3F5RTYAC"
        try:
            _break_store(home)
            app, holder = self._echo_parent()
            assert app.test(["go"]).exit_code == 0
            assert holder["seen"] == "<unset>"
        finally:
            del os.environ[TRACE_PARENT]


# --- the seam --------------------------------------------------------------


class TestSeam:
    """One entry per real child-process start, and nothing else."""

    def test_a_live_run_writes_one_entry(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["go"])
        entries, _ = read_entries(home)
        assert len(entries) == 1
        assert entries[0]["command"] == "go"
        assert entries[0]["effect"] == "mutating"
        assert entries[0]["dry_run"] is False

    def test_a_live_spawn_writes_one_entry(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.spawn([PY, "-c", "pass"]).wait()
            return 0

        app.test(["go"])
        entries, _ = read_entries(home)
        assert len(entries) == 1

    def test_three_children_yield_three_entries_with_distinct_ids(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            for _ in range(3):
                ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["go"])
        entries, _ = read_entries(home)
        assert len({e["id"] for e in entries}) == 3

    def test_a_process_that_never_spawns_writes_nothing(
        self, home, tmp_path, monkeypatch
    ):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.write("f.txt", "x")
            ctx.effects.mkdir("d")
            return 0

        monkeypatch.chdir(tmp_path)
        app.test(["go"])
        assert read_entries(home)[0] == []

    def test_a_recorded_dry_mode_spawn_writes_nothing(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.spawn([PY, "-c", "pass"])
            return 0

        app.test(["--dry-run", "go"])
        assert read_entries(home)[0] == []

    def test_a_recorded_dry_mode_run_writes_nothing(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["--dry-run", "go"])
        assert read_entries(home)[0] == []

    def test_an_allowlisted_observe_in_dry_mode_writes_an_entry(self, home):
        # An observe genuinely executes in dry mode, so a real child starts --
        # and the entry carries dry_run: true, which is the only way that field
        # can ever be true.
        app = _app(proc_observe_allowlist=[[PY, "-c"]])

        @app.command("go", help="go", effect="read_only")
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["--dry-run", "go"])
        (entry,), _ = read_entries(home)
        assert entry["dry_run"] is True
        assert entry["effect"] == "read_only"

    def test_an_allowlisted_observe_in_live_mode_writes_an_entry(self, home):
        app = _app(proc_observe_allowlist=[[PY, "-c"]])

        @app.command("go", help="go", effect="read_only")
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["go"])
        (entry,), _ = read_entries(home)
        assert entry["dry_run"] is False

    def test_a_stale_observe_in_dry_mode_writes_nothing(self, home):
        # After a recorded mutation the observe is not executed at all, so no
        # child starts and no entry is written.
        app = _app(proc_observe_allowlist=[[PY, "-c"]])

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.mkdir("d")
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["--dry-run", "go"])
        assert read_entries(home)[0] == []

    def test_the_reserved_flag_state_is_recorded(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating", consequential=True)
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["go", "--quiet", "--approve-consequential"])
        (entry,), _ = read_entries(home)
        assert entry["quiet"] is True
        assert entry["verbose"] is False
        assert entry["approve_consequential"] is True
        assert entry["machine_mode"] is False

    def test_machine_mode_is_recorded(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        app.test(["go", "--json"])
        (entry,), _ = read_entries(home)
        assert entry["machine_mode"] is True

    def test_argv_is_never_recorded(self, home):
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass  # s3cr3t-token"])
            return 0

        app.test(["go"])
        text = partitions(home)[0].read_text()
        assert "s3cr3t-token" not in text
        assert "-c" not in json.loads(text)["command"]


# --- failure policy --------------------------------------------------------


def _break_store(home: Path) -> Path:
    """Make the store directory exist and be unwritable."""
    d = store_dir(home)
    d.mkdir(parents=True)
    d.chmod(0o500)
    return d


class TestFailurePolicy:
    def test_a_write_failure_never_fails_the_run_and_prints_nothing(self, home):
        _break_store(home)
        app = _app()

        @app.command("go", help="go", effect="mutating")
        def _go(ctx):
            ctx.effects.run([PY, "-c", "pass"])
            return 0

        r = app.test(["go"])
        assert r.exit_code == 0
        assert r.stdout == ""
        assert r.stderr == ""

    def test_a_write_failure_returns_no_identifier(self, home):
        _break_store(home)
        assert sc._trace_write_entry(_identity()) is None

    def test_the_first_failure_writes_the_marker(self, home):
        d = _break_store(home)
        d.chmod(0o700)
        # A directory the writer cannot create a partition in, but can create
        # the marker in: emulate by making the partition path a directory.
        label = sc._trace_label(int(time.time() * 1000))
        (d / f"{label}.jsonl").mkdir()
        assert sc._trace_write_entry(_identity()) is None
        marker = d / "write-failure.marker"
        assert marker.exists()
        content = marker.read_text()
        assert content.endswith("\n")
        assert content.count("\n") == 1
        stamp = content[:-1]
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", stamp)
        assert stamp[:13] == sc._trace_label(int(time.time() * 1000))

    def test_the_marker_is_write_once_and_carries_no_counter(self, home):
        d = _break_store(home)
        d.chmod(0o700)
        label = sc._trace_label(int(time.time() * 1000))
        (d / f"{label}.jsonl").mkdir()
        sc._trace_write_entry(_identity())
        first = (d / "write-failure.marker").read_text()
        time.sleep(0.005)
        for _ in range(3):
            sc._trace_write_entry(_identity())
        assert (d / "write-failure.marker").read_text() == first

    def test_a_marker_that_cannot_be_written_is_swallowed_too(self, home):
        _break_store(home)
        assert sc._trace_write_entry(_identity()) is None
        assert not (store_dir(home) / "write-failure.marker").exists()

    def test_a_store_path_that_is_a_file_is_swallowed(self, home):
        parent = home / ".local" / "share" / "strictcli"
        parent.mkdir(parents=True)
        (parent / "trace").write_text("not a directory")
        assert sc._trace_write_entry(_identity()) is None


# --- malformed data --------------------------------------------------------


class TestMalformedData:
    def test_a_torn_line_is_skipped_and_recorded_as_an_anomaly(self, home):
        sc._trace_write_entry(_identity())
        path = partitions(home)[0]
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"id":"01JZ8X4M6N7QK2WVBD3F5RTYAC","parent\n')
        sc._trace_write_entry(_identity())
        entries, anomalies = read_entries(home)
        assert len(entries) == 2
        assert anomalies == ['{"id":"01JZ8X4M6N7QK2WVBD3F5RTYAC","parent']

    def test_a_truncated_final_line_does_not_disturb_writers(self, home):
        sc._trace_write_entry(_identity())
        path = partitions(home)[0]
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"id":"01JZ8X4M6N7QK2WVBD3F5R')
        assert sc._trace_write_entry(_identity()) is not None
        assert not (store_dir(home) / "write-failure.marker").exists()
        entries, anomalies = read_entries(home)
        assert len(entries) == 1
        assert len(anomalies) == 1

    def test_an_entry_missing_a_key_is_an_anomaly_not_a_default(self, home):
        sc._trace_write_entry(_identity())
        path = partitions(home)[0]
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"id":"01JZ8X4M6N7QK2WVBD3F5RTYAC"}\n')
        entries, anomalies = read_entries(home)
        assert len(entries) == 1
        assert len(anomalies) == 1


# --- the chain -------------------------------------------------------------


CHAIN_SCRIPT = '''\
import sys

import strictcli as sc

app = sc.App(name="chain", version="9.9.9", help="chain")


@app.command(
    "go", help="go", effect="mutating",
    args=[sc.Arg(name="depth", type=int, help="how many more children to start")],
)
def _go(ctx, depth):
    if depth > 0:
        ctx.effects.spawn(
            [sys.executable, __file__, "go", str(depth - 1)]
        ).wait()
    return 0


app.run()
'''


class TestChain:
    def test_a_three_deep_spawn_chain_yields_a_flattened_ancestry(
        self, home, tmp_path
    ):
        import subprocess

        script = tmp_path / "chain.py"
        script.write_text(CHAIN_SCRIPT)
        env = dict(os.environ)
        env["HOME"] = str(home)
        env.pop(TRACE_PARENT, None)
        proc = subprocess.run(
            [PY, str(script), "go", "3"],
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, proc.stderr

        entries, anomalies = read_entries(home)
        assert anomalies == []
        # Four processes, three of which start a child: three entries.
        assert len(entries) == 3
        assert {e["app"] for e in entries} == {"chain"}
        assert {e["command"] for e in entries} == {"go"}

        by_id = {e["id"]: e for e in entries}
        leaves = [e for e in entries if e["id"] not in
                  {x["parent_id"] for x in entries}]
        assert len(leaves) == 1
        chain = flatten_ancestry(home, leaves[0]["id"])
        assert len(chain) == 3
        assert by_id[chain[-1]]["parent_id"] is None
        # The pids are three distinct witnesses, one per spawning process.
        assert len({by_id[i]["pid"] for i in chain}) == 3
