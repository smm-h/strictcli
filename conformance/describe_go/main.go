// Command describe_go emits a JSON description of the strictcli Go API surface
// by parsing the package source with go/ast + go/parser (not reflect, which
// cannot enumerate package-level functions or unexported struct fields).
//
// It is a dev-only tool for the conformance suite: check_describe_equivalence.py
// runs it and compares its extraction against the legacy regex extraction in
// check_api_surface.py. The dumper is authoritative and may legitimately find
// MORE than the regex (e.g. unexported fields, ConfigFieldOption constructors).
//
// Output is deterministic: files are processed in sorted order, and every list
// is sorted before emission. The top-level object carries a schema_version.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/printer"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const schemaVersion = 1

// sourceDir is the strictcli Go package relative to this program's directory.
// The equivalence check runs the compiled binary with cwd set here.
const sourceDir = "../../go/strictcli"

type field struct {
	Name     string `json:"name"`
	Type     string `json:"type"`
	Exported bool   `json:"exported"`
	Embedded bool   `json:"embedded"`
}

type structDecl struct {
	Name   string  `json:"name"`
	Fields []field `json:"fields"`
}

type typeParam struct {
	Name       string `json:"name"`
	Constraint string `json:"constraint"`
}

type funcDecl struct {
	Name             string      `json:"name"`
	Receiver         string      `json:"receiver,omitempty"`
	TypeParams       []typeParam `json:"type_params,omitempty"`
	Params           []string    `json:"params"`
	Results          []string    `json:"results"`
	ResultOptionType string      `json:"result_option_type,omitempty"`
}

type valueDecl struct {
	Name string `json:"name"`
	Type string `json:"type"`
}

type apiSurface struct {
	SchemaVersion      int          `json:"schema_version"`
	Package            string       `json:"package"`
	OptionTypes        []string     `json:"option_types"`
	Structs            []structDecl `json:"structs"`
	OptionConstructors []funcDecl   `json:"option_constructors"`
	Functions          []funcDecl   `json:"functions"`
	GenericFunctions   []funcDecl   `json:"generic_functions"`
	Methods            []funcDecl   `json:"methods"`
	Constants          []valueDecl  `json:"constants"`
	Variables          []valueDecl  `json:"variables"`
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "describe_go:", err)
		os.Exit(1)
	}
}

func run() error {
	fset := token.NewFileSet()

	entries, err := os.ReadDir(sourceDir)
	if err != nil {
		return fmt.Errorf("reading source dir %q: %w", sourceDir, err)
	}
	var goFiles []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		goFiles = append(goFiles, name)
	}
	sort.Strings(goFiles)

	var files []*ast.File
	pkgName := ""
	for _, name := range goFiles {
		f, err := parser.ParseFile(fset, filepath.Join(sourceDir, name), nil, parser.SkipObjectResolution)
		if err != nil {
			return fmt.Errorf("parsing %s: %w", name, err)
		}
		if pkgName == "" {
			pkgName = f.Name.Name
		}
		files = append(files, f)
	}

	// Pass 1: discover option types -- named types whose underlying type is a
	// function type `func(*T)`. These are the "Option family"; a package-level
	// function is an option constructor iff its single result is one of these.
	optionTypes := map[string]bool{}
	for _, f := range files {
		for _, decl := range f.Decls {
			gd, ok := decl.(*ast.GenDecl)
			if !ok || gd.Tok != token.TYPE {
				continue
			}
			for _, spec := range gd.Specs {
				ts, ok := spec.(*ast.TypeSpec)
				if !ok || !ts.Name.IsExported() {
					continue
				}
				ft, ok := ts.Type.(*ast.FuncType)
				if !ok {
					continue
				}
				if isPointerParamFunc(ft) {
					optionTypes[ts.Name.Name] = true
				}
			}
		}
	}

	api := apiSurface{
		SchemaVersion:      schemaVersion,
		Package:            pkgName,
		OptionTypes:        []string{},
		Structs:            []structDecl{},
		OptionConstructors: []funcDecl{},
		Functions:          []funcDecl{},
		GenericFunctions:   []funcDecl{},
		Methods:            []funcDecl{},
		Constants:          []valueDecl{},
		Variables:          []valueDecl{},
	}
	for name := range optionTypes {
		api.OptionTypes = append(api.OptionTypes, name)
	}
	sort.Strings(api.OptionTypes)

	// Pass 2: structs, functions, methods, values.
	for _, f := range files {
		for _, decl := range f.Decls {
			switch d := decl.(type) {
			case *ast.GenDecl:
				collectGenDecl(fset, d, &api)
			case *ast.FuncDecl:
				collectFunc(fset, d, optionTypes, &api)
			}
		}
	}

	sortSurface(&api)

	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", "  ")
	enc.SetEscapeHTML(false)
	return enc.Encode(&api)
}

