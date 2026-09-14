---
paket: K3d
titel: Ett deployjobb som inte deployar får inte vara grönt
---

Backenden stod stilla i **fjorton timmar** med nio mergade commits bakom
sig. Ingen larmade, för jobbet som heter *"Deploy backend till Render"*
skrev en notis och `exit 0` när `RENDER_DEPLOY_HOOK` saknades — med
motiveringen att *"Renders egen Auto-Deploy gör jobbet i stället"*.

Den motiveringen var falsk. `render.yaml` sa hela tiden motsatsen:
`autoDeploy: false` på båda tjänsterna, med kommentaren att deploy sker
**bara** via hooken och att det måste vara Off i dashboarden också, så att
en blueprint-synk inte slår på det igen.

Två filer som sa emot varandra, och den som ljög var den som körde.

Nu blir bygget rött med en gång, och felmeddelandet säger var hooken hämtas
och varför man **inte** ska slå på Auto-Deploy i stället: hooken pekar ut
exakt SHA med `?ref=`, och det är vad hälsogrinden och rökprovet bygger på.

Testet vaktar sambandet, inte texten. Slår någon på `autoDeploy` faller det
också — med flit, för då måste beslutet tas medvetet.
