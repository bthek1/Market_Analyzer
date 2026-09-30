/**
 * Guards on the single repo-root .env contract (issue #4).
 *
 * The root .env holds SECRET_KEY, the DB password and ANTHROPIC_API_KEY next to
 * the frontend's VITE_* config. That is only safe because Vite exposes nothing
 * but VITE_-prefixed keys to the bundle - so the prefix behaviour is a security
 * boundary, not a convenience, and these tests pin it.
 */
import { copyFileSync, existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { readdirSync } from "node:fs";

import { loadEnv } from "vite";
import { describe, expect, it } from "vitest";

// happy-dom gives import.meta.url an http: scheme, so derive the root from the
// vitest working directory (always frontend/) instead.
const REPO_ROOT = resolve(process.cwd(), "..");
const ENV_EXAMPLE = `${REPO_ROOT}/.env.example`;
const VITE_CONFIG = `${REPO_ROOT}/frontend/vite.config.ts`;
const SRC_DIR = `${REPO_ROOT}/frontend/src`;

/** Every .ts/.tsx file under a directory, recursively. */
function collectSources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = `${dir}/${entry.name}`;
    if (entry.isDirectory()) return collectSources(full);
    return /\.tsx?$/.test(entry.name) ? [full] : [];
  });
}

// Asserted against the config SOURCE rather than the imported module: importing
// vite.config.ts here would either break on its import.meta.url or, via
// resolveConfig, run the router plugin's codegen as a side effect of a unit test.
const viteConfigSource = readFileSync(VITE_CONFIG, "utf8");

/**
 * loadEnv only ever reads `.env*`, never `.env.example`, and a developer's real
 * `.env` does not exist in CI - so stage the committed example as the `.env` of
 * a throwaway directory and load from there. That tests the contract rather
 * than whatever happens to be on this machine.
 */
function loadFromExample(prefix: string): Record<string, string> {
  const staged = mkdtempSync(join(tmpdir(), "env-contract-"));
  copyFileSync(ENV_EXAMPLE, join(staged, ".env"));
  return loadEnv("production", staged, prefix);
}

describe("vite env configuration", () => {
  it("reads env files from the repo root, not frontend/", () => {
    expect(viteConfigSource).toMatch(/envDir:\s*fileURLToPath\(new URL\("\.\.",/);
    expect(existsSync(`${REPO_ROOT}/.env.example`)).toBe(true);
  });

  it("leaves envPrefix at its default", () => {
    // An explicit envPrefix (especially "") would ship SECRET_KEY and
    // ANTHROPIC_API_KEY to every browser that loads the app.
    expect(viteConfigSource).not.toMatch(/^\s*envPrefix\s*:/m);
  });
});

describe("root .env.example", () => {
  it("supplies VITE_API_BASE_URL to the frontend", () => {
    const env = loadFromExample("VITE_");

    expect(env.VITE_API_BASE_URL).toBeTruthy();
  });

  it("does not expose backend secrets under the default prefix", () => {
    const exposed = loadFromExample("VITE_");
    const everything = loadFromExample("");

    // The example file must actually contain a secret, or this proves nothing.
    expect(everything.SECRET_KEY).toBeTruthy();
    expect(everything.ANTHROPIC_API_KEY).toBeTruthy();

    for (const key of Object.keys(exposed)) {
      expect(key.startsWith("VITE_")).toBe(true);
    }
    expect(exposed.SECRET_KEY).toBeUndefined();
    expect(exposed.ANTHROPIC_API_KEY).toBeUndefined();
  });

  it("declares every VITE_ key the app actually reads", () => {
    const declared = new Set(
      readFileSync(ENV_EXAMPLE, "utf8")
        .split("\n")
        .map((line) => line.trim().match(/^(VITE_[A-Z0-9_]*)=/)?.[1])
        .filter((key): key is string => Boolean(key)),
    );

    // An undeclared key is not a crash - it is the empty string at runtime,
    // which surfaces as requests to a relative URL long after the build.
    const read = new Set(
      [...collectSources(SRC_DIR)]
        .flatMap((file) => [
          ...readFileSync(file, "utf8").matchAll(/import\.meta\.env\.(VITE_[A-Z0-9_]*)/g),
        ])
        .map((match) => match[1]),
    );

    expect(read.size).toBeGreaterThan(0);
    expect([...read].filter((key) => !declared.has(key))).toEqual([]);
  });
});
