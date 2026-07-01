package strictcli

import (
	"fmt"
	"testing"
)

func TestTagContractWithGlobalFlag(t *testing.T) {
	app := NewApp("myapp", "1.0.0", "test app")
	app.GlobalFlag(BoolFlag("json", "output json", Default(false)))
	app.TagContract("json", "json")
	app.Command("cmd", "a command", func(args map[string]interface{}) int {
		fmt.Print("ok")
		return 0
	}, WithTags("json"))
	r := app.Test([]string{"cmd"})
	// This SHOULD pass because the global flag --json satisfies the contract
	// But currently FAILS because checkCommandTagContract only looks at cmd.flags
	if r.ExitCode != 0 {
		t.Fatalf("EXPECTED exit 0 (global flag satisfies contract), got %d: stderr=%q", r.ExitCode, r.Stderr)
	}
}
