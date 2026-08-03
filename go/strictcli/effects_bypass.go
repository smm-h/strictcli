package strictcli

// The effects-bypass lint (the `effects-bypass` check provider).
//
// Closed lists, matched on the called function/selector name: process starts,
// filesystem mutations, and network calls. The analyser is the stdlib go/ast +
// go/parser -- a regular dependency, no optional import and no soft
// degradation.

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// bypassProcess is the closed list of process-starting members. They are
// findings only when reached through a receiver (os/exec.Command, syscall.Exec),
// so an ordinary local Run() helper is not flagged by name alone.
var bypassProcess = map[string]bool{
	"Command": true, "CommandContext": true, "Start": true, "Output": true,
	"CombinedOutput": true, "StartProcess": true, "Exec": true,
	"ForkExec": true,
}

// bypassProcessReceivers are the receivers that make a bypassProcess member a
// finding.
var bypassProcessReceivers = map[string]bool{
	"exec": true, "syscall": true, "os": true, "cmd": true,
}

// bypassFilesystem is the closed list of filesystem-mutating members.
var bypassFilesystem = map[string]bool{
	"Create": true, "CreateTemp": true, "WriteFile": true, "Remove": true,
	"RemoveAll": true, "Mkdir": true, "MkdirAll": true, "MkdirTemp": true,
	"Rename": true, "Chmod": true, "Chown": true, "Truncate": true,
	"Symlink": true, "Link": true, "OpenFile": true,
}

// bypassNetwork is the closed list of network members, banned only when reached
// through one of the receivers below so an ordinary mapping.Get is not a
// finding.
var bypassNetwork = map[string]bool{
	"Get": true, "Post": true, "PostForm": true, "Head": true, "Do": true,
	"Dial": true, "DialTimeout": true, "NewRequest": true,
	"NewRequestWithContext": true,
}

var bypassNetworkReceivers = map[string]bool{
	"http": true, "net": true, "client": true, "Client": true,
	"DefaultClient": true, "transport": true, "ws": true,
}

// bypassSkipDirs are never walked.
var bypassSkipDirs = map[string]bool{
	".git": true, "vendor": true, "node_modules": true, "testdata": true,
	"dist": true, "build": true,
}

// bypassFinding is one direct effect call inside a function that opted into
// ctx.Effects().
type bypassFinding struct {
	file   string
	line   int
	fn     string
	target string
}

// effectsBypassProvider is the built-in check provider for the effects-bypass
// lint. It is registered whenever the check system turns on, so a consumer that
// adopts checks at all gets the lint without a TOML declaration. It fails on any
// direct process, filesystem-mutation or network call made from a function that
// opted into ctx.Effects().
func (a *App) effectsBypassProvider() []CheckSpec {
	impl := func(ctx CheckContext, reporter *ErrorReporter) CheckOutcome {
		findings := scanEffectsBypasses(ctx.ProjectRoot())
		for _, f := range findings {
			reporter.Error(fmt.Sprintf("%s:%d: %s calls %s directly; route it through ctx.Effects()",
				f.file, f.line, f.fn, f.target))
		}
		if len(findings) > 0 {
			return reporter.Found(fmt.Sprintf("%d direct effect call(s) bypassing ctx.Effects()", len(findings)))
		}
		return reporter.Passed("no direct effect calls bypass ctx.Effects()")
	}

	return []CheckSpec{
		NewErrorCheckSpec(CheckSpecMeta{
			Name:         "effects-bypass",
			Tags:         []string{"effects", "quality"},
			Severity:     "error",
			Fast:         true,
			Pure:         true,
			NeedsNetwork: false,
			DependsOn:    []string{},
		}, impl),
	}
}

