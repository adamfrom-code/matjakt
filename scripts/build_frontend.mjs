// Bygger den frontend som deployas: en kopia av frontend/ där app.js är
// buntad och minifierad (ESM, es2020) och styles.css minifierad. Källorna
// rörs aldrig - lokalt körs appen som förut direkt från frontend/app.
//
//   node scripts/build_frontend.mjs [utkatalog]   (standard: dist/frontend)
//
// Ingen funktionsändring: samma moduler, samma exekveringsordning, bara
// ihopslagna till en fil så telefonen gör EN hämtning i stället för tretton.
// Testerna (node --test, backend, Playwright-E2E) körs mot källorna; E2E:n
// kan pekas mot bygget med MATJAKT_E2E_FRONTEND_DIR=dist/frontend.
import { build } from "esbuild";
import { cpSync, mkdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "frontend");
const out = resolve(process.argv[2] || join(root, "dist", "frontend"));

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(source, out, { recursive: true, filter: path => !path.includes("node_modules") });

const kb = path => (statSync(path).size / 1024).toFixed(1);
const before = { app: kb(join(source, "app", "app.js")), css: kb(join(source, "app", "styles.css")) };

await build({
  entryPoints: [join(source, "app", "app.js")],
  outfile: join(out, "app", "app.js"),
  bundle: true,
  minify: true,
  format: "esm",
  target: ["es2020"],
  charset: "utf8",
  legalComments: "none",
  logLevel: "warning",
});
await build({
  entryPoints: [join(source, "app", "styles.css")],
  outfile: join(out, "app", "styles.css"),
  minify: true,
  charset: "utf8",
  logLevel: "warning",
});
// Modulerna ligger i bundeln - kopian behöver dem inte.
rmSync(join(out, "app", "src"), { recursive: true, force: true });

const after = { app: kb(join(out, "app", "app.js")), css: kb(join(out, "app", "styles.css")) };
console.log(`build: app.js ${before.app} kB -> ${after.app} kB, styles.css ${before.css} kB -> ${after.css} kB -> ${out}`);
