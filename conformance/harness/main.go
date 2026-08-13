package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"

	tomledit "github.com/smm-h/go-toml-edit"
	"github.com/smm-h/strictcli/go/strictcli"
)

// Suppress unused-import errors when templates have no substitutions.
var _ = strings.ReplaceAll
var _ = fmt.Println
var _ = sort.Strings

// goPanicExitStatus is the status the Go runtime gives a process whose panic
// was never recovered.
const goPanicExitStatus = 2

// dispatching is set immediately before app.Run(). It is what lets the recover
// below tell the harness's two panic sources apart, which they are not
// interchangeable:
//
//   - BEFORE it, a panic is a REGISTRATION error -- Go's idiomatic spelling of
//     the ValueError ref_python raises and the throw the TS harness makes. All
//     three harnesses report it as "error: <message>" and exit 1, and ~118
//     cases pin that. Nothing in the framework has claimed an exit status at
//     that point: a registration error precedes machine mode and emits no
//     envelope.
//   - AFTER it, a panic is a handler ABORT, and the framework has by then
//     written an envelope whose exit_code says what status this process will
//     leave with (effects contract §19.2 read through §3.5: the panic is not
//     handled, so the status is the language's own). Substituting 1 there
//     would make the envelope contradict its own process, so the harness
//     reproduces Go's 2.
//
// Either way the recover normalizes only the crash REPORT: the sibling
// harnesses print the message as "error: <message>", and dumping Go's
// goroutine trace instead would make every aborting case's stderr incomparable
// for a reason that has nothing to do with the framework.
var dispatching bool

