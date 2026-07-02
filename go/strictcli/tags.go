package strictcli

import (
	"fmt"
	"reflect"
	"strconv"
	"strings"
)

// tagInfo holds parsed struct tag values for a single field.
type tagInfo struct {
	// Exactly one of flagName or argName is set (never both).
	flagName string
	argName  string

	help         string
	short        string
	env          string
	prefixed     *bool   // nil = not set (default true)
	negatable    *bool   // nil = not set (default true for bool)
	choices      string  // raw comma-separated string
	choicesFrom  string  // method name on the handler type returning []string
	unique       *bool   // nil = not set
	envSeparator string
	variadic     *bool   // nil = not set
	required     *bool   // nil = not set; only "false" on variadic slice args is valid
	defaultVal   *string // nil = not set; pointer to distinguish "not present" from "empty string"
}

// knownTagKeys is the set of recognized struct tag keys on cli/arg fields.
var knownTagKeys = map[string]bool{
	"cli":           true,
	"arg":           true,
	"help":          true,
	"short":         true,
	"env":           true,
	"prefixed":      true,
	"negatable":     true,
	"choices":       true,
	"choices_from":  true,
	"unique":        true,
	"env_separator": true,
	"variadic":      true,
	"required":      true,
	"default":       true,
}

// parseStructTag extracts tagInfo from a reflect.StructField's tag.
// Returns nil if the field has no cli: or arg: tag (skip it).
// Panics on invalid tag combinations.
func parseStructTag(structName string, field reflect.StructField) *tagInfo {
	cliVal, hasCli := field.Tag.Lookup("cli")
	argVal, hasArg := field.Tag.Lookup("arg")

	if !hasCli && !hasArg {
		return nil
	}
	if hasCli && hasArg {
		panic(fmt.Sprintf("%s.%s: cannot have both cli and arg tags", structName, field.Name))
	}

	info := &tagInfo{}
	if hasCli {
		info.flagName = cliVal
	} else {
		info.argName = argVal
	}

	// help is mandatory
	helpVal, hasHelp := field.Tag.Lookup("help")
	if !hasHelp {
		panic(fmt.Sprintf("%s.%s: help tag is required", structName, field.Name))
	}
	info.help = helpVal

	// Parse optional tags
	if v, ok := field.Tag.Lookup("short"); ok {
		if len(v) != 1 {
			panic(fmt.Sprintf("%s.%s: short tag must be exactly one character, got %q", structName, field.Name, v))
		}
		info.short = v
	}
	if v, ok := field.Tag.Lookup("env"); ok {
		info.env = v
	}
	if v, ok := field.Tag.Lookup("prefixed"); ok {
		b := parseBoolTag(structName, field.Name, "prefixed", v)
		info.prefixed = &b
	}
	if v, ok := field.Tag.Lookup("negatable"); ok {
		b := parseBoolTag(structName, field.Name, "negatable", v)
		info.negatable = &b
	}
	if v, ok := field.Tag.Lookup("choices"); ok {
		info.choices = v
	}
	if v, ok := field.Tag.Lookup("choices_from"); ok {
		info.choicesFrom = v
	}
	if info.choices != "" && info.choicesFrom != "" {
		panic(fmt.Sprintf("%s.%s: cannot have both choices and choices_from tags", structName, field.Name))
	}
	if v, ok := field.Tag.Lookup("unique"); ok {
		b := parseBoolTag(structName, field.Name, "unique", v)
		info.unique = &b
	}
	if v, ok := field.Tag.Lookup("env_separator"); ok {
		info.envSeparator = v
	}
	if v, ok := field.Tag.Lookup("variadic"); ok {
		b := parseBoolTag(structName, field.Name, "variadic", v)
		info.variadic = &b
	}
	if v, ok := field.Tag.Lookup("required"); ok {
		b := parseBoolTag(structName, field.Name, "required", v)
		info.required = &b
	}
	if v, ok := field.Tag.Lookup("default"); ok {
		info.defaultVal = &v
	}

	// Reject unknown tag keys
	checkUnknownTagKeys(structName, field)

	return info
}

