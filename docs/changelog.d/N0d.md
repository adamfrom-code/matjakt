### Kontrollrummet följer inte med in i appen

`admin.html` och `admin.js` byggs inte längre in i native-bundlet. De ligger
kvar i webbygget, där de hör hemma - kontrollrummet serveras från samma
origin som API:t och skyddas av admin-tokengrinden.

Upptäckt när det första iOS-arkivet inspekterades: `App.app/public/`
innehöll en driftsinloggning. Ingen säkerhetslucka, grinden ligger på
servern, men sidan hör inte hemma i en app som laddas ner från App Store.
