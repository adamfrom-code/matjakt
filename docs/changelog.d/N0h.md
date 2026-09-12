### Granskningskontot kan inte committas ifyllt

Hemlighetsskanningen kontrollerar nu butiksmetadatan under `store/`: står det
`Lösenord:` och något som inte är en platshållare efter, är raden ifylld och
bygget faller.

Bakgrunden är konkret. Ett riktigt lösenord låg i arbetsträdets
`review_notes.txt`, ocommitterat men en `git add -A` från att bli publicerat
för alltid i ett publikt repo. Skanningen sa "inga hemligheter" — och hade
rätt enligt sina mönster: ett lösenord ser ut som vilket ord som helst.
Därför är den här kontrollen inte ett mönster utan en **plats**.

Kontot hör hemma i App Store Connects egna fält för App Review Information.
