// Hjälpskripten för iOS-passet. De körs på en Mac, men logiken i dem är
// vanlig JavaScript och testas här - annars upptäcks ett fel först mitt i
// ett Xcode-bygge, där felmeddelandet inte pekar hit.
import assert from "node:assert/strict";
import { test } from "node:test";

import { addResourceFile, isInResources, looksIntact } from "../scripts/ios_pbxproj_add_file.mjs";
import { analyse, readBmp, verdict } from "../scripts/ios_screenshot_check.mjs";

// Samma form som Capacitors iOS-mall (objectVersion 60), nedkortad till de
// fyra sektioner inläggningen rör.
const PBXPROJ = `// !$*UTF8*$!
{
	archiveVersion = 1;
	objectVersion = 60;
	objects = {

/* Begin PBXBuildFile section */
		50379B232058CBB4000EE86E /* capacitor.config.json in Resources */ = {isa = PBXBuildFile; fileRef = 50379B222058CBB4000EE86E /* capacitor.config.json */; };
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
		50379B222058CBB4000EE86E /* capacitor.config.json */ = {isa = PBXFileReference; fileEncoding = 4; lastKnownFileType = text.json; path = capacitor.config.json; sourceTree = "<group>"; };
/* End PBXFileReference section */

/* Begin PBXGroup section */
		504EC3061FED79650016851F /* App */ = {
			isa = PBXGroup;
			children = (
				50379B222058CBB4000EE86E /* capacitor.config.json */,
			);
			path = App;
			sourceTree = "<group>";
		};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
		504EC3031FED79650016851F /* App */ = {
			isa = PBXNativeTarget;
			buildPhases = (
				504EC3021FED79650016851F /* Resources */,
			);
		};
/* End PBXNativeTarget section */

/* Begin PBXResourcesBuildPhase section */
		504EC3021FED79650016851F /* Resources */ = {
			isa = PBXResourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
				50379B232058CBB4000EE86E /* capacitor.config.json in Resources */,
			);
			runOnlyForDeploymentPostprocessing = 0;
		};
/* End PBXResourcesBuildPhase section */
	};
}
`;

test("PrivacyInfo läggs in i alla fyra sektionerna", () => {
  const { text, changed } = addResourceFile(PBXPROJ, "PrivacyInfo.xcprivacy");
  assert.equal(changed, true);
  assert.ok(looksIntact(text), "projektfilen ska vara hel");
  assert.ok(isInResources(text, "PrivacyInfo.xcprivacy"), "utan Resources hamnar filen aldrig i app-bundlen");
  assert.match(text, /PrivacyInfo\.xcprivacy in Resources \*\/ = \{isa = PBXBuildFile; fileRef = [0-9A-F]{24}/);
  assert.match(text, /PrivacyInfo\.xcprivacy \*\/ = \{isa = PBXFileReference; lastKnownFileType = text\.xml/);
  // Fyra rader till, inte fler: bygg, referens, grupp, Resources.
  assert.equal(text.split("\n").length - PBXPROJ.split("\n").length, 4);
});

test("en andra körning ändrar ingenting", () => {
  const once = addResourceFile(PBXPROJ, "PrivacyInfo.xcprivacy").text;
  const twice = addResourceFile(once, "PrivacyInfo.xcprivacy");
  assert.equal(twice.changed, false);
  assert.equal(twice.text, once, "id:n är härledda ur filnamnet, så inget nytt får skrivas");
});

test("en halvfärdig inläggning lagas i stället för att dubbleras", () => {
  // Filen finns som referens men saknas i Resources (någon avbröt i Xcode).
  const partial = addResourceFile(PBXPROJ, "PrivacyInfo.xcprivacy").text
    .replace(/\n\t+[0-9A-F]{24} \/\* PrivacyInfo\.xcprivacy in Resources \*\/,/, "");
  assert.equal(isInResources(partial, "PrivacyInfo.xcprivacy"), false);
  const fixed = addResourceFile(partial, "PrivacyInfo.xcprivacy");
  assert.equal(fixed.changed, true);
  assert.ok(isInResources(fixed.text, "PrivacyInfo.xcprivacy"));
  assert.equal((fixed.text.match(/= \{isa = PBXFileReference; lastKnownFileType = text\.xml/g) || []).length, 1,
               "referensen får inte dubbleras");
});

test("en okänd grupp är ett fel, inte en tyst miss", () => {
  assert.throws(() => addResourceFile(PBXPROJ, "PrivacyInfo.xcprivacy", { targetGroup: "FinnsInte" }), /FinnsInte/);
});

// ---- skärmdumpen: vit skärm är den vanligaste native-regressionen ----
function bmp(width, height, fill) {
  const rowSize = Math.floor((24 * width + 31) / 32) * 4;
  const buffer = Buffer.alloc(54 + rowSize * height);
  buffer.write("BM");
  buffer.writeUInt32LE(buffer.length, 2);
  buffer.writeUInt32LE(54, 10);
  buffer.writeUInt32LE(40, 14);
  buffer.writeInt32LE(width, 18);
  buffer.writeInt32LE(height, 22);
  buffer.writeUInt16LE(1, 26);
  buffer.writeUInt16LE(24, 28);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const at = 54 + y * rowSize + x * 3;
      const [r, g, b] = fill(x, y);
      buffer[at] = b; buffer[at + 1] = g; buffer[at + 2] = r;
    }
  }
  return buffer;
}
const look = image => verdict(analyse(readBmp(image)));

test("en vit skärm känns igen som tom", () => {
  assert.equal(look(bmp(200, 400, () => [255, 255, 255])).blank, true);
});

test("appens bakgrundsfärg utan innehåll är också tom", () => {
  // Capacitor målar #f6f7f4 innan webviewen laddat - "inte vit" räcker inte.
  assert.equal(look(bmp(200, 400, (x, y) => (y < 8 ? [10, 20, 30] : [246, 247, 244]))).blank, true);
});

test("en ritad skärm har innehåll", () => {
  assert.equal(look(bmp(200, 400, (x, y) => [(x * 7) % 256, (y * 3) % 256, (x + y) % 256])).blank, false);
});

test("BMP:ar uppifrån och ner läses likadant", () => {
  const image = bmp(64, 64, (x, y) => [x * 4, y * 4, 128]);
  image.writeInt32LE(-64, 22);   // negativ höjd = top-down
  assert.equal(look(image).blank, false);
});
