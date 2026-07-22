/**
 * TypeScript half of the cross-language float differential fuzz driven by
 * conformance/check_float_fuzz.py. NOT a test file (no .test.ts suffix, so
 * `npm test`'s node --test glob never runs it): it is a batch stdin->stdout
 * filter, compiled by tsconfig.test.json into dist-test/tests/ and executed
 * once per fuzz run as a plain Node program.
 *
 * Contract (mirrors go/strictcli/float_fuzz_filter_test.go): read hex uint64
 * IEEE-754 bit patterns, one per line, from stdin; write the SCF canonical
 * string for each double, one per line in the same order, to stdout. The
 * whole batch flows through ONE process -- no per-value spawning. Unlike the
 * Go side (where `go test` noise forces file output), plain Node stdout is
 * clean, so the canonical strings go straight to stdout.
 */

import { stdin, stdout } from "node:process";
import { formatFloatCanonical } from "../src/float.js";

let input = "";
stdin.setEncoding("utf8");
for await (const chunk of stdin) {
	input += chunk;
}

const view = new DataView(new ArrayBuffer(8));
const out: string[] = [];
for (const raw of input.split("\n")) {
	const line = raw.trim();
	if (line === "") {
		continue;
	}
	if (!/^[0-9a-fA-F]{1,16}$/.test(line)) {
		throw new Error(`bad hex bit pattern ${JSON.stringify(line)}`);
	}
	view.setBigUint64(0, BigInt(`0x${line}`));
	out.push(formatFloatCanonical(view.getFloat64(0)));
}
if (out.length > 0) {
	stdout.write(`${out.join("\n")}\n`);
}
