# strictcli

A strict, zero-dependency CLI framework for Python.

strictcli makes you declare everything -- every command, flag, argument, and environment variable must have help text or the framework errors at registration time. Types are `str` and `bool` only; there is no magic type inference. Environment variables are first-class, with prefix enforcement to keep your config namespace clean.

## Installation

```
uv add strictcli
```

Or:

```
pip install strictcli
```

Requires Python 3.11+.

## Quickstart

```python
# greet.py
import strictcli

app = strictcli.App(name="greet", version="0.1.0", help="a friendly greeter")

@app.command("hello", help="say hello", args=[strictcli.Arg(name="name", help="who to greet")])
@strictcli.flag("loud", short="l", type=bool, help="shout the greeting")
def hello(name, loud):
    msg = f"Hello, {name}!"
    if loud:
        msg = msg.upper()
    print(msg)

app.run()
```

```
$ python greet.py hello World
Hello, World!

$ python greet.py hello --loud World
HELLO, WORLD!

$ python greet.py hello --help
greet hello -- say hello

Arguments:
  name    who to greet

Flags:
  --loud, --no-loud, -l    shout the greeting [default: false]
```

## Commands and Groups

Register top-level commands with `@app.command`:

```python
app = strictcli.App(name="myapp", version="1.0.0", help="manage deployments")

@app.command("status", help="show current status")
def status():
    print("all systems go")
```

Create groups for two-level nesting with `app.group`:

```python
db = app.group("db", help="manage databases")

@db.command("migrate", help="run database migrations")
@strictcli.flag("dry-run", type=bool, help="preview without applying")
def migrate(dry_run):
    if dry_run:
        print("would run migrations")
    else:
        print("running migrations")

@db.command("seed", help="populate with sample data")
@strictcli.flag("count", type=str, help="number of records", default="100")
def seed(count):
    print(f"seeding {count} records")
```

```
$ myapp db migrate --dry-run
would run migrations

$ myapp db seed --count 500
seeding 500 records
```

## Flags

Declare flags with the `@strictcli.flag` decorator. Every flag must have `help` text.

### String flags

```python
@app.command("build", help="build the project")
@strictcli.flag("output", short="o", type=str, help="output directory", default="dist")
def build(output):
    print(f"building to {output}")
```

String flags accept values via `--output dist` or `--output=dist`. A string flag without a `default` is required.

### Bool flags

```python
@app.command("deploy", help="deploy the app")
@strictcli.flag("force", short="f", type=bool, help="skip confirmation")
def deploy(force):
    if force:
        print("deploying without confirmation")
```

Bool flags default to `False`. Pass `--force` to set `True`, or `--no-force` to explicitly set `False`. The `--no-` negation form is available by default for all bool flags; disable it with `negatable=False`.

### Short aliases

Any flag can have a one-character short alias:

```python
@strictcli.flag("verbose", short="v", type=bool, help="verbose output")
```

This allows both `--verbose` and `-v`.

### Required vs optional

- `str` flags with no `default` are required -- the parser errors if missing.
- `str` flags with a `default` are optional.
- `bool` flags always default to `False`.

## Arguments

Positional arguments are declared with `strictcli.Arg`. There are two equivalent forms.

Using the `args=` parameter:

```python
@app.command("copy", help="copy files", args=[
    strictcli.Arg(name="src", help="source path"),
    strictcli.Arg(name="dst", help="destination path"),
])
def copy(src, dst):
    print(f"copying {src} to {dst}")
```

Using the `@strictcli.arg` decorator:

```python
@app.command("show", help="show a file")
@strictcli.arg("path", help="file to show")
def show(path):
    print(f"showing {path}")
```

Arguments are matched in order. Use `required=False` for optional arguments. The `--` separator stops flag parsing, so everything after it becomes positional:

```
$ myapp cmd -- --not-a-flag
```

## Environment Variables

Flags can be backed by environment variables with the `env` parameter:

```python
app = strictcli.App(name="myapp", version="1.0.0", help="my app", env_prefix="MYAPP")

@app.command("deploy", help="deploy the app")
@strictcli.flag("region", type=str, help="cloud region", env="MYAPP_REGION", default="us-east-1")
def deploy(region):
    print(f"deploying to {region}")
```

### Prefix enforcement

When `env_prefix` is set on the App, all env vars must start with that prefix. This is validated at registration time:

```python
# This raises ValueError: env var 'REGION' must start with 'MYAPP_'
@strictcli.flag("region", type=str, help="region", env="REGION", default="x")
```

### External env vars

Use `prefixed=False` for env vars outside your app's namespace:

```python
@strictcli.flag("token", type=str, help="auth token", env="GITHUB_TOKEN", prefixed=False, default="")
```

### Priority

Values resolve in this order: CLI argument > environment variable > default. If none of the three provides a value, the parser errors.

### Bool env vars

Bool flags from env vars accept `1`, `true`, `yes` (case-insensitive) for `True` and `0`, `false`, `no` for `False`. Any other value is an error.

## Tags

Tags are reusable bundles of flags that can be applied to multiple commands:

```python
auth_tag = strictcli.Tag(
    name="auth",
    flags=[
        strictcli.Flag(name="token", type=str, help="auth token", env="MYAPP_TOKEN", default=""),
        strictcli.Flag(name="insecure", type=bool, help="skip TLS verification"),
    ],
)

@app.command("deploy", help="deploy the app", tags=[auth_tag])
def deploy(token, insecure):
    print(f"token={'set' if token else 'unset'}, insecure={insecure}")

@app.command("status", help="check status", tags=[auth_tag])
def status(token, insecure):
    print(f"checking status")
```

Both commands now have `--token` and `--insecure` flags. Tag flags appear in help output and are parsed like any other flag.

## Mutex Groups

Mutex groups declare mutually exclusive flags -- exactly one flag from the group must be provided. If the user provides more than one, or provides none, the parser errors.

```python
@app.command("log", help="show logs", mutex=[
    strictcli.MutexGroup(flags=[
        strictcli.Flag(name="verbose", type=bool, help="verbose output"),
        strictcli.Flag(name="quiet", type=bool, help="quiet output"),
    ]),
])
def log(verbose, quiet):
    if verbose:
        print("showing all logs")
    elif quiet:
        print("showing errors only")
```

If both flags are provided:

```
$ myapp log --verbose --quiet
error: --verbose and --quiet are mutually exclusive
try 'myapp --help'
```

If neither flag is provided:

```
$ myapp log
error: one of --verbose, --quiet is required
try 'myapp --help'
```

Mutex group flags appear in a separate section in help output:

```
$ myapp log --help
myapp log -- show logs

Flags (mutually exclusive):
  --verbose, --no-verbose    verbose output [default: false]
  --quiet, --no-quiet        quiet output [default: false]
```

Flags inside a mutex group follow the same rules as regular flags (short aliases, env vars, types), but they are not declared with `@strictcli.flag` -- they live inside the `MutexGroup`.

## Flag Dependencies

Flag dependencies enforce relationships between flags. Two types are available:

- `CoRequired(flags=["output", "format"])` -- all listed flags must be provided together, or none. Providing some but not all is an error.
- `Requires(flag="verbose", depends_on="output")` -- if `--verbose` is provided, `--output` must also be provided. But `--output` can appear alone.

```python
@app.command("export", help="export data", dependencies=[
    strictcli.CoRequired(flags=["output", "format"]),
    strictcli.Requires(flag="verbose", depends_on="output"),
])
@strictcli.flag("output", short="o", type=str, help="output file path", default="")
@strictcli.flag("format", type=str, help="output format (json, csv)", default="")
@strictcli.flag("verbose", type=bool, help="show export progress")
def export(output, format, verbose):
    if output:
        print(f"exporting to {output} as {format}")
    if verbose:
        print("progress: 100%")
```

If `--output` is provided without `--format`:

```
$ myapp export --output data.csv
error: flags --output, --format must be used together
try 'myapp --help'
```

If `--verbose` is provided without `--output`:

```
$ myapp export --verbose
error: flag '--verbose' requires '--output'
try 'myapp --help'
```

Notes:

- Flag names in dependencies are strings (names without `--` prefix).
- `CoRequired` needs at least 2 flags.
- `Requires` is unidirectional -- use two `Requires` for bidirectional dependency.
- Checked after environment variable resolution, before defaults are applied.
- Can be combined with mutex groups.

## Help Output

Help is auto-generated at three levels. Pass `--help` or `-h` at any level, or invoke the app with no arguments.

**App level** (`myapp --help`):

```
myapp v1.0.0 -- manage deployments

Commands:
  deploy    deploy the application

Groups:
  db    manage databases

Use 'myapp <command> --help' for more information.
```

**Group level** (`myapp db --help`):

```
myapp db -- manage databases

Commands:
  migrate    run database migrations
  seed       populate with sample data

Use 'myapp db <command> --help' for more information.
```

**Command level** (`myapp deploy --help`):

```
myapp deploy -- deploy the application

Arguments:
  target    deployment target

Flags:
  --region, -r <str>         cloud region [env: MYAPP_REGION] [default: us-east-1]
  --force, --no-force, -f    skip confirmation prompt [default: false]
```

Version: `--version` or `-v` prints `myapp 1.0.0`.

## Testing

`app.test(argv)` runs the CLI in-process and returns a `Result` with captured output:

```python
result = app.test(["deploy", "--force", "production"])

assert result.exit_code == 0
assert "deploying" in result.stdout
assert result.stderr == ""
```

The `Result` dataclass has three fields: `stdout`, `stderr`, and `exit_code`.

## Strict by Design

strictcli is opinionated about strictness:

- **Help is mandatory.** Every command, flag, and argument must have help text. Missing help raises `ValueError` at registration time, not at runtime.
- **Only str and bool.** No int, float, or list types. Parse them yourself in the handler -- it is one line of code and makes the conversion visible.
- **Handler signatures are validated.** Every declared flag and arg must have a matching parameter in the handler function, and vice versa. Extra or missing parameters raise `ValueError`.
- **Env var prefixes are enforced.** If you set `env_prefix="MYAPP"`, every env-backed flag must use that prefix (or explicitly opt out with `prefixed=False`).
- **No hidden defaults.** Required flags fail loudly. Bool flags default to `False`. Everything else must be declared.

If you want automatic type coercion, subcommand hierarchies deeper than two levels, or rich terminal formatting, consider [argparse](https://docs.python.org/3/library/argparse.html), [click](https://click.palletsprojects.com/), or [typer](https://typer.tiangolo.com/).
