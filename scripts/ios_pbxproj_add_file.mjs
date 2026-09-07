// Lägger en fil i ett Xcode-targets Resources-fas, direkt i project.pbxproj.
//
//   node scripts/ios_pbxproj_add_file.mjs ios/App/App.xcodeproj/project.pbxproj PrivacyInfo.xcprivacy
//   node scripts/ios_pbxproj_add_file.mjs <pbxproj> <filnamn> --verify   # ändrar inget, säger bara läget
//
// VARFÖR. Capacitors iOS-mall innehåller ingen PrivacyInfo.xcprivacy, och en
// fil som bara ligger på disk hamnar aldrig i app-bundlen - Apple kräver att
// den är med i targetets Resources. Att be en människa klicka i Xcode varje
// gång ios/ genereras om är både långsamt och lätt att glömma; det här gör
// samma sak reproducerbart.
//
// SÄKERHET. Filen skrivs bara om när något faktiskt saknas, en .bak sparas
// först, och resultatet kontrolleras (alla fyra sektioner + balanserade
// klamrar) innan det ersätter originalet. Körningen är idempotent: en fil
// som redan är med i Resources lämnas orörd.
//
// Formatet är OpenStep-plisten Xcode skriver (objectVersion 60), och
// raderna följer mallens egen stil exakt - se node_modules/@capacitor/cli/
// assets/ios-spm-template.tar.gz.

import { createHash } from "node:crypto";
import { copyFileSync, readFileSync, writeFileSync } from "node:fs";

const TYPES = {
  ".xcprivacy": "text.xml",
  ".plist": "text.plist.xml",
  ".json": "text.json",
  ".xml": "text.xml",
  ".png": "image.png",
};

/** 24 hexadecimaler, härledda ur filnamnet så samma fil får samma id vid
 * varje körning (annars växer projektfilen för varje anrop). */
function objectId(kind, name, taken) {
  const base = createHash("sha1").update(`matjakt:${kind}:${name}`).digest("hex").toUpperCase();
  for (let attempt = 0; attempt < 16; attempt++) {
    const id = (attempt ? createHash("sha1").update(base + attempt).digest("hex").toUpperCase() : base).slice(0, 24);
    if (!taken.has(id)) return id;
  }
  throw new Error("kunde inte hitta ett ledigt objekt-id");
}

function sectionRange(text, name) {
  const start = text.indexOf(`/* Begin ${name} section */`);
  const end = text.indexOf(`/* End ${name} section */`);
  if (start < 0 || end < 0) throw new Error(`saknar sektionen ${name}`);
  return { start, end };
}

/** Blocket för ett objekt, hittat på dess id + kommentar. */
function blockRange(text, header) {
  const start = text.indexOf(header);
  if (start < 0) return null;
  const end = text.indexOf("\n\t\t};", start);
  return end < 0 ? null : { start, end };
}

