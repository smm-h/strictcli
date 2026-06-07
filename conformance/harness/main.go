package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/smm-h/strictcli/go/strictcli"
)

// Suppress unused-import errors when templates have no substitutions.
var _ = strings.ReplaceAll
var _ = fmt.Println

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
	if v, ok := appDef["checks_toml"]; ok {
		appOpts = append(appOpts, strictcli.WithChecksEmbed([]byte(v.(string))))
	}

	app := strictcli.NewApp(
		appDef["name"].(string),
		appDef["version"].(string),
		appDef["help"].(string),
		appOpts...,
	)

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
			registerCommand(c.(map[string]interface{}), appTarget{app}, globalFlags)
		}
	}

	// Register checks.
	if _, ok := appDef["checks_toml"]; ok {
		if checks, ok := appDef["checks"]; ok {
			for _, c := range checks.([]interface{}) {
				cd := c.(map[string]interface{})
				cname := cd["name"].(string)
				cstatus := cd["check_returns"].(string)
				cmessage := cd["check_message"].(string)
				var cdetails []string
				if d, ok := cd["check_details"]; ok {
					for _, item := range d.([]interface{}) {
						cdetails = append(cdetails, item.(string))
					}
				}
				// Capture for closure.
				status, message, details := cstatus, cmessage, cdetails
				app.RegisterCheck(cname, func(ctx strictcli.CheckContext) strictcli.CheckResult {
					if details == nil {
						details = []string{}
					}
					return strictcli.CheckResult{Status: status, Message: message, Details: details}
				})
			}
		}

		app.SetCheckContext(func() strictcli.CheckContext {
			return &testCheckCtx{}
		})
	}

	app.Run()
}

type testCheckCtx struct{}

func (c *testCheckCtx) ProjectRoot() string { return "." }

// target abstracts over App and Group for command registration.
type target interface {
	Command(name, help string, handler func(map[string]interface{}) int, opts ...strictcli.CmdOption)
	Deprecated(name, message string)
}

type appTarget struct{ a *strictcli.App }

func (t appTarget) Command(name, help string, handler func(map[string]interface{}) int, opts ...strictcli.CmdOption) {
	t.a.Command(name, help, handler, opts...)
}
func (t appTarget) Deprecated(name, message string) { t.a.Deprecated(name, message) }

type groupTarget struct{ g *strictcli.Group }

func (t groupTarget) Command(name, help string, handler func(map[string]interface{}) int, opts ...strictcli.CmdOption) {
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
	default:
		return strictcli.StringFlag(name, help, opts...)
	}
}

// buildArg constructs a strictcli.Arg from a JSON arg definition.
func buildArg(ad map[string]interface{}) strictcli.Arg {
	name := ad["name"].(string)
	help := ad["help"].(string)

	var opts []strictcli.ArgOption

	if v, ok := ad["required"]; ok {
		opts = append(opts, strictcli.ArgRequired(v.(bool)))
	}
	if v, ok := ad["default"]; ok {
		if v == nil {
			opts = append(opts, strictcli.ArgDefault(nil))
		} else {
			opts = append(opts, strictcli.ArgDefault(v.(string)))
		}
	}
	if v, ok := ad["variadic"]; ok && v.(bool) {
		opts = append(opts, strictcli.Variadic())
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

	// Tags.
	if tags, ok := cmdDef["tags"]; ok {
		for _, t := range tags.([]interface{}) {
			td := t.(map[string]interface{})
			tagName := td["name"].(string)
			var tagFlags []strictcli.Flag
			for _, f := range td["flags"].([]interface{}) {
				tagFlags = append(tagFlags, buildFlag(f.(map[string]interface{})))
			}
			opts = append(opts, strictcli.WithTags(strictcli.Tag{Name: tagName, Flags: tagFlags}))
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

	return opts
}

// collectAllFlagDefs gathers all flag definitions for a command (global + direct + tags + mutex).
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

	// Tag flags.
	if tags, ok := cmdDef["tags"]; ok {
		for _, t := range tags.([]interface{}) {
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
func makeHandler(cmdDef map[string]interface{}, globalFlags []map[string]interface{}) func(map[string]interface{}) int {
	handlerPrints := cmdDef["handler_prints"].(string)
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
	template := handlerPrints
	ec := exitCode

	return func(args map[string]interface{}) int {
		out := template

		// Substitute flags.
		for _, fd := range allFlags {
			name := fd["name"].(string)
			key := strings.ReplaceAll(name, "-", "_")
			ftype := "str"
			if t, ok := fd["type"]; ok {
				ftype = t.(string)
			}

			if rep, ok := fd["repeatable"]; ok && rep.(bool) {
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
				if args[key].(bool) {
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

			if v, ok := ad["variadic"]; ok && v.(bool) {
				raw := args[key]
				var parts []string
				if raw != nil {
					for _, v := range raw.([]interface{}) {
						parts = append(parts, fmt.Sprintf("%v", v))
					}
				}
				out = strings.ReplaceAll(out, "{"+name+"}", strings.Join(parts, ","))
			} else {
				if args[key] != nil {
					out = strings.ReplaceAll(out, "{"+name+"}", fmt.Sprintf("%v", args[key]))
				} else {
					out = strings.ReplaceAll(out, "{"+name+"}", "None")
				}
			}
		}

		fmt.Println(out)
		return ec
	}
}

// makePassthroughHandler builds a passthrough command handler.
func makePassthroughHandler(cmdDef map[string]interface{}, globalFlags []map[string]interface{}) strictcli.PassthroughHandler {
	exitCode := 0
	if v, ok := cmdDef["handler_exit_code"]; ok {
		exitCode = int(v.(float64))
	}
	ec := exitCode

	return func(name string, args []string, globals map[string]interface{}) int {
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
				if globals[gfKey].(bool) {
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
func registerCommand(cmdDef map[string]interface{}, t target, globalFlags []map[string]interface{}) {
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
	opts := buildCmdOptions(cmdDef)
	t.Command(name, help, handler, opts...)
}

// buildGroup recursively registers a group and its contents on an App.
func buildGroup(groupDef map[string]interface{}, app *strictcli.App, globalFlags []map[string]interface{}) {
	name := groupDef["name"].(string)
	help := groupDef["help"].(string)
	group := app.Group(name, help)
	populateGroup(groupDef, group, globalFlags)
}

// buildSubGroup recursively registers a sub-group and its contents on a parent Group.
func buildSubGroup(groupDef map[string]interface{}, parent *strictcli.Group, globalFlags []map[string]interface{}) {
	name := groupDef["name"].(string)
	help := groupDef["help"].(string)
	group := parent.Group(name, help)
	populateGroup(groupDef, group, globalFlags)
}

// populateGroup registers commands and sub-groups on a group.
func populateGroup(groupDef map[string]interface{}, group *strictcli.Group, globalFlags []map[string]interface{}) {
	// Register commands.
	if cmds, ok := groupDef["commands"]; ok {
		for _, c := range cmds.([]interface{}) {
			registerCommand(c.(map[string]interface{}), groupTarget{group}, globalFlags)
		}
	}

	// Register sub-groups recursively.
	if groups, ok := groupDef["groups"]; ok {
		for _, g := range groups.([]interface{}) {
			buildSubGroup(g.(map[string]interface{}), group, globalFlags)
		}
	}
}