func main() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", r)
			if dispatching {
				os.Exit(goPanicExitStatus)
			}
			os.Exit(1)
		}
	}()

	defPath := os.Getenv("CONFORMANCE_APP_DEF")
	if defPath == "" {
		fmt.Fprintln(os.Stderr, "CONFORMANCE_APP_DEF environment variable not set")
		os.Exit(2)
	}

	data, err := os.ReadFile(defPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "failed to read app def: %v\n", err)
		os.Exit(2)
	}

	var appDef map[string]interface{}
	if err := json.Unmarshal(data, &appDef); err != nil {
		fmt.Fprintf(os.Stderr, "failed to parse app def: %v\n", err)
		os.Exit(2)
	}

	// Build app options.
	var appOpts []strictcli.AppOption
	if v, ok := appDef["env_prefix"]; ok {
		appOpts = append(appOpts, strictcli.WithEnvPrefix(v.(string)))
	}
	if v, ok := appDef["config"]; ok && v.(bool) {
		appOpts = append(appOpts, strictcli.WithConfig())
	}
	if v, ok := appDef["config_path"]; ok && v != nil {
		appOpts = append(appOpts, strictcli.WithConfigPath(v.(string)))
	}
	if v, ok := appDef["config_format"]; ok && v.(string) != "json" {
		appOpts = append(appOpts, strictcli.WithConfigFormat(v.(string)))
	}
	if v, ok := appDef["config_conflict_mode"]; ok && v.(string) != "cli-wins" {
		appOpts = append(appOpts, strictcli.WithConfigConflictMode(v.(string)))
	}
	if v, ok := appDef["infra_root"]; ok {
		for envVar, def := range v.(map[string]interface{}) {
			appOpts = append(appOpts, strictcli.WithInfraRoot(envVar, def.(string)))
		}
	}
	if v, ok := appDef["handshake_env"]; ok {
		for envVar, hlp := range v.(map[string]interface{}) {
			appOpts = append(appOpts, strictcli.WithHandshakeEnv(envVar, hlp.(string)))
		}
	}
	if v, ok := appDef["checks_toml"]; ok {
		appOpts = append(appOpts, strictcli.WithChecksEmbed([]byte(v.(string))))
	}
	if v, ok := appDef["test_coverage"]; ok && v.(bool) {
		appOpts = append(appOpts, strictcli.WithTestCoverage())
	}
	if v, ok := appDef["proc_observe_allowlist"]; ok {
		var prefixes [][]string
		for _, p := range v.([]interface{}) {
			var prefix []string
			for _, e := range p.([]interface{}) {
				prefix = append(prefix, e.(string))
			}
			prefixes = append(prefixes, prefix)
		}
		appOpts = append(appOpts, strictcli.WithProcObserveAllowlist(prefixes))
	}

	app := strictcli.NewApp(
		appDef["name"].(string),
		appDef["version"].(string),
		appDef["help"].(string),
		appOpts...,
	)

	// Register config fields (before commands, since commands may bind to them).
	if cfs, ok := appDef["config_fields_def"]; ok {
		for _, item := range cfs.([]interface{}) {
			cfDef := item.(map[string]interface{})
			cfName := cfDef["name"].(string)
			cfHelp := cfDef["help"].(string)
			var cfOpts []strictcli.ConfigFieldOption
			cfType := "str"
			if t, ok := cfDef["type"]; ok {
				cfType = t.(string)
			}
			switch cfType {
			case "bool":
				cfOpts = append(cfOpts, strictcli.ConfigFieldType(strictcli.TypeBool))
			case "int":
				cfOpts = append(cfOpts, strictcli.ConfigFieldType(strictcli.TypeInt))
			case "float":
				cfOpts = append(cfOpts, strictcli.ConfigFieldType(strictcli.TypeFloat))
			default:
				cfOpts = append(cfOpts, strictcli.ConfigFieldType(strictcli.TypeStr))
			}
			cfOpts = append(cfOpts, strictcli.ConfigFieldHelp(cfHelp))
			if v, ok := cfDef["default"]; ok {
				switch cfType {
				case "bool":
					cfOpts = append(cfOpts, strictcli.ConfigFieldDefault(v.(bool)))
				case "int":
					cfOpts = append(cfOpts, strictcli.ConfigFieldDefault(int(v.(float64))))
				case "float":
					cfOpts = append(cfOpts, strictcli.ConfigFieldDefault(v.(float64)))
				default:
					cfOpts = append(cfOpts, strictcli.ConfigFieldDefault(v.(string)))
				}
			}
			app.ConfigField(cfName, cfOpts...)
		}
	}

	// Register global flags.
	var globalFlags []map[string]interface{}
	if gf, ok := appDef["global_flags"]; ok {
		for _, item := range gf.([]interface{}) {
			fd := item.(map[string]interface{})
			globalFlags = append(globalFlags, fd)
			app.GlobalFlag(buildFlag(fd))
		}
	}

	// Register groups (recursive).
	if groups, ok := appDef["groups"]; ok {
		for _, g := range groups.([]interface{}) {
			buildGroup(g.(map[string]interface{}), app, globalFlags)
		}
	}

	// Register top-level commands.
	if cmds, ok := appDef["commands"]; ok {
		for _, c := range cmds.([]interface{}) {
			registerCommand(c.(map[string]interface{}), appTarget{app}, globalFlags, app)
		}
	}

	// Register tag contracts.
	if tc, ok := appDef["tag_contracts"]; ok {
		for tag, contract := range tc.(map[string]interface{}) {
			cd := contract.(map[string]interface{})
			app.TagContract(tag, cd["requires_flag"].(string))
		}
	}

	// Register checks. The registration FORM (error vs warn) is derived from the
	// check's declared severity in the embedded checks_toml -- there is no
	// per-check registration field. The case only specifies what the impl mints
	// (mint + message + problems); the reporter is minted here per severity.
	if _, ok := appDef["checks_toml"]; ok {
		if checks, ok := appDef["checks"]; ok {
			severities := checkSeverities(appDef["checks_toml"].(string))
			for _, c := range checks.([]interface{}) {
				cd := c.(map[string]interface{})
				cname := cd["name"].(string)
				// An aborting impl mints nothing: it panics instead, which is
				// how a case reaches the runner's per-check containment.
				if aborts, ok := cd["aborts"].(bool); ok && aborts {
					if severities[cname] == "warn" {
						app.RegisterWarnCheck(cname, func(ctx strictcli.CheckContext, r *strictcli.WarnReporter) strictcli.CheckOutcome {
							panic(CheckAborted{msg: checkAbortMessage})
						})
					} else {
						app.RegisterErrorCheck(cname, func(ctx strictcli.CheckContext, r *strictcli.ErrorReporter) strictcli.CheckOutcome {
							panic(CheckAborted{msg: checkAbortMessage})
						})
					}
					continue
				}
				// Capture for closure.
				m, msg, probs, notes := cd["mint"].(string), cd["message"].(string), parseProblems(cd), parseNotes(cd)
				if severities[cname] == "warn" {
					app.RegisterWarnCheck(cname, func(ctx strictcli.CheckContext, r *strictcli.WarnReporter) strictcli.CheckOutcome {
						return mintWarnOutcome(r, m, msg, probs, notes)
					})
				} else {
					app.RegisterErrorCheck(cname, func(ctx strictcli.CheckContext, r *strictcli.ErrorReporter) strictcli.CheckOutcome {
						return mintErrorOutcome(r, m, msg, probs, notes)
					})
				}
			}
		}
	}

	// Register check providers. Each provider is a list of specs it returns;
	// every spec carries its 8 meta fields inline (providers have no TOML). The
	// registration form (NewErrorCheckSpec vs NewWarnCheckSpec) is the spec's
	// impl_form (defaults to its meta severity); a spec whose impl_form differs
	// from its severity pins the materialization-time severity-mismatch panic.
	if providers, ok := appDef["providers"]; ok {
		for _, prov := range providers.([]interface{}) {
			specDefs := prov.([]interface{})
			app.RegisterCheckProvider(func() []strictcli.CheckSpec {
				var specs []strictcli.CheckSpec
				for _, s := range specDefs {
					sd := s.(map[string]interface{})
					meta := providerSpecMeta(sd)
					m, msg, probs, notes := sd["mint"].(string), sd["message"].(string), parseProblems(sd), parseNotes(sd)
					implForm := meta.Severity
					if v, ok := sd["impl_form"]; ok {
						implForm = v.(string)
					}
					if implForm == "warn" {
						specs = append(specs, strictcli.NewWarnCheckSpec(meta,
							func(ctx strictcli.CheckContext, r *strictcli.WarnReporter) strictcli.CheckOutcome {
								return mintWarnOutcome(r, m, msg, probs, notes)
							}))
					} else {
						specs = append(specs, strictcli.NewErrorCheckSpec(meta,
							func(ctx strictcli.CheckContext, r *strictcli.ErrorReporter) strictcli.CheckOutcome {
								return mintErrorOutcome(r, m, msg, probs, notes)
							}))
					}
				}
				return specs
			})
		}
	}

	_, hasToml := appDef["checks_toml"]
	_, hasProviders := appDef["providers"]
	_, hasTestCoverage := appDef["test_coverage"]
	if hasToml || hasProviders || hasTestCoverage {
		app.SetCheckContext(func() strictcli.CheckContext {
			return &testCheckCtx{}
		})
	}

	// Write config_content_late AFTER construction but BEFORE run
	if v, ok := appDef["config_content_late"]; ok {
		configPath := ""
		if cp, ok := appDef["config_path"]; ok && cp != nil {
			configPath = cp.(string)
		}
		if configPath != "" {
			os.WriteFile(configPath, []byte(v.(string)), 0o644)
		}
	}

	// Pre-test argv lists: run app.Test() for each before the main app.Run().
	// Used by test_coverage conformance cases to generate shard files before
	// the check command runs.
	if v, ok := appDef["pre_test"]; ok {
		for _, item := range v.([]interface{}) {
			var argv []string
			for _, arg := range item.([]interface{}) {
				argv = append(argv, arg.(string))
			}
			app.Test(argv)
		}
	}

	// Tool descriptor dump: the exported classification, one line per tool.
	if v, ok := appDef["dump_tools"]; ok && v == true {
		for _, tl := range app.AsTools() {
			fmt.Printf("tool: %s effect=%s consequential=%t\n",
				tl.Name, tl.Effect, tl.Consequential)
		}
	}

	// Programmatic calls: the App.Call() channel, which argv cannot reach.
	if v, ok := appDef["pre_call"]; ok {
		for _, item := range v.([]interface{}) {
			spec := item.(map[string]interface{})
			cmdPath := spec["command"].(string)
			kwargs := map[string]interface{}{}
			if raw, ok := spec["kwargs"]; ok {
				kwargs = raw.(map[string]interface{})
			}
			var callOpts []strictcli.CallOption
			if raw, ok := spec["approve_consequential"]; ok && raw == true {
				callOpts = append(callOpts, strictcli.WithApproveConsequential())
			}
			if _, err := app.Call(cmdPath, kwargs, callOpts...); err != nil {
				fmt.Fprintf(os.Stderr, "call error: %s\n", err.Error())
			} else {
				fmt.Printf("call ok: %s\n", cmdPath)
			}
		}
	}

	// The confirm protocol's interactive branch is otherwise unreachable from a
	// subprocess: a case's stdin is a pipe, and a pipe is not a TTY in any of
	// the three implementations, so every consequential case would take the
	// non-interactive error branch. The framework's test-only confirm seam
	// says the answer channel IS interactive and leaves the answer itself
	// coming from the case's real stdin -- WHERE the answer comes from, never
	// WHETHER the protocol runs.
	if v, ok := appDef["confirm_stdin_interactive"]; ok && v.(bool) {
		app.SetConfirmIO(&strictcli.ConfirmIO{
			IsInteractive: func() bool { return true },
			In:            os.Stdin,
		})
	}

	// The structured effect-log side channel (§14.3): the same env-var file
	// handoff as CONFORMANCE_APP_DEF. App.Run ends in os.Exit, so the write
	// rides SetExitHook -- the Go counterpart of the Python ref's atexit and
	// the TS harness's process.on("exit").
	if logPath := os.Getenv("CONFORMANCE_EFFECT_LOG"); logPath != "" {
		app.SetExitHook(func() {
			records := app.EffectLog()
			if records == nil {
				records = []map[string]interface{}{}
			}
			// encoding/json sorts map keys, which is what §14.3 asks for.
			data, err := json.Marshal(records)
			if err != nil {
				fmt.Fprintf(os.Stderr, "failed to marshal effect log: %v\n", err)
				return
			}
			if err := os.WriteFile(logPath, data, 0o644); err != nil {
				fmt.Fprintf(os.Stderr, "failed to write effect log: %v\n", err)
			}
		})
	}

	dispatching = true
	app.Run()
}

