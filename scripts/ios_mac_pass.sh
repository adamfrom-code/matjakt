#!/usr/bin/env bash
# Matjakt - iOS-passet på Mac, i ETT kommando.
#
#   bash scripts/ios_mac_pass.sh                # allt: kontroller, bygge, cap sync, Xcode, simulator, djuplänk
#   bash scripts/ios_mac_pass.sh --checks-only  # bara miljö- och repokontroller
#   bash scripts/ios_mac_pass.sh --simulator "iPhone 16 Pro"   # välj simulator (annars nyaste iPhone)
#   bash scripts/ios_mac_pass.sh --open         # öppna projektet i Xcode på slutet
#
# Skriptet rör ALDRIG webb/pricing/mejl/hushåll - bara ios/, dist/native och
# byggkatalogen build/ios. Varje steg skriver ✓ eller ✗ och skriptet
# fortsätter så långt det går, så rapporten i slutet visar hela läget.
# Det som kräver Apple-ID/Team-ID (signering för fysisk iPhone, Associated
# Domains) görs inte här - simulatorn behöver ingen signering.

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
FAILED=0; WARNINGS=0
SIM_NAME=""; OPEN_XCODE=0; CHECKS_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --simulator) SIM_NAME="$2"; shift 2 ;;
    --open) OPEN_XCODE=1; shift ;;
    --checks-only) CHECKS_ONLY=1; shift ;;
    *) echo "okänd flagga: $1"; exit 2 ;;
  esac
