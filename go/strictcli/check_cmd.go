package strictcli

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// enableChecks turns on the check system exactly once. It flips checksEnabled,
// initializes the check registry if absent, and registers the auto-generated
// "check" command a single time. Idempotent: calling it again is a no-op, which
// prevents double-registration (Command appends to cmdOrder on every call).
func (a *App) enableChecks() {
	if a.checksEnabled {
		return
	}
	a.checksEnabled = true
	if a.checkDefs == nil {
		a.checkDefs = make(map[string]*checkDef)
	}
	a.registerCheckCommand()
	// The built-in effects-bypass lint rides the same provider hook the built-in
	// cli-test-coverage check uses. Appended directly (not through
	// RegisterCheckProvider) because that method routes back here.
	a.checkProviders = append(a.checkProviders, a.effectsBypassProvider)
	a.providerMaterialized = false
	a.providerMaterializedCwd = ""
}

// registerCheckCommand registers the auto-generated "check" command.
// Called from enableChecks when the check system is turned on.
func (a *App) registerCheckCommand() {
	handler := func(ctx *Context, args map[string]interface{}) Outcome {
		// Materialize provider-sourced checks before any registry read (covers
		// the --list, --dry-run, and execution branches below).
		a.materializeCheckProviders()

		runAll := Get[bool](args, "all")
		tagExpr := Get[string](args, "tag")
		nameGlob := Get[string](args, "name")
		list := Get[bool](args, "list")
		jsonOut := Get[bool](args, "json")
		ignoreWarnings := Get[bool](args, "ignore_warnings")
		// --verbose and --dry-run are framework-owned reserved names, so the
		// check command's own two flags are gone and their values are read off
		// the Context instead.
		verbose := ctx.Verbose()
		dryRun := ctx.DryRun()

		if list {
			return Exit(a.checkList(jsonOut))
		}

		if dryRun {
			return Exit(a.checkDryRun(runAll, tagExpr, nameGlob))
		}

		if runAll || tagExpr != "" || nameGlob != "" {
			return Exit(a.checkRun(ctx, runAll, tagExpr, nameGlob, jsonOut, ignoreWarnings, verbose))
		}

		// No flags: show help
		cmd := a.commands["check"]
		fmt.Println(formatCommandHelp(a, cmd, ""))
		return Exit(0)
	}
	// Filter out candidate flags that already exist as global flags to avoid
	// collisions -- the handler absorbs global flag values automatically.
	// --verbose and --dry-run are absent from the candidate list entirely: both
	// names are now reserved by the framework and their values arrive on the
	// Context (§7.5).
	globalFlagNames := make(map[string]bool, len(a.globalFlags))
	for _, gf := range a.globalFlags {
		globalFlagNames[gf.Name] = true
	}
	candidates := []Flag{
		BoolFlag("all", "Run every registered check regardless of tag or name filters", Default(false)),
		StringFlag("tag", "Tag DSL expression to select checks (e.g. 'changelog & !quality')", Default("")),
		StringFlag("name", "Glob pattern to filter checks by name (e.g. 'hash-*', '*coverage*')", Default("")),
		BoolFlag("list", "List all registered checks with their tags and exit without running", Default(false)),
		BoolFlag("json", "Output check results as machine-readable JSON instead of human text", Default(false)),
		BoolFlag("ignore-warnings", "Treat warn-severity results as passing so they do not cause nonzero exit", Default(false)),
	}
	extraFlags := make([]Flag, 0, len(candidates))
	for _, f := range candidates {
		if !globalFlagNames[f.Name] {
			extraFlags = append(extraFlags, f)
		}
	}
	// read_only: the check command's only writes are framework-blessed
	// CACHE_WRITEs (the coverage manifest), which never trip enforcement.
	a.registerFrameworkCommand("check",
		"Run project checks registered via the check framework and report results",
		EffectReadOnly, handler, WithFlags(extraFlags...))
}

// registerFrameworkCommand registers one of strictcli's own auto-registered
// commands through the single validated registration path. Their handlers
// absorb the app's app-defined global flag values, which is legal only because
// they declare forwarding, and the private framework-internal marker makes the
// framework verify that the handler really is defined in this package.
func (a *App) registerFrameworkCommand(name, help, effect string, handler func(ctx *Context, args map[string]interface{}) Outcome, opts ...CmdOption) {
	all := append([]CmdOption{
		WithEffect(effect),
		WithForwarding(frameworkInternalForwardingReason),
		withFrameworkInternal(),
	}, opts...)
	a.Command(name, help, handler, all...)
}

// registerFrameworkSubcommand is registerFrameworkCommand for a command living
// inside a framework-owned group (the five `config` subcommands).
func registerFrameworkSubcommand(grp *Group, name, help, effect string, handler func(ctx *Context, args map[string]interface{}) Outcome, opts ...CmdOption) {
	all := append([]CmdOption{
		WithEffect(effect),
		WithForwarding(frameworkInternalForwardingReason),
		withFrameworkInternal(),
	}, opts...)
	grp.Command(name, help, handler, all...)
}