type testCheckCtx struct{}

func (c *testCheckCtx) ProjectRoot() string { return "." }

// checkProblemSpec is a single problem the case asks the impl to mint.
type checkProblemSpec struct {
	severity string // "error" or "warn"
	text     string
}

// parseProblems extracts the optional "problems" list from a check/spec def.
func parseProblems(cd map[string]interface{}) []checkProblemSpec {
	var problems []checkProblemSpec
	if p, ok := cd["problems"]; ok {
		for _, item := range p.([]interface{}) {
			pm := item.(map[string]interface{})
			problems = append(problems, checkProblemSpec{
				severity: pm["severity"].(string),
				text:     pm["text"].(string),
			})
		}
	}
	return problems
}

// parseNotes extracts the optional "notes" list from a check/spec def. Notes are
// verdict-inert informational strings replayed onto the reporter via Note().
func parseNotes(cd map[string]interface{}) []string {
	var notes []string
	if n, ok := cd["notes"]; ok {
		for _, item := range n.([]interface{}) {
			notes = append(notes, item.(string))
		}
	}
	return notes
}

// providerSpecMeta builds a CheckSpecMeta from a provider spec def, carrying all
// eight declarative meta fields inline (providers have no TOML).
func providerSpecMeta(sd map[string]interface{}) strictcli.CheckSpecMeta {
	toStrList := func(key string) []string {
		var out []string
		if v, ok := sd[key]; ok && v != nil {
			for _, x := range v.([]interface{}) {
				out = append(out, x.(string))
			}
		}
		return out
	}
	scope := ""
	if v, ok := sd["scope"]; ok && v != nil {
		scope = v.(string)
	}
	return strictcli.CheckSpecMeta{
		Name:         sd["name"].(string),
		Tags:         toStrList("tags"),
		Severity:     sd["severity"].(string),
		Fast:         sd["fast"].(bool),
		Pure:         sd["pure"].(bool),
		NeedsNetwork: sd["needs_network"].(bool),
		DependsOn:    toStrList("depends_on"),
		Scope:        scope,
	}
}

// checkSeverities parses the embedded checks_toml and returns a name->severity
// map. The registration form is derived from this (there is no per-check
// registration field in the case). A parse failure yields an empty map, which
// falls back to error-severity registration -- the strictcli severity
// cross-check would then surface any genuine mismatch as a panic.
func checkSeverities(tomlStr string) map[string]string {
	result := map[string]string{}
	var raw map[string]interface{}
	if err := tomledit.Unmarshal([]byte(tomlStr), &raw); err != nil {
		return result
	}
	checks, ok := raw["checks"].(map[string]interface{})
	if !ok {
		return result
	}
	for name, v := range checks {
		if fields, ok := v.(map[string]interface{}); ok {
			if sev, ok := fields["severity"].(string); ok {
				result[name] = sev
			}
		}
	}
	return result
}

// checkAbortMessage is what an `aborts` check impl panics with. The sibling
// harnesses raise/throw the identical text carried by a type spelled the same,
// so the framework's containment line is byte-identical across targets.
const checkAbortMessage = "conformance: check aborted"

// CheckAborted is the panic value an `aborts` check impl carries. Its NAME is
// part of the contract: Python raises a CheckAborted exception and TypeScript
// throws a CheckAborted error, and the framework prints the unqualified type
// name, so all three containment lines read the same.
type CheckAborted struct{ msg string }

// Error makes CheckAborted an error, which is how the Go framework recovers its
// message (the sibling harnesses' types carry theirs the same way).
func (e CheckAborted) Error() string { return e.msg }

// mintErrorOutcome replays the case's problems onto an ErrorReporter and mints
// the requested terminal outcome.
func mintErrorOutcome(r *strictcli.ErrorReporter, mint, message string, problems []checkProblemSpec, notes []string) strictcli.CheckOutcome {
	for _, n := range notes {
		r.Note(n)
	}
	for _, p := range problems {
		if p.severity == "error" {
			r.Error(p.text)
		} else {
			r.Warn(p.text)
		}
	}
	switch mint {
	case "passed":
		return r.Passed(message)
	case "skipped":
		return r.Skipped(message)
	default:
		return r.Found(message)
	}
}

// mintWarnOutcome replays the case's problems onto a WarnReporter (which can
// only mint warn-severity problems) and mints the requested terminal outcome.
func mintWarnOutcome(r *strictcli.WarnReporter, mint, message string, problems []checkProblemSpec, notes []string) strictcli.CheckOutcome {
	for _, n := range notes {
		r.Note(n)
	}
	for _, p := range problems {
		r.Warn(p.text)
	}
	switch mint {
	case "passed":
		return r.Passed(message)
	case "skipped":
		return r.Skipped(message)
	default:
		return r.Found(message)
	}
}

// target abstracts over App and Group for command registration.
type target interface {
	Command(name, help string, handler func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome, opts ...strictcli.CmdOption)
	Deprecated(name, message string, opts ...strictcli.CmdOption)
}

type appTarget struct{ a *strictcli.App }

func (t appTarget) Command(name, help string, handler func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome, opts ...strictcli.CmdOption) {
	t.a.Command(name, help, handler, opts...)
}
func (t appTarget) Deprecated(name, message string, opts ...strictcli.CmdOption) {
	t.a.Deprecated(name, message, opts...)
}

type groupTarget struct{ g *strictcli.Group }

func (t groupTarget) Command(name, help string, handler func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome, opts ...strictcli.CmdOption) {
	t.g.Command(name, help, handler, opts...)
}
func (t groupTarget) Deprecated(name, message string, opts ...strictcli.CmdOption) {
	t.g.Deprecated(name, message, opts...)
}