// scanEffectsBypasses finds direct effect calls inside functions that opted
// into ctx.Effects(). Results are in file then line order.
func scanEffectsBypasses(root string) []bypassFinding {
	var findings []bypassFinding
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		return findings
	}
	var files []string
	_ = filepath.Walk(root, func(path string, fi os.FileInfo, err error) error {
		if err != nil {
			return nil
		}
		if fi.IsDir() {
			base := filepath.Base(path)
			if path != root && (bypassSkipDirs[base] || strings.HasPrefix(base, ".")) {
				return filepath.SkipDir
			}
			return nil
		}
		if strings.HasSuffix(path, ".go") {
			files = append(files, path)
		}
		return nil
	})
	sort.Strings(files)

	fset := token.NewFileSet()
	for _, path := range files {
		tree, err := parser.ParseFile(fset, path, nil, 0)
		if err != nil {
			// A file the analyser cannot read is not evidence of a bypass.
			continue
		}
		rel, relErr := filepath.Rel(root, path)
		if relErr != nil {
			rel = path
		}
		ast.Inspect(tree, func(n ast.Node) bool {
			name, body := functionNameAndBody(n)
			if body == nil {
				return true
			}
			if !functionOptsIntoEffects(body) {
				return true
			}
			ast.Inspect(body, func(inner ast.Node) bool {
				call, ok := inner.(*ast.CallExpr)
				if !ok {
					return true
				}
				if reachesEffectsHandle(call.Fun) {
					return true
				}
				target, receiver := callTargetName(call.Fun)
				if target == "" {
					return true
				}
				leaf := target
				if i := strings.LastIndex(target, "."); i >= 0 {
					leaf = target[i+1:]
				}
				banned := (bypassProcess[leaf] && bypassProcessReceivers[receiver]) ||
					(bypassFilesystem[leaf] && receiver != "") ||
					(bypassNetwork[leaf] && bypassNetworkReceivers[receiver])
				if banned {
					findings = append(findings, bypassFinding{
						file:   rel,
						line:   fset.Position(call.Pos()).Line,
						fn:     name,
						target: target,
					})
				}
				return true
			})
			return true
		})
	}
	return findings
}

// functionNameAndBody returns a function-like node's display name and body.
func functionNameAndBody(n ast.Node) (string, *ast.BlockStmt) {
	switch fn := n.(type) {
	case *ast.FuncDecl:
		return fn.Name.Name, fn.Body
	case *ast.FuncLit:
		return "func literal", fn.Body
	}
	return "", nil
}

// functionOptsIntoEffects reports whether a function body reaches for an
// Effects handle at all. Opting in is the trigger: a function that uses the
// effects handle must route ALL of its effects through it, or the preview it
// promises is a lie.
func functionOptsIntoEffects(body *ast.BlockStmt) bool {
	found := false
	ast.Inspect(body, func(n ast.Node) bool {
		if sel, ok := n.(*ast.SelectorExpr); ok && sel.Sel.Name == "Effects" {
			found = true
			return false
		}
		return true
	})
	return found
}

// reachesEffectsHandle reports whether a callee's receiver chain goes through
// .Effects().
func reachesEffectsHandle(expr ast.Expr) bool {
	for {
		switch e := expr.(type) {
		case *ast.SelectorExpr:
			if e.Sel.Name == "Effects" {
				return true
			}
			expr = e.X
		case *ast.CallExpr:
			expr = e.Fun
		default:
			return false
		}
	}
}

// callTargetName returns (dottedTarget, receiver) for a call's callee.
func callTargetName(expr ast.Expr) (string, string) {
	switch e := expr.(type) {
	case *ast.Ident:
		return e.Name, ""
	case *ast.SelectorExpr:
		parts := []string{e.Sel.Name}
		cur := e.X
		for {
			sel, ok := cur.(*ast.SelectorExpr)
			if !ok {
				break
			}
			parts = append(parts, sel.Sel.Name)
			cur = sel.X
		}
		if ident, ok := cur.(*ast.Ident); ok {
			parts = append(parts, ident.Name)
		}
		for i, j := 0, len(parts)-1; i < j; i, j = i+1, j-1 {
			parts[i], parts[j] = parts[j], parts[i]
		}
		receiver := ""
		if len(parts) >= 2 {
			receiver = parts[len(parts)-2]
		}
		return strings.Join(parts, "."), receiver
	}
	return "", ""
}
