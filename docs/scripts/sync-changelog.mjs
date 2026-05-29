#!/usr/bin/env node
/**
 * Sync CHANGELOG.md to docs/en/release-notes/changelog.md
 *
 * This script copies the content from the root CHANGELOG.md to the docs site,
 * with only formatting changes (title format).
 *
 * Run from the docs directory: node scripts/sync-changelog.mjs
 */

import { readFileSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const docsDir = join(__dirname, "..");
const rootDir = join(docsDir, "..");

const sourcePath = join(rootDir, "CHANGELOG.md");
const targetPath = join(docsDir, "en/release-notes/changelog.md");

const HEADER = `# Changelog

This page documents the changes in each Pythinker Code release.

`;

// Read the source file
let content = readFileSync(sourcePath, "utf-8");

// Remove the HTML comment block at the top
content = content.replace(/<!--[\s\S]*?-->\n*/g, "");

// Remove the "# Changelog" title (we'll add our own header)
content = content.replace(/^# Changelog\n+/, "");

// Release headers (`## X.Y.Z (YYYY-MM-DD)`) and the `### What changed in this
// release` subsections are copied through verbatim — the root CHANGELOG already
// uses the format the docs site renders, so no title rewriting is needed.

// The docs changelog is emitted under docs/en/release-notes/, so links that are
// correct from the repository root need to be adjusted for VitePress dead-link
// checking.
content = content.replaceAll(
  "docs/history/CHANGELOG-pre-0.8.0.md",
  "../../history/CHANGELOG-pre-0.8.0.md"
);

// Write the target file
writeFileSync(targetPath, HEADER + content.trim() + "\n");

console.log(`Synced changelog to ${targetPath}`);
