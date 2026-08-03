/**
 * Shared test helpers. Not a `.test.ts` file, so the runner does not pick it up.
 */

import { type App, type AppImpl, type AppSpec, createApp } from "../src/app.js";

/**
 * Strips strictcli's own built-in check providers from an app.
 *
 * Enabling the check system also registers the built-in `effects-bypass` lint.
 * Tests that assert on a specific check inventory (counts, --list output,
 * result ordering) drop it so they keep testing the runner rather than the
 * framework's own checks; dedicated tests cover the built-in itself.
 *
 * Mirrors Python's conftest drop_builtin_check_providers, which filters on the
 * provider function's __name__ for exactly the same reason.
 */
export function dropBuiltinCheckProviders<T extends App>(app: T): T {
	const impl = app as unknown as AppImpl;
	const kept = impl.checks.providers.filter(
		(p) => p.name !== "effectsBypassCheckProvider",
	);
	impl.checks.providers.length = 0;
	impl.checks.providers.push(...kept);
	impl.checks.providerMaterializedCwd = undefined;
	return app;
}

/**
 * An empty, dedicated project root. Checks that statically analyse the
 * consumer's sources (effects-bypass) walk this, so it must not be a shared
 * scratch directory.
 */
export const EMPTY_PROJECT_ROOT = new URL(
	"./_fixtures/empty_project/",
	import.meta.url,
).pathname;

/**
 * createApp for tests that assert on a specific check inventory: the built-in
 * effects-bypass lint is dropped both at construction (checksEmbed/checksPath
 * enable checks there) and after every registerCheckProvider call (a provider
 * registration is the other thing that enables checks).
 */
export function createTestApp(spec: AppSpec): App {
	const app = dropBuiltinCheckProviders(createApp(spec));
	const original = app.registerCheckProvider.bind(app);
	(
		app as { registerCheckProvider: App["registerCheckProvider"] }
	).registerCheckProvider = (provider): void => {
		original(provider);
		dropBuiltinCheckProviders(app);
	};
	return app;
}