// parseBoolTag parses a string tag value as a boolean.
// Panics if the value is not "true" or "false".
func parseBoolTag(structName, fieldName, tagName, value string) bool {
	switch value {
	case "true":
		return true
	case "false":
		return false
	default:
		panic(fmt.Sprintf("%s.%s: %s tag must be \"true\" or \"false\", got %q",
			structName, fieldName, tagName, value))
	}
}

// checkUnknownTagKeys panics if a cli/arg field has any unknown struct tag keys.
// This uses raw tag string parsing since reflect only exposes Lookup for known keys.
func checkUnknownTagKeys(structName string, field reflect.StructField) {
	tag := string(field.Tag)
	keys := extractTagKeys(tag)
	for _, key := range keys {
		if !knownTagKeys[key] {
			panic(fmt.Sprintf("%s.%s: unknown tag key %q", structName, field.Name, key))
		}
	}
}

// extractTagKeys extracts all tag key names from a raw struct tag string.
// This parses the Go struct tag format: `key:"value" key2:"value2"`
func extractTagKeys(tag string) []string {
	var keys []string
	for tag != "" {
		// Skip whitespace
		i := 0
		for i < len(tag) && tag[i] == ' ' {
			i++
		}
		tag = tag[i:]
		if tag == "" {
			break
		}

		// Find the key: everything up to ':'
		i = 0
		for i < len(tag) && tag[i] != ' ' && tag[i] != ':' && tag[i] != '"' {
			i++
		}
		if i == 0 || i >= len(tag) || tag[i] != ':' {
			break
		}
		key := tag[:i]
		tag = tag[i+1:] // skip ':'

		// Must be followed by a quoted string
		if len(tag) == 0 || tag[0] != '"' {
			break
		}
		// Find end of quoted string (handle escaped quotes)
		i = 1
		for i < len(tag) {
			if tag[i] == '\\' {
				i += 2
				continue
			}
			if tag[i] == '"' {
				break
			}
			i++
		}
		if i >= len(tag) {
			break
		}
		keys = append(keys, key)
		tag = tag[i+1:] // skip closing '"'
	}
	return keys
}

// extractFlags extracts Flag and Arg declarations from a struct type using
// reflection and struct tags. The struct type must be a struct (not a pointer).
// A fresh zero instance serves as the receiver for choices_from method
// resolution. Panics on invalid configurations.
func extractFlags(structType reflect.Type) ([]Flag, []Arg) {
	if structType.Kind() == reflect.Ptr {
		structType = structType.Elem()
	}
	if structType.Kind() != reflect.Struct {
		panic(fmt.Sprintf("extractFlags: expected struct type, got %s", structType.Kind()))
	}
	return extractFlagsWithReceiver(structType, reflect.New(structType))
}

// extractFlagsWithReceiver is extractFlags with an explicit receiver instance.
// The receiver must be a pointer to structType (pointer receivers carry the
// full method set); choices_from methods are resolved and invoked on it, so a
// factory-built instance exposes injected dependencies to those methods.
func extractFlagsWithReceiver(structType reflect.Type, receiver reflect.Value) ([]Flag, []Arg) {
	visited := make(map[reflect.Type]bool)
	return extractFlagsRecursive(structType, receiver, visited)
}

