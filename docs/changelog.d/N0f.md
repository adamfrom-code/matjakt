### Signeringsnycklarna kan inte committas av misstag

`.gitignore` håller ute `*.p8`, `AuthKey_*`, `*.mobileprovision`, `*.p12`
och `*.cer`. Ett test kontrollerar att mönstren står kvar, att git faktiskt
biter på dem, och att ingen sådan fil redan är spårad.

`ExportOptions.plist` står medvetet inte på listan: team-ID syns i varje
utgiven .ipa och filen ska gå att klona med.
