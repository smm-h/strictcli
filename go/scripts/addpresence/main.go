// Command addpresence is a mechanical sweep that adds the mandatory presence
// declaration to flag and arg declarations that lack it.
//
// The presence declaration (effects contract §23) makes exactly one of
// Required() / Optional() / Default(v) mandatory on every flag, and one of
// ArgRequired() / ArgOptional() / ArgDefault(v) mandatory on every positional
// arg. This tool rewrites StringFlag/BoolFlag/IntFlag/FloatFlag/ListFlag/
// DictFlag/NewArg call sites that declare none, appending the chosen option
// immediately after the call's last argument:
//
//	StringFlag("target", "where to deploy", Required())
//
// The inserted declaration depends on the shape of the call, because the
// behaviour the old derivation gave a site depends on it too:
//
//   - a compound declaration (ListFlag, DictFlag, or any call carrying
//     Repeatable()) got a silent empty collection, so it takes -compound
//     (default: Optional());
//   - every other flag was required by the absence of a default, so it takes
//     Required();
//   - an arg was required unless it declared ArgRequired(false), so it takes
//     ArgRequired().
//
// It uses go/parser purely to locate byte offsets, then splices text in, so the
// rest of the file's formatting is preserved exactly. Re-running is a no-op
// (sites that already declare a presence are skipped). Every site it touches
// still wants a human read: the mechanical choice preserves the OLD behaviour,
// which is not always the honest declaration.
//
// Usage:
//
//	go run ./scripts/addpresence [-compound optional] [-qualifier strictcli.] FILE [FILE ...]
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

var flagCtors = map[string]bool{
	"StringFlag": true,
	"BoolFlag":   true,
	"IntFlag":    true,
	"FloatFlag":  true,
	"ListFlag":   true,
	"DictFlag":   true,
}

var presenceOpts = map[string]bool{
	"Required":    true,
	"Optional":    true,
	"Default":     true,
	"ArgRequired": true,
	"ArgOptional": true,
	"ArgDefault":  true,
}

func main() {
	compound := flag.String("compound", "optional", `declaration for compound flags ("optional", "required", or "empty" for an explicit empty default)`)
	qualifier := flag.String("qualifier", "", `package qualifier for the inserted identifiers (e.g. "strictcli.")`)
	flag.Parse()

	var compoundList, compoundDict string
	switch *compound {
	case "optional":
		compoundList, compoundDict = "Optional()", "Optional()"
	case "required":
		compoundList, compoundDict = "Required()", "Required()"
	case "empty":
		compoundList = "Default([]interface{}{})"
		compoundDict = "Default(map[string]interface{}{})"
	default:
		fmt.Fprintf(os.Stderr, "addpresence: -compound must be optional, required or empty, got %q\n", *compound)
		os.Exit(2)
	}

	total := 0
	for _, path := range flag.Args() {
		n, err := rewrite(path, *qualifier, compoundList, compoundDict)
		if err != nil {
			fmt.Fprintf(os.Stderr, "addpresence: %s: %v\n", path, err)
			os.Exit(1)
		}
		if n > 0 {
			fmt.Printf("%s: %d declaration(s)\n", path, n)
		}
		total += n
	}
	fmt.Printf("total: %d\n", total)
}

// rewrite splices a presence declaration into every undeclared flag or arg
// declaration in path and returns how many sites were touched.
func rewrite(path, qualifier, compoundList, compoundDict string) (int, error) {
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
		name := calleeName(call.Fun)
		isArg := name == "NewArg"
		if !isArg && !flagCtors[name] {
			return true
		}
		if call.Ellipsis != token.NoPos {
			// A spread call forwards someone else's options; the declaration
			// belongs at their site, not here.
			return true
		}
		if declaresPresence(call.Args) {
			return true
		}
		var text string
		switch {
		case isArg:
			text = ", " + qualifier + "ArgRequired()"
		case name == "DictFlag":
			text = ", " + qualified(qualifier, compoundDict)
		case name == "ListFlag" || carriesRepeatable(call.Args):
			text = ", " + qualified(qualifier, compoundList)
		default:
			text = ", " + qualifier + "Required()"
		}
		last := call.Args[len(call.Args)-1]
		splices = append(splices, splice{at: file.Offset(last.End()), text: text})
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

// qualified prefixes the identifier part of a declaration with the qualifier.
func qualified(qualifier, decl string) string {
	return qualifier + decl
}

// calleeName returns the called function's own name, ignoring any package
// qualifier.
func calleeName(fun ast.Expr) string {
	switch fn := fun.(type) {
	case *ast.Ident:
		return fn.Name
	case *ast.SelectorExpr:
		return fn.Sel.Name
	}
	return ""
}

// declaresPresence reports whether any argument is one of the six presence
// options.
func declaresPresence(args []ast.Expr) bool {
	for _, arg := range args {
		call, ok := arg.(*ast.CallExpr)
		if !ok {
			continue
		}
		if presenceOpts[calleeName(call.Fun)] {
			return true
		}
	}
	return false
}

// carriesRepeatable reports whether the call declares Repeatable(), which is
// what made a scalar flag compound under the old derivation.
func carriesRepeatable(args []ast.Expr) bool {
	for _, arg := range args {
		call, ok := arg.(*ast.CallExpr)
		if !ok {
			continue
		}
		if calleeName(call.Fun) == "Repeatable" {
			return true
		}
	}
	return false
}