// extractFlagsRecursive recurses into the struct type to extract flags and args.
// Tracks visited types to detect cycles in embedded structs. The receiver is
// always the root handler instance, not the embedded struct.
func extractFlagsRecursive(structType reflect.Type, receiver reflect.Value, visited map[reflect.Type]bool) ([]Flag, []Arg) {
	if visited[structType] {
		panic(fmt.Sprintf("extractFlags: cycle detected involving type %s", structType.Name()))
	}
	visited[structType] = true
	defer func() { visited[structType] = false }()

	structName := structType.Name()
	if structName == "" {
		structName = structType.String()
	}

	var flags []Flag
	var args []Arg

	for i := 0; i < structType.NumField(); i++ {
		field := structType.Field(i)

		// Handle embedded structs (FlagSets): recurse
		if field.Anonymous && field.Type.Kind() == reflect.Struct {
			embeddedFlags, embeddedArgs := extractFlagsRecursive(field.Type, receiver, visited)
			flags = append(flags, embeddedFlags...)
			args = append(args, embeddedArgs...)
			continue
		}

		info := parseStructTag(structName, field)
		if info == nil {
			continue
		}

		if info.flagName != "" {
			f := buildFlag(structName, field, info, receiver)
			flags = append(flags, f)
		} else {
			a := buildArg(structName, field, info, receiver)
			args = append(args, a)
		}
	}

	return flags, args
}

// buildFlag constructs a Flag from parsed tag info and field type.
// The receiver is the root handler instance, used to resolve choices_from.
func buildFlag(structName string, field reflect.StructField, info *tagInfo, receiver reflect.Value) Flag {
	fieldType := field.Type
	isPointer := fieldType.Kind() == reflect.Ptr

	flagType, isSlice, isMap := resolveFieldType(structName, field.Name, fieldType)

	if isPointer && (isSlice || isMap) {
		panic(fmt.Sprintf("%s.%s: pointer-to-slice and pointer-to-map field types are unsupported "+
			"(a missing repeatable flag always resolves to an empty list/map, never nil); "+
			"use a plain slice/map flag field, or a plain slice arg field with variadic:\"true\" required:\"false\"",
			structName, field.Name))
	}

	if info.required != nil {
		panic(fmt.Sprintf("%s.%s: required tag is only valid on variadic slice args; "+
			"flags express optionality via pointer types or the default tag",
			structName, field.Name))
	}

	var opts []FlagOption

	// Short
	if info.short != "" {
		opts = append(opts, Short(info.short))
	}

	// Env
	if info.env != "" {
		opts = append(opts, Env(info.env))
	}

	// Prefixed
	if info.prefixed != nil {
		opts = append(opts, Prefixed(*info.prefixed))
	}

	// Negatable
	if info.negatable != nil {
		opts = append(opts, NegatableOpt(*info.negatable))
	}

	// Choices (flags only, scalar types)
	if info.choices != "" {
		parts := strings.Split(info.choices, ",")
		choiceVals := parseChoiceValues(structName, field.Name, parts, flagType)
		opts = append(opts, Choices(choiceVals...))
	}

	// Choices resolved from a handler method
	if info.choicesFrom != "" {
		choiceVals := resolveChoicesFrom(structName, field, info, receiver, flagType)
		opts = append(opts, Choices(choiceVals...))
	}

	// EnvSeparator
	if info.envSeparator != "" {
		opts = append(opts, EnvSeparator(info.envSeparator))
	}

	// Handle default tag
	if info.defaultVal != nil {
		if isPointer {
			panic(fmt.Sprintf("%s.%s: default tag is invalid on pointer types (pointer already means optional-with-nil)",
				structName, field.Name))
		}
		defVal := parseDefaultValue(structName, field.Name, *info.defaultVal, flagType)
		opts = append(opts, Default(defVal))
	} else if isPointer {
		// Pointer type: optional with nil default
		opts = append(opts, Default(nil))
	}

	// Build the flag based on the kind (scalar, list, dict)
	if isMap {
		// Unique: required for dict, defaults to true if not specified
		if info.unique != nil {
			opts = append(opts, Unique(*info.unique))
		} else {
			opts = append(opts, Unique(true))
		}
		return DictFlag(flagType, info.flagName, info.help, opts...)
	}
	if isSlice {
		// Unique: required for list, defaults to true if not specified
		if info.unique != nil {
			opts = append(opts, Unique(*info.unique))
		} else {
			opts = append(opts, Unique(true))
		}
		return ListFlag(flagType, info.flagName, info.help, opts...)
	}

	// Scalar flag
	switch flagType {
	case TypeStr:
		return StringFlag(info.flagName, info.help, opts...)
	case TypeBool:
		return BoolFlag(info.flagName, info.help, opts...)
	case TypeInt:
		return IntFlag(info.flagName, info.help, opts...)
	case TypeFloat:
		return FloatFlag(info.flagName, info.help, opts...)
	default:
		panic(fmt.Sprintf("%s.%s: unsupported flag type %d", structName, field.Name, flagType))
	}
}

