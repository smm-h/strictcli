package strictcli

import (
	"fmt"
	"path"
	"sort"
	"strings"
)

// CheckRunResult holds the outcome of running a single check. The verdict is
// derived from the minted CheckOutcome -- the runner's exit/cascade logic and
// the formatters all consume the same derived accessors (one source of truth).
type CheckRunResult struct {
	Name    string
	Outcome CheckOutcome
}

// Status returns the derived label ("pass", "fail", "warn", "skip") used for
// display and JSON output.
func (r CheckRunResult) Status() string {
	return deriveStatus(r.Outcome)
}

// Gated reports whether the outcome carries an error-severity problem (derived
// FAIL). Cascade (skipping dependents) and the FAIL exit key on this predicate.
func (r CheckRunResult) Gated() bool {
	return r.Status() == "fail"
}

// Warned reports whether the outcome carries only warn-severity problems
// (derived WARN). The --ignore-warnings predicate keys on this.
func (r CheckRunResult) Warned() bool {
	return r.Status() == "warn"
}

// resolveCheckOrder builds a DAG from depends_on, expands the selected set to include
// transitive dependencies (pull-in), detects cycles, and returns a topological order.
// Uses Kahn's algorithm.
func resolveCheckOrder(checkDefs map[string]*checkDef, selected map[string]bool) ([]string, error) {
	// Expand selected to include transitive dependencies
	expanded := make(map[string]bool)
	var expand func(name string) error
	visited := make(map[string]bool) // for cycle detection during expansion
	expand = func(name string) error {
		if expanded[name] {
			return nil
		}
		if visited[name] {
			// Build cycle path for error message
			return fmt.Errorf("check dependency cycle detected involving %q", name)
		}
		visited[name] = true
		def := checkDefs[name]
		for _, dep := range def.dependsOn {
			if err := expand(dep); err != nil {
				return err
			}
		}
		visited[name] = false
		expanded[name] = true
		return nil
	}

	// Expand all selected checks
	sortedSelected := sortedKeys(selected)
	for _, name := range sortedSelected {
		if err := expand(name); err != nil {
			return nil, err
		}
	}

	// Build the subgraph of only expanded nodes
	// Compute in-degrees and adjacency (within expanded set only)
	inDegree := make(map[string]int)
	dependents := make(map[string][]string) // dep -> list of checks that depend on it
	for name := range expanded {
		inDegree[name] = 0
	}
	for name := range expanded {
		def := checkDefs[name]
		for _, dep := range def.dependsOn {
			if expanded[dep] {
				inDegree[name]++
				dependents[dep] = append(dependents[dep], name)
			}
		}
	}

	// Kahn's algorithm with sorted queue for deterministic output
	var queue []string
	for name := range expanded {
		if inDegree[name] == 0 {
			queue = append(queue, name)
		}
	}
	sort.Strings(queue)

	var order []string
	for len(queue) > 0 {
		// Pop first (sorted order ensures determinism)
		node := queue[0]
		queue = queue[1:]
		order = append(order, node)

		// Sort dependents for deterministic ordering
		deps := dependents[node]
		sort.Strings(deps)
		for _, dep := range deps {
			inDegree[dep]--
			if inDegree[dep] == 0 {
				queue = append(queue, dep)
				// Re-sort queue to maintain sorted order
				sort.Strings(queue)
			}
		}
	}

	// If not all expanded nodes are in order, there's a cycle
	if len(order) != len(expanded) {
		// Find the cycle for a helpful error message
		cyclePath := findCycle(checkDefs, expanded, inDegree)
		if cyclePath != "" {
			return nil, fmt.Errorf("check dependency cycle: %s", cyclePath)
		}
		return nil, fmt.Errorf("check dependency cycle detected")
	}

	return order, nil
}

// findCycle finds and formats a cycle path among nodes with non-zero in-degree.
func findCycle(checkDefs map[string]*checkDef, expanded map[string]bool, inDegree map[string]int) string {
	// Find nodes still with non-zero in-degree (part of a cycle)
	remaining := make(map[string]bool)
	for name, deg := range inDegree {
		if deg > 0 {
			remaining[name] = true
		}
	}
	if len(remaining) == 0 {
		return ""
	}

	// Pick the lexicographically smallest starting node for determinism
	var start string
	for name := range remaining {
		if start == "" || name < start {
			start = name
		}
	}

	// Follow dependencies to trace the cycle
	visited := make(map[string]bool)
	var path []string
	current := start
	for {
		if visited[current] {
			// Found cycle start; trim path to the cycle
			for i, name := range path {
				if name == current {
					cycle := append(path[i:], current)
					return strings.Join(cycle, " -> ")
				}
			}
			break
		}
		visited[current] = true
		path = append(path, current)

		// Follow first dependency that's in remaining set
		def := checkDefs[current]
		var next string
		sortedDeps := make([]string, len(def.dependsOn))
		copy(sortedDeps, def.dependsOn)
		sort.Strings(sortedDeps)
		for _, dep := range sortedDeps {
			if remaining[dep] {
				next = dep
				break
			}
		}
		if next == "" {
			break
		}
		current = next
	}
	return ""
}