// isPointerParamFunc reports whether ft has exactly one parameter that is a
// pointer type and no results, e.g. func(*App).
func isPointerParamFunc(ft *ast.FuncType) bool {
	if ft.Results != nil && len(ft.Results.List) > 0 {
		return false
	}
	if ft.Params == nil || len(ft.Params.List) != 1 {
		return false
	}
	_, ok := ft.Params.List[0].Type.(*ast.StarExpr)
	return ok
}

func collectGenDecl(fset *token.FileSet, gd *ast.GenDecl, api *apiSurface) {
	switch gd.Tok {
	case token.TYPE:
		for _, spec := range gd.Specs {
			ts, ok := spec.(*ast.TypeSpec)
			if !ok || !ts.Name.IsExported() {
				continue
			}
			st, ok := ts.Type.(*ast.StructType)
			if !ok {
				continue
			}
			sd := structDecl{Name: ts.Name.Name, Fields: []field{}}
			if st.Fields != nil {
				for _, fld := range st.Fields.List {
					typeStr := exprString(fset, fld.Type)
					if len(fld.Names) == 0 {
						// Embedded (anonymous) field: name is the type's identifier.
						name := embeddedName(fld.Type)
						sd.Fields = append(sd.Fields, field{
							Name:     name,
							Type:     typeStr,
							Exported: ast.IsExported(name),
							Embedded: true,
						})
						continue
					}
					for _, n := range fld.Names {
						sd.Fields = append(sd.Fields, field{
							Name:     n.Name,
							Type:     typeStr,
							Exported: n.IsExported(),
						})
					}
				}
			}
			api.Structs = append(api.Structs, sd)
		}
	case token.CONST, token.VAR:
		for _, spec := range gd.Specs {
			vs, ok := spec.(*ast.ValueSpec)
			if !ok {
				continue
			}
			typeStr := ""
			if vs.Type != nil {
				typeStr = exprString(fset, vs.Type)
			}
			for _, n := range vs.Names {
				if !n.IsExported() {
					continue
				}
				vd := valueDecl{Name: n.Name, Type: typeStr}
				if gd.Tok == token.CONST {
					api.Constants = append(api.Constants, vd)
				} else {
					api.Variables = append(api.Variables, vd)
				}
			}
		}
	}
}