// buildArg constructs an Arg from parsed tag info and field type.
// The receiver is the root handler instance, used to resolve choices_from.
func buildArg(structName string, field reflect.StructField, info *tagInfo, receiver reflect.Value) Arg {
	fieldType := field.Type
	isPointer := fieldType.Kind() == reflect.Ptr

	flagType, isSlice, isMap := resolveFieldType(structName, field.Name, fieldType)

	if isMap {
		panic(fmt.Sprintf("%s.%s: map types are not supported for positional arguments",
			structName, field.Name))
	}

	if isPointer && isSlice {
		panic(fmt.Sprintf("%s.%s: pointer-to-slice and pointer-to-map field types are unsupported "+
			"(a missing optional variadic arg always resolves to an empty list, never nil); "+
			"use a plain slice field with variadic:\"true\" required:\"false\"",
			structName, field.Name))
	}

	var opts []ArgOption

	// Type
	if isSlice {
		opts = append(opts, ArgType(ListOf(flagType)))
	} else {
		opts = append(opts, ArgType(flagType))
	}

	// Variadic
	isVariadic := info.variadic != nil && *info.variadic
	if isVariadic {
		if !isSlice {
			panic(fmt.Sprintf("%s.%s: variadic requires a slice type",
				structName, field.Name))
		}
		opts = append(opts, Variadic())
	}

	// required tag: only required:"false" on a variadic slice arg is valid
	// (zero positionals then bind an empty slice). Everything else is redundant
	// or expressed elsewhere: args are required by default, and optional scalar
	// args use pointer types or the default tag.
	if info.required != nil {
		if !isVariadic {
			panic(fmt.Sprintf("%s.%s: required tag is only valid on variadic slice args; "+
				"optional scalar args use pointer types or the default tag",
				structName, field.Name))
		}
		if *info.required {
			panic(fmt.Sprintf("%s.%s: required:\"true\" is redundant (args are required by default; "+
				"pointer types and the default tag express optionality elsewhere) -- "+
				"only required:\"false\" on a variadic slice arg is meaningful",
				structName, field.Name))
		}
		opts = append(opts, ArgRequired(false))
	}

	// Choices (args)
	if info.choices != "" {
		parts := strings.Split(info.choices, ",")
		choiceVals := parseChoiceValues(structName, field.Name, parts, flagType)
		opts = append(opts, ArgChoices(choiceVals...))
	}

	// Choices resolved from a handler method
	if info.choicesFrom != "" {
		choiceVals := resolveChoicesFrom(structName, field, info, receiver, flagType)
		opts = append(opts, ArgChoices(choiceVals...))
	}

	// Handle default tag
	if info.defaultVal != nil {
		if isPointer {
			panic(fmt.Sprintf("%s.%s: default tag is invalid on pointer types (pointer already means optional-with-nil)",
				structName, field.Name))
		}
		defVal := parseDefaultValue(structName, field.Name, *info.defaultVal, flagType)
		opts = append(opts, ArgRequired(false), ArgDefault(defVal))
	} else if isPointer {
		// Pointer type: optional with nil default
		opts = append(opts, ArgRequired(false), ArgDefault(nil))
	}
	// Non-pointer without default: required (the default for NewArg)

	return NewArg(info.argName, info.help, opts...)
}

