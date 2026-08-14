package strictcli

import (
	"strings"
	"testing"
)

// The corrections and spellings the three scoped-selector implementations
// forced (effects contract §18.19, items 213-224). Each test names the item it
// pins; the sentences and rendered forms are the contract's, not Go's.

// --- Item 215: a defaulted selector renders its COMPLETE elected value ---

func defaultedSelectorApp(t *testing.T) *App {
	t.Helper()
	webhook := Choice("webhook", "post the notification to a URL",
		StringFlag("url", "the endpoint", Default("https://example.test/hook")),
		IntFlag("retries", "how many times to retry", Default(5)),
	)
	email := Choice("email", "deliver the notification as an email message",
		StringFlag("subject", "subject line of the message", Required()),
	)
	return simpleApp("send", "send one notification", "ok",
		WithFlags(ChoiceFlag("via", "delivery channel", Default("webhook"), webhook, email)))
}

func TestDefaultedSelectorHelpRendersTheElectedChoicesFields(t *testing.T) {
	r := defaultedSelectorApp(t).Test([]string{"send", "--help"})
	if r.ExitCode != 0 {
		t.Fatalf("expected exit 0, got %d: %s", r.ExitCode, r.Stderr)
	}
	want := "[default: webhook (url=https://example.test/hook, retries=5)]"
	if !strings.Contains(r.Stdout, want) {
		t.Fatalf("help missing %q:\n%s", want, r.Stdout)
	}
}

func TestDefaultedSelectorHelpRendersTheBareChoiceForAnEmptyScope(t *testing.T) {
	all := Choice("all", "operate on everything")
	one := Choice("one", "operate on one thing",
		StringFlag("target", "which thing", Required()))
	app := simpleApp("run", "run it", "ok",
		WithFlags(ChoiceFlag("scope-of", "what to operate on", Default("all"), all, one)))
	r := app.Test([]string{"run", "--help"})
	if !strings.Contains(r.Stdout, "[default: all]") {
		t.Fatalf("help missing the bare-choice form:\n%s", r.Stdout)
	}
	if strings.Contains(r.Stdout, "[default: all (") {
		t.Fatalf("an empty scope rendered a parenthesized part:\n%s", r.Stdout)
	}
}

func TestDefaultedSelectorHelpDoesNotExpandANestedSelectorInline(t *testing.T) {
	inner := ChoiceFlag("format", "the output format", Default("json"),
		Choice("json", "machine-readable JSON"),
		Choice("text", "human-readable text"),
	)
	full := Choice("full", "the full report",
		inner,
		BoolFlag("colour", "colourize the report", Default(false)),
	)
	brief := Choice("brief", "the short report",
		StringFlag("title", "the report title", Required()))
	app := simpleApp("report", "report it", "ok",
		WithFlags(ChoiceFlag("depth", "how much to report", Default("full"), full, brief)))
	r := app.Test([]string{"report", "--help"})
	want := "[default: full (colour=false)]"
	if !strings.Contains(r.Stdout, want) {
		t.Fatalf("help missing %q:\n%s", want, r.Stdout)
	}
	// The nested selector states its own default on its own line.
	if !strings.Contains(r.Stdout, "[default: json]") {
		t.Fatalf("the nested selector's own line lost its default:\n%s", r.Stdout)
	}
}

// --- Item 218: the content-keyed block rule reaches positional args ---

func TestArgChoicesRenderAsABlockOnceAnEntryCarriesHelp(t *testing.T) {
	app := simpleApp("push", "push it", "ok",
		WithArgs(NewArg("target", "what to push", ArgRequired(),
			ArgChoices(Ch("head", "push only the current HEAD branch"), Ch("tags", "")))))
	r := app.Test([]string{"push", "--help"})
	if strings.Contains(r.Stdout, "[choices:") {
		t.Fatalf("expected the block form, got the one-line meta:\n%s", r.Stdout)
	}
	if !strings.Contains(r.Stdout, "push only the current HEAD branch") {
		t.Fatalf("the entry help is missing from help:\n%s", r.Stdout)
	}
	var sawHead, sawTags bool
	for _, line := range strings.Split(r.Stdout, "\n") {
		if strings.HasPrefix(line, "    head ") {
			sawHead = true
		}
		if line == "    tags" {
			sawTags = true
		}
	}
	if !sawHead {
		t.Fatalf("the entry block is not indented two columns past the arg:\n%s", r.Stdout)
	}
	if !sawTags {
		t.Fatalf("an entry with no help must render the value alone:\n%s", r.Stdout)
	}
}

func TestArgChoicesKeepTheOneLineFormWithoutHelp(t *testing.T) {
	app := simpleApp("push", "push it", "ok",
		WithArgs(NewArg("target", "what to push", ArgRequired(),
			ArgChoices(Ch("head", ""), Ch("tags", "")))))
	r := app.Test([]string{"push", "--help"})
	if !strings.Contains(r.Stdout, "[choices: head, tags]") {
		t.Fatalf("an arg with no entry help must keep the one-line form:\n%s", r.Stdout)
	}
}

// --- §24.10: a member-spelled selector's own line carries the clause on the
// RIGHT, after its help and before its presence part ---

func TestMemberSelectorLineCarriesTheClauseAfterItsHelp(t *testing.T) {
	r := electionApp().Test([]string{"run", "--help"})
	want := "which profiles to run over (exactly one of the following) [required]"
	if !strings.Contains(r.Stdout, want) {
		t.Fatalf("help missing %q:\n%s", want, r.Stdout)
	}
	for _, line := range strings.Split(r.Stdout, "\n") {
		if strings.HasPrefix(strings.TrimSpace(line), "(exactly one of the following)") {
			t.Fatalf("the clause is still in the left column: %q", line)
		}
	}
	if !strings.Contains(r.Stdout, "  mode ") {
		t.Fatalf("the selector's own name is missing from the left column:\n%s", r.Stdout)
	}
}
