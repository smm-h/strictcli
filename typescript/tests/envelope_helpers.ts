/**
 * Test helpers for machine mode's envelope (contract §19.2).
 *
 * In machine mode stdout carries exactly one document, so a test that used to
 * pin a bare payload document reads the envelope through these helpers and
 * takes the member it means.
 */

/** The parsed envelope a machine-mode run wrote to stdout. */
export function envelope(stdout: string): Record<string, unknown> {
	return JSON.parse(stdout) as Record<string, unknown>;
}

/** The envelope's `payload` member, parsed. */
export function envelopePayload(stdout: string): unknown {
	return envelope(stdout).payload;
}

/**
 * The envelope's `payload` member re-serialized compactly, for tests that pin
 * the payload's bytes (key order survives parse and re-stringify).
 */
export function envelopePayloadText(stdout: string): string {
	return `${JSON.stringify(envelopePayload(stdout))}\n`;
}
