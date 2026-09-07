// app.js anropar hjälpfunktioner ur src/ - och ett bortglömt namn i
// import-satsen syns inte förrän funktionen faktiskt körs, som en
// ReferenceError mitt i en rendering hos en användare. `node --check` hittar
// det inte (syntaxen är giltig) och esbuild inte heller (den behandlar
// okända namn som globaler). Hittat på riktigt 2026-09-07: householdDietary
// användes i receptfiltret utan att vara importerad.
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const APP_DIR = new URL("../frontend/app/", import.meta.url);
const appPath = new URL("app.js", APP_DIR);
const source = readFileSync(appPath, "utf8");

function ownModules(dir = new URL("src/", APP_DIR)) {
  const found = [];
  for (const entry of readdirSync(dir)) {
    const path = new URL(entry, dir);
    if (statSync(path).isDirectory()) found.push(...ownModules(new URL(entry + "/", dir)));
    else if (entry.endsWith(".js")) found.push(path);
  }
  return found;
}

function importedNames(text) {
  const names = new Set();
  for (const match of text.matchAll(/import\s*\{([^}]+)\}\s*from\s*"(\.[^"]+)"/g)) {
    for (const raw of match[1].split(",")) names.add(raw.trim().split(/\s+as\s+/).pop().trim());
  }
  return names;
}

function exportedNames(text) {
  const names = [];
  for (const match of text.matchAll(/export\s+(?:async\s+)?function\s+([A-Za-z0-9_$]+)|export\s+const\s+([A-Za-z0-9_$]+)/g)) {
    names.push(match[1] || match[2]);
  }
  return names;
}

test("varje modulfunktion som app.js anropar är importerad", () => {
  const imported = importedNames(source);
  const missing = [];
  for (const module of ownModules()) {
    const relative = module.pathname.split("/frontend/app/")[1];
    for (const name of exportedNames(readFileSync(module, "utf8"))) {
      if (imported.has(name)) continue;
      const calledHere = new RegExp(`(?<![\\w.$])${name}\\s*\\(`).test(source);
      const declaredHere = new RegExp(`(?:function|const|let|var)\\s+${name}\\b`).test(source);
      if (calledHere && !declaredHere) missing.push(`${relative}: ${name}`);
    }
  }
  assert.deepEqual(missing, [], `app.js anropar namn som inte är importerade:\n${missing.join("\n")}`);
});

test("inga importerade namn är oanvända", () => {
  // Oanvända importer är döda kilobyte i bundeln och gör det svårare att se
  // vad skärmen faktiskt beror på.
  const unused = [];
  for (const name of importedNames(source)) {
    const uses = source.split(new RegExp(`(?<![\\w.$])${name}(?![\\w$])`)).length - 1;
    if (uses <= 1) unused.push(name);
  }
  assert.deepEqual(unused, [], `oanvända importer i app.js: ${unused.join(", ")}`);
});
