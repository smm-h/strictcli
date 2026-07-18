package strictcli

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// recordCoverage appends a coverage record for the resolved command path.
// Each Test() or Call() invocation writes one JSONL line to a per-process
// shard file. The shard counter increments per-write for uniqueness.
func (a *App) recordCoverage(cmdPath string) {
	if !a.testCoverage || a.coverageShardFmt == "" {
		return
	}
	path := fmt.Sprintf(a.coverageShardFmt, a.coverageCounter)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	data, _ := json.Marshal(map[string]string{"command": cmdPath})
	f.Write(data)
	f.Write([]byte("\n"))
}

// collectAllCommandPaths enumerates all non-deprecated leaf command paths
// as dot-separated strings (e.g. "deploy", "infra.deploy").
func (a *App) collectAllCommandPaths() map[string]bool {
	paths := make(map[string]bool)
	for name := range a.commands {
		paths[name] = true
	}
	var walkGroup func(grp *Group, prefix []string)
	walkGroup = func(grp *Group, prefix []string) {
		for cmdName := range grp.Commands {
			paths[strings.Join(append(prefix, cmdName), ".")] = true
		}
		for subName, subGrp := range grp.Groups {
			walkGroup(subGrp, append(prefix, subName))
		}
	}
	for groupName, grp := range a.groups {
		walkGroup(grp, []string{groupName})
	}
	return paths
}

// testCoverageProvider is the built-in check provider for cli-test-coverage.
// Auto-registered when WithTestCoverage() is used.
func (a *App) testCoverageProvider() []CheckSpec {
	impl := func(ctx CheckContext, reporter *ErrorReporter) CheckOutcome {
		coverageDir := ".strictcli/coverage"
		manifestPath := ".strictcli/test-coverage.json"

		// Merge shards
		covered := make(map[string]bool)
		entries, err := os.ReadDir(coverageDir)
		if err == nil {
			for _, entry := range entries {
				if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".jsonl") {
					continue
				}
				fpath := filepath.Join(coverageDir, entry.Name())
				f, err := os.Open(fpath)
				if err != nil {
					continue
				}
				scanner := bufio.NewScanner(f)
				for scanner.Scan() {
					line := strings.TrimSpace(scanner.Text())
					if line == "" {
						continue
					}
					var record map[string]string
					if err := json.Unmarshal([]byte(line), &record); err != nil {
						continue
					}
					if cmd, ok := record["command"]; ok {
						covered[cmd] = true
					}
				}
				f.Close()
			}
		}

		if len(covered) == 0 {
			reporter.Error("stale or empty manifest")
			return reporter.Found("no coverage data: .strictcli/coverage/ contains no shard files")
		}

		// Write canonical manifest
		manifest := make([]string, 0, len(covered))
		for cmd := range covered {
			manifest = append(manifest, cmd)
		}
		sort.Strings(manifest)
		data, _ := json.MarshalIndent(manifest, "", "  ")
		os.WriteFile(manifestPath, append(data, '\n'), 0o644)

		// Compare against command surface (exclude the framework-injected
		// check command -- it is not a user command)
		allCommands := a.collectAllCommandPaths()
		delete(allCommands, "check")
		var uncovered []string
		for cmd := range allCommands {
			if !covered[cmd] {
				uncovered = append(uncovered, cmd)
			}
		}
		sort.Strings(uncovered)

		if len(uncovered) > 0 {
			for _, cmd := range uncovered {
				reporter.Error(fmt.Sprintf("no test coverage for command: %s", cmd))
			}
			return reporter.Found(fmt.Sprintf("%d command(s) with zero test coverage", len(uncovered)))
		}
		return reporter.Passed(fmt.Sprintf("all %d commands have test coverage", len(allCommands)))
	}

	return []CheckSpec{
		NewErrorCheckSpec(CheckSpecMeta{
			Name:         "cli-test-coverage",
			Tags:         []string{"test"},
			Severity:     "error",
			Fast:         true,
			Pure:         true,
			NeedsNetwork: false,
			DependsOn:    []string{},
		}, impl),
	}
}