done
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*"; WARNINGS=$((WARNINGS + 1)); }
fail() { printf '  ✗ %s\n' "$*"; FAILED=$((FAILED + 1)); }
step() { printf '\n== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
PB=/usr/libexec/PlistBuddy
APP_ID="se.matjakt.app"
API_URL="https://matjakt.onrender.com/api"
REPORT=()

# ---------------------------------------------------------------- 1. Xcode
step "Xcode"
if [ "$(uname -s)" != "Darwin" ]; then fail "det här är inte macOS ($(uname -s)) - skriptet är för Macen"; exit 1; fi
XCODE_PATH="$(xcode-select -p 2>/dev/null || true)"
if [ -z "$XCODE_PATH" ]; then
  fail "xcode-select pekar ingenstans. Installera Xcode från App Store, öppna det en gång, kör sedan: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
elif [[ "$XCODE_PATH" != *"Xcode"*"/Contents/Developer" ]]; then
  fail "xcode-select pekar på '$XCODE_PATH' (Command Line Tools?). Kör: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer"
else
  ok "xcode-select: $XCODE_PATH"
fi
XCODE_VERSION="$(xcodebuild -version 2>/dev/null | tr '\n' ' ')"
if [ -z "$XCODE_VERSION" ]; then
  fail "xcodebuild svarar inte - godkänn licensen: sudo xcodebuild -license accept"
else
  ok "$XCODE_VERSION"
fi
REPORT+=("Xcode: ${XCODE_VERSION:-saknas}")
if xcodebuild -checkFirstLaunchStatus >/dev/null 2>&1; then ok "första starten klar"; else warn "Xcode har inte gjort sin första start: sudo xcodebuild -runFirstLaunch"; fi
have xcrun && ok "xcrun finns" || fail "xcrun saknas"

# ---------------------------------------------------------------- 2. Node/npm
step "Node/npm"
if have node; then
  NODE_MAJOR="$(node -v | sed 's/v\([0-9]*\).*/\1/')"
  [ "${NODE_MAJOR:-0}" -ge 20 ] && ok "node $(node -v)" || fail "node $(node -v) - behöver 20+ (brew install node@22)"
else
  fail "node saknas (brew install node@22)"
fi
have npm && ok "npm $(npm -v)" || fail "npm saknas"

# ---------------------------------------------------------------- 3. Repo
step "Repo"
if have git && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git fetch -q origin 2>/dev/null || warn "kunde inte hämta från origin (offline?)"
  LOCAL="$(git rev-parse --short HEAD)"; REMOTE="$(git rev-parse --short origin/main 2>/dev/null || echo '?')"
  if [ "$LOCAL" = "$REMOTE" ]; then ok "HEAD $LOCAL = origin/main"; else warn "HEAD $LOCAL ≠ origin/main $REMOTE - kör: git checkout main && git pull --ff-only"; fi
  if [ -z "$(git status --porcelain)" ]; then ok "arbetskopian är ren"; else warn "arbetskopian har ändringar:"; git status --short | head -10; fi
  REPORT+=("Git: HEAD $LOCAL (origin/main $REMOTE)")
else
  fail "inte ett git-repo - klona: git clone https://github.com/adamfrom-code/matjakt.git && cd matjakt"
fi
for f in capacitor.config.json ios-prep/Info.plist.additions.xml ios-prep/PrivacyInfo.xcprivacy resources/icon-only.png resources/splash.png; do
  [ -f "$f" ] && ok "$f" || fail "$f saknas"
done
if have node; then
  CFG_ID="$(node -e 'console.log(require("./capacitor.config.json").appId)' 2>/dev/null)"
  CFG_NAME="$(node -e 'console.log(require("./capacitor.config.json").appName)' 2>/dev/null)"
  CFG_WEBDIR="$(node -e 'console.log(require("./capacitor.config.json").webDir)' 2>/dev/null)"
  [ "$CFG_ID" = "$APP_ID" ] && ok "appId $CFG_ID" || fail "appId är '$CFG_ID', ska vara $APP_ID"
  [ "$CFG_NAME" = "Matjakt" ] && ok "appName $CFG_NAME" || fail "appName är '$CFG_NAME'"
  [ "$CFG_WEBDIR" = "dist/native/app" ] && ok "webDir $CFG_WEBDIR" || fail "webDir är '$CFG_WEBDIR', ska vara dist/native/app"
fi

# ---------------------------------------------------------------- 4. Backend + CORS från den här maskinen
step "Backend och CORS (capacitor://localhost)"
if have curl; then
  HEALTH="$(curl -s --max-time 20 "$API_URL/health" || true)"
  if echo "$HEALTH" | grep -q '"gate": false'; then ok "api/health: gate false, commit $(echo "$HEALTH" | sed -n 's/.*"commit": "\([^"]*\)".*/\1/p')"; else fail "api/health svarar inte som väntat: ${HEALTH:0:120}"; fi
  ACAO="$(curl -s -D - -o /dev/null --max-time 20 -H "Origin: capacitor://localhost" "$API_URL/recipes?limit=1" | tr -d '\r' | grep -i '^access-control-allow-origin' | awk '{print $2}')"
  [ "$ACAO" = "capacitor://localhost" ] && ok "CORS ekar capacitor://localhost" || fail "CORS ekar '$ACAO' - sätt MATJAKT_FRONTEND_ORIGIN i Render (render.yaml har värdet)"
  REPORT+=("API/CORS: health $(echo "$HEALTH" | grep -q '"gate": false' && echo ok || echo FEL), CORS ${ACAO:-saknas}")
else
  fail "curl saknas"
fi

if [ "$CHECKS_ONLY" = 1 ]; then step "Bara kontroller (--checks-only)"; printf '\n%s\n' "${REPORT[@]}"; exit $FAILED; fi
[ "$FAILED" -gt 0 ] && { step "Stoppar: $FAILED kontroll(er) föll ovan - fixa dem först"; exit 1; }

# ---------------------------------------------------------------- 5. Beroenden + native-bygge
step "npm ci"
if npm ci --no-audit --no-fund >/tmp/matjakt-npm.log 2>&1; then ok "npm ci"; else fail "npm ci föll - se /tmp/matjakt-npm.log"; tail -5 /tmp/matjakt-npm.log; exit 1; fi

step "Native-bygge (npm run build:native)"
if npm run build:native >/tmp/matjakt-build.log 2>&1; then
  tail -1 /tmp/matjakt-build.log
  grep -q "matjakt-api-url\" content=\"$API_URL\"" dist/native/app/index.html && ok "API-URL i metataggen: $API_URL" || fail "API-URL saknas i dist/native/app/index.html"
  grep -q "traffic.js" dist/native/app/index.html && fail "landningens statistikskript ligger kvar i native-bygget" || ok "inget ../traffic.js i native-bygget"
  [ -f dist/native/app/app.js ] && ok "app.js $(du -k dist/native/app/app.js | cut -f1) kB" || fail "dist/native/app/app.js saknas"
else
  fail "build:native föll - se /tmp/matjakt-build.log"; tail -5 /tmp/matjakt-build.log; exit 1
fi

# ---------------------------------------------------------------- 6. cap add ios (bara om ios/ saknas) + sync
step "Capacitor iOS"
if [ ! -d ios ]; then
  PM_FLAG=""
  if ! have pod; then PM_FLAG="--packagemanager SPM"; warn "CocoaPods saknas - använder Swift Package Manager ($PM_FLAG)"; fi
  # shellcheck disable=SC2086
  if npx cap add ios $PM_FLAG >/tmp/matjakt-capadd.log 2>&1; then ok "npx cap add ios $PM_FLAG"; else fail "cap add ios föll - se /tmp/matjakt-capadd.log"; tail -8 /tmp/matjakt-capadd.log; exit 1; fi
else
  ok "ios/ finns redan - hoppar över cap add"
fi
if npx cap sync ios >/tmp/matjakt-capsync.log 2>&1; then ok "npx cap sync ios"; grep -iE "plugin|@capacitor/(app|browser)" /tmp/matjakt-capsync.log | head -4; else fail "cap sync ios föll - se /tmp/matjakt-capsync.log"; tail -8 /tmp/matjakt-capsync.log; exit 1; fi
[ -d ios/App/App/public ] && ok "webben kopierad till ios/App/App/public" || fail "ios/App/App/public saknas efter sync"
grep -q "matjakt-api-url\" content=\"$API_URL\"" ios/App/App/public/index.html 2>/dev/null && ok "API-URL med i den kopierade appen" || fail "API-URL saknas i ios/App/App/public/index.html"

# ---------------------------------------------------------------- 7. Bundle id, namn, Info.plist, PrivacyInfo
step "Bundle id och Info.plist"
PBX=ios/App/App.xcodeproj/project.pbxproj
PLIST=ios/App/App/Info.plist
if grep -q "PRODUCT_BUNDLE_IDENTIFIER = $APP_ID;" "$PBX"; then ok "PRODUCT_BUNDLE_IDENTIFIER = $APP_ID"; else fail "bundle id i $PBX är inte $APP_ID (Xcode: target App → General → Bundle Identifier)"; fi
plist_set() {   # nyckel typ värde - Add om saknas, annars Set
  local key="$1" type="$2" value="$3"
  if $PB -c "Print :$key" "$PLIST" >/dev/null 2>&1; then $PB -c "Set :$key $value" "$PLIST"; else $PB -c "Add :$key $type $value" "$PLIST"; fi
}
if [ -f "$PLIST" ] && [ -x "$PB" ]; then
  plist_set CFBundleDisplayName string "Matjakt"
  plist_set NSLocationWhenInUseUsageDescription string "Matjakt använder din plats för att hitta matbutiker nära dig."
  plist_set ITSAppUsesNonExemptEncryption bool false
  plist_set CFBundleDevelopmentRegion string "sv"
  # Enbart stående läge.
  $PB -c "Delete :UISupportedInterfaceOrientations" "$PLIST" >/dev/null 2>&1 || true
  $PB -c "Add :UISupportedInterfaceOrientations array" "$PLIST"
  $PB -c "Add :UISupportedInterfaceOrientations:0 string UIInterfaceOrientationPortrait" "$PLIST"
  $PB -c "Delete :UISupportedInterfaceOrientations~ipad" "$PLIST" >/dev/null 2>&1 || true
  $PB -c "Add :UISupportedInterfaceOrientations~ipad array" "$PLIST"
  $PB -c "Add :UISupportedInterfaceOrientations~ipad:0 string UIInterfaceOrientationPortrait" "$PLIST"
  $PB -c "Add :UISupportedInterfaceOrientations~ipad:1 string UIInterfaceOrientationPortraitUpsideDown" "$PLIST"
  $PB -c "Delete :CFBundleLocalizations" "$PLIST" >/dev/null 2>&1 || true
  $PB -c "Add :CFBundleLocalizations array" "$PLIST"
  $PB -c "Add :CFBundleLocalizations:0 string sv" "$PLIST"
  # Eget URL-schema matjakt:// så djuplänkar kan testas i simulatorn utan
  # Team-ID (universella https-länkar kräver Associated Domains).
  $PB -c "Delete :CFBundleURLTypes" "$PLIST" >/dev/null 2>&1 || true
  $PB -c "Add :CFBundleURLTypes array" "$PLIST"
  $PB -c "Add :CFBundleURLTypes:0 dict" "$PLIST"
  $PB -c "Add :CFBundleURLTypes:0:CFBundleURLName string $APP_ID" "$PLIST"
  $PB -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$PLIST"
  $PB -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string matjakt" "$PLIST"
  ok "Info.plist: display name, plats-text, ingen egen kryptering, stående läge, sv, URL-schema matjakt://"
  [ "$($PB -c 'Print :CFBundleDisplayName' "$PLIST")" = "Matjakt" ] && ok "CFBundleDisplayName = Matjakt" || fail "CFBundleDisplayName fel"
else
  fail "$PLIST eller PlistBuddy saknas"
fi
if [ -f ios/App/App/PrivacyInfo.xcprivacy ]; then
  cp ios-prep/PrivacyInfo.xcprivacy ios/App/App/PrivacyInfo.xcprivacy && ok "PrivacyInfo.xcprivacy ersatt med Matjakts (redan i target)"
else
  cp ios-prep/PrivacyInfo.xcprivacy ios/App/App/PrivacyInfo.xcprivacy
  grep -q "PrivacyInfo.xcprivacy" "$PBX" && ok "PrivacyInfo.xcprivacy kopierad (refererad i projektet)" || warn "PrivacyInfo.xcprivacy kopierad men INTE i target: Xcode → högerklicka App-mappen → Add Files to \"App\" → PrivacyInfo.xcprivacy"
fi
plutil -lint ios/App/App/PrivacyInfo.xcprivacy >/dev/null 2>&1 && ok "PrivacyInfo är giltig plist" || fail "PrivacyInfo.xcprivacy är inte en giltig plist"
plutil -lint "$PLIST" >/dev/null 2>&1 && ok "Info.plist är giltig" || fail "Info.plist är trasig"

# ---------------------------------------------------------------- 8. Ikon + splash
step "Ikon och splash (@capacitor/assets)"
if npx --yes @capacitor/assets generate --ios --iconBackgroundColor '#f6f7f4' --iconBackgroundColorDark '#17211b' --splashBackgroundColor '#f6f7f4' --splashBackgroundColorDark '#17211b' >/tmp/matjakt-assets.log 2>&1; then
  ok "assets genererade"
else
  warn "assets-generering föll (se /tmp/matjakt-assets.log) - Capacitors standardikon används tills vidare"
fi
ls ios/App/App/Assets.xcassets/AppIcon.appiconset/*.png >/dev/null 2>&1 && ok "AppIcon.appiconset har bilder" || warn "AppIcon.appiconset saknar bilder"
ls ios/App/App/Assets.xcassets/Splash.imageset/*.png >/dev/null 2>&1 && ok "Splash.imageset har bilder" || warn "Splash.imageset saknar bilder"

# ---------------------------------------------------------------- 9. Simulator
step "Simulator"
SIM_JSON="$(xcrun simctl list devices available -j 2>/dev/null)"
pick_sim() {   # nyaste iOS-runtime, nyaste iPhone; eller namnet från --simulator
  node -e '
    const j = JSON.parse(require("fs").readFileSync(0, "utf8")); const want = process.argv[1] || "";
    const runtimes = Object.keys(j.devices).filter(r => /iOS/.test(r)).sort();
    for (const rt of runtimes.reverse()) {
      const phones = (j.devices[rt] || []).filter(d => d.isAvailable && /^iPhone/.test(d.name) && (!want || d.name === want));
      phones.sort((a, b) => b.name.localeCompare(a.name, "en", { numeric: true }));
      if (phones.length) { console.log(phones[0].udid + "\t" + phones[0].name + "\t" + rt.replace(/.*iOS-/, "iOS ").replace(/-/g, ".")); process.exit(0); }
    }
    process.exit(1);' "$1"
}
SIM_PICK="$(echo "$SIM_JSON" | pick_sim "$SIM_NAME" 2>/dev/null || true)"
if [ -z "$SIM_PICK" ]; then
  fail "ingen iPhone-simulator hittades${SIM_NAME:+ med namnet '$SIM_NAME'}. Xcode → Settings → Components → ladda ner en iOS-runtime, eller: xcodebuild -downloadPlatform iOS"
  printf '\n%s\n' "${REPORT[@]}"; exit 1
fi
SIM_UDID="$(echo "$SIM_PICK" | cut -f1)"; SIM_LABEL="$(echo "$SIM_PICK" | cut -f2) ($(echo "$SIM_PICK" | cut -f3))"
ok "simulator: $SIM_LABEL"
REPORT+=("Simulator: $SIM_LABEL")
xcrun simctl boot "$SIM_UDID" >/dev/null 2>&1 || true
open -a Simulator >/dev/null 2>&1 || true
xcrun simctl bootstatus "$SIM_UDID" -b >/dev/null 2>&1 && ok "simulatorn är igång" || warn "kunde inte bekräfta att simulatorn bootat"

# ---------------------------------------------------------------- 10. Xcode-bygge (ingen signering behövs för simulatorn)
step "xcodebuild"
BUILD_DIR="$ROOT/build/ios"
if [ -e ios/App/App.xcworkspace ]; then XC_TARGET=(-workspace ios/App/App.xcworkspace); else XC_TARGET=(-project ios/App/App.xcodeproj); fi
if xcodebuild "${XC_TARGET[@]}" -scheme App -configuration Debug -sdk iphonesimulator \
     -destination "id=$SIM_UDID" -derivedDataPath "$BUILD_DIR" \
     CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
     -quiet build >/tmp/matjakt-xcodebuild.log 2>&1; then
  ok "xcodebuild: BUILD SUCCEEDED"; BUILD_STATUS="BUILD SUCCEEDED"
else
  BUILD_STATUS="BUILD FAILED"; fail "xcodebuild föll - de sista raderna:"; grep -E "error:|warning: .*deprecated|BUILD" /tmp/matjakt-xcodebuild.log | tail -12
fi
REPORT+=("Build: $BUILD_STATUS")
APP_BUNDLE="$(find "$BUILD_DIR/Build/Products" -maxdepth 2 -name 'App.app' -path '*iphonesimulator*' 2>/dev/null | head -1)"

# ---------------------------------------------------------------- 11. Installera + starta
step "Installera och starta i simulatorn"
APP_START="inte startad"
if [ -n "$APP_BUNDLE" ]; then
  BUNDLE_ID_BUILT="$($PB -c 'Print :CFBundleIdentifier' "$APP_BUNDLE/Info.plist" 2>/dev/null)"
  [ "$BUNDLE_ID_BUILT" = "$APP_ID" ] && ok "byggd bundle id $BUNDLE_ID_BUILT" || fail "byggd bundle id är '$BUNDLE_ID_BUILT'"
  DISPLAY_BUILT="$($PB -c 'Print :CFBundleDisplayName' "$APP_BUNDLE/Info.plist" 2>/dev/null)"
  [ "$DISPLAY_BUILT" = "Matjakt" ] && ok "byggt display name $DISPLAY_BUILT" || fail "byggt display name är '$DISPLAY_BUILT'"
  if xcrun simctl install "$SIM_UDID" "$APP_BUNDLE" >/dev/null 2>&1; then ok "installerad"; else fail "kunde inte installera $APP_BUNDLE"; fi
  LAUNCH="$(xcrun simctl launch "$SIM_UDID" "$APP_ID" 2>&1 || true)"
  if echo "$LAUNCH" | grep -q "$APP_ID"; then ok "startad: $LAUNCH"; APP_START="startad ($LAUNCH)"; else fail "start föll: $LAUNCH"; fi
  sleep 6
  xcrun simctl io "$SIM_UDID" screenshot "$BUILD_DIR/start.png" >/dev/null 2>&1 && ok "skärmdump: build/ios/start.png (kolla att den INTE är vit)"
else
  fail "ingen App.app byggd"
fi
REPORT+=("App-start: $APP_START")

# ---------------------------------------------------------------- 12. Djuplänk via eget schema
step "Djuplänkar (matjakt://)"
DEEP="inte testad"
if [ "$APP_START" != "inte startad" ]; then
  for q in "recept=test-recept" "verify=testtoken" "reset=testtoken" "invite=testtoken"; do
    if xcrun simctl openurl "$SIM_UDID" "matjakt://app/?$q" >/dev/null 2>&1; then ok "openurl matjakt://app/?$q levererad (appen laddar om med query-strängen)"; DEEP="matjakt:// levereras"; else fail "openurl matjakt://app/?$q föll"; DEEP="FEL"; fi
    sleep 2
  done
  xcrun simctl io "$SIM_UDID" screenshot "$BUILD_DIR/deeplink.png" >/dev/null 2>&1 || true
  warn "https://matjakt.store/app/?... öppnas i Safari tills Associated Domains (Team-ID) är på plats - se docs/IOS_RELEASE.md"
fi
REPORT+=("Djuplänk: $DEEP (universella https-länkar kräver Team-ID)")

[ "$OPEN_XCODE" = 1 ] && { npx cap open ios >/dev/null 2>&1 && ok "Xcode öppnat"; }

# ---------------------------------------------------------------- Rapport
step "RAPPORT"
printf '%s\n' "${REPORT[@]}"
printf 'Fel: %s  Varningar: %s\n' "$FAILED" "$WARNINGS"
cat <<'EOF'

Manuellt i simulatorn (docs/IOS_RELEASE.md "Simulatorkontroller"):
  Kallstart utan vit skärm → onboarding → Gävle-postnummer 80252 → butiker → vecka
  → recept → Handla (Har hemma / Köpt / Ångra) → Skafferi → Konto: registrera, logga in
  → Hushåll: skapa, bjud in → Cmd+Shift+H (bakgrund) → tillbaka → logga ut/in.
  Tangentbord: Cmd+K växlar mjukt tangentbord. Rotation: Cmd+← ska INTE rotera (stående).
  Flygplansläge: Simulator → Features → Toggle... saknas; stäng Macens wifi i stället.
EOF
exit $FAILED
