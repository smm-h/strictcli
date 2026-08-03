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

// bypassFunc is one analysable function-like node, with the file it came from.
type bypassFunc struct {
	name    string
	body    *ast.BlockStmt
	rel     string
	pkgDir  string
	aliases map[string]bool
}

// scanEffectsBypasses finds direct effect calls REACHABLE FROM A REGISTERED
// COMMAND HANDLER. Results are in file then line order.
//
// §11's scope is reachability, not "a function whose own body mentions
// Effects()" -- a handler that never touches the handle, and a bypass one
// helper-call away, are both trivial escapes from the narrower reading, and this
// lint is the sole stated mitigation for the accepted no-sandbox ceiling.
//
// Roots are handler-shaped functions (first parameter *Context /
// *strictcli.Context, which is exactly the command-handler and
// passthrough-handler signature) plus, as before, any function that reaches for
// Effects() itself. From each root the closure follows DIRECT calls to
// package-level functions, transitively, WITHIN ONE PACKAGE (one directory) --
// the most go/ast can resolve without a type checker, and the boundary at which
// a bare name stops being unambiguous.
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
	// Pass 1: parse every file, index package-level funcs per directory, and
	// collect every function-like node with its roots-ness precomputed.
	var all []*bypassFunc
	roots := map[*bypassFunc]bool{}
	// pkgDir -> func name -> the package-level function
	pkgFuncs := map[string]map[string]*bypassFunc{}
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
		pkgDir := filepath.Dir(path)
		fileAliases := effectsHandleAliases(tree)
		for _, decl := range tree.Decls {
			fd, ok := decl.(*ast.FuncDecl)
			if !ok || fd.Body == nil || fd.Recv != nil {
				continue
			}
			if _, seen := pkgFuncs[pkgDir]; !seen {
				pkgFuncs[pkgDir] = map[string]*bypassFunc{}
			}
			if _, dup := pkgFuncs[pkgDir][fd.Name.Name]; !dup {
				pkgFuncs[pkgDir][fd.Name.Name] = nil // reserved; filled below
			}
		}
		ast.Inspect(tree, func(n ast.Node) bool {
			name, body := functionNameAndBody(n)
			if body == nil {
				return true
			}
			bf := &bypassFunc{
				name:    name,
				body:    body,
				rel:     rel,
				pkgDir:  pkgDir,
				aliases: fileAliases,
			}
			all = append(all, bf)
			if isHandlerShaped(n) || functionOptsIntoEffects(body) {
				roots[bf] = true
			}
			if fd, ok := n.(*ast.FuncDecl); ok && fd.Recv == nil {
				if m := pkgFuncs[pkgDir]; m != nil {
					if existing, seen := m[fd.Name.Name]; seen && existing == nil {
						m[fd.Name.Name] = bf
					}
				}
			}
			return true
		})
	}

	// Pass 2: transitive closure over direct calls to package-level functions.
	reachable := map[*bypassFunc]bool{}
	var queue []*bypassFunc
	for _, bf := range all {
		if roots[bf] {
			queue = append(queue, bf)
		}
	}
	for len(queue) > 0 {
		bf := queue[len(queue)-1]
		queue = queue[:len(queue)-1]
		if reachable[bf] {
			continue
		}
		reachable[bf] = true
		for _, callee := range directCallNames(bf.body) {
			if target := pkgFuncs[bf.pkgDir][callee]; target != nil && !reachable[target] {
				queue = append(queue, target)
			}
		}
	}
	if len(reachable) == 0 {
		return findings
	}

	// Pass 3: report banned calls, once per call site, at the innermost
	// reachable enclosing function. Nesting means a call can sit inside several
	// analysable bodies; the innermost one names the finding.
	seen := map[token.Pos]bool{}
	for _, bf := range all {
		if !reachable[bf] {
			continue
		}
		ast.Inspect(bf.body, func(inner ast.Node) bool {
			if inner != ast.Node(bf.body) {
				if _, nested := functionNameAndBody(inner); nested != nil {
					// A nested function is its own bypassFunc; it reports its
					// own calls (and inherits reachability through `all`).
					if isNestedAnalysable(inner, all, reachable) {
						return false
					}
				}
			}
			call, ok := inner.(*ast.CallExpr)
			if !ok {
				return true
			}
			if seen[call.Pos()] {
				return true
			}
			if reachesEffectsHandle(call.Fun, bf.aliases) {
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
				seen[call.Pos()] = true
				findings = append(findings, bypassFinding{
					file:   bf.rel,
					line:   fset.Position(call.Pos()).Line,
					fn:     bf.name,
					target: target,
				})
			}
			return true
		})
	}
	sort.SliceStable(findings, func(i, j int) bool {
		if findings[i].file != findings[j].file {
			return findings[i].file < findings[j].file
		}
		return findings[i].line < findings[j].line
	})
	return findings
}

