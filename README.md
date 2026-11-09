# E7 Secret Shop Bot

Outil Windows qui **actualise automatiquement la boutique secrète d'Epic Seven** (client PC / Steam) et **s'arrête ou achète** dès qu'un objet recherché apparaît (Signets de la Prophétie, Médailles mystiques…).

- 🔍 Reconnaissance d'image des objets + vérification du **nom écrit** (OCR) pour éviter les fausses détections
- 💎 Lecture de tes **cristaux** et de ton **or** : le bot s'arrête avant de descendre sous le minimum que tu fixes
- 🛒 Deux modes : **s'arrêter** quand un objet apparaît, ou **l'acheter automatiquement** (avec vérification de l'achat)
- 📊 Statistiques : objets trouvés (depuis toujours / depuis l'ouverture), actualisations, cristaux dépensés
- 🖱️ Onglet **Auto click** bonus (F7 / F8)
- 🌙 Interface sombre

> ⚠️ **Avertissement** : l'utilisation de macros/automatisation est contraire aux conditions d'utilisation d'Epic Seven. Tu l'utilises **à tes risques et périls** (risque de sanction sur ton compte). Cet outil est fourni tel quel, sans garantie.

---

## Sommaire

1. [Installation](#1-installation)
2. [Premier lancement et réglages](#2-premier-lancement-et-réglages)
3. [Utilisation](#3-utilisation)
4. [Détail des onglets](#4-détail-des-onglets)
5. [Raccourcis clavier et sécurités](#5-raccourcis-clavier-et-sécurités)
6. [Problèmes fréquents](#6-problèmes-fréquents)
7. [Modifier le code](#7-modifier-le-code)

---

## 1. Installation

### Option A — Version .exe (le plus simple, rien à installer)

1. Va dans l'onglet **Releases** du dépôt GitHub et télécharge **`SecretShopBot.exe`**.
2. Place-le dans un dossier à lui (ex. `Documents\SecretShopBot\`) : tes réglages (`config.json`) et tes captures (`templates\`) seront créés **à côté du .exe**.
3. Double-clique dessus et accepte la demande **administrateur**.

Le .exe contient déjà Python, les bibliothèques et Tesseract : **aucune installation nécessaire**. Il pèse ~140 Mo et met quelques secondes à démarrer (il se décompresse à chaque lancement).

> ⚠️ Windows SmartScreen ou ton antivirus peut afficher un avertissement (programme non signé qui simule des clics et lit le clavier) : clique sur **Informations complémentaires → Exécuter quand même**. Si tu as un doute, utilise l'option B : le code source est lisible.

### Option B — Depuis le code source

### Prérequis

| Logiciel | Pourquoi | Où le trouver |
|---|---|---|
| **Windows 10 / 11** | l'outil utilise des fonctions Windows | — |
| **Python 3.12** | fait tourner le programme | [python.org](https://www.python.org/downloads/) — ⚠️ coche **« Add python.exe to PATH »** pendant l'installation |
| **Tesseract OCR** | lit les nombres (or, cristaux) et les noms d'objets | [Installeur UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) — garde le dossier par défaut `C:\Program Files\Tesseract-OCR` |

Avec `winget` (dans un terminal Windows), tu peux tout installer en deux commandes :

```bash
winget install -e --id Python.Python.3.12
```

```bash
winget install -e --id UB-Mannheim.TesseractOCR
```

### Récupérer l'outil

Télécharge le projet (bouton vert **Code → Download ZIP** sur GitHub) et décompresse-le où tu veux. Le dossier contient :

```
e7_shop_bot.py     le programme
lancer.bat         double-clic pour démarrer
requirements.txt   bibliothèques Python (installées automatiquement)
```

### Lancer

Double-clique sur **`lancer.bat`**.

- Windows demande l'autorisation **administrateur** : accepte (sinon le jeu peut ignorer les clics simulés).
- Au premier lancement, les bibliothèques Python s'installent (quelques secondes à une minute).
- L'interface s'ouvre. Tes réglages seront enregistrés dans `config.json` (créé automatiquement).

---

## 2. Premier lancement et réglages

> 💡 Ouvre le jeu sur la **boutique secrète** avant de commencer. **Ne déplace plus et ne redimensionne plus la fenêtre du jeu** ensuite : les positions sont enregistrées en coordonnées d'écran.

### Étape 1 — Positions de clic (onglet **Positions**)

Pour chaque ligne, clique sur **Définir** : tu as **3 secondes** pour placer ta souris sur le bouton correspondant dans le jeu (l'indicateur en haut affiche le compte à rebours).

| Position | Où placer la souris |
|---|---|
| Bouton « Actualiser » | le bouton **Rafraîchir** de la boutique |
| Confirmer l'actualisation | le bouton **Confirmer** de la popup « Utilisez des Pieraciel pour rafraîchir ? » (ouvre-la d'abord) |
| Défilement : départ | un point **en bas** de la liste d'objets |
| Défilement : arrivée | un point **en haut** de la liste d'objets (le bot glisse de « départ » vers « arrivée » pour voir les 2 derniers objets) |
| Confirmer l'achat (popup) | le bouton **Confirmer** de la popup d'achat (utile seulement en mode achat auto) |

Le bouton **Voir** déplace la souris sur la position enregistrée pour vérifier.

### Étape 2 — Objets à chercher (onglet **Objets**)

1. Fais apparaître l'objet voulu dans la boutique (ou utilise une capture d'écran que tu as déjà).
2. Clique sur **＋ Capturer** : l'écran se fige, **trace un cadre autour de la ligne de l'objet** (icône + nom, tu peux inclure le prix et le bouton « Acheter »).
3. Donne-lui un nom **proche de celui écrit dans le jeu** (ex. `Signet de la prophétie`, `Médailles mystiques`) : ce nom sert à vérifier la détection.
4. Clique sur **Tester la détection à l'écran** : les objets reconnus sont encadrés en vert.

Tu peux aussi **Importer** une image existante.

### Étape 3 — Or et cristaux (onglet **Ressources**)

1. Clique sur **Sélectionner** à côté de « Or » et **trace un cadre autour du nombre** dans la barre du haut du jeu, **sans l'icône ni le bouton +**. Laisse un peu de marge à droite si le nombre peut gagner un chiffre.
2. La valeur lue s'affiche aussitôt : vérifie qu'elle correspond au jeu. Sinon, recommence.
3. Fais pareil pour les **Cristaux**.
4. Indique le **minimum à garder** : le bot s'arrête s'il passe en dessous.

### Étape 4 — (Achat auto uniquement) Point « Acheter »

Dans **Réglages**, choisis **Acheter automatiquement**, puis dans **Objets** : sélectionne un objet → **Point « Acheter »…** (ou double-clic sur sa ligne) → clique sur le bouton « Acheter » dans la capture → **Valider**. La colonne **ACHAT** affiche ✔.

Le point est relatif à l'objet : il suit l'objet quelle que soit la ligne où il apparaît.

---

## 3. Utilisation

1. Ouvre la boutique secrète dans le jeu (liste en haut).
2. Clique sur **▶ Démarrer** ou appuie sur **F9**.
3. À chaque tour, le bot :
   1. lit ton or et tes cristaux (et s'arrête s'ils passent sous le minimum) ;
   2. cherche les objets dans le haut de la liste ;
   3. fait défiler et cherche dans le bas ;
   4. actualise la boutique (et vérifie que l'actualisation a bien eu lieu).
4. Quand un objet est trouvé :
   - **mode « S'arrêter »** : bip sonore, la fenêtre passe au premier plan, à toi d'acheter ;
   - **mode « Acheter automatiquement »** : le bot achète, **vérifie que l'achat est passé** (l'or a baissé ou le bouton a changé), réessaie jusqu'à 3 fois si besoin, et continue. Si l'achat n'est pas confirmé, il **s'arrête sans actualiser** pour ne pas perdre l'objet.
5. Arrête à tout moment avec **■ Arrêter** ou **F10**.

Les cartes en haut affichent les actualisations, la cadence, les cristaux dépensés et tes ressources. Le **Journal** à droite détaille tout ce que fait le bot (en or : objet trouvé / acheté, en orange : avertissement, en rouge : erreur).

---

## 4. Détail des onglets

### Objets

| Élément | Rôle |
|---|---|
| Pastille **ON / OFF** | clic = activer / désactiver la recherche de cet objet |
| **ACHAT** | ✔ si le point « Acheter » est défini |
| **TOTAL** / **SESSION** | nombre de fois trouvé depuis toujours / depuis l'ouverture de l'appli |
| ＋ Capturer / Importer | ajouter un objet |
| Point « Acheter »… | placer le clic d'achat dans la capture (double-clic sur la ligne = pareil) |
| Renommer | changer le nom (doit ressembler au nom écrit dans le jeu) |
| Supprimer | retirer l'objet |
| Tester la détection à l'écran | montre ce que le bot reconnaît en ce moment |
| Remettre le total à zéro | réinitialise les compteurs « Total » |

### Positions

Les 5 positions de clic (voir [Étape 1](#étape-1--positions-de-clic-onglet-positions)) et le **Mode arrière-plan** (expérimental) : le bot lit la fenêtre du jeu et lui envoie ses clics directement, **sans prendre ta souris**. Le jeu peut être derrière d'autres fenêtres mais **pas réduit**. Clique d'abord sur **Tester l'arrière-plan** (bot arrêté, boutique ouverte) : il envoie un clic sur « Actualiser » (ça ouvre juste la confirmation, rien n'est dépensé) et affiche l'image avant / après. Si la confirmation apparaît, coche **Activer**.

### Ressources

Zone du nombre d'**Or** et de **Cristaux**, minimum à garder, case pour activer/désactiver la surveillance, bouton **Tester**.

### Réglages

| Réglage | Par défaut | Conseil |
|---|---|---|
| Seuil de ressemblance | 0.85 | plus haut = plus strict. Avec la vérification du nom, tu peux le monter (0.9–0.95) sans rater d'objets bien visibles |
| Délai après un clic | 0.5 s | |
| Délai après actualisation | 1.2 s | trop court = le bot scanne avant que la boutique soit affichée → objets ratés. ~0.8 s minimum conseillé |
| Délai après défilement | 0.8 s | la liste glisse encore un peu après le défilement. ~0.5 s minimum conseillé |
| Délai après achat | 1.2 s | |
| Actualisations max | 0 | 0 = illimité |
| Scans par page | 2 | si rien n'est vu, le bot rescanne (utile pendant l'animation d'apparition) |
| Délai entre deux scans | 0.25 s | |
| Remonter la liste avant le premier scan | non | à cocher seulement si la liste ne revient pas en haut toute seule après une actualisation |
| Vérifier le nom écrit (OCR) | oui | évite de confondre deux objets qui se ressemblent. Décoche pour revenir à l'image seule |
| Quand un objet apparaît | S'arrêter | ou Acheter automatiquement |
| Décalage « Acheter » (secours) | — | ancienne méthode, utilisée seulement pour un objet sans point « Acheter » |
| Chemin tesseract.exe | vide = auto | à remplir si Tesseract est installé ailleurs |

### Auto click

Clique en boucle **là où se trouve ta souris**. **F7** = démarrer, **F8** = arrêter. Délai entre les clics en millisecondes (boutons rapides 10 ms → 1000 ms), bouton gauche ou droit. Le bouton « Démarrer » laisse 3 s pour placer la souris ; F7 démarre immédiatement. L'auto click et le bot ne peuvent pas tourner en même temps.

---

## 5. Raccourcis clavier et sécurités

| Touche | Action |
|---|---|
| **F9** | démarrer le bot |
| **F10** | arrêter le bot |
| **F7** | démarrer l'auto click |
| **F8** | arrêter l'auto click |
| Souris dans le **coin haut-gauche** de l'écran | **arrêt d'urgence** (bot et auto click) |

Sécurités intégrées :
- arrêt si l'or ou les cristaux passent sous ton minimum ;
- arrêt si l'or / les cristaux ne peuvent pas être lus 3 fois de suite ;
- un objet n'est compté et acheté qu'**une fois par boutique** ;
- un objet déjà acheté n'est **jamais racheté** tant que la boutique n'a pas été réellement actualisée ;
- arrêt si l'actualisation ne passe pas 3 fois de suite.

---

## 6. Problèmes fréquents

**Le bot ne clique pas dans le jeu**
→ Lance `lancer.bat` en acceptant le mode administrateur. Vérifie les positions avec le bouton **Voir**.

**« Tesseract introuvable »**
→ Installe Tesseract (voir [Prérequis](#prérequis)) ou indique le chemin de `tesseract.exe` dans **Réglages**.

**La valeur de l'or / des cristaux est fausse**
→ Resélectionne la zone en encadrant **uniquement le nombre** (sans icône ni « + »). Utilise **Tester** pour vérifier.

**Un objet visible n'est pas détecté**
→ Clique sur **Tester la détection à l'écran** et regarde le score dans le journal. Augmente le **Délai après actualisation** / **après défilement**, ou mets **3 scans par page**. Si le journal affiche « Presque détecté », baisse un peu le seuil. Si l'objet a été recapturé dans une autre résolution, recapture-le.

**Le journal affiche « Écarté : … le nom lu est … »**
→ C'est la vérification du nom qui a évité une fausse détection. Si c'était bien ton objet, vérifie que son nom dans l'onglet Objets ressemble à celui du jeu (bouton **Renommer**).

**Tout est décalé**
→ La fenêtre du jeu a bougé ou changé de taille : redéfinis les positions, les zones et recapture les objets.

**Je veux partager l'outil**
→ Envoie simplement **`SecretShopBot.exe`** (seul, sans ton `config.json` qui contient tes positions et statistiques). La personne fait ensuite ses propres réglages.

**L'antivirus bloque le .exe**
→ Faux positif fréquent pour les outils d'automatisation non signés. Autorise-le, ou utilise la version code source (option B).

---

## 7. Modifier le code

Le programme est un seul fichier Python : **`e7_shop_bot.py`**. Pas besoin de compiler : modifie-le avec un éditeur (VS Code, Notepad++…), enregistre, puis relance `lancer.bat`.

Organisation du fichier :

| Partie | Contenu |
|---|---|
| `DEFAULT_CONFIG` | valeurs par défaut des réglages |
| *vision* | capture d'écran, reconnaissance d'image, OCR des nombres et des noms |
| *arrière-plan* | capture de la fenêtre du jeu et clics envoyés sans la souris |
| `AutoClicker` | l'auto click |
| `Bot` | la boucle : lecture des ressources, scan, achat vérifié, actualisation |
| `apply_theme` | couleurs et style de l'interface |
| `App` | l'interface (onglets, boutons, journal, statistiques) |
| `selftest` | autotest utilisé pour vérifier le .exe |

Autres fichiers : `build.bat` (fabrique le .exe), `outils\preparer_tesseract.py` (extrait le strict nécessaire de Tesseract), `icone.ico` (icône de l'appli et du .exe).

### Fabriquer le .exe

Après une modification, double-clique sur **`build.bat`** (il faut Python 3.12 et Tesseract installés sur **ta** machine). Il :

1. installe PyInstaller et les bibliothèques ;
2. copie le strict nécessaire de Tesseract (`outils\preparer_tesseract.py`) ;
3. fabrique **`dist\SecretShopBot.exe`** (1 à 3 minutes), avec l'icône `icone.ico` — remplace ce fichier par ta propre icône si tu veux.

Pour vérifier un .exe sans l'interface : `SecretShopBot.exe --selftest` écrit un rapport `selftest.txt` à côté (Tesseract trouvé, lecture d'un nombre et d'un nom, capture d'écran).

Pour publier : onglet **Releases** du dépôt → **Draft a new release** → glisse `SecretShopBot.exe` dans les fichiers joints (ne le mets pas dans le dépôt lui-même).

Fichiers créés à l'utilisation (à ne pas publier, déjà dans `.gitignore`) : `config.json` (tes réglages), `templates/` (tes captures d'objets, propres à ta résolution et ta langue) et `versions/` (tes sauvegardes).
