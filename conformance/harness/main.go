package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"

	tomledit "github.com/smm-h/go-toml-edit"
	"github.com/smm-h/strictcli/go/strictcli"
)

// Suppress unused-import errors when templates have no substitutions.
var _ = strings.ReplaceAll
var _ = fmt.Println
var _ = sort.Strings

func main() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", r)
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
	if hasToml || hasProviders {
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
	Deprecated(name, message string)
}

type appTarget struct{ a *strictcli.App }

func (t appTarget) Command(name, help string, handler func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome, opts ...strictcli.CmdOption) {
	t.a.Command(name, help, handler, opts...)
}
func (t appTarget) Deprecated(name, message string) { t.a.Deprecated(name, message) }

type groupTarget struct{ g *strictcli.Group }

func (t groupTarget) Command(name, help string, handler func(ctx *strictcli.Context, kwargs map[string]interface{}) strictcli.Outcome, opts ...strictcli.CmdOption) {
	t.g.Command(name, help, handler, opts...)
}
func (t groupTarget) Deprecated(name, message string) { t.g.Deprecated(name, message) }

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

	return opts
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

// makeHandler builds a normal command handler function from a command definition.
func makeHandler(cmdDef map[string]interface{}, globalFlags []map[string]interface{}) func(ctx *strictcli.Context, args map[string]interface{}) strictcli.Outcome {
	// handler_returns pins an explicit Outcome (survivor-contract cases): an
	// exit-only, data-only, exit+data, or None-equivalent return. When present,
	// the template-printing path is skipped entirely.
	if hrRaw, ok := cmdDef["handler_returns"]; ok {
		hr := hrRaw.(map[string]interface{})
		kind := hr["kind"].(string)
		code := 0
		if v, ok := hr["code"]; ok {
			code = int(v.(float64))
		}
		data := hr["data"]
		return func(ctx *strictcli.Context, args map[string]interface{}) strictcli.Outcome {
			switch kind {
			case "data":
				return strictcli.ExitData(0, data)
			case "exit_data":
				return strictcli.ExitData(code, data)
			default: // "exit" or "none" (Go has no None; None maps to Exit(0))
				return strictcli.Exit(code)
			}
		}
	}

	template := cmdDef["handler_prints"].(string)
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

	// Deprecated command.
	if v, ok := cmdDef["deprecated"]; ok && v.(bool) {
		message := ""
		if m, ok := cmdDef["deprecated_message"]; ok {
			message = m.(string)
		}
		t.Deprecated(name, message)
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
