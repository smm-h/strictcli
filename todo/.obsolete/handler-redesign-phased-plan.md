# Handler redesign — phased implementation plan

Companion to `handler-redesign-0.9.md` (the decision record). This file is the execution plan with phases, subphases, verifiable goals, and codebase-grounded implementation details.

## Additional decisions (post-ASKME)

These decisions were made after the main ASKME session and supplement the ones in `handler-redesign-0.9.md`:

- **--quiet behavior:** suppresses stdout (both handler output via out.info and subprocess stdout). Stderr always flows through regardless of --quiet. No buffering needed.
- **--quiet vs --verbose:** mutually exclusive. Using both produces a parse error.
- **Built-in checks:** the check system is extended to support framework-auto-registered checks that don't need checks.toml entries. Built-in checks are visible alongside user checks in `myapp check --list`, marked with a [built-in] tag. Runnable via --name and --tag like any other check.
- **AST enforcement home:** lives in the extended check system as a built-in check, not at registration time and not as a separate lint command.
- **Subprocess failure under --quiet:** subprocess stderr always flows through (not buffered, not retroactively shown). The handler uses out.error() to report failures if it wants to add context.

## Phase 0: Internal refactoring

No API changes, no release. Lays the foundation for everything that follows.

### 0.1 — Shared execution path for run() and test()

Both languages duplicate post-parse logic. Extract a shared internal method that parses, handles special cases, invokes the handler, and returns a structured internal result — without calling exit or doing I/O capture.

**Python:** run() has 6 sys.exit() calls (lines 1273, 1285, 1288, 1292, 1296, 1302). test() mirrors them (lines 1310-1356). Both call self._parse(). Extract _execute(argv) that returns an internal result. run() becomes _execute(sys.argv[1:]) then exit. test() becomes _execute(argv) with stdout/stderr capture wrapping the handler call.

**Go:** Run() has 8 os.Exit() calls (lines 767-801). Test() mirrors them (lines 811-862). Both call a.doParse(). Extract an internal execute(argv) method. Same pattern.

**Verifiable goal:** run() and test() both delegate to the shared method. All existing test suites pass. No behavioral change.

### 0.2 — Framework-owned global flag infrastructure

Currently zero built-in global flags in either language. Users add their own via App(flags=[...]) (Python) or app.GlobalFlag(...) (Go). Phase 2 needs built-in --quiet, --verbose, and --output flags.

Add a separate internal list for framework-owned global flags. Merge with user flags for parsing. If a user declares a global flag with the same name as a framework flag, raise a registration-time error.

Python stores user flags in self._global_flags (line 597). Add self._framework_flags populated by the framework. Merge both for parsing in _parse_global_flags().

Go stores user flags in a.globalFlags (line 123). Same pattern: add a.frameworkFlags, merge for parsing in extractGlobalFlags().

**Verifiable goal:** framework flags are stored separately from user flags. Adding a user flag with a framework flag's name raises ValueError (Python) / panic (Go). No framework flags registered yet — the lists start empty. All existing tests pass.

### 0.3 — Go check command flag-collision filtering

Python's check command registration (lines 717-730) filters candidate flags (--verbose, --dry-run, etc.) against existing global flags to avoid collisions. Go's check_cmd.go lacks this. Must be added before Phase 2 introduces framework-owned global flags that would collide with the check command's own --verbose and --dry-run.

**Verifiable goal:** create a Go app with a global --verbose flag and a check command. The check command omits its own --verbose flag and uses the global one. Matches Python behavior.

### 0.4 — Built-in check infrastructure

The check system requires every check to be declared in user-owned checks.toml and registered via user code. Extend it to support framework-provided built-in checks.

Built-in checks:
- Are auto-registered by the framework when certain features are enabled
- Do not need entries in checks.toml
- Appear in `myapp check --list` alongside user checks, marked [built-in]
- Are selectable via --name and --tag like any other check
- Have a reserved tag: "builtin"
- Cannot be overridden by user checks with the same name

Implementation: add a builtinChecks map alongside the user checkDefs map. Merge both for listing, filtering, and execution. The validation that errors on "declared but not registered" and "registered but not declared" skips built-in checks.

**Python:** extend _run_checks() (lines 2619-2676) and the check listing logic. Add built-in checks to _format_check_list output with [built-in] marker.

**Go:** extend runChecks() (check_runner.go lines 172-221) and check listing. Same pattern.

**Verifiable goal:** register a test built-in check programmatically. It appears in --list with [built-in] marker. It runs via --tag builtin. It runs alongside user checks. No checks.toml entry needed. Existing check tests pass.

### 0.5 — Conformance infrastructure for new handler behaviors

