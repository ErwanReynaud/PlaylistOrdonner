# PlaylistOrdonner

Application macOS qui réordonne une playlist Spotify **par genre, du moins
énergique au plus énergique**, puis, **à l'intérieur de chaque genre, par BPM
croissant** (du plus lent au plus rapide).

Le second critère ne peut jamais casser le premier : les titres sont triés par
BPM *à l'intérieur* de leur bloc de genre, et les blocs sont ensuite mis bout à
bout du plus calme au plus énergique.

```
=== Ambient / Drone ===         (énergie 6)
   1.   62   Weightless — Marconi Union
   2.   71   An Ending — Brian Eno
=== Pop ===                     (énergie 68)
   3.  102   …
   4.  128   …
=== Métal ===                   (énergie 94)
   5.  118   …
   6.  186   …
```

Aucune dépendance à installer : tout repose sur la bibliothèque standard de
Python 3, déjà présente sur macOS.

---

## 1. Installer l'application

Dans le Terminal, depuis le dossier du projet :

```bash
./build_mac_app.sh
```

Le script fabrique `PlaylistOrdonner.app`, l'installe dans `~/Applications` et
ouvre le Finder dessus. Double-clique dessus, ou glisse-le dans le Dock.

* `./build_mac_app.sh --no-install` : construit seulement dans `./dist`.
* `./build_mac_app.sh --install-dir=/Applications` : installe ailleurs.

L'application n'est pas signée par Apple, mais comme elle est construite
localement sur ta machine, macOS la lance sans avertissement.

Tu peux aussi te passer du bundle et double-cliquer sur
`Lancer-PlaylistOrdonner.command`.

## 2. Autoriser l'accès à ton compte Spotify

Spotify exige que chaque application ait son propre identifiant. C'est gratuit
et l'écran de configuration te guide, mais voici le résumé :

1. Va sur <https://developer.spotify.com/dashboard> et connecte-toi.
2. **Create app** → nom et description libres.
3. Dans **Redirect URIs**, colle exactement :

   ```
   http://127.0.0.1:8888/callback
   ```

4. Coche **Web API**, accepte les conditions, **Save**.
5. Ouvre l'app → **Settings** → copie le **Client ID**.
6. Colle-le dans PlaylistOrdonner. Le *Client Secret* n'est pas nécessaire :
   l'authentification utilise OAuth avec PKCE.

Le navigateur s'ouvre, tu autorises l'accès, et c'est réglé. Le jeton est
stocké dans `~/Library/Application Support/PlaylistOrdonner/`, en lecture seule
pour ton compte utilisateur, et renouvelé automatiquement ensuite.

## 3. Trier

1. Choisis une playlist dans la liste (ou ❤️ *Titres likés*).
2. **1 · Analyser et classer** : l'app lit les titres, récupère les genres et
   les BPM, puis affiche le classement complet dans le journal. Rien n'est
   encore modifié sur Spotify.
3. Vérifie la liste, puis **2 · Enregistrer sur Spotify**.

Deux destinations possibles :

| Destination | Effet |
|---|---|
| **Nouvelle playlist** (par défaut) | crée `Nom (ordonnée)`, l'original n'est pas touché |
| **Réordonner la playlist d'origine** | réécrit la playlist existante dans le nouvel ordre |

> Le mode « en place » remplace le contenu de la playlist. Les titres sont
> identiques, seul l'ordre change, mais les dates d'ajout sont réinitialisées.
> En cas de doute, garde la nouvelle playlist : c'est réversible.

Le bouton **Exporter la liste (.txt)** enregistre le classement sur le disque
sans rien écrire sur Spotify.

---

## Comment l'ordre est décidé

### Le genre

Spotify attache les genres aux **artistes**, pas aux titres. L'app récupère les
genres de chaque artiste et retient le premier qu'elle sait classer.

Chaque genre est rattaché à une **famille** (`playlistordonner/genres.py`) et
reçoit un score d'énergie de 0 à 100 :

| | Famille | Score |
|---|---|---|
| le plus calme | Ambient / Drone | 6 |
| | Classique, Chill, Acoustique, Jazz | 16 – 40 |
| | Soul, Reggae, Variété, Pop, Latino | 42 – 62 |
| | Rock, House, Électro | 64 – 78 |
| | Techno / Trance, Bass / DnB | 78 – 88 |
| le plus énergique | Punk, Métal, Hardcore | 84 – 99 |

La reconnaissance se fait sur le mot-clé le plus à droite du nom, parce que
c'est lui qui porte le sens : *chill **house*** reste de la house (avec une
nuance qui abaisse son score), *pop **punk*** est du punk, *melodic **death
metal*** tombe sur « death metal » plutôt que sur « metal ».

Deux niveaux de regroupement au choix : par **famille** (une vingtaine de blocs
lisibles) ou par **genre Spotify exact** (plus fin, plus de blocs).

L'option *« Affiner l'ordre des genres avec l'énergie mesurée »* mélange ce
score théorique avec l'énergie réellement mesurée par Spotify sur tes titres,
quand cette donnée est disponible — un bloc rock calme passe alors devant un
bloc pop nerveux.

Les titres dont aucun artiste n'a de genre connu finissent dans un bloc
« Genre inconnu », placé en toute fin.

### Le BPM

Deux sources, dans l'ordre :