// buildFlag constructs a strictcli.Flag from a JSON flag definition.
func buildFlag(fd map[string]interface{}) strictcli.Flag {
	name := fd["name"].(string)
	help := fd["help"].(string)
	ftype := "str"
	if t, ok := fd["type"]; ok {
		ftype = t.(string)
	}

	var opts []strictcli.FlagOption

	if v, ok := fd["short"]; ok {
		opts = append(opts, strictcli.Short(v.(string)))
	}
	if v, ok := fd["default_relative_to_root"]; ok {
		rtr := v.(map[string]interface{})
		var parts []string
		if ps, ok := rtr["parts"]; ok {
			for _, p := range ps.([]interface{}) {
				parts = append(parts, p.(string))
			}
		}
		opts = append(opts, strictcli.Default(strictcli.RelativeToRoot(rtr["env_var"].(string), parts...)))
	}
	if v, ok := fd["default"]; ok {
		if v == nil {
			opts = append(opts, strictcli.Default(nil))
		} else if arr, ok := v.([]interface{}); ok {
			// Array default (repeatable flags).
			converted := make([]interface{}, len(arr))
			for i, elem := range arr {
				switch ftype {
				case "int":
					converted[i] = int(elem.(float64))
				case "float":
					converted[i] = elem.(float64)
				default: // str
					converted[i] = elem.(string)
				}
			}
			opts = append(opts, strictcli.Default(converted))
		} else {
			switch ftype {
			case "bool":
				opts = append(opts, strictcli.Default(v.(bool)))
			case "int":
				if f, ok := v.(float64); ok {
					opts = append(opts, strictcli.Default(int(f)))
				} else {
					opts = append(opts, strictcli.Default(v))
				}
			case "float":
				if f, ok := v.(float64); ok {
					opts = append(opts, strictcli.Default(f))
				} else {
					opts = append(opts, strictcli.Default(v))
				}
			default: // str
				opts = append(opts, strictcli.Default(v.(string)))
			}
		}
	}
	if v, ok := fd["env"]; ok {
		opts = append(opts, strictcli.Env(v.(string)))
	}
	if v, ok := fd["prefixed"]; ok {
		opts = append(opts, strictcli.Prefixed(v.(bool)))
	}
	if v, ok := fd["choices_str"]; ok {
		var items []interface{}
		for _, item := range v.([]interface{}) {
			items = append(items, item.(string))
		}
		opts = append(opts, strictcli.Choices(items...))
	}
	if v, ok := fd["choices_int"]; ok {
		var items []interface{}
		for _, item := range v.([]interface{}) {
			items = append(items, int(item.(float64)))
		}
		opts = append(opts, strictcli.Choices(items...))
	}
	if v, ok := fd["choices_float"]; ok {
		var items []interface{}
		for _, item := range v.([]interface{}) {
			items = append(items, item.(float64))
		}
		opts = append(opts, strictcli.Choices(items...))
	}
	if v, ok := fd["repeatable"]; ok && v.(bool) {
		opts = append(opts, strictcli.Repeatable())
	}
	if v, ok := fd["unique"]; ok {
		opts = append(opts, strictcli.Unique(v.(bool)))
	} else if strings.HasPrefix(ftype, "list[") || strings.HasPrefix(ftype, "dict[") {
		// Compound types in Go require explicit unique; default to false
		// (Python auto-defaults this for list types and disallows it for dict types)
		opts = append(opts, strictcli.Unique(false))
	}
	if v, ok := fd["conflict_mode"]; ok {
		opts = append(opts, strictcli.ConflictMode(v.(string)))
	}
	if v, ok := fd["env_separator"]; ok {
		opts = append(opts, strictcli.EnvSeparator(v.(string)))
	}
	if v, ok := fd["negatable"]; ok && !v.(bool) {
		opts = append(opts, strictcli.NegatableOpt(false))
	}

	switch ftype {
	case "bool":
		return strictcli.BoolFlag(name, help, opts...)
	case "int":
		return strictcli.IntFlag(name, help, opts...)
	case "float":
		return strictcli.FloatFlag(name, help, opts...)
	case "list[str]":
		return strictcli.ListFlag(strictcli.TypeStr, name, help, opts...)
	case "list[int]":
		return strictcli.ListFlag(strictcli.TypeInt, name, help, opts...)
	case "list[float]":
		return strictcli.ListFlag(strictcli.TypeFloat, name, help, opts...)
	case "dict[str,str]":
		return strictcli.DictFlag(strictcli.TypeStr, name, help, opts...)
	case "dict[str,int]":
		return strictcli.DictFlag(strictcli.TypeInt, name, help, opts...)
	case "dict[str,float]":
		return strictcli.DictFlag(strictcli.TypeFloat, name, help, opts...)
	default:
		return strictcli.StringFlag(name, help, opts...)
	}
}

// buildArg constructs a strictcli.Arg from a JSON arg definition.
func buildArg(ad map[string]interface{}) strictcli.Arg {
	name := ad["name"].(string)
	help := ad["help"].(string)

	var opts []strictcli.ArgOption

	atype := "str"
	if t, ok := ad["type"]; ok {
		atype = t.(string)
	}
	switch atype {
	case "bool":
		opts = append(opts, strictcli.ArgType(strictcli.TypeBool))
	case "int":
		opts = append(opts, strictcli.ArgType(strictcli.TypeInt))
	case "float":
		opts = append(opts, strictcli.ArgType(strictcli.TypeFloat))
	}

	if v, ok := ad["required"]; ok {
		opts = append(opts, strictcli.ArgRequired(v.(bool)))
	}
	if v, ok := ad["default"]; ok {
		if v == nil {
			opts = append(opts, strictcli.ArgDefault(nil))
		} else {
			switch atype {
			case "int":
				opts = append(opts, strictcli.ArgDefault(int(v.(float64))))
			case "float":
				opts = append(opts, strictcli.ArgDefault(v.(float64)))
			case "bool":
				opts = append(opts, strictcli.ArgDefault(v.(bool)))
			default:
				opts = append(opts, strictcli.ArgDefault(v.(string)))
			}
		}
	}
	if v, ok := ad["variadic"]; ok && v.(bool) {
		opts = append(opts, strictcli.Variadic())
	}
	if v, ok := ad["choices_str"]; ok {
		var items []interface{}
		for _, item := range v.([]interface{}) {
			items = append(items, item.(string))
		}
		opts = append(opts, strictcli.ArgChoices(items...))
	}
	if v, ok := ad["choices_int"]; ok {
		var items []interface{}
		for _, item := range v.([]interface{}) {
			items = append(items, int(item.(float64)))
		}
		opts = append(opts, strictcli.ArgChoices(items...))
	}
	if v, ok := ad["choices_float"]; ok {
		var items []interface{}
		for _, item := range v.([]interface{}) {
			items = append(items, item.(float64))
		}
		opts = append(opts, strictcli.ArgChoices(items...))
	}

	return strictcli.NewArg(name, help, opts...)
}