// resolveFieldType maps a Go reflect.Type to a strictcli FlagType.
// Returns the scalar element type and whether it's a slice or map.
// Panics for unsupported types.
func resolveFieldType(structName, fieldName string, fieldType reflect.Type) (FlagType, bool, bool) {
	// Unwrap pointer
	if fieldType.Kind() == reflect.Ptr {
		fieldType = fieldType.Elem()
	}

	switch fieldType.Kind() {
	case reflect.String:
		return TypeStr, false, false
	case reflect.Bool:
		return TypeBool, false, false
	case reflect.Int:
		return TypeInt, false, false
	case reflect.Float64:
		return TypeFloat, false, false
	case reflect.Slice:
		elemType := fieldType.Elem()
		switch elemType.Kind() {
		case reflect.String:
			return TypeStr, true, false
		case reflect.Int:
			return TypeInt, true, false
		case reflect.Float64:
			return TypeFloat, true, false
		default:
			panic(fmt.Sprintf("%s.%s: unsupported slice element type %s",
				structName, fieldName, elemType.Kind()))
		}
	case reflect.Map:
		if fieldType.Key().Kind() != reflect.String {
			panic(fmt.Sprintf("%s.%s: map key type must be string, got %s",
				structName, fieldName, fieldType.Key().Kind()))
		}
		valType := fieldType.Elem()
		switch valType.Kind() {
		case reflect.String:
			return TypeStr, false, true
		case reflect.Int:
			return TypeInt, false, true
		case reflect.Float64:
			return TypeFloat, false, true
		default:
			panic(fmt.Sprintf("%s.%s: unsupported map value type %s",
				structName, fieldName, valType.Kind()))
		}
	default:
		panic(fmt.Sprintf("%s.%s: unsupported field type %s",
			structName, fieldName, fieldType.Kind()))
	}
}

// parseDefaultValue parses a string default tag value to the appropriate Go type.
func parseDefaultValue(structName, fieldName, raw string, flagType FlagType) interface{} {
	switch flagType {
	case TypeStr:
		return raw
	case TypeBool:
		switch raw {
		case "true":
			return true
		case "false":
			return false
		default:
			panic(fmt.Sprintf("%s.%s: default tag for bool must be \"true\" or \"false\", got %q",
				structName, fieldName, raw))
		}
	case TypeInt:
		v, err := strconv.Atoi(raw)
		if err != nil {
			panic(fmt.Sprintf("%s.%s: default tag for int is invalid: %q",
				structName, fieldName, raw))
		}
		return v
	case TypeFloat:
		v, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			panic(fmt.Sprintf("%s.%s: default tag for float is invalid: %q",
				structName, fieldName, raw))
		}
		return v
	default:
		panic(fmt.Sprintf("%s.%s: default tag not supported for type %d",
			structName, fieldName, flagType))
	}
}

// bindValues populates a struct from a map of flag values. The target must be a
// pointer to a struct. The values map is keyed by flag name (dashes, matching cli:
// tag values). For each struct field with a cli: tag, the corresponding value is
// looked up and coerced to the field's Go type. Untagged fields are skipped.
// Embedded structs are recursed into.
//
// This function is shared by Globals[T] (Phase 5) and struct handler dispatch (Phase 6).
func bindValues(target interface{}, values map[string]interface{}) error {
	rv := reflect.ValueOf(target)
	if rv.Kind() != reflect.Ptr || rv.Elem().Kind() != reflect.Struct {
		return fmt.Errorf("bindValues: target must be a pointer to a struct, got %T", target)
	}
	return bindValuesRecursive(rv.Elem(), values)
}

