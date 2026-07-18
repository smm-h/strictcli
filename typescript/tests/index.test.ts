import { strict as assert } from "node:assert";
import { test } from "node:test";
import { VERSION } from "../src/index.js";

test("stub module imports and exposes the package version", () => {
	assert.equal(VERSION, "0.31.0");
});