// buildCmdOptions constructs CmdOption list from a command definition.
func buildCmdOptions(cmdDef map[string]interface{}) []strictcli.CmdOption {
	var opts []strictcli.CmdOption

	// Args.
	if args, ok := cmdDef["args"]; ok {
		var argList []strictcli.Arg
		for _, a := range args.([]interface{}) {
			argList = append(argList, buildArg(a.(map[string]interface{})))
		}
		opts = append(opts, strictcli.WithArgs(argList...))
	}

	// Direct flags.
	if flags, ok := cmdDef["flags"]; ok {
		var flagList []strictcli.Flag
		for _, f := range flags.([]interface{}) {
			flagList = append(flagList, buildFlag(f.(map[string]interface{})))
		}
		opts = append(opts, strictcli.WithFlags(flagList...))
	}

	// Flag sets.
	if flagSets, ok := cmdDef["flag_sets"]; ok {
		for _, t := range flagSets.([]interface{}) {
			td := t.(map[string]interface{})
			fsName := td["name"].(string)
			var fsFlags []strictcli.Flag
			for _, f := range td["flags"].([]interface{}) {
				fsFlags = append(fsFlags, buildFlag(f.(map[string]interface{})))
			}
			opts = append(opts, strictcli.WithFlagSets(strictcli.FlagSet{Name: fsName, Flags: fsFlags}))
		}
	}

	// Mutex groups.
	if mutex, ok := cmdDef["mutex"]; ok {
		for _, m := range mutex.([]interface{}) {
			md := m.(map[string]interface{})
			var mFlags []strictcli.Flag
			for _, f := range md["flags"].([]interface{}) {
				mFlags = append(mFlags, buildFlag(f.(map[string]interface{})))
			}
			opts = append(opts, strictcli.WithMutex(strictcli.MutexGroup{Flags: mFlags}))
		}
	}

	// Dependencies.
	if deps, ok := cmdDef["dependencies"]; ok {
		var depList []strictcli.Dependency
		for _, d := range deps.([]interface{}) {
			dd := d.(map[string]interface{})
			switch dd["type"].(string) {
			case "co_required":
				var flags []string
				for _, f := range dd["flags"].([]interface{}) {
					flags = append(flags, f.(string))
				}
				depList = append(depList, strictcli.CoRequired{Flags: flags})
			case "requires":
				depList = append(depList, strictcli.Requires{
					Flag:      dd["flag"].(string),
					DependsOn: dd["depends_on"].(string),
				})
			case "implies":
				depList = append(depList, strictcli.Implies{
					Flag:    dd["flag"].(string),
					Implies: dd["implies"].(string),
					Value:   dd["value"].(bool),
				})
			}
		}
		opts = append(opts, strictcli.WithDependencies(depList...))
	}

	// Tags.
	if tags, ok := cmdDef["tags"]; ok {
		var tagList []string
		for _, t := range tags.([]interface{}) {
			tagList = append(tagList, t.(string))
		}
		opts = append(opts, strictcli.WithTags(tagList...))
	}

	// Config fields.
	if cfs, ok := cmdDef["config_fields"]; ok {
		var cfNames []string
		for _, f := range cfs.([]interface{}) {
			cfNames = append(cfNames, f.(string))
		}
		opts = append(opts, strictcli.WithConfigFields(cfNames...))
	}

	// Hidden.
	if v, ok := cmdDef["hidden"]; ok && v.(bool) {
		opts = append(opts, strictcli.WithHidden())
	}

	// Interactive.
	if v, ok := cmdDef["interactive"]; ok && v.(bool) {
		opts = append(opts, strictcli.WithInteractive())
	}

	// The effects regime: classification (§1.1), grants (§6.1) and declared
	// forwarding (§10.2). A case that omits `effect` is asserting the
	// registration hard error, so the option is only appended when declared.
	if v, ok := cmdDef["effect"]; ok {
		opts = append(opts, strictcli.WithEffect(v.(string)))
	}
	// `consequential` is NOT mandatory (§8.1): absence means "not
	// consequential", so the option is only appended when declared.
	if v, ok := cmdDef["consequential"]; ok && v.(bool) {
		opts = append(opts, strictcli.WithConsequential())
	}
	// `dry_run_supported` is likewise NOT mandatory: absence means supported.
	// Only false is declarable, and Go's single option carries the mandatory
	// reason, so the two case keys collapse into one call here.
	if v, ok := cmdDef["dry_run_supported"]; ok && !v.(bool) {
		reason, _ := cmdDef["dry_run_unsupported_reason"].(string)
		opts = append(opts, strictcli.WithDryRunUnsupported(reason))
	} else if reason, ok := cmdDef["dry_run_unsupported_reason"].(string); ok {
		// The orphan state: a reason with no declaration. WithDryRunUnsupported
		// cannot express it (it always sets both fields), but CmdOption is a
		// plain func(*Command) over exported fields, which is exactly the route
		// a consumer could take -- and exactly what the framework's guard
		// rejects.
		opts = append(opts, func(c *strictcli.Command) {
			c.DryRunUnsupportedReason = reason
		})
	}
	// The machine payload's declared schema (§19.5). A handler_returns of kind
	// "data"/"exit_data" supplies a payload, and ctx.Payload refuses to run on
	// a command that declares no schema -- so the harness declares the
	// permissive literal for exactly those commands. The literal is identical
	// in all three harnesses, which is what keeps the schema dump in parity.
	// A case may declare its own literal with "payload_schema", which is how
	// the closed subset's enforcement becomes observable through the CLI: the
	// schema dump publishes it verbatim and a payload is validated against it.
	if declared, ok := cmdDef["payload_schema"].(map[string]interface{}); ok {
		opts = append(opts, strictcli.PayloadSchema(declared))
	} else if hr, ok := cmdDef["handler_returns"].(map[string]interface{}); ok {
		if k, _ := hr["kind"].(string); k == "data" || k == "exit_data" {
			opts = append(opts, strictcli.PayloadSchema(map[string]interface{}{}))
		}
	} else if v, ok := cmdDef["handler_payloads_recorded"].(bool); ok && v {
		opts = append(opts, strictcli.PayloadSchema(map[string]interface{}{}))
	}
	// Stdout ownership (§19.6): the command's own document keeps stdout and the
	// envelope moves to stderr in machine mode.
	if v, ok := cmdDef["owns_stdout"].(bool); ok && v {
		opts = append(opts, strictcli.OwnsStdout())
	}
	if v, ok := cmdDef["grants"]; ok {
		var grants []strictcli.Grant
		for _, item := range v.([]interface{}) {
			g := item.(map[string]interface{})
			grants = append(grants, strictcli.Grant{
				Name:   g["name"].(string),
				Reason: g["reason"].(string),
				Kind:   g["kind"].(string),
			})
		}
		opts = append(opts, strictcli.WithGrants(grants...))
	}
	if v, ok := cmdDef["forwarding"]; ok {
		opts = append(opts, strictcli.WithForwarding(
			v.(map[string]interface{})["reason"].(string),
		))
	}

	return opts
}

// --- the effects vocabulary (effects contract §14.4) ---------------------
//
// `handler_effects` is materialized identically by all three harnesses:
// iterate the array in order, call the named method with EXACTLY the keys the
// entry declares (no per-method filtering -- a case declaring a key the method
// does not accept is asserting the error), and keep the returned carrier in a
// per-run map indexed by position so `forward_from` / `extract_from` can
// reference it.
//
// Go's carriers have no exported method in common (§2.5.3), so the map holds
// them as `any`: forwarding passes the value straight into the effects API's
// `any` parameter, and extraction type-switches to the shape's own extractor.