// isNestedAnalysable reports whether a nested function node is itself one of the
// reachable bypassFuncs, so the enclosing walk can stop and let it report.
func isNestedAnalysable(n ast.Node, all []*bypassFunc, reachable map[*bypassFunc]bool) bool {
	_, body := functionNameAndBody(n)
	for _, bf := range all {
		if bf.body == body {
			return reachable[bf]
		}
	}
	return false
}

// isHandlerShaped reports whether a function's FIRST parameter is *Context (or
// *strictcli.Context) -- exactly the command-handler and passthrough-handler
// signatures, and nothing else in the surface.
func isHandlerShaped(n ast.Node) bool {
	var params *ast.FieldList
	switch fn := n.(type) {
	case *ast.FuncDecl:
		params = fn.Type.Params
	case *ast.FuncLit:
		params = fn.Type.Params
	default:
		return false
	}
	if params == nil || len(params.List) == 0 {
		return false
	}
	star, ok := params.List[0].Type.(*ast.StarExpr)
	if !ok {
		return false
	}
	switch t := star.X.(type) {
	case *ast.Ident:
		return t.Name == "Context"
	case *ast.SelectorExpr:
		return t.Sel.Name == "Context"
	}
	return false
}

// directCallNames returns the bare `name(...)` callees inside a body.
func directCallNames(body *ast.BlockStmt) []string {
	var names []string
	ast.Inspect(body, func(n ast.Node) bool {
		if call, ok := n.(*ast.CallExpr); ok {
			if ident, ok := call.Fun.(*ast.Ident); ok {
				names = append(names, ident.Name)
			}
		}
		return true
	})
	return names
}

// effectsHandleAliases returns the names bound to the effects handle anywhere in
// a file: locals assigned from ctx.Effects() (`e := ctx.Effects()`) and
// parameters declared *Effects (a helper that takes the handle). Both are
// ordinary ways to write handler code and must not read as bypasses. File scope,
// not function scope, so a closure that uses its enclosing function's handle is
// covered too.
func effectsHandleAliases(tree *ast.File) map[string]bool {
	aliases := map[string]bool{}
	record := func(lhs, rhs []ast.Expr) {
		for i, r := range rhs {
			if i >= len(lhs) || !reachesEffectsHandle(r, nil) {
				continue
			}
			if ident, ok := lhs[i].(*ast.Ident); ok {
				aliases[ident.Name] = true
			}
		}
	}
	ast.Inspect(tree, func(n ast.Node) bool {
		switch s := n.(type) {
		case *ast.AssignStmt:
			record(s.Lhs, s.Rhs)
		case *ast.ValueSpec:
			lhs := make([]ast.Expr, len(s.Names))
			for i, name := range s.Names {
				lhs[i] = name
			}
			record(lhs, s.Values)
		case *ast.Field:
			if star, ok := s.Type.(*ast.StarExpr); ok && isEffectsTypeName(star.X) {
				for _, name := range s.Names {
					aliases[name.Name] = true
				}
			}
		}
		return true
	})
	return aliases
}

// isEffectsTypeName reports whether a type expression names the Effects handle.
func isEffectsTypeName(expr ast.Expr) bool {
	switch t := expr.(type) {
	case *ast.Ident:
		return t.Name == "Effects"
	case *ast.SelectorExpr:
		return t.Sel.Name == "Effects"
	}
	return false
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
// Effects handle at all. One of the two root conditions: a function that uses
// the effects handle must route ALL of its effects through it, or the preview
// it promises is a lie.
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
// .Effects(). `aliases` are local names bound to the handle (`e :=
// ctx.Effects()`), which is an ordinary way to write a handler.
func reachesEffectsHandle(expr ast.Expr, aliases map[string]bool) bool {
	for {
		switch e := expr.(type) {
		case *ast.SelectorExpr:
			if e.Sel.Name == "Effects" {
				return true
			}
			expr = e.X
		case *ast.CallExpr:
			expr = e.Fun
		case *ast.Ident:
			return aliases[e.Name]
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
