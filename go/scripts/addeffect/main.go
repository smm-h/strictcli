// Command addeffect is a mechanical sweep that adds the mandatory effect
// classification to command registrations that lack it.
//
// The effects regime makes WithEffect(EffectReadOnly) / WithEffect(EffectMutating)
// mandatory on every command. This tool rewrites `.Command(...)` and
// `.Passthrough(...)` call sites that do not already declare one, appending the
// option immediately after the call's last argument:
//
//	app.Command("deploy", "deploy the app", handler, WithEffect(EffectReadOnly))
//
// It uses go/parser purely to locate byte offsets, then splices text in, so the
// rest of the file's formatting is preserved exactly. Re-running is a no-op
// (sites that already declare an effect are skipped).
//
// Usage:
//
//	go run ./scripts/addeffect [-effect read_only] [-qualifier strictcli.] FILE [FILE ...]
package main

import (
	"flag"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"sort"
)

func main() {
	effect := flag.String("effect", "read_only", `classification to insert ("read_only" or "mutating")`)
	qualifier := flag.String("qualifier", "", `package qualifier for the inserted identifiers (e.g. "strictcli.")`)
	flag.Parse()

	var constName string
	switch *effect {
	case "read_only":
		constName = "EffectReadOnly"
	case "mutating":
		constName = "EffectMutating"
	default:
		fmt.Fprintf(os.Stderr, "addeffect: -effect must be read_only or mutating, got %q\n", *effect)
		os.Exit(2)
	}
	insertion := fmt.Sprintf(", %sWithEffect(%s%s)", *qualifier, *qualifier, constName)

	total := 0
	for _, path := range flag.Args() {
		n, err := rewrite(path, insertion)
		if err != nil {
			fmt.Fprintf(os.Stderr, "addeffect: %s: %v\n", path, err)
			os.Exit(1)
		}
		if n > 0 {
			fmt.Printf("%s: %d registration(s)\n", path, n)
		}
		total += n
	}
	fmt.Printf("total: %d\n", total)
}

// rewrite splices the insertion into every unclassified registration in path
// and returns how many sites were touched.
func rewrite(path, insertion string) (int, error) {
	src, err := os.ReadFile(path)
	if err != nil {
		return 0, err
	}
	fset := token.NewFileSet()
	tree, err := parser.ParseFile(fset, path, src, parser.ParseComments)
	if err != nil {
		return 0, err
	}
	file := fset.File(tree.Pos())

	type splice struct {
		at   int
		text string
	}
	var splices []splice
	ast.Inspect(tree, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		sel, ok := call.Fun.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		if sel.Sel.Name != "Command" && sel.Sel.Name != "Passthrough" {
			return true
		}
		// Skip WithPassthrough(...) / anything that is not a registration.
		if len(call.Args) < 3 {
			return true
		}
		if declaresEffect(call.Args) {
			return true
		}
		last := call.Args[len(call.Args)-1]
		if call.Ellipsis != token.NoPos {
			// A spread call cannot take an extra argument, so the option goes
			// into the spread slice itself: f(a, b, append(opts, WithEffect(..))...)
			splices = append(splices,
				splice{at: file.Offset(last.Pos()), text: "append("},
				splice{at: file.Offset(last.End()), text: insertion + ")"})
			return true
		}
		splices = append(splices, splice{at: file.Offset(last.End()), text: insertion})
		return true
	})
	if len(splices) == 0 {
		return 0, nil
	}
	// Apply bottom-up so earlier offsets stay valid.
	sort.SliceStable(splices, func(i, j int) bool { return splices[i].at > splices[j].at })
	out := src
	for _, s := range splices {
		spliced := make([]byte, 0, len(out)+len(s.text))
		spliced = append(spliced, out[:s.at]...)
		spliced = append(spliced, s.text...)
		spliced = append(spliced, out[s.at:]...)
		out = spliced
	}
	return len(splices), os.WriteFile(path, out, 0o644)
}

// declaresEffect reports whether any argument is already a WithEffect(...) call.
func declaresEffect(args []ast.Expr) bool {
	for _, arg := range args {
		call, ok := arg.(*ast.CallExpr)
		if !ok {
			continue
		}
		switch fn := call.Fun.(type) {
		case *ast.Ident:
			if fn.Name == "WithEffect" {
				return true
			}
		case *ast.SelectorExpr:
			if fn.Sel.Name == "WithEffect" {
				return true
			}
		}
	}
	return false
}