export function addResourceFile(text, fileName, { targetGroup = "App" } = {}) {
  const inResources = `${fileName} in Resources`;
  const already = {
    buildFile: text.includes(`/* ${inResources} */ = {isa = PBXBuildFile;`),
    fileRef: text.includes(`/* ${fileName} */ = {isa = PBXFileReference;`),
    group: false,
    phase: false,
  };

  const taken = new Set(text.match(/\b[0-9A-F]{24}\b/g) || []);
  const ext = fileName.slice(fileName.lastIndexOf("."));
  const fileType = TYPES[ext] || "text";

  // Befintliga id:n återanvänds så en halvfärdig inläggning kan lagas.
  const fileRefId = (text.match(new RegExp(`([0-9A-F]{24}) /\\* ${fileName} \\*/ = \\{isa = PBXFileReference;`)) || [])[1]
    || objectId("fileref", fileName, taken);
  taken.add(fileRefId);
  const buildFileId = (text.match(new RegExp(`([0-9A-F]{24}) /\\* ${inResources} \\*/ = \\{isa = PBXBuildFile;`)) || [])[1]
    || objectId("buildfile", fileName, taken);
  taken.add(buildFileId);

  let out = text;
  if (!already.buildFile) {
    const { start } = sectionRange(out, "PBXBuildFile");
    const anchor = out.indexOf("\n", start) + 1;
    out = out.slice(0, anchor)
      + `\t\t${buildFileId} /* ${inResources} */ = {isa = PBXBuildFile; fileRef = ${fileRefId} /* ${fileName} */; };\n`
      + out.slice(anchor);
  }
  if (!already.fileRef) {
    const { start } = sectionRange(out, "PBXFileReference");
    const anchor = out.indexOf("\n", start) + 1;
    out = out.slice(0, anchor)
      + `\t\t${fileRefId} /* ${fileName} */ = {isa = PBXFileReference; lastKnownFileType = ${fileType}; path = ${fileName}; sourceTree = "<group>"; };\n`
      + out.slice(anchor);
  }

  // Gruppen (mappen i Xcodes navigator) - utan den syns filen inte, även om
  // den byggs. Hittas på gruppens kommentar, aldrig på ett hårdkodat id.
  const groupHeaderMatch = out.match(new RegExp(`[0-9A-F]{24} /\\* ${targetGroup} \\*/ = \\{\\n\\t\\t\\tisa = PBXGroup;`));
  if (!groupHeaderMatch) throw new Error(`hittade ingen PBXGroup som heter ${targetGroup}`);
  const group = blockRange(out, groupHeaderMatch[0]);
  if (!group) throw new Error(`kunde inte läsa gruppen ${targetGroup}`);
  const groupText = out.slice(group.start, group.end);
  already.group = groupText.includes(`/* ${fileName} */,`);
  if (!already.group) {
    const childrenAt = out.indexOf("children = (\n", group.start);
    if (childrenAt < 0 || childrenAt > group.end) throw new Error(`gruppen ${targetGroup} saknar children`);
    const anchor = childrenAt + "children = (\n".length;
    out = out.slice(0, anchor) + `\t\t\t\t${fileRefId} /* ${fileName} */,\n` + out.slice(anchor);
  }

  // Resources-fasen: det här är det som avgör om filen hamnar i .app-bundlen.
  const phaseHeaderMatch = out.match(/[0-9A-F]{24} \/\* Resources \*\/ = \{\n\t\t\tisa = PBXResourcesBuildPhase;/);
  if (!phaseHeaderMatch) throw new Error("hittade ingen PBXResourcesBuildPhase");
  const phase = blockRange(out, phaseHeaderMatch[0]);
  if (!phase) throw new Error("kunde inte läsa Resources-fasen");
  already.phase = out.slice(phase.start, phase.end).includes(`/* ${inResources} */,`);
  if (!already.phase) {
    const filesAt = out.indexOf("files = (\n", phase.start);
    if (filesAt < 0 || filesAt > phase.end) throw new Error("Resources-fasen saknar files");
    const anchor = filesAt + "files = (\n".length;
    out = out.slice(0, anchor) + `\t\t\t\t${buildFileId} /* ${inResources} */,\n` + out.slice(anchor);
  }

  const alreadyComplete = already.buildFile && already.fileRef && already.group && already.phase;
  return { text: out, changed: !alreadyComplete, already, fileRefId, buildFileId };
}

/** Grov men effektiv kontroll: en projektfil med obalanserade klamrar eller
 * en tappad sektion öppnar inte i Xcode, och då är allt annat meningslöst. */
export function looksIntact(text) {
  const opens = (text.match(/\{/g) || []).length;
  const closes = (text.match(/\}/g) || []).length;
  const sections = ["PBXBuildFile", "PBXFileReference", "PBXGroup", "PBXResourcesBuildPhase", "PBXNativeTarget"];
  return opens === closes && sections.every(s => text.includes(`/* Begin ${s} section */`) && text.includes(`/* End ${s} section */`));
}

export function isInResources(text, fileName) {
  const phaseHeader = (text.match(/[0-9A-F]{24} \/\* Resources \*\/ = \{\n\t\t\tisa = PBXResourcesBuildPhase;/) || [])[0];
  if (!phaseHeader) return false;
  const phase = blockRange(text, phaseHeader);
  return Boolean(phase) && text.slice(phase.start, phase.end).includes(`/* ${fileName} in Resources */,`);
}

const isMain = process.argv[1] && import.meta.url.endsWith(process.argv[1].replace(/\\/g, "/").split("/").pop());
if (isMain) {
  const [pbxPath, fileName, ...flags] = process.argv.slice(2);
  if (!pbxPath || !fileName) {
    console.error("Användning: node scripts/ios_pbxproj_add_file.mjs <project.pbxproj> <filnamn> [--verify]");
    process.exit(2);
  }
  const original = readFileSync(pbxPath, "utf8");
  if (flags.includes("--verify")) {
    const inPhase = isInResources(original, fileName);
    console.log(inPhase ? `${fileName}: i Resources` : `${fileName}: SAKNAS i Resources`);
    process.exit(inPhase ? 0 : 1);
  }
  try {
    const { text, changed } = addResourceFile(original, fileName);
    if (!changed) { console.log(`${fileName} var redan med i App-targetets Resources`); process.exit(0); }
    if (!looksIntact(text) || !isInResources(text, fileName)) throw new Error("resultatet ser inte rätt ut - skriver inte");
    copyFileSync(pbxPath, `${pbxPath}.bak`);
    writeFileSync(pbxPath, text);
    console.log(`${fileName} tillagd i App-targetets Resources (original: ${pbxPath}.bak)`);
  } catch (error) {
    console.error(`kunde inte lägga till ${fileName}: ${error.message}`);
    process.exit(1);
  }
}
