package strictcli

import (
	"fmt"
	"testing"
)

func TestTagContractSatisfiedByGlobalFlag(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("json", "output json", Default(false)))
	app.TagContract("json", "json")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("ok")
		return 0
	}, WithTags("json"))
	r := app.Test([]string{"cmd"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0 (global flag satisfies contract), got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
	if r.Stdout != "ok" {
		t.Fatalf("expected stdout %q, got %q", "ok", r.Stdout)
	}
}
