#!/usr/bin/env bash
# Matjakt - arkivera och ladda upp till TestFlight, i ETT kommando.
#
#   ASC_KEY_PATH=~/nycklar/AuthKey_ABC123.p8 \
#   ASC_KEY_ID=ABC123XYZ \
#   ASC_ISSUER_ID=69a6de00-... \
#   bash scripts/ios_testflight.sh
#
#   --build <n>     sätt CFBundleVersion (varje uppladdning måste ha ett NYTT
#                   nummer; Apple avvisar ett som redan finns)
#   --version <x>   sätt CFBundleShortVersionString (t.ex. 1.0)
#   --checks-only   bara förhandskontrollerna, inget bygge
#   --no-upload     arkivera och exportera .ipa, men ladda inte upp
#
# Systerskript till ios_mac_pass.sh, som gör simulatorpasset. Det här är
# distributionspasset: det kräver en Apple-utvecklarprenumeration och en
# App Store Connect-API-nyckel, och det rör inget utanför ios/, dist/native
# och build/.
#
# HEMLIGHETERNA. De tre värdena läses ur miljön, aldrig ur argument -
# argument syns i `ps` för varje användare på maskinen. .p8-filen läses men
# skrivs aldrig ut, och skriptet vägrar starta om den ligger inuti repot:
# en nyckel i arbetskatalogen är en nyckel som förr eller senare blir
# committad. (.gitignore håller ute *.p8 och AuthKey_*, men bara i den här
# klonen - filen kan ligga i en annan.)

set -u
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
FEL=0
BUILD_NR=""; VERSION=""; CHECKS_ONLY=0; UPLOAD=1

while [ $# -gt 0 ]; do
  case "$1" in
    --build)   [ $# -ge 2 ] || { echo "fel: --build kräver ett heltal" >&2; exit 2; }; BUILD_NR="$2"; shift 2 ;;
    --version) [ $# -ge 2 ] || { echo "fel: --version kräver ett versionsnummer" >&2; exit 2; }; VERSION="$2"; shift 2 ;;
    --checks-only) CHECKS_ONLY=1; shift ;;
    --no-upload)   UPLOAD=0; shift ;;
    *) echo "okänd flagga: $1" >&2; exit 2 ;;
  esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