// effectOptions builds the option variadic from the keys the entry declares,
// in the harnesses' shared order.
func effectOptions(e map[string]interface{}) []strictcli.EffectOption {
	var opts []strictcli.EffectOption
	if v, ok := e["stream"]; ok {
		opts = append(opts, strictcli.Stream(v.(bool)))
	}
	if v, ok := e["resource"]; ok {
		opts = append(opts, strictcli.Resource(v.(string)))
	}
	if v, ok := e["skip_if_current"]; ok {
		opts = append(opts, strictcli.SkipIfCurrent(v.(string)))
	}
	if v, ok := e["grant"]; ok {
		opts = append(opts, strictcli.UseGrant(v.(string)))
	}
	return opts
}

// extractCarrier reads a concrete value out of a carrier -- the illegal use
// that trips the runtime seal and truncates the preview (§4.4). Each shape has
// its own extractor; all four panic with the truncation error when unsettled.
func extractCarrier(c interface{}) {
	switch v := c.(type) {
	case strictcli.Completed:
		_ = v.Stdout()
	case strictcli.Response:
		_ = v.Body()
	case strictcli.Spawned:
		_ = v.PID()
	case strictcli.Unsettled:
		_ = v.Bool()
	}
}

// runHandlerDiagnostics issues the declared Context diagnostic calls, in
// order. The four levels are gated by --quiet / --verbose (effects contract
// §7.4); the harness does no gating of its own, it just calls the method.
func runHandlerDiagnostics(ctx *strictcli.Context, entries []interface{}) {
	for _, raw := range entries {
		d := raw.(map[string]interface{})
		msg := d["message"].(string)
		switch d["level"].(string) {
		case "debug":
			ctx.Debug(msg)
		case "info":
			ctx.Info(msg)
		case "warn":
			ctx.Warn(msg)
		case "error":
			ctx.Error(msg)
		default:
			panic(fmt.Sprintf("unknown handler_diagnostics level: %v", d["level"]))
		}
	}
}

// runHandlerEffects issues the declared effect calls, in order.
func runHandlerEffects(ctx *strictcli.Context, entries []interface{}) {
	eff := map[int]interface{}{}
	for i, item := range entries {
		e := item.(map[string]interface{})
		method := e["method"].(string)

		if v, ok := e["extract_from"]; ok {
			// Terminal by construction: the extraction truncates the run.
			extractCarrier(eff[int(v.(float64))])
			return
		}

		var fwd interface{}
		hasFwd := false
		if v, ok := e["forward_from"]; ok {
			fwd = eff[int(v.(float64))]
			hasFwd = true
		}
		opts := effectOptions(e)

		var carrier interface{}
		var err error
		switch method {
		case "run", "spawn":
			var argv []any
			if v, ok := e["argv"]; ok {
				for _, a := range v.([]interface{}) {
					argv = append(argv, a.(string))
				}
			}
			if hasFwd {
				argv = append(argv, fwd)
			}
			if method == "run" {
				carrier, err = ctx.Effects().Run(argv, opts...)
			} else {
				carrier, err = ctx.Effects().Spawn(argv, opts...)
			}
		case "write":
			var path any = e["path"].(string)
			var content any
			if hasFwd {
				content = fwd
			} else {
				content = e["content"].(string)
			}
			carrier, err = ctx.Effects().Write(path, content, opts...)
		case "mkdir", "remove":
			var path any
			if hasFwd {
				path = fwd
			} else {
				path = e["path"].(string)
			}
			if method == "mkdir" {
				carrier, err = ctx.Effects().Mkdir(path, opts...)
			} else {
				carrier, err = ctx.Effects().Remove(path, opts...)
			}
		case "rename":
			var dst any
			if hasFwd {
				dst = fwd
			} else {
				dst = e["to"].(string)
			}
			carrier, err = ctx.Effects().Rename(e["path"].(string), dst, opts...)
		case "chmod":
			var path any
			if hasFwd {
				path = fwd
			} else {
				path = e["path"].(string)
			}
			mode, perr := strconv.ParseInt(e["mode"].(string), 8, 32)
			if perr != nil {
				panic(perr)
			}
			carrier, err = ctx.Effects().Chmod(path, int(mode), opts...)
		case "http":
			var url any
			if hasFwd {
				url = fwd
			} else {
				url = e["url"].(string)
			}
			carrier, err = ctx.Effects().HTTP(e["http_method"].(string), url, opts...)
		}
		if err != nil {
			// The Go idiom for what Python and TypeScript raise (§2.5.4, §17).
			// The harness surfaces it the same way the siblings' uncaught
			// exception surfaces: "error: <msg>" on stderr, exit 1.
			panic(err.Error())
		}
		eff[i+1] = carrier
	}
}

// collectAllFlagDefs gathers all flag definitions for a command (global + direct + flag sets + mutex).
func collectAllFlagDefs(cmdDef map[string]interface{}, globalFlags []map[string]interface{}) []map[string]interface{} {
	var all []map[string]interface{}

	// Global flags first.
	all = append(all, globalFlags...)

	// Direct command flags.
	if flags, ok := cmdDef["flags"]; ok {
		for _, f := range flags.([]interface{}) {
			all = append(all, f.(map[string]interface{}))
		}
	}

	// Flag set flags.
	if flagSets, ok := cmdDef["flag_sets"]; ok {
		for _, t := range flagSets.([]interface{}) {
			td := t.(map[string]interface{})
			for _, f := range td["flags"].([]interface{}) {
				all = append(all, f.(map[string]interface{}))
			}
		}
	}

	// Mutex flags.
	if mutex, ok := cmdDef["mutex"]; ok {
		for _, m := range mutex.([]interface{}) {
			md := m.(map[string]interface{})
			for _, f := range md["flags"].([]interface{}) {
				all = append(all, f.(map[string]interface{}))
			}
		}
	}

	return all
}

// handlerAbortMessage is what a `handler_aborts` handler panics with. The
// sibling harnesses raise/throw the identical text, and all three surface it
// as "error: <message>", so an aborting case's stderr is byte-identical
// across targets.
const handlerAbortMessage = "conformance: handler aborted"

// runHandlerClaim performs the claimed-rendering calls (effects contract
// §19.7). It runs AFTER handler_effects and BEFORE handler_diagnostics /
// handler_prints, so a rendered log lands ahead of the handler's own output --
// which is exactly the ordering the feature exists to make possible.
func runHandlerClaim(ctx *strictcli.Context, cmdDef map[string]interface{}) {
	if v, ok := cmdDef["handler_claims_log"].(bool); ok && v {
		ctx.Effects().Recorded()
	}
	if v, ok := cmdDef["handler_payloads_recorded"].(bool); ok && v {
		verbs := []string{}
		for _, rec := range ctx.Effects().Recorded() {
			verbs = append(verbs, rec["verb"].(string))
		}
		ctx.Payload(verbs)
	}
	if v, ok := cmdDef["handler_renders_log"].(bool); ok && v {
		ctx.Effects().RenderLog()
	}
}