1. **Spotify** (`/audio-features`), la plus fiable ;
2. **Deezer**, dont l'API publique expose un champ `bpm` : correspondance
   exacte par code ISRC, sinon par recherche titre + artiste.

⚠️ **À savoir** : depuis fin 2024, Spotify a fermé `/audio-features` aux
applications nouvellement créées. Si tu crées ton app Spotify aujourd'hui,
l'endpoint répondra `403` — l'application le détecte, te le dit dans le
journal, et bascule automatiquement sur Deezer. C'est pour cette raison que la
source de secours existe : sans elle, le tri par BPM serait impossible pour une
app récente.

Les BPM trouvés sont mis en cache dans
`~/Library/Application Support/PlaylistOrdonner/cache_bpm.json`, donc le second
tri d'une même playlist est quasi instantané. Si Deezer est injoignable, le tri
aboutit quand même : les titres sans BPM connu sont placés en fin de leur
genre, jamais ailleurs.

### Personnaliser les scores

Si ton classement personnel diffère, crée
`~/Library/Application Support/PlaylistOrdonner/genres_perso.json` :

```json
{
  "deep house": 40,
  "post-rock": 30,
  "drum and bass": 95
}
```

Les clés sont des genres Spotify en minuscules, les valeurs des scores de 0 à
100. Elles prennent le pas sur la table interne.

---

## En ligne de commande

Le même moteur est utilisable sans interface :

```bash
python3 -m playlistordonner config --client-id TON_CLIENT_ID
python3 -m playlistordonner playlists
python3 -m playlistordonner trier 37i9dQ... --apercu       # simulation
python3 -m playlistordonner trier 37i9dQ... --nom "Soirée"
python3 -m playlistordonner trier likes                     # titres likés
python3 -m playlistordonner trier <url> --en-place
python3 -m playlistordonner diagnostic                      # vérifie l'installation
```

Options utiles : `--genres-precis`, `--sans-deezer`, `--sans-affinage`,
`--publique`.

## Dépannage

Premier réflexe, qui répond à la plupart des questions :

```bash
python3 -m playlistordonner diagnostic
```

Cette commande liste les Python installés, dit lesquels savent réellement
ouvrir une fenêtre et avec quelle version de Tk, et teste l'accès réseau à
Spotify et Deezer.

### « Python a quitté de manière imprévue »

C'est la version de **Tk** qui est en cause, pas l'application. Le Python
fourni par Apple (`/usr/bin/python3`) s'appuie sur **Tk 8.5.9**, déprécié, qui
fait tomber le processus au moment d'ouvrir une fenêtre sur les macOS récents.

Le lanceur évite ce piège : il essaie réellement d'ouvrir une fenêtre dans un
sous-processus jetable avant de démarrer l'application, écarte les
interpréteurs qui plantent, et préfère toujours Tk 8.6. Il cherche dans cet
ordre : les versions python.org, Homebrew, Anaconda/Miniconda, puis le `PATH`,
et le Python d'Apple en dernier recours.

S'il ne trouve aucun Tk 8.6, installe l'un des deux :

```bash
brew install python-tk          # avec Homebrew
```

ou le paquet officiel depuis <https://www.python.org/downloads/macos/>, qui
embarque un Tk 8.6 à jour. Puis relance l'application — rien d'autre à faire,
elle le détectera seule.

| Symptôme | Cause et remède |
|---|---|
| L'app ne s'ouvre pas | Regarde `~/Library/Logs/PlaylistOrdonner.log` : il indique quel interpréteur a été retenu, sa version de Tk, et ceux qui ont été écartés. |
| « INVALID_CLIENT: Invalid redirect URI » | L'adresse `http://127.0.0.1:8888/callback` n'est pas enregistrée à l'identique dans ton app Spotify. |
| « Le port 8888 est déjà utilisé » | Un autre programme l'occupe ; ferme-le, puis relance la connexion. |
| Beaucoup de titres sans BPM | Deezer ne connaît pas ces titres, ou l'option Deezer est décochée. Ils sont regroupés en fin de leur genre. |
| Beaucoup de « Genre inconnu » | Les artistes concernés n'ont pas de genre chez Spotify (fréquent pour les artistes peu connus). |
| Playlist non modifiable | Tu ne peux réécrire que tes propres playlists ou les playlists collaboratives. Pour les autres, utilise « nouvelle playlist ». |

## Développement

```bash
python3 -m unittest discover -s tests -v
```

Structure :

| Fichier | Rôle |
|---|---|
| `playlistordonner/genres.py` | table des genres, familles et scores d'énergie |
| `playlistordonner/sorter.py` | modèle de titre et algorithme de tri à deux niveaux |
| `playlistordonner/bpm.py` | résolution des BPM (Deezer) et cache disque |
| `playlistordonner/spotify.py` | client de l'API Web Spotify |
| `playlistordonner/auth.py` | OAuth 2.0 avec PKCE et serveur de retour local |
| `playlistordonner/engine.py` | enchaînement lecture → tri → écriture |
| `playlistordonner/gui.py` | interface Tkinter |
| `playlistordonner/cli.py` | interface en ligne de commande |
| `tools/make_icon.py` | génération de l'icône (PNG écrit à la main) |
| `build_mac_app.sh` | fabrication du bundle `.app` |