nej()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FEL=$((FEL+1)); }
rubrik(){ printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---------------------------------------------------------------- kontroller
rubrik "Förhandskontroller"

if command -v xcodebuild >/dev/null 2>&1; then
  ok "Xcode $(xcodebuild -version | head -1 | cut -d' ' -f2)"
else
  nej "xcodebuild saknas - installera Xcode och kör xcode-select --switch"
fi

# De tre nycklarna. Tomma värden räknas som saknade.
for namn in ASC_KEY_PATH ASC_KEY_ID ASC_ISSUER_ID; do
  varde="${!namn:-}"
  if [ -n "$varde" ]; then ok "$namn satt"; else nej "$namn saknas"; fi
done

NYCKEL="${ASC_KEY_PATH:-}"
if [ -n "$NYCKEL" ]; then
  # ~ expanderas inte i en miljövariabel.
  NYCKEL="${NYCKEL/#\~/$HOME}"
  if [ ! -r "$NYCKEL" ]; then
    nej "går inte att läsa: $NYCKEL"
  else
    ABS="$(cd "$(dirname "$NYCKEL")" && pwd)/$(basename "$NYCKEL")"
    case "$ABS" in
      "$ROOT"/*)
        nej "nyckeln ligger INUTI repot ($ABS). Flytta den utanför - en
     nyckel i arbetskatalogen blir förr eller senare committad." ;;
      *) ok "nyckeln ligger utanför repot" ;;
    esac
    # Innehållet kontrolleras men skrivs aldrig ut.
    if head -1 "$NYCKEL" | grep -q "BEGIN PRIVATE KEY"; then
      ok "nyckeln ser ut som en PKCS#8-nyckel"
    else
      nej "nyckeln börjar inte med PEM-huvudet för en privat nyckel - är det rätt fil?"
    fi
  fi
fi

# Ett rent träd. Ett arkiv byggt ur ocommitterade ändringar går inte att
# hitta tillbaka till när någon frågar vad som ligger i TestFlight.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  printf '  \033[33m!\033[0m arbetsträdet har ocommitterade ändringar - bygget går att göra,\n'
  printf '    men det går inte att härleda ur en commit\n'
else
  ok "rent arbetsträd ($(git rev-parse --short HEAD 2>/dev/null))"
fi

PBX="ios/App/App.xcodeproj/project.pbxproj"
[ -f "$PBX" ] && ok "iOS-projektet finns" || nej "$PBX saknas - kör npx cap add ios"

if [ "$FEL" -gt 0 ]; then
  printf '\n\033[31m%d kontroll(er) föll. Inget byggdes.\033[0m\n' "$FEL"
  exit 1
fi
[ "$CHECKS_ONLY" -eq 1 ] && { printf '\nAlla kontroller gröna.\n'; exit 0; }

# ------------------------------------------------------------------- version
if [ -n "$VERSION" ] || [ -n "$BUILD_NR" ]; then
  rubrik "Version"
  [ -n "$VERSION" ]  && sed -i '' "s/MARKETING_VERSION = [^;]*;/MARKETING_VERSION = $VERSION;/g" "$PBX" && ok "MARKETING_VERSION = $VERSION"
  [ -n "$BUILD_NR" ] && sed -i '' "s/CURRENT_PROJECT_VERSION = [^;]*;/CURRENT_PROJECT_VERSION = $BUILD_NR;/g" "$PBX" && ok "CURRENT_PROJECT_VERSION = $BUILD_NR"
fi

# --------------------------------------------------------------------- bygge
rubrik "Bygge"
npm run build:native >/dev/null 2>&1 && ok "webbundlet byggt (dist/native)" || { nej "npm run build:native föll"; exit 1; }

# cap sync är det ENDA som skriver config.xml och capacitor.config.json in i
# ios/App/App/. En filkopia till public/ räcker inte - det var det som fällde
# det första arkivförsöket med exit 65.
npx cap sync ios >/dev/null 2>&1 && ok "cap sync ios" || { nej "npx cap sync ios föll"; exit 1; }

for f in ios/App/App/config.xml ios/App/App/capacitor.config.json; do
  [ -f "$f" ] && ok "$(basename "$f") på plats" || { nej "$f saknas efter cap sync"; exit 1; }
done

# Kontrollrummet ska inte vara med (N0d).
for f in admin.html admin.js; do
  [ -e "ios/App/App/public/$f" ] && nej "$f ligger i appbundlet - se N0d" || ok "$f inte med"
done

# ------------------------------------------------------------------- arkivet
rubrik "Arkivering"
ARKIV="$ROOT/build/Matjakt.xcarchive"
rm -rf "$ARKIV"
xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release \
  -destination 'generic/platform=iOS' -archivePath "$ARKIV" archive \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$NYCKEL" \
  -authenticationKeyID "$ASC_KEY_ID" \
  -authenticationKeyIssuerID "$ASC_ISSUER_ID" \
  >build/arkiv.log 2>&1
if [ $? -ne 0 ]; then
  nej "arkiveringen föll - build/arkiv.log:"
  grep -E "error:|Signing for" build/arkiv.log | head -10
  exit 1
fi
ok "ARCHIVE SUCCEEDED"

PLIST="$ARKIV/Products/Applications/App.app/Info.plist"
for nyckel in CFBundleIdentifier CFBundleShortVersionString CFBundleVersion; do
  printf '     %-30s %s\n' "$nyckel" "$(/usr/libexec/PlistBuddy -c "Print :$nyckel" "$PLIST" 2>/dev/null)"
done

# ------------------------------------------------------------------- export
rubrik "Export$([ "$UPLOAD" -eq 1 ] && echo ' och uppladdning')"
UT="$ROOT/build/export"
rm -rf "$UT"
OPT="$ROOT/ios/ExportOptions.plist"
# Team-ID och lokal export skrivs in i en KOPIA - den spårade filen ska
# se likadan ut efter körningen som före.
if [ "$UPLOAD" -eq 0 ] || [ -n "${ASC_TEAM_ID:-}" ]; then
  OPT="$ROOT/build/ExportOptions-kord.plist"
  cp "$ROOT/ios/ExportOptions.plist" "$OPT"
  if [ "$UPLOAD" -eq 0 ]; then
    sed -i '' 's|<string>upload</string>|<string>export</string>|' "$OPT"
  fi
  if [ -n "${ASC_TEAM_ID:-}" ]; then
    # Behövs bara när Apple-ID:t hör till mer än ett team; annars härleder
    # xcodebuild teamet ur API-nyckeln.
    /usr/libexec/PlistBuddy -c "Add :teamID string $ASC_TEAM_ID" "$OPT" >/dev/null 2>&1 \
      || /usr/libexec/PlistBuddy -c "Set :teamID $ASC_TEAM_ID" "$OPT" >/dev/null
    ok "teamID = $ASC_TEAM_ID"
  fi
fi

xcodebuild -exportArchive -archivePath "$ARKIV" \
  -exportOptionsPlist "$OPT" -exportPath "$UT" \
  -allowProvisioningUpdates \
  -authenticationKeyPath "$NYCKEL" \
  -authenticationKeyID "$ASC_KEY_ID" \
  -authenticationKeyIssuerID "$ASC_ISSUER_ID" \
  >build/export.log 2>&1
if [ $? -ne 0 ]; then
  nej "exporten föll - build/export.log:"
  grep -E "error:|Error Domain" build/export.log | head -10
  exit 1
fi

if [ "$UPLOAD" -eq 1 ]; then
  ok "uppladdad till App Store Connect"
  printf '\n  Bygget dyker upp i TestFlight om 5-30 minuter, efter Apples\n'
  printf '  automatiska bearbetning. Intern testning kräver ingen App Review.\n'
else
  ok "exporterad: $(ls "$UT"/*.ipa 2>/dev/null | head -1)"
fi