// bindValuesRecursive recurses through struct fields setting values from the map.
func bindValuesRecursive(structVal reflect.Value, values map[string]interface{}) error {
	structType := structVal.Type()
	structName := structType.Name()
	if structName == "" {
		structName = structType.String()
	}

	for i := 0; i < structType.NumField(); i++ {
		field := structType.Field(i)
		fieldVal := structVal.Field(i)

		// Handle embedded structs: recurse
		if field.Anonymous && field.Type.Kind() == reflect.Struct {
			if err := bindValuesRecursive(fieldVal, values); err != nil {
				return err
			}
			continue
		}

		// Process fields with cli: or arg: tags
		cliVal, hasCli := field.Tag.Lookup("cli")
		argVal, hasArg := field.Tag.Lookup("arg")

		var key string
		if hasCli {
			key = cliVal
		} else if hasArg {
			key = argVal
		} else {
			continue
		}

		// Look up the value by flag name (dashes) or arg name
		mapVal, exists := values[key]
		if !exists {
			// Not in the map: leave zero value (or nil for pointer)
			continue
		}

		if err := setFieldValue(structName, field, fieldVal, mapVal); err != nil {
			return err
		}
	}
	return nil
}

// setFieldValue sets a struct field to the given value with type coercion.
func setFieldValue(structName string, field reflect.StructField, fieldVal reflect.Value, value interface{}) error {
	fieldType := field.Type

	// Handle nil value
	if value == nil {
		// For pointer types, set to nil (zero value); for non-pointer, leave zero value
		return nil
	}

	// Pointer types: wrap value in a pointer
	if fieldType.Kind() == reflect.Ptr {
		elemType := fieldType.Elem()
		coerced, err := coerceToGoType(structName, field.Name, value, elemType)
		if err != nil {
			return err
		}
		ptr := reflect.New(elemType)
		ptr.Elem().Set(reflect.ValueOf(coerced))
		fieldVal.Set(ptr)
		return nil
	}

	// Slice types: convert []interface{} to typed slice
	if fieldType.Kind() == reflect.Slice {
		return setSliceField(structName, field, fieldVal, value)
	}

	// Map types: convert map[string]interface{} to typed map
	if fieldType.Kind() == reflect.Map {
		return setMapField(structName, field, fieldVal, value)
	}

	// Scalar types: direct coercion
	coerced, err := coerceToGoType(structName, field.Name, value, fieldType)
	if err != nil {
		return err
	}
	fieldVal.Set(reflect.ValueOf(coerced))
	return nil
}

// coerceToGoType converts a value from the values map to the target Go type.
func coerceToGoType(structName, fieldName string, value interface{}, targetType reflect.Type) (interface{}, error) {
	switch targetType.Kind() {
	case reflect.String:
		if s, ok := value.(string); ok {
			return s, nil
		}
		return nil, fmt.Errorf("%s.%s: expected string, got %T", structName, fieldName, value)
	case reflect.Bool:
		if b, ok := value.(bool); ok {
			return b, nil
		}
		return nil, fmt.Errorf("%s.%s: expected bool, got %T", structName, fieldName, value)
	case reflect.Int:
		switch v := value.(type) {
		case int:
			return v, nil
		case float64:
			// JSON numbers are float64; accept if it's a whole number
			if v == float64(int(v)) {
				return int(v), nil
			}
			return nil, fmt.Errorf("%s.%s: expected int, got non-integer float64 %v", structName, fieldName, v)
		}
		return nil, fmt.Errorf("%s.%s: expected int, got %T", structName, fieldName, value)
	case reflect.Float64:
		switch v := value.(type) {
		case float64:
			return v, nil
		case int:
			return float64(v), nil
		}
		return nil, fmt.Errorf("%s.%s: expected float64, got %T", structName, fieldName, value)
	default:
		return nil, fmt.Errorf("%s.%s: unsupported target type %s", structName, fieldName, targetType.Kind())
	}
}

