// K1 — LINT SOM FAILAR PÅ FEL, INTE PÅ FORMATERING.
//
// ESLint har aldrig körts i det här repot. Den första körningen med
// standardreglerna gav hundratals träffar, och nästan alla handlade om hur
// koden SER UT. En lint som failar på åttahundra ställen dag ett stängs av
// dag två, och då fångas inte heller de fem som var riktiga buggar.
//
// Reglerna nedan är därför uppräknade en och en. Varje rad är ett fel som
// gör att programmet gör något annat än författaren skrev - aldrig en åsikt
// om semikolon, citattecken, indrag eller radlängd. Det som INTE står här
// står inte här med avsikt; skälen finns i PR:en för K1.
//
// `tests/app-imports.test.js` skrevs en gång för att fånga en klass av fel
// som `no-undef` fångar gratis. Testet står kvar - det prövar bundlets
// verkliga moduler och inte bara källfilerna - men nu finns grinden före det.

const BROWSER = {
  window: "readonly", document: "readonly", navigator: "readonly", console: "readonly",
  localStorage: "readonly", sessionStorage: "readonly", indexedDB: "readonly",
  fetch: "readonly", Headers: "readonly", Request: "readonly", Response: "readonly",
  setTimeout: "readonly", clearTimeout: "readonly", setInterval: "readonly",
  clearInterval: "readonly", queueMicrotask: "readonly", requestAnimationFrame: "readonly",
  cancelAnimationFrame: "readonly", location: "readonly", history: "readonly",
  alert: "readonly", confirm: "readonly", prompt: "readonly",
  URL: "readonly", URLSearchParams: "readonly", Intl: "readonly",
  CustomEvent: "readonly", Event: "readonly", EventTarget: "readonly",
  FormData: "readonly", Blob: "readonly", File: "readonly", FileReader: "readonly",
  AbortController: "readonly", AbortSignal: "readonly", performance: "readonly",
  matchMedia: "readonly", getComputedStyle: "readonly", crypto: "readonly",
  Image: "readonly", Audio: "readonly", DOMParser: "readonly", XMLHttpRequest: "readonly",
  TextEncoder: "readonly", TextDecoder: "readonly", atob: "readonly", btoa: "readonly",
  structuredClone: "readonly", globalThis: "readonly",
  IntersectionObserver: "readonly", MutationObserver: "readonly", ResizeObserver: "readonly",
  HTMLElement: "readonly", Element: "readonly", Node: "readonly", NodeList: "readonly",
  CSS: "readonly", Notification: "readonly", ServiceWorkerRegistration: "readonly",
  DOMException: "readonly", ErrorEvent: "readonly", PromiseRejectionEvent: "readonly",
  screen: "readonly", visualViewport: "readonly", scrollTo: "readonly",
  getSelection: "readonly", ClipboardItem: "readonly",
};

const SERVICE_WORKER = {
  self: "readonly", caches: "readonly", clients: "readonly",
  skipWaiting: "readonly", registration: "readonly",
  ExtendableEvent: "readonly", FetchEvent: "readonly",
};

const NODE = {
  process: "readonly", console: "readonly", Buffer: "readonly",
  __dirname: "readonly", __filename: "readonly", module: "writable",
  require: "readonly", exports: "writable", globalThis: "readonly",
  setTimeout: "readonly", clearTimeout: "readonly", setInterval: "readonly",
  clearInterval: "readonly", queueMicrotask: "readonly",
  URL: "readonly", URLSearchParams: "readonly", TextEncoder: "readonly",
  TextDecoder: "readonly", structuredClone: "readonly", fetch: "readonly",
  AbortController: "readonly", performance: "readonly", crypto: "readonly",
};