The conformance schema currently has handler_prints (template string) and handler_exit_code (int). Extend with handler_returns (structured data the handler returns as HandlerResult.data) and handler_error (string the handler returns as HandlerResult.error).

Update both reference code generators (ref_python.py, ref_go.py) to emit handler code that returns HandlerResult when handler_returns or handler_error is specified. When neither is specified, generate backward-compatible code (print-based handler, int return).

Update conformance/schema.json with the new optional fields.

**Verifiable goal:** a test case with handler_returns generates correct reference code in both languages that compiles and runs. Existing test cases (314 cases) continue to pass unchanged — the new fields are optional.

## Phase 1: Non-breaking additions

Ships as Python 0.8.6 / Go 0.5.4. All items are additive — no existing API changes.

### 1.1 — Pure parse mode

Expose app.parse(argv) returning a public ParseResult.

**Python:** the internal _parse() (line 915) returns tuple[Command, dict]. It communicates help/version/error via exceptions (_HelpRequested, _VersionRequested, _ParseError). parse() wraps _parse() in a try/except, catches all three exception types, and maps them to ParseResult fields.

ParseResult fields: command (str, dotted path for nested like "group.cmd"), kwargs (dict), errors (list of str), help_text (str or None), version_text (str or None).

**Go:** the internal doParse() (line 878) already returns a parseResult struct with all the right fields: cmd, kwargs, helpText, versionText, parseErr, dumpSchema. Create a public ParseResult struct. Map parseResult to ParseResult (command name as string instead of *Command pointer, parseErr as errors list).

**Verifiable goal:** app.parse(["greet", "--name", "world"]) returns ParseResult with command="greet", kwargs={"name": "world"}, empty errors. app.parse(["--help"]) returns ParseResult with help_text populated. app.parse(["--unknown"]) returns ParseResult with errors populated. Conformance cases added.

### 1.2 — Python handler signature type validation

Extend _build_and_validate_command() (lines 1873-1918). The function already validates parameter names against flag/arg names via inspect.signature(). Add: for each parameter with a type annotation, check that the annotation is compatible with the declared flag type.

Type compatibility: str flag matches str hint, bool flag matches bool hint, int flag matches int hint, float flag matches float hint. list[str] matches repeatable str flag, etc. Handlers without type hints skip type validation entirely. The **kwargs escape hatch bypasses all validation as before.

