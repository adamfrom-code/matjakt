// Bygger den frontend som deployas: en kopia av frontend/ där app.js är
// buntad och minifierad (ESM, es2020) och styles.css minifierad. Källorna
// rörs aldrig - lokalt körs appen som förut direkt från frontend/app.
//
//   node scripts/build_frontend.mjs [utkatalog]   (standard: dist/frontend)
//   node scripts/build_frontend.mjs dist/native --native --api-url=https://matjakt.onrender.com/api
//
// --api-url skriver in adressen i <meta name="matjakt-api-url"> (native-appen
// kör inte same-origin med backend). --native tar bort landningssidans
// statistikskript (ligger utanför webDir) - inget annat skiljer bygget.
//
// Ingen funktionsändring: samma moduler, samma exekveringsordning, bara
// ihopslagna till en fil så telefonen gör EN hämtning i stället för tretton.
// Testerna (node --test, backend, Playwright-E2E) körs mot källorna; E2E:n
// kan pekas mot bygget med MATJAKT_E2E_FRONTEND_DIR=dist/frontend.
import { build } from "esbuild";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { stampBuild } from "./frontend_version.mjs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "frontend");
const args = process.argv.slice(2);
const flags = args.filter(arg => arg.startsWith("--"));
const positional = args.filter(arg => !arg.startsWith("--"));
const out = resolve(positional[0] || join(root, "dist", "frontend"));
const apiUrl = (flags.find(arg => arg.startsWith("--api-url=")) || "").slice("--api-url=".length).trim();
const native = flags.includes("--native");
if (apiUrl && !/^https:\/\/[a-z0-9.-]+\/api$/i.test(apiUrl)) {
  throw new Error(`--api-url måste vara https://<värd>/api, fick: ${apiUrl}`);
}

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

// Native-/fjärrbygge: appen ska prata med produktionens backend, inte med
// sin egen (obefintliga) origin. Metataggen är den enda platsen appen
// läser adressen ifrån (src/api/config.js).
const indexPath = join(out, "app", "index.html");
let index = readFileSync(indexPath, "utf8");
if (apiUrl) {
  const before = index;
  index = index.replace('<meta name="matjakt-api-url" content="">', `<meta name="matjakt-api-url" content="${apiUrl}">`);
  if (index === before) throw new Error("hittade inte den tomma matjakt-api-url-metataggen i app/index.html");
}
if (native) {
  index = index.replace(/\s*<script src="\.\.\/traffic\.js" defer><\/script>/, "");
}
writeFileSync(indexPath, index);

// KONTROLLRUMMET FÖLJER INTE MED IN I APPEN.
//
// admin.html och admin.js ligger i app/ för att backend-servern ska kunna
// servera dem på samma origin som API:t - kontrollrummet är en driftsida,
// inte en konsumentskärm. I ett webbygge är det rätt: den som kan adressen
// möts ändå av en admin-tokengrind som svarar 404 för alla andra.
//
// I native-bundlet är det fel. Sidan hamnar i en app som laddas ner från
// App Store, och den som packar upp .ipa:n hittar den. Ingen säkerhetslucka
// - grinden ligger på servern - men en granskare som ser en inloggningssida
// för "drift" i en matbudgetapp kommer att fråga, och frågan är dyrare att
// besvara än filen är att utesluta.
//
// Tas bort EFTER att index.html skrivits och FÖRE stampBuild, så
// cache-digesten räknas på det som faktiskt paketeras.
if (native) {
  for (const namn of ["admin.html", "admin.js"]) {
    const sökväg = join(out, "app", namn);
    if (existsSync(sökväg)) rmSync(sökväg);
  }
}

// CACHE-STÄMPELN SKRIVS HÄR, OCH FINNS INGEN ANNANSTANS.
//
// Källorna bär `__MATJAKT_VERSION__`, inte ett tal (L9). Ett tal i källan var
// tre handredigerade rader som måste vara lika, som kunde SJUNKA vid merge,
// och som var den enda raden åtta parallella grenar konfliktade på. Bygget
// stämplar i stället in ett värde som är HÄRLETT ur det som faktiskt byggts:
// eran ur scripts/frontend_version.mjs plus en digest över varje fil under
// app/ i utdatan - bundeln, den minifierade CSS:en, index.html, admin-sidan,
// manifestet, receptbanken och bilderna.
//
// Därför kan ändrad kod aldrig hamna bakom en adress webbläsaren redan sett:
// det finns inget att glömma. stampBuild kastar om en platshållare står kvar
// i utdatan efteråt - en ostämplad CACHE_NAME i produktion vore en trasig
// cache-nyckel, och ett tyst genomsläpp är det farligaste utfallet här.
const stamp = stampBuild(join(out, "app"));

const after = { app: kb(join(out, "app", "app.js")), css: kb(join(out, "app", "styles.css")) };
console.log(`build: app.js ${before.app} kB -> ${after.app} kB, styles.css ${before.css} kB -> ${after.css} kB, cache v${stamp} -> ${out}${apiUrl ? ` (api: ${apiUrl})` : ""}${native ? " [native]" : ""}`);