func collectFunc(fset *token.FileSet, fd *ast.FuncDecl, optionTypes map[string]bool, api *apiSurface) {
	// Methods: receiver present. Recorded regardless of export so that the
	// full surface is visible; exported filter applies to the method name.
	if fd.Recv != nil && len(fd.Recv.List) > 0 {
		if !fd.Name.IsExported() {
			return
		}
		m := funcDecl{
			Name:     fd.Name.Name,
			Receiver: exprString(fset, fd.Recv.List[0].Type),
			Params:   fieldTypes(fset, fd.Type.Params),
			Results:  fieldTypes(fset, fd.Type.Results),
		}
		api.Methods = append(api.Methods, m)
		return
	}

	if !fd.Name.IsExported() {
		return
	}

	f := funcDecl{
		Name:    fd.Name.Name,
		Params:  fieldTypes(fset, fd.Type.Params),
		Results: fieldTypes(fset, fd.Type.Results),
	}

	// Generic functions: type parameters present.
	if fd.Type.TypeParams != nil && len(fd.Type.TypeParams.List) > 0 {
		for _, tp := range fd.Type.TypeParams.List {
			constraint := exprString(fset, tp.Type)
			for _, n := range tp.Names {
				f.TypeParams = append(f.TypeParams, typeParam{Name: n.Name, Constraint: constraint})
			}
		}
		api.GenericFunctions = append(api.GenericFunctions, f)
		return
	}

	// Option constructors: single result whose type is a named option type.
	if opt := singleResultOptionType(fset, fd.Type, optionTypes); opt != "" {
		f.ResultOptionType = opt
		api.OptionConstructors = append(api.OptionConstructors, f)
		return
	}

	api.Functions = append(api.Functions, f)
}

// singleResultOptionType returns the option type name if the function has
// exactly one result and that result is an identifier naming an option type.
func singleResultOptionType(fset *token.FileSet, ft *ast.FuncType, optionTypes map[string]bool) string {
	if ft.Results == nil || len(ft.Results.List) != 1 {
		return ""
	}
	res := ft.Results.List[0]
	if len(res.Names) > 1 {
		return ""
	}
	ident, ok := res.Type.(*ast.Ident)
	if !ok {
		return ""
	}
	if optionTypes[ident.Name] {
		return ident.Name
	}
	return ""
}

// fieldTypes renders each field's type, repeating for grouped names so that a
// signature like (a, b int) yields ["int", "int"].
func fieldTypes(fset *token.FileSet, fl *ast.FieldList) []string {
	out := []string{}
	if fl == nil {
		return out
	}
	for _, f := range fl.List {
		typeStr := exprString(fset, f.Type)
		n := len(f.Names)
		if n == 0 {
			n = 1
		}
		for i := 0; i < n; i++ {
			out = append(out, typeStr)
		}
	}
	return out
}

func embeddedName(expr ast.Expr) string {
	switch e := expr.(type) {
	case *ast.Ident:
		return e.Name
	case *ast.SelectorExpr:
		return e.Sel.Name
	case *ast.StarExpr:
		return embeddedName(e.X)
	default:
		return ""
	}
}

// exprString renders an AST type expression to its Go source form.
func exprString(fset *token.FileSet, expr ast.Expr) string {
	if expr == nil {
		return ""
	}
	var buf bytes.Buffer
	if err := printer.Fprint(&buf, fset, expr); err != nil {
		return fmt.Sprintf("<unprintable:%v>", err)
	}
	// Normalize internal whitespace/newlines for deterministic single-line types.
	s := buf.String()
	s = strings.ReplaceAll(s, "\n", " ")
	s = strings.ReplaceAll(s, "\t", " ")
	for strings.Contains(s, "  ") {
		s = strings.ReplaceAll(s, "  ", " ")
	}
	return strings.TrimSpace(s)
}

func sortSurface(api *apiSurface) {
	sort.Slice(api.Structs, func(i, j int) bool { return api.Structs[i].Name < api.Structs[j].Name })
	// Struct fields retain declaration order (deterministic); do not sort them.
	sortFuncs(api.OptionConstructors)
	sortFuncs(api.Functions)
	sortFuncs(api.GenericFunctions)
	sortFuncs(api.Methods)
	sort.Slice(api.Constants, func(i, j int) bool { return api.Constants[i].Name < api.Constants[j].Name })
	sort.Slice(api.Variables, func(i, j int) bool { return api.Variables[i].Name < api.Variables[j].Name })
}

func sortFuncs(fs []funcDecl) {
	sort.Slice(fs, func(i, j int) bool {
		if fs[i].Receiver != fs[j].Receiver {
			return fs[i].Receiver < fs[j].Receiver
		}
		return fs[i].Name < fs[j].Name
	})
}
