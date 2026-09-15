# A runtime-facts object in the schema, the selection language's replacement, an argv terminator, signal handling, and two effect-handle gaps

## Context

During a design round on 2026-09-13 to 2026-09-16 a runtime built on
go-strictcli was measured against a collection of Go programs and against the
demands of a first-class server, and a new expression language, strictexpr,
was designed for the fleet to adopt. Several findings are strictcli's to act
on. All line references are as of 2026-09-15; verify before acting.

## 1. A reserved runtime-facts object in the schema dump and the `--json` envelope

**Problem.** A runtime layered on go-strictcli proves facts about a command at
check time — a purity level below read-only, the prefixes of every contact the
command may make, the child-process vocabularies it reads through, the
platform facts it consults — and can publish them only in its own report. The
schema dump and the machine-mode output a consumer actually reads (a release
tool, an orchestrator, a documentation generator) come from go-strictcli,
which has no key for any of them, and each new fact would otherwise wait on a
framework release.

**Decision (owner, 2026-09-15, on recommendation).** go-strictcli reserves one
namespaced object — in the schema dump per command, and in the `--json`
envelope per dispatch — that a runtime fills and go-strictcli passes through
untouched. The runtime publishes a schema for that object's contents;
consumers validate against the runtime's schema, not go-strictcli's. One
framework change, ever; the layering stays right: the framework carries the
object, the runtime defines its meaning.

**Affected.** The schema-dump emitter and the machine-mode envelope in all
three ports (Python `__init__.py`, `go/strictcli/strictcli.go`, the TypeScript
port), the conformance cases that pin the dump's shape, and the
`--dump-schema` documentation. Effort: small in each port; the conformance
cases are the larger half.

## 2. The check-selection language is replaced by strictexpr at its lowest tier

**Problem.** `rlsbl check --tag 'changelog & !quality'` and every other
consumer's `--tag` are parsed by go-strictcli's own selection language:
identifiers, `&`, `|`, `^`, `-`, `!`, parentheses, with five precedence
levels. It is implemented three times by hand — Python
(`python/strictcli/__init__.py:16165-16338`), Go (`go/strictcli/tagdsl.go`),
TypeScript (`typescript/src/checks/tagdsl.ts`) — and the shared conformance
cases (`conformance/cases/checks.json`) exercise only bare identifiers:
precedence, associativity, parenthesisation and every error message are
covered by each port's own unit tests alone. That is live drift risk in
shipped code. An unknown tag today evaluates to false and prints "no matches".

**Decision (owner, 2026-09-15).** The fleet adopts strictexpr, an expression
language with one grammar, a tiered closed builtin library, no host functions,
a declared typed environment, and a data-file conformance corpus every port
must pass for the tier it claims. The selection language is strictexpr's
lowest tier — identifiers resolving to booleans, conjunction, disjunction,
negation, parentheses — with the registered tag set as the declared
environment. Consequences: the three hand-ported parsers are deleted in favour
of the strictexpr port for each language; **an unknown tag becomes a
check-time error naming the known tags** rather than an empty selection (a
ruled behaviour change); and the migration of every stored selection
expression is verified by re-parsing each under both grammars and comparing
trees, because strictexpr's precedence is its own and a silent re-association
is worse than a loud failure.

**Until strictexpr exists**, the immediate defect stands on its own: extend
`conformance/cases/checks.json` to cover the operators, precedence,
associativity, parenthesisation and each error sentence, so the three ports
are held to one suite.

**Affected.** The three `tagdsl` implementations, `_filter_checks` and its
ports, `conformance/cases/checks.json`, the `--tag` flag help. Effort: the
conformance extension is small; the replacement depends on strictexpr's
Python, Go and TypeScript ports existing at the atoms tier.

## 3. An argv terminator, so a positional argument may begin with a dash

**Problem.** `rlsbl check-name --target=npm -gexpress` is refused as an
unexpected argument, and so is the quoted form, because the shell strips the
quotes before the program sees them — the parser cannot be told that a token
beginning with a dash is a positional. The name `-gexpress` is a real npm
package, and go-strictcli's own output had just named it as a moniker
collision; a program that names a thing in its output must accept that thing
as input.

**Fix.** Support the conventional `--` terminator in all three ports: every
token after it is positional. When a token beginning with a dash is refused as
unknown, the error names the terminator as the remedy (`unknown flag
'-gexpress'; to pass it as an argument, put it after --`). Red-green: a
conformance case that refuses `-gexpress` today and accepts `-- -gexpress`
after the fix, and a remedy-truthfulness case that performs the suggested
spelling.

**Affected.** The argv parser in each port; the unknown-flag error sentence;
`conformance/cases/`. Effort: small.

## 4. An interrupt ends a dispatch cleanly, not with a traceback

**Problem.** Ctrl-C during a network-bound command (`rlsbl check-name` in
batch mode, sleeping between names) prints a raw Python `KeyboardInterrupt`
traceback through `time.sleep` inside the variant checker. Interrupting a
long command is the ordinary case, not an exception, and every consumer CLI
inherits the behaviour.

**Fix.** The dispatch loop in each port handles the interrupt once: a
one-line message on stderr, exit status 130, deferred effects allowed to
finish, the machine-mode wrapper emitted in `--json` mode. Red-green: a
conformance case that sends an interrupt to a sleeping command and asserts
the exit status and the absence of a traceback.

**Affected.** The dispatch entry in each port (Python `run`/`_dispatch`, Go
`runSealed`, the TypeScript equivalent). Effort: small.

## 5. A `Timeout` option on the `Run` and `HTTP` effects

**Problem.** The Go effects handle's `Run` and `HTTP` accept no timeout
(`go/strictcli/effects.go:365-368`, the accepted-option tables). A runtime
that wants every outbound effect to carry a mandatory timeout — so that a
slow child or a slow endpoint cannot stall a dispatch indefinitely — has
nothing to pass. The collection measured had children started with no timeout
in production code, one of which hangs a worker forever on a hung child.

**Fix.** A `Timeout(d)` effect option accepted by `Run`, `Spawn` and `HTTP`,
recorded in the would-do log, enforced live by cancelling the child or the
request and returning a typed error. Ports follow. Effort: small to medium.

## 6. The seal is per-goroutine; a panic on another goroutine escapes it

**Problem.** `runSealed` (`go/strictcli/strictcli.go:2627-2653`) recovers a
panic on the dispatching goroutine only. A runtime that starts goroutines
under its own control (a fork-join over items, a worker per request) needs
the dispatch to be aborted from a goroutine other than the dispatching one,
with the machine-mode wrapper and the would-do log rendered once: a
process-wide first-panic-wins lock, and a way for a non-dispatching goroutine
to end the dispatch with the same exit status and wrapper.

**Fix.** A framework-level abort that any goroutine may call once, serialised
so the log and the wrapper render exactly one time; `runSealed` participates
in it. Effort: medium; needs its own fixtures.

## 7. Recorded, not a defect: the configuration editor's binary comes from the environment

`go/strictcli/config.go:1225-1237` runs whatever `$EDITOR` names, defaulting
to `vi`, through the effects handle. The comment already says launching an
editor is a mutation. It is recorded here because a subprocess inventory
across the collection found it to be the one production child whose *binary*
is environment-supplied, which no argv declaration can bound. Nothing to
change; the fact belongs in the effects documentation.