// makeHandler builds a normal command handler function from a command definition.
func makeHandler(cmdDef map[string]interface{}, globalFlags []map[string]interface{}) func(ctx *strictcli.Context, args map[string]interface{}) strictcli.Outcome {
	// handler_aborts: the handler unwinds instead of returning, after its
	// effects and diagnostics have run. This is the language-neutral way to
	// reach the framework's aborted-preview path -- Go's Outcome type makes
	// handler_returns kind "bad" unrepresentable, but a panic is not.
	if v, ok := cmdDef["handler_aborts"]; ok && v.(bool) {
		effects, _ := cmdDef["handler_effects"].([]interface{})
		diags, _ := cmdDef["handler_diagnostics"].([]interface{})
		return func(ctx *strictcli.Context, args map[string]interface{}) strictcli.Outcome {
			runHandlerEffects(ctx, effects)
			runHandlerClaim(ctx, cmdDef)
			runHandlerDiagnostics(ctx, diags)
			panic(handlerAbortMessage)
		}
	}

	// handler_returns pins an explicit Outcome (survivor-contract cases): an
	// exit-only, data-only, exit+data, or None-equivalent return. When present,
	// the template-printing path is skipped entirely.
	if hrRaw, ok := cmdDef["handler_returns"]; ok {
		hr := hrRaw.(map[string]interface{})
		kind := hr["kind"].(string)
		// Inexpressible kinds are a HARD ERROR at registration, never a silent
		// mapping to something else. "bad" (a non-Outcome return) has no Go
		// representation, and quietly falling through to Exit(0) would turn a
		// case whose target restriction was dropped into a false pass.
		switch kind {
		case "exit", "data", "exit_data", "none":
		default:
			panic(fmt.Sprintf(
				"conformance harness: handler_returns kind %q is inexpressible "+
					"in Go's Outcome type; the case must restrict its targets",
				kind,
			))
		}
		code := 0
		if v, ok := hr["code"]; ok {
			code = int(v.(float64))
		}
		data := hr["data"]
		effects, _ := cmdDef["handler_effects"].([]interface{})
		diags, _ := cmdDef["handler_diagnostics"].([]interface{})
		return func(ctx *strictcli.Context, args map[string]interface{}) strictcli.Outcome {
			runHandlerEffects(ctx, effects)
			runHandlerClaim(ctx, cmdDef)
			runHandlerDiagnostics(ctx, diags)
			switch kind {
			case "data":
				ctx.Payload(data)
				return strictcli.Exit(0)
			case "exit_data":
				ctx.Payload(data)
				return strictcli.Exit(code)
			default: // "exit" or "none" (Go has no None; None maps to Exit(0))
				return strictcli.Exit(code)
			}
		}
	}

	// handler_effects runs BEFORE the handler_prints path and does not replace
	// it (§14.4). A handler_effects-only command declares no template.
	handlerEffects, _ := cmdDef["handler_effects"].([]interface{})
	handlerDiagnostics, _ := cmdDef["handler_diagnostics"].([]interface{})
	template := ""
	hasTemplate := false
	if v, ok := cmdDef["handler_prints"]; ok {
		template = v.(string)
		hasTemplate = true
	}
	exitCode := 0
	if v, ok := cmdDef["handler_exit_code"]; ok {
		exitCode = int(v.(float64))
	}

	allFlags := collectAllFlagDefs(cmdDef, globalFlags)

	// Collect arg defs.
	var argDefs []map[string]interface{}
	if args, ok := cmdDef["args"]; ok {
		for _, a := range args.([]interface{}) {
			argDefs = append(argDefs, a.(map[string]interface{}))
		}
	}

	// Capture for closure.
	ec := exitCode

	return func(ctx *strictcli.Context, args map[string]interface{}) strictcli.Outcome {
		runHandlerEffects(ctx, handlerEffects)
		runHandlerClaim(ctx, cmdDef)
		runHandlerDiagnostics(ctx, handlerDiagnostics)
		if !hasTemplate {
			return strictcli.Exit(ec)
		}
		out := template

		// Substitute {source:name} provenance references via ctx.Source().
		for _, fd := range allFlags {
			name := fd["name"].(string)
			sourceKey := "{source:" + name + "}"
			if strings.Contains(out, sourceKey) {
				out = strings.ReplaceAll(out, sourceKey, ctx.Source(name))
			}
		}

		// Substitute flags.
		for _, fd := range allFlags {
			name := fd["name"].(string)
			key := strings.ReplaceAll(name, "-", "_")
			ftype := "str"
			if t, ok := fd["type"]; ok {
				ftype = t.(string)
			}

			if strings.HasPrefix(ftype, "list[") {
				raw := args[key]
				var parts []string
				if raw != nil {
					itemType := ftype[5 : len(ftype)-1] // extract "int" from "list[int]"
					for _, v := range raw.([]interface{}) {
						if itemType == "int" {
							parts = append(parts, fmt.Sprintf("%d", v.(int)))
						} else {
							parts = append(parts, fmt.Sprintf("%v", v))
						}
					}
				}
				out = strings.ReplaceAll(out, "{"+name+"}", strings.Join(parts, ","))
			} else if strings.HasPrefix(ftype, "dict[") {
				raw := args[key]
				var parts []string
				if raw != nil {
					m := raw.(map[string]interface{})
					keys := make([]string, 0, len(m))
					for k := range m {
						keys = append(keys, k)
					}
					sort.Strings(keys)
					for _, k := range keys {
						parts = append(parts, fmt.Sprintf("%s=%v", k, m[k]))
					}
				}
				out = strings.ReplaceAll(out, "{"+name+"}", strings.Join(parts, ","))
			} else if rep, ok := fd["repeatable"]; ok && rep.(bool) {
				raw := args[key]
				var parts []string
				if raw != nil {
					for _, v := range raw.([]interface{}) {
						if ftype == "int" {
							parts = append(parts, fmt.Sprintf("%d", v.(int)))
						} else {
							parts = append(parts, fmt.Sprintf("%v", v))
						}
					}
				}
				out = strings.ReplaceAll(out, "{"+name+"}", strings.Join(parts, ","))
			} else if ftype == "bool" {
				if args[key] == nil {
					out = strings.ReplaceAll(out, "{"+name+"}", "None")
				} else if args[key].(bool) {
					out = strings.ReplaceAll(out, "{"+name+"}", "true")
				} else {
					out = strings.ReplaceAll(out, "{"+name+"}", "false")
				}
			} else if ftype == "int" {
				out = strings.ReplaceAll(out, "{"+name+"}", fmt.Sprintf("%d", args[key].(int)))
			} else if ftype == "float" {
				out = strings.ReplaceAll(out, "{"+name+"}", fmt.Sprintf("%v", args[key].(float64)))
			} else {
				// str -- might be nil
				if args[key] != nil {
					out = strings.ReplaceAll(out, "{"+name+"}", fmt.Sprintf("%v", args[key]))
				} else {
					out = strings.ReplaceAll(out, "{"+name+"}", "None")
				}
			}
		}

		// Substitute args.
		for _, ad := range argDefs {
			name := ad["name"].(string)
			key := name // args use name as-is
			atype := "str"
			if t, ok := ad["type"]; ok {
				atype = t.(string)
			}

			if v, ok := ad["variadic"]; ok && v.(bool) {
				raw := args[key]
				var parts []string
				if raw != nil {
					for _, v := range raw.([]interface{}) {
						switch atype {
						case "int":
							parts = append(parts, fmt.Sprintf("%d", v.(int)))
						default:
							parts = append(parts, fmt.Sprintf("%v", v))
						}
					}
				}
				out = strings.ReplaceAll(out, "{"+name+"}", strings.Join(parts, ","))
			} else if atype == "bool" {
				if args[key] == nil {
					out = strings.ReplaceAll(out, "{"+name+"}", "None")
				} else if args[key].(bool) {
					out = strings.ReplaceAll(out, "{"+name+"}", "true")
				} else {
					out = strings.ReplaceAll(out, "{"+name+"}", "false")
				}
			} else if atype == "int" {
				out = strings.ReplaceAll(out, "{"+name+"}", fmt.Sprintf("%d", args[key].(int)))
			} else if atype == "float" {
				out = strings.ReplaceAll(out, "{"+name+"}", fmt.Sprintf("%v", args[key].(float64)))
			} else {
				if args[key] != nil {
					out = strings.ReplaceAll(out, "{"+name+"}", fmt.Sprintf("%v", args[key]))
				} else {
					out = strings.ReplaceAll(out, "{"+name+"}", "None")
				}
			}
		}

		fmt.Println(out)
		return strictcli.Exit(ec)
	}
}