**Verifiable goal:** handler with def cmd(name: int) paired with str flag raises ValueError at registration. handler with def cmd(name: str) passes. handler with no type hints passes. Run against all 6 Python consumer codebases in test mode — all must pass (3 have type hints, 3 don't).

### 1.3 — Go generic accessor

Add Get[T any](kwargs map[string]interface{}, key string) T. Type assertion with zero-value fallback for missing keys. Single function, ~10 lines.

**Verifiable goal:** Get[string](kwargs, "name") returns the string value. Get[bool](kwargs, "missing") returns false. Get[int](kwargs, "count") returns the int value. Unit tests pass.

### 1.4 — Pluggable config source

Add optional config_source parameter to App constructor.

**Python:** App(config=True, config_source=my_loader) where my_loader is Callable[[], dict]. When provided, _load_config() (lines 45-59) is skipped. The result is stored in self._config_data as before. Config subcommand availability: config show works with any source. config set/path/edit only registered for filesystem source.

**Go:** WithConfigSource(fn func() (map[string]interface{}, error)) option alongside WithConfig(). When provided, loadConfig() (config.go lines 24-40) is skipped. Same subcommand availability rules.

Detection of filesystem vs custom source: add a boolean (e.g., self._config_is_filesystem / a.configIsFilesystem). _register_config_group() / registerConfigGroup() checks this to decide which subcommands to register.

**Verifiable goal:** app with in-memory config source (returns hardcoded dict) resolves flags from the in-memory config with correct precedence (CLI > env > config > default). config show works. config set/path/edit absent from help. Existing filesystem config tests pass.

## Phase 2: Handler contract redesign

Breaking changes. No standalone release — feeds into Phase 5.

### 2.1 — HandlerResult and Output types, handler signature change

Define both types and change the handler signature in one shot.

HandlerResult: data (any/interface{}, default None/nil), exit_code (int, default 0), error (string, default None/empty).

Output: stateful wrapper with info(), debug(), warn(), error() methods. Knows current verbosity level. Routes info to stdout, debug/warn/error to stderr. Created by the framework per-invocation.

Handler signature changes:
- Python: from def cmd(**kwargs) -> int|None to def cmd(out: Output, **kwargs) -> HandlerResult. The out parameter is injected as the first positional argument before flag/arg kwargs.
- Go: from func(map[string]interface{}) int to func(*Output, map[string]interface{}) HandlerResult. PassthroughHandler changes similarly.

The _build_and_validate_command() signature validation (Python) must be updated to expect the out parameter and exclude it from flag/arg matching.

**Python _execute() changes:** create Output instance, pass as first arg to handler, receive HandlerResult, format data via output system, write error to stderr if present, return exit_code.

**Go execute() changes:** same pattern.

**test() changes:** Output writes to internal buffers in test mode. Test Result gains a Data field (the raw HandlerResult.data) alongside existing Stdout/Stderr/ExitCode.

**Verifiable goal:** handler returning HandlerResult(data={"count": 5}) works — data is formatted to stdout. Handler returning HandlerResult(error="not found", exit_code=1) prints error to stderr. out.info("msg") writes to stdout. out.debug("msg") writes to stderr. test() captures all output and returns data. Conformance cases using handler_returns work in both languages.

### 2.2 — Built-in --quiet, --verbose, --output global flags

Register three framework-owned global flags using Phase 0.2 infrastructure.

--quiet (bool): sets Output verbosity to suppress info-level messages and subprocess stdout.
--verbose (bool): sets Output verbosity to include debug-level messages.
--output (str, default "text"): selects the formatter for HandlerResult.data.

--quiet and --verbose are mutually exclusive. Using both produces a parse error. Enforced via the existing mutex mechanism.

The Output wrapper reads these values from the resolved global flags. The framework reads --output to select the formatter.

**Verifiable goal:** myapp --quiet cmd suppresses out.info() output. myapp --verbose cmd shows out.debug() output. myapp --quiet --verbose cmd errors. myapp --output json cmd formats data as JSON. App declaring its own --quiet global flag gets registration error.

### 2.3 — Pluggable formatter registry

register_formatter(name, fn) / RegisterFormatter(name, fn) on App. Framework ships json and text built-in. --output value selects which formatter processes HandlerResult.data.

Formatter callable: takes data, returns formatted string.
- text: str() / fmt.Sprint()
- json: json.dumps() / json.Marshal()
- Unrecognized --output value: parse error listing available formatters.
- data=None: no output regardless of formatter.

**Verifiable goal:** --output json on handler returning data={"k": "v"} prints {"k": "v"}. --output text prints text representation. --output csv errors listing available formatters. After register_formatter("csv", fn), --output csv works.

## Phase 3: Subprocess control

### 3.1 — Subprocess runner on Output

out.run(args) / out.Run(args...) spawns a subprocess with the framework's stdout/stderr wrappers as the child's file descriptors.

--quiet behavior: subprocess stdout suppressed. Subprocess stderr always flows through.

Returns a result with returncode, stdout (captured string), stderr (captured string).

**Python:** internally wraps subprocess.run(), setting stdout and stderr to the Output's file descriptors. When --quiet is active, stdout goes to devnull (or a capture buffer); stderr always goes to real stderr.

**Go:** wraps os/exec.Command, setting cmd.Stdout and cmd.Stderr to the Output's writers. Same --quiet logic.

In test() mode: subprocess output captured in test Result buffers.

**Verifiable goal:** out.run(["echo", "hello"]) writes "hello" to stdout. With --quiet, subprocess stdout is suppressed. Subprocess stderr always visible. In test() mode, subprocess output captured. Runner returns subprocess exit code.

### 3.2 — AST enforcement as built-in check

Register a built-in check (using Phase 0.4 infrastructure) that statically analyzes handler source code for direct subprocess usage.

**Python check implementation:** for each registered handler, use inspect.getsource() to get source, parse with ast module, walk for Call nodes targeting subprocess.run, subprocess.Popen, subprocess.call, os.system, os.popen. Report violations with function name and line number.

**Go check implementation:** use go/ast and go/parser to parse .go files under CheckContext.ProjectRoot(). Identify handler functions (match against registered handler names or by convention). Walk for os/exec.Command, os/exec.CommandContext, syscall.Exec calls. Report violations.

The check has tag "subprocess" and tag "builtin". Runs via myapp check --tag subprocess or myapp check --all.

**Limitation:** neither language catches indirect calls through helper functions. Catches the direct ~90% case.

**Verifiable goal:** handler with subprocess.run() call triggers check failure. Handler using out.run() passes. Check appears in myapp check --list with [built-in] marker. Check runs via --tag subprocess.

## Phase 4: Env var injection

### 4.1 — Standalone env var declarations

Commands declare env var dependencies not tied to flags.

**Python:** @env("API_KEY", help="...", required=True) decorator. Adds api_key (lowercased, underscored) to handler kwargs. Resolution happens at the same point as flag env vars (lines 1168-1202 for globals, 1538-1571 for commands).

**Go:** EnvVar("API_KEY", "...", Required()) option on Command. Same resolution point (strictcli.go lines 1130-1186 for globals, parse.go lines 195-252 for commands).

Reuse existing infrastructure: bool parsing (1/true/yes, 0/false/no case-insensitive), strict int/float parsing, env_prefix validation.

Missing required env vars produce parse error matching the format of missing required flags. Help output shows env vars in a dedicated section. --dump-schema includes env vars.

**Verifiable goal:** command with @env("API_KEY") receives api_key="secret" when API_KEY=secret is set. Without env var: parse error. With required=False: receives None. Help output shows the env var. Schema includes it. Conformance cases pass.

## Phase 5: Conformance, release, and migration

### 5.1 — Full conformance suite update

Update all 314 existing test cases for new handler signature (out parameter, HandlerResult return). Both reference code generators handle this via Phase 0.5.

Add new conformance cases covering:
- HandlerResult with data/error/exit_code combinations
- Output wrapper message levels with --quiet/--verbose
- --output json/text formatting
- Pure parse mode (tested via app.test() returning ParseResult data)
- Env var injection (required, optional, missing)
- Subprocess wrapper output
- Built-in check listing

Target ~50-80 new cases.

Run full parity checks: error parity (check_error_parity.py), API surface (check_api_surface.py).

**Verifiable goal:** python run.py --both passes with zero failures. check_error_parity.py passes. check_api_surface.py passes.

### 5.2 — Release Python 0.9 / Go 0.6

Version bumps in pyproject.toml, package.json, go/VERSION. Changelog entries via rlsbl for all changes across both sub-projects. Release via rlsbl release from each sub-project directory.

### 5.3 — Consumer migration todos

File a migration todo in each of the 10 consumer projects:
- Python (6): rlsbl (35 handlers), selfdoc (7), claudewheel (13), claudestream (4), predraw (6), wesktop (1)
- Go (4): safegit (14), saferm (5), howmuchleft (7), migrable (5)

Each todo describes: wrap run() with exit, add out parameter to handlers, return HandlerResult instead of int, replace print/fmt with out.info/debug/warn/error, replace subprocess calls with out.run. ~97 handlers total across all consumers.

Filing is the handoff — each project's maintainers handle the actual migration.

## Phase dependencies

```
Phase 0 (foundation)
  0.1 shared execution path
  0.2 framework-owned global flags
  0.3 Go check command flag filtering
  0.4 built-in check infrastructure      --> needed by 3.2
  0.5 conformance infrastructure          --> needed by 2.1, 5.1

Phase 1 (non-breaking, ships independently)
  1.1 pure parse mode                    <-- benefits from 0.1
  1.2 Python signature type validation
  1.3 Go generic accessor
  1.4 pluggable config source

Phase 2 (breaking handler contract)       <-- requires 0.1, 0.2, 0.5
  2.1 HandlerResult + Output + signature
  2.2 --quiet/--verbose/--output flags    <-- requires 0.2, 2.1
  2.3 pluggable formatter registry        <-- requires 2.2

Phase 3 (subprocess)                      <-- requires 2.1
  3.1 subprocess runner on Output
  3.2 AST enforcement check              <-- requires 0.4, 3.1

Phase 4 (env vars)                        <-- independent, but ships with Phase 5
  4.1 standalone env var declarations

Phase 5 (release)                         <-- requires everything
  5.1 conformance suite update
  5.2 release Python 0.9 / Go 0.6
  5.3 consumer migration todos
```

Phase 1 can ship independently as a minor release at any time after Phase 0 completes. Phases 2-4 are all breaking and ship together in Phase 5.

## Effort summary

| Subphase | Effort | Sessions |
|----------|--------|----------|
| 0.1 shared execution path | Small | 1 |
| 0.2 framework global flags | Small | 0.5 |
| 0.3 Go check flag filtering | Small | 0.5 |
| 0.4 built-in check infrastructure | Medium | 1 |
| 0.5 conformance infrastructure | Medium | 1 |
| 1.1 pure parse mode | Small-medium | 1 |
| 1.2 Python type validation | Small | 0.5 |
| 1.3 Go generic accessor | Small | 0.5 |
| 1.4 pluggable config source | Medium | 1-2 |
| 2.1 HandlerResult + Output + signature | Large | 3-4 |
| 2.2 built-in global flags | Medium | 1 |
| 2.3 pluggable formatters | Small | 1 |
| 3.1 subprocess runner | Medium | 1-2 |
| 3.2 AST enforcement check | Medium | 1-2 |
| 4.1 env var injection | Small-medium | 1 |
| 5.1 conformance suite update | Medium | 2 |
| 5.2 release | Small | 0.5 |
| 5.3 consumer migration todos | Small | 0.5 |
| **Total** | | **~18-22 sessions** |
