// Är skärmdumpen från simulatorn en riktig skärm - eller en vit ruta?
//
//   node scripts/ios_screenshot_check.mjs build/ios/start.png
//
// VARFÖR. "Appen startade" bevisar ingenting: en webview som inte laddade
// visar en helt vit (eller helt bakgrundsfärgad) yta, och en människa måste
// annars titta på bilden för att upptäcka det. Den vanligaste iOS-regressionen
// i en Capacitor-app är just den vita skärmen.
//
// HUR. macOS har `sips` i basinstallationen: PNG konverteras till BMP, som
// går att läsa utan bibliotek. Sedan samplas ett rutnät av pixlar och två
// tal räknas fram: hur stor andel bilden domineras av EN färg, och hur många
// olika färger som förekommer. En laddad app har innehåll; en vit skärm har
// en enda färg på nästan varje pixel.

import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const BLANK_DOMINANT_SHARE = 0.985;   // > 98,5 % samma färg = tom yta
export const BLANK_MIN_COLORS = 6;

/** Minimal BMP-läsare: bilddatans offset står i filhuvudet, bredd/höjd och
 * bitdjup i DIB-huvudet. Klarar 24 och 32 bitar, top-down och bottom-up. */
export function readBmp(buffer) {
  if (buffer.length < 34 || buffer[0] !== 0x42 || buffer[1] !== 0x4d) throw new Error("inte en BMP");
  const dataOffset = buffer.readUInt32LE(10);
  const width = buffer.readInt32LE(18);
  const rawHeight = buffer.readInt32LE(22);
  const height = Math.abs(rawHeight);
  const bpp = buffer.readUInt16LE(28);
  if (![24, 32].includes(bpp)) throw new Error(`oväntat bitdjup: ${bpp}`);
  const bytesPerPixel = bpp / 8;
  const rowSize = Math.floor((bpp * width + 31) / 32) * 4;
  const topDown = rawHeight < 0;
  const pixel = (x, y) => {
    const row = topDown ? y : height - 1 - y;
    const at = dataOffset + row * rowSize + x * bytesPerPixel;
    if (at + 2 >= buffer.length) return null;
    return (buffer[at + 2] << 16) | (buffer[at + 1] << 8) | buffer[at];   // BGR -> RGB
  };
  return { width, height, pixel };
}

/** Samplar ett rutnät i stället för varje pixel: 4 000 punkter räcker gott
 * för att skilja en tom yta från en ritad skärm, och går på millisekunder. */
export function analyse(bmp, samples = 64) {
  const counts = new Map();
  let total = 0;
  for (let sy = 0; sy < samples; sy++) {
    for (let sx = 0; sx < samples; sx++) {
      const x = Math.floor((sx + 0.5) * bmp.width / samples);
      const y = Math.floor((sy + 0.5) * bmp.height / samples);
      const value = bmp.pixel(x, y);
      if (value === null) continue;
      counts.set(value, (counts.get(value) || 0) + 1);
      total++;
    }
  }
  let dominant = 0;
  let dominantColor = 0;
  for (const [color, count] of counts) {
    if (count > dominant) { dominant = count; dominantColor = color; }
  }
  return {
    colors: counts.size,
    dominantShare: total ? dominant / total : 1,
    dominantColor: `#${dominantColor.toString(16).padStart(6, "0")}`,
    samples: total,
  };
}

export function verdict(stats) {
  const blank = stats.dominantShare >= BLANK_DOMINANT_SHARE || stats.colors < BLANK_MIN_COLORS;
  return { blank, ...stats };
}

function toBmp(pngPath) {
  const dir = mkdtempSync(join(tmpdir(), "matjakt-shot-"));
  const bmpPath = join(dir, "shot.bmp");
  execFileSync("sips", ["-s", "format", "bmp", pngPath, "--out", bmpPath], { stdio: "pipe" });
  const buffer = readFileSync(bmpPath);
  rmSync(dir, { recursive: true, force: true });
  return buffer;
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop());
if (isMain) {
  const path = process.argv[2];
  if (!path || !existsSync(path)) { console.error("Användning: node scripts/ios_screenshot_check.mjs <skärmdump.png>"); process.exit(2); }
  let buffer;
  try {
    buffer = path.toLowerCase().endsWith(".bmp") ? readFileSync(path) : toBmp(path);
  } catch (error) {
    console.error(`kunde inte läsa bilden (sips): ${error.message}`);
    process.exit(2);   // 2 = kunde inte avgöra, inte "tom skärm"
  }
  const result = verdict(analyse(readBmp(buffer)));
  const detail = `${result.colors} färger, ${(result.dominantShare * 100).toFixed(1)} % ${result.dominantColor}`;
  if (result.blank) { console.error(`TOM SKÄRM: ${detail}`); process.exit(1); }
  console.log(`skärmen har innehåll: ${detail}`);
}
