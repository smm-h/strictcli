package strictcli

// Dev-only third-party cross-check for the payload-schema validator
// (effects contract §19.5).
//
// santhosh-tekuri/jsonschema v6 is a TEST dependency and never a runtime one:
// it exists to assert that the in-house validator's verdicts agree with an
// independent implementation on every shared vector. A disagreement is a test
// failure to investigate, never something the code resolves for itself.
//
// Two families are excluded by construction, because they are ours and not
// JSON Schema's: decision 16's magnitude guard, and JSON representability
// (which a JSON vector file cannot express in the first place).

import (
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// crossCheckable reports whether a vector's verdict is one JSON Schema itself
// decides.
func crossCheckable(v payloadVector) bool {
	if v.skipHere() {
		return false
	}
	if v.Valid {
		return true
	}
	return v.Detail != pdetailMagnitude && v.Detail != pdetailNotJSON
}

func compileVectorSchema(t *testing.T, schema interface{}) *jsonschema.Schema {
	t.Helper()
	c := jsonschema.NewCompiler()
	if err := c.AddResource("vector.json", schema); err != nil {
		t.Fatalf("add resource: %v", err)
	}
	sch, err := c.Compile("vector.json")
	if err != nil {
		t.Fatalf("compile: %v", err)
	}
	return sch
}

func TestPayloadValidatorAgreesWithThirdParty(t *testing.T) {
	doc := loadPayloadVectors(t)
	checked := 0
	for _, v := range doc.InstanceVectors {
		if !crossCheckable(v) {
			continue
		}
		checked++
		t.Run(v.Name, func(t *testing.T) {
			schemaTree := decodeVectorJSON(t, v.Schema)
			schema := decodeVectorSchema(t, v.Schema)
			value := decodeVectorJSON(t, v.Value)
			theirs := compileVectorSchema(t, schemaTree).Validate(value) == nil
			ours := validatePayloadValue(value, schema) == nil
			if ours != theirs {
				t.Fatalf("in-house says %v, santhosh-tekuri v6 says %v", ours, theirs)
			}
		})
	}
	if checked < 130 {
		t.Fatalf("cross-check covered only %d vectors", checked)
	}
}

func TestAcceptedSchemasCompileAsJSONSchema(t *testing.T) {
	// Anything the subset admits must be a legal JSON Schema document: the
	// subset is a restriction of JSON Schema, never a dialect of its own.
	doc := loadPayloadVectors(t)
	for _, v := range doc.SchemaVectors {
		if !v.Valid || v.skipHere() {
			continue
		}
		t.Run(v.Name, func(t *testing.T) {
			compileVectorSchema(t, decodeVectorJSON(t, v.Schema))
		})
	}
}