// Fel som gör att koden gör något annat än det som står skrivet.
const FEL = {
  // Den viktigaste. Ett felstavat namn, en borttagen import, en funktion som
  // bytt modul - allt blir ett ReferenceError först när användaren trycker
  // på knappen. Det är exakt den klass av fel tests/app-imports.test.js
  // skrevs för att fånga.
  "no-undef": "error",

  // Två nycklar med samma namn i ett objektliteral: den ena försvinner tyst.
  // Samma fel finns i backend (ruffs F601) och hade där tappat tolv
  // receptbilder och en buljongpost utan ett ljud.
  "no-dupe-keys": "error",
  "no-dupe-args": "error",
  "no-dupe-class-members": "error",
  "no-dupe-else-if": "error",
  "no-duplicate-case": "error",

  // Kod efter return/throw körs aldrig. Antingen är den onödig eller så är
  // den viktig och ligger på fel rad.
  "no-unreachable": "error",
  "no-unsafe-finally": "error",

  // Tilldelningar som inte gör det de ser ut att göra.
  "no-const-assign": "error",
  "no-class-assign": "error",
  "no-func-assign": "error",
  "no-import-assign": "error",
  "no-setter-return": "error",
  "no-self-assign": "error",
  "no-ex-assign": "error",
  "no-this-before-super": "error",
  "no-redeclare": "error",
  "no-shadow-restricted-names": "error",

  // Jämförelser som alltid ger samma svar.
  "no-self-compare": "error",
  "no-constant-condition": ["error", { checkLoops: false }],
  "no-constant-binary-expression": "error",
  "use-isnan": "error",
  "valid-typeof": ["error", { requireStringLiterals: true }],
  "no-unsafe-negation": "error",
  "no-unsafe-optional-chaining": "error",

  // `if (x = 1)` när man menade `==`. Klassiker.
  //
  // "except-parens", inte "always". Skillnaden är hela skillnaden mellan en
  // grind folk läser och en de stänger av: `for (let m; (m = re.exec(s)); )`
  // är den etablerade formen för att gå igenom varje träff i ett globalt
  // reguljärt uttryck, och de extra parenteserna ÄR författarens sätt att
  // säga "jag menade tilldelning". "always" fäller den formen - den finns i
  // tests/ikvall-forst.test.js:35 just nu - och en regel som är röd på
  // idiomet lär folk att ignorera rött. "except-parens" fångar fortfarande
  // det som faktiskt är felet: `if (x = 1)` utan parenteser.
  "no-cond-assign": ["error", "except-parens"],

  // Reguljära uttryck som inte gör det de ser ut att göra. no-control-regex
  // är inte en formalitet: i backend hittade ruff sex LITERALA
  // backsteg-tecken där någon menat \b, vilket tyst avväpnade fem av
  // hemlighetsskannerns mönster.
  "no-invalid-regexp": "error",
  "no-control-regex": "error",
  "no-misleading-character-class": "error",
  "no-useless-backreference": "error",
  "no-empty-character-class": "error",

  // Fällor i asynkron kod.
  "no-async-promise-executor": "error",
  // no-promise-executor-return är AV: den fäller `new Promise(r =>
  // setTimeout(r, ms))`, som är den vanliga formen för en paus och inte ett
  // fel. En regel som är röd på idiomet lär folk att ignorera rött.
  "no-promise-executor-return": "off",
  "require-atomic-updates": "off", // för många falska träffar för att vara en grind

  // Övrigt som är fel och inte smak.
  "getter-return": "error",
  "no-obj-calls": "error",
  "no-sparse-arrays": "error",
  "no-empty-pattern": "error",
  "no-loss-of-precision": "error",
  "no-new-native-nonconstructor": "error",
  "no-octal": "error",
  "no-delete-var": "error",
  "no-irregular-whitespace": ["error", { skipStrings: false, skipComments: false }],
  "no-fallthrough": "error",
  "no-with": "error",
  "no-debugger": "error",

  // VARNING, inte fel - baslinjen. Tolv träffar i dag, elva av dem i
  // frontend/app/app.js som fem agenter refaktorerar just nu (F-vågen). Död
  // kod är inte fel kod, och en grind som är röd från dag ett på filer man
  // inte får röra blir avstängd. De syns i loggen och i --max-warnings-talet;
  // skärps när F-vågen har landat.
  "no-unused-vars": ["warn", {
    args: "after-used",
    argsIgnorePattern: "^_",
    varsIgnorePattern: "^_",
    caughtErrors: "none",
  }],
};

export default [
  {
    ignores: [
      "node_modules/**", "dist/**", "build/**",
      "backend/venv/**", "backend/data/**",
      "marketing/**", "android/**", "ios/**", "ios-prep/**", "resources/**",
      // Tredjepartskod och byggartefakter som råkar ligga i repot.
      "**/*.min.js",
    ],
  },
  {
    // Appen och webbplatsen: moduler i webbläsaren.
    files: ["frontend/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...BROWSER },
    },
    rules: FEL,
  },
  {
    // Service workern har sina egna globaler och är ingen modul.
    files: ["frontend/app/sw.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "script",
      globals: { ...BROWSER, ...SERVICE_WORKER },
    },
    rules: FEL,
  },
  {
    // Byggskript och tester kör i Node.
    files: ["scripts/**/*.{js,mjs}", "tests/**/*.{js,mjs}", "*.{js,mjs}"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...NODE },
    },
    rules: FEL,
  },
];