// wrapCheckContext augments a tool-supplied CheckContext with connection-env
// access derived from the framework *Context's infra snapshot. When the app
// declares no connection envs, the base context is returned unchanged so the
// common case is unaffected.
func (a *App) wrapCheckContext(base CheckContext, frameworkCtx *Context) CheckContext {
	if len(a.connectionEnvs) == 0 {
		return base
	}
	var infra *infraAccess
	if frameworkCtx != nil {
		infra = frameworkCtx.infra
	}
	return checkContextWithConn{CheckContext: base, infra: infra}
}

// checkList implements the --list mode.
func (a *App) checkList(jsonOut bool) int {
	if jsonOut {
		return a.checkListJSON()
	}
	return a.checkListHuman()
}

// checkListHuman prints an aligned table of checks.
func (a *App) checkListHuman() int {
	order := a.checkOrder

	// Compute column widths
	maxName := len("NAME")
	maxTags := len("TAGS")
	for _, name := range order {
		if len(name) > maxName {
			maxName = len(name)
		}
		def := a.checkDefs[name]
		tagsStr := strings.Join(def.tags, ", ")
		if len(tagsStr) > maxTags {
			maxTags = len(tagsStr)
		}
	}

	// Print header
	fmt.Printf("%-*s   %-*s   %s\n", maxName, "NAME", maxTags, "TAGS", "SEVERITY")
	for _, name := range order {
		def := a.checkDefs[name]
		tagsStr := strings.Join(def.tags, ", ")
		fmt.Printf("%-*s   %-*s   %s\n", maxName, name, maxTags, tagsStr, def.severity)
	}
	return 0
}

// checkListJSON prints checks as a JSON array.
func (a *App) checkListJSON() int {
	type checkEntry struct {
		Name     string   `json:"name"`
		Tags     []string `json:"tags"`
		Severity string   `json:"severity"`
		Scope    string   `json:"scope,omitempty"`
	}

	entries := make([]checkEntry, len(a.checkOrder))
	for i, name := range a.checkOrder {
		def := a.checkDefs[name]
		entries[i] = checkEntry{
			Name:     name,
			Tags:     def.tags,
			Severity: def.severity,
			Scope:    def.scope,
		}
	}

	data, err := json.Marshal(entries)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}
	fmt.Println(string(data))
	return 0
}

// checkDryRun shows which checks would run and in what order.
func (a *App) checkDryRun(runAll bool, tagExpr, nameGlob string) int {
	selected, err := filterChecks(a.checkDefs, tagExpr, nameGlob, runAll)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	order, err := resolveCheckOrder(a.checkDefs, selected)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	noun := "checks"
	if len(order) == 1 {
		noun = "check"
	}
	fmt.Printf("Would run %d %s:\n", len(order), noun)
	for i, name := range order {
		def := a.checkDefs[name]
		purity := "impure"
		if checkIsPure(def) {
			purity = "pure"
		}
		if len(def.dependsOn) > 0 {
			fmt.Printf("  %d. %s (depends on: %s) [%s]\n", i+1, name, strings.Join(def.dependsOn, ", "), purity)
		} else {
			fmt.Printf("  %d. %s [%s]\n", i+1, name, purity)
		}
	}
	return 0
}

// checkRun executes checks and formats output. The framework *Context (which
// carries the invocation's infra snapshot, including declared connection envs
// and the hermetic flag) is no longer discarded: the tool-supplied CheckContext
// is wrapped so check functions can read declared connection envs via the
// ConnectionEnvReader capability (hermetic-suppressed).
func (a *App) checkRun(frameworkCtx *Context, runAll bool, tagExpr, nameGlob string, jsonOut, ignoreWarnings, verbose bool) int {
	if a.checkContextFactory == nil {
		fmt.Fprintln(os.Stderr, "error: no check context factory set (call SetCheckContext before running checks)")
		return 1
	}

	ctx := a.wrapCheckContext(a.checkContextFactory(), frameworkCtx)
	// The check command executes all selected checks; the purity partition is an
	// API-only mode (RunChecksOptions.PureOnly) consumed programmatically, so no
	// checks are ever left in the impure listing here.
	results, _, exitCode, err := a.RunChecks(ctx, RunChecksOptions{
		TagExpr:        tagExpr,
		NameGlob:       nameGlob,
		RunAll:         runAll,
		IgnoreWarnings: ignoreWarnings,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %s\n", err)
		return 1
	}

	if len(results) == 0 {
		fmt.Println("No checks matched the given filters.")
		return 0
	}

	if jsonOut {
		fmt.Println(FormatCheckResultsJSON(results))
	} else {
		fmt.Println(FormatCheckResults(results, verbose))
	}

	return exitCode
}