// runChecks executes checks in order, skipping dependents of failed checks.
// Returns results and an exit code (0 = all pass or all warn with ignoreWarnings, 1 otherwise).
func runChecks(checkDefs map[string]*checkDef, order []string, ctx CheckContext, ignoreWarnings bool) ([]CheckRunResult, int) {
	results := make([]CheckRunResult, 0, len(order))
	// Track checks whose dependents should be cascade-skipped. Cascade keys
	// ONLY on a derived FAIL (Gated: an error-severity problem present) or a
	// cascade-skip. A WARN outcome satisfies the dependency (dependents still
	// run) and only affects the exit code -- warn-severity checks physically
	// cannot cascade because WarnReporter lacks error-minting. An explicit
	// SKIP from an impl is NOT a failure -- dependents still run.
	failedChecks := make(map[string]bool)

	exitCode := 0
	for _, name := range order {
		def := checkDefs[name]

		// Check if any dependency failed -- skip if so
		skipReason := ""
		for _, dep := range def.dependsOn {
			if failedChecks[dep] {
				skipReason = fmt.Sprintf("skipped: dependency %q failed", dep)
				break
			}
		}

		if skipReason != "" {
			// Internally minted skip outcome (in-package construction is the
			// runner's own mint; user impls can only mint via reporters).
			o := CheckOutcome{minted: true, kind: "skipped", message: skipReason}
			results = append(results, CheckRunResult{Name: name, Outcome: o})
			failedChecks[name] = true
			exitCode = 1
			continue
		}

		// Run the check
		o := def.impl(ctx)
		// Belt-and-braces: an impl must return a reporter-minted outcome.
		if !o.minted {
			panic(fmt.Sprintf("check %q returned an outcome not minted by its reporter; use reporter methods (Passed/Skipped/Found)", name))
		}
		r := CheckRunResult{Name: name, Outcome: o}
		results = append(results, r)

		switch {
		case r.Gated():
			failedChecks[name] = true
			exitCode = 1
		case r.Warned():
			// Warn satisfies the dependency (no cascade), but still makes
			// the run exit non-zero unless warnings are ignored.
			if !ignoreWarnings {
				exitCode = 1
			}
			// pass / skip: not a failure, no cascade, no exit code change.
		}
	}

	return results, exitCode
}

// filterChecks selects checks based on tag expression, name glob, or runAll flag.
// If both tagExpr and nameGlob are provided, the result is their intersection.
func filterChecks(checkDefs map[string]*checkDef, tagExpr string, nameGlob string, runAll bool) (map[string]bool, error) {
	if runAll {
		result := make(map[string]bool, len(checkDefs))
		for name := range checkDefs {
			result[name] = true
		}
		return result, nil
	}

	var tagMatches map[string]bool
	if tagExpr != "" {
		tagMatches = make(map[string]bool)
		for name, def := range checkDefs {
			tagSet := make(map[string]bool, len(def.tags))
			for _, t := range def.tags {
				tagSet[t] = true
			}
			match, err := matchTagExpr(tagExpr, tagSet)
			if err != nil {
				return nil, err
			}
			if match {
				tagMatches[name] = true
			}
		}
	}

	var globMatches map[string]bool
	if nameGlob != "" {
		globMatches = make(map[string]bool)
		for name := range checkDefs {
			matched, err := path.Match(nameGlob, name)
			if err != nil {
				return nil, fmt.Errorf("invalid glob pattern %q: %s", nameGlob, err)
			}
			if matched {
				globMatches[name] = true
			}
		}
	}

	// Determine result based on which filters are active
	if tagMatches != nil && globMatches != nil {
		// Intersection
		result := make(map[string]bool)
		for name := range tagMatches {
			if globMatches[name] {
				result[name] = true
			}
		}
		return result, nil
	}
	if tagMatches != nil {
		return tagMatches, nil
	}
	if globMatches != nil {
		return globMatches, nil
	}

	// Neither filter provided
	return make(map[string]bool), nil
}

// sortedKeys returns the keys of a map[string]bool sorted alphabetically.
func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