// makePassthroughHandler builds a passthrough command handler.
func makePassthroughHandler(cmdDef map[string]interface{}, globalFlags []map[string]interface{}) strictcli.PassthroughHandler {
	exitCode := 0
	if v, ok := cmdDef["handler_exit_code"]; ok {
		exitCode = int(v.(float64))
	}
	ec := exitCode

	// handler_aborts: the passthrough handler unwinds instead of printing and
	// returning, exactly as the normal-command form does.
	if v, ok := cmdDef["handler_aborts"]; ok && v.(bool) {
		return func(ctx *strictcli.Context, name string, args []string, globals map[string]interface{}) int {
			panic(handlerAbortMessage)
		}
	}

	return func(ctx *strictcli.Context, name string, args []string, globals map[string]interface{}) int {
		// Print global flag values.
		for _, gf := range globalFlags {
			gfName := gf["name"].(string)
			gfKey := strings.ReplaceAll(gfName, "-", "_")
			gfType := "str"
			if t, ok := gf["type"]; ok {
				gfType = t.(string)
			}

			switch gfType {
			case "bool":
				if globals[gfKey] == nil {
					fmt.Printf("%s=None\n", gfName)
				} else if globals[gfKey].(bool) {
					fmt.Printf("%s=true\n", gfName)
				} else {
					fmt.Printf("%s=false\n", gfName)
				}
			case "int":
				fmt.Printf("%s=%d\n", gfName, globals[gfKey].(int))
			default:
				fmt.Printf("%s=%v\n", gfName, globals[gfKey])
			}
		}

		// Print using passthrough_handler_prints template, or default format.
		if pt, ok := cmdDef["passthrough_handler_prints"]; ok {
			out := pt.(string)
			out = strings.ReplaceAll(out, "{name}", name)
			out = strings.ReplaceAll(out, "{args}", strings.Join(args, ","))
			fmt.Println(out)
		} else {
			fmt.Printf("%s:%s\n", name, strings.Join(args, ","))
		}

		return ec
	}
}

// registerCommand registers a single command (normal, passthrough, or deprecated) on a target.
func registerCommand(cmdDef map[string]interface{}, t target, globalFlags []map[string]interface{}, app *strictcli.App) {
	name := cmdDef["name"].(string)
	help := cmdDef["help"].(string)

	// Deprecated command. Deprecated entries are classification-EXEMPT
	// (effects contract §1.1), so `effect` is forwarded ONLY when the case
	// declares it -- which is a case asserting errDeprecatedCommandEffect.
	if v, ok := cmdDef["deprecated"]; ok && v.(bool) {
		message := ""
		if m, ok := cmdDef["deprecated_message"]; ok {
			message = m.(string)
		}
		var depOpts []strictcli.CmdOption
		if e, ok := cmdDef["effect"]; ok {
			depOpts = append(depOpts, strictcli.WithEffect(e.(string)))
		}
		t.Deprecated(name, message, depOpts...)
		return
	}

	// Passthrough command.
	if v, ok := cmdDef["passthrough"]; ok && v.(bool) {
		handler := makePassthroughHandler(cmdDef, globalFlags)
		opts := []strictcli.CmdOption{strictcli.WithPassthrough(handler)}
		opts = append(opts, buildCmdOptions(cmdDef)...)
		t.Command(name, help, nil, opts...)
		return
	}

	// Normal command.
	handler := makeHandler(cmdDef, globalFlags)
	_ = app
	opts := buildCmdOptions(cmdDef)
	t.Command(name, help, handler, opts...)
}

// buildGroup recursively registers a group and its contents on an App.
func buildGroup(groupDef map[string]interface{}, app *strictcli.App, globalFlags []map[string]interface{}) {
	name := groupDef["name"].(string)
	help := groupDef["help"].(string)
	var tags []string
	if t, ok := groupDef["tags"]; ok {
		for _, item := range t.([]interface{}) {
			tags = append(tags, item.(string))
		}
	}
	group := app.Group(name, help, tags...)
	if v, ok := groupDef["hidden"]; ok && v.(bool) {
		group.Hidden = true
	}
	populateGroup(groupDef, group, globalFlags, app)
}

// buildSubGroup recursively registers a sub-group and its contents on a parent Group.
func buildSubGroup(groupDef map[string]interface{}, parent *strictcli.Group, globalFlags []map[string]interface{}, app *strictcli.App) {
	name := groupDef["name"].(string)
	help := groupDef["help"].(string)
	var tags []string
	if t, ok := groupDef["tags"]; ok {
		for _, item := range t.([]interface{}) {
			tags = append(tags, item.(string))
		}
	}
	group := parent.Group(name, help, tags...)
	if v, ok := groupDef["hidden"]; ok && v.(bool) {
		group.Hidden = true
	}
	populateGroup(groupDef, group, globalFlags, app)
}

// populateGroup registers commands and sub-groups on a group.
func populateGroup(groupDef map[string]interface{}, group *strictcli.Group, globalFlags []map[string]interface{}, app *strictcli.App) {
	// Register commands.
	if cmds, ok := groupDef["commands"]; ok {
		for _, c := range cmds.([]interface{}) {
			registerCommand(c.(map[string]interface{}), groupTarget{group}, globalFlags, app)
		}
	}

	// Register sub-groups recursively.
	if groups, ok := groupDef["groups"]; ok {
		for _, g := range groups.([]interface{}) {
			buildSubGroup(g.(map[string]interface{}), group, globalFlags, app)
		}
	}
}