// setSliceField converts []interface{} to a typed Go slice and sets it on the field.
func setSliceField(structName string, field reflect.StructField, fieldVal reflect.Value, value interface{}) error {
	srcSlice, ok := value.([]interface{})
	if !ok {
		return fmt.Errorf("%s.%s: expected []interface{}, got %T", structName, field.Name, value)
	}

	elemType := field.Type.Elem()
	result := reflect.MakeSlice(field.Type, len(srcSlice), len(srcSlice))

	for i, item := range srcSlice {
		coerced, err := coerceToGoType(structName, field.Name, item, elemType)
		if err != nil {
			return fmt.Errorf("%s.%s[%d]: %w", structName, field.Name, i, err)
		}
		result.Index(i).Set(reflect.ValueOf(coerced))
	}

	fieldVal.Set(result)
	return nil
}

// setMapField converts map[string]interface{} to a typed Go map and sets it on the field.
func setMapField(structName string, field reflect.StructField, fieldVal reflect.Value, value interface{}) error {
	srcMap, ok := value.(map[string]interface{})
	if !ok {
		return fmt.Errorf("%s.%s: expected map[string]interface{}, got %T", structName, field.Name, value)
	}

	valType := field.Type.Elem()
	result := reflect.MakeMap(field.Type)

	for k, v := range srcMap {
		coerced, err := coerceToGoType(structName, field.Name, v, valType)
		if err != nil {
			return fmt.Errorf("%s.%s[%q]: %w", structName, field.Name, k, err)
		}
		result.SetMapIndex(reflect.ValueOf(k), reflect.ValueOf(coerced))
	}

	fieldVal.Set(result)
	return nil
}

// resolveChoicesFrom resolves a choices_from tag: it looks up the named method
// on the handler receiver, validates its signature (func() []string), invokes
// it once at registration time, and feeds the result through the same typed
// parsing as the choices tag. The resulting concrete choice list flows through
// help text, parse errors, schema dump, and MCP enums unchanged.
func resolveChoicesFrom(structName string, field reflect.StructField, info *tagInfo, receiver reflect.Value, flagType FlagType) []interface{} {
	m := receiver.MethodByName(info.choicesFrom)
	if !m.IsValid() {
		panic(fmt.Sprintf("%s.%s: choices_from method %q not found on %s (value or pointer receiver)",
			structName, field.Name, info.choicesFrom, receiver.Type().Elem()))
	}
	mt := m.Type()
	if mt.NumIn() != 0 || mt.NumOut() != 1 || mt.Out(0) != reflect.TypeOf([]string(nil)) {
		panic(fmt.Sprintf("%s.%s: choices_from method %q must have signature func() []string, got func%s",
			structName, field.Name, info.choicesFrom, strings.TrimPrefix(mt.String(), "func")))
	}
	result := m.Call(nil)[0].Interface().([]string)
	if len(result) == 0 {
		panic(fmt.Sprintf("%s.%s: choices_from method %q returned an empty list",
			structName, field.Name, info.choicesFrom))
	}
	return parseChoiceValues(structName, field.Name, result, flagType)
}

// parseChoiceValues parses string choice values into typed values matching the flag type.
func parseChoiceValues(structName, fieldName string, parts []string, flagType FlagType) []interface{} {
	vals := make([]interface{}, len(parts))
	for i, p := range parts {
		switch flagType {
		case TypeStr:
			vals[i] = p
		case TypeInt:
			v, err := strconv.Atoi(p)
			if err != nil {
				panic(fmt.Sprintf("%s.%s: choices value %q is not a valid int",
					structName, fieldName, p))
			}
			vals[i] = v
		case TypeFloat:
			v, err := strconv.ParseFloat(p, 64)
			if err != nil {
				panic(fmt.Sprintf("%s.%s: choices value %q is not a valid float",
					structName, fieldName, p))
			}
			vals[i] = v
		default:
			panic(fmt.Sprintf("%s.%s: choices not supported for type %d",
				structName, fieldName, flagType))
		}
	}
	return vals
}
