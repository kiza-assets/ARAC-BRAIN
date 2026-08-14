# =============================================================================
# ARAC — les gestes courants
#
#     make help        la liste, commentée
#     make test        la suite hermétique — le gate de tous les jours
#     make acceptance  le critère de réussite du framework, rendu exécutable
#
# CONVENTION : rien ici n'écrit dans la mémoire de production, et rien ne
# dépense un centime sans qu'on l'ait explicitement demandé. Une cible qui
# coûterait de l'argent à l'insu de qui la tape n'appartient pas à un
# Makefile — elle demande une décision, pas une frappe.
#
# `acceptance` est la seule cible qui écrive sur disque : elle installe un
# cerveau d'essai, complet, sur un cluster PostgreSQL et des ports qui lui
# sont propres, puis démonte tout. Elle ne touche jamais une installation
# vivante, et ce n'est pas une promesse : c'est une garde qui refuse de
# démarrer, elle-même testée par `make test`.
# =============================================================================

# L'interpréteur de l'installation. Redéfinissable : `make test PY=python3`.
PY ?= .venv/bin/python
PYTEST ?= $(PY) -m pytest

.PHONY: help venv test test-fast _exige-venv lint scopes doctor env-audit schema-audit acceptance acceptance-complet clean

help:
	@echo "ARAC — cibles disponibles :"
	@echo ""
	@echo "  make venv       cree .venv et installe les dependances"
	@echo "  make test       la suite complete, HERMETIQUE (ni base, ni reseau)"
	@echo "  make test-fast  idem, s'arrete au premier echec"
	@echo "  make lint       le shell d'installation : syntaxe + pieges + angle mort"
	@echo "  make scopes     regenere l'enumeration + le seed depuis config/scopes.toml"
	@echo "  make doctor     verifie que l'installation peut demarrer"
	@echo "  make env-audit  compare .env.example au code (variables fantomes)"
	@echo "  make schema-audit  croise les references arac.<objet> et le schema bati"
	@echo "  make clean      supprime les caches Python"
	@echo ""
	@echo "Rien ci-dessus n'ecrit en base ni n'appelle un service payant."
	@echo ""
	@echo "  make acceptance  INSTALLE REELLEMENT un cerveau et rend un verdict"
	@echo "                   sur les sept etapes. Exige root. Ecrit sur disque."
	@echo "                   Ne touche NI la base 5432, NI les ports 8000/8100."
	@echo "                   Demonte tout a la fin, meme en cas d'echec."

# -----------------------------------------------------------------------------
venv:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt
	@echo ""
	@echo "Environnement pret. Etape suivante : python3 bootstrap/wizard.py"

# -----------------------------------------------------------------------------
# LA SUITE EST HERMÉTIQUE, ET CE N'EST PLUS UNE PROMESSE : C'EST UNE GARDE.
#
# Aucune base, aucun réseau, aucune clef d'API. Les tests qui exigeraient une
# base se DÉCLARENT ignorés plutôt que d'échouer : un test rouge doit vouloir
# dire « le code est cassé », jamais « PostgreSQL n'est pas lancé ».
#
# Cette phrase était FAUSSE, et elle l'a été dans cinq documents à la fois.
# `make test` émettait de vrais GET HTTP vers http://127.0.0.1:8000 — sur la
# machine de qui lance la suite, son API de PRODUCTION — et exécutait pour de
# vrai `systemctl is-active`, `journalctl --since -7 days`, `ss -ltn`. Le garde
# F1, qui rend les pages du cockpit et y cherche des traces de l'auteur, y
# trouvait les scopes PRIVÉS du cerveau réel : quatre tests rouges dont la
# cause n'était pas dans le code.
#
# Trois gardes, posés dans `tests/garde_hermetique.py` avant le premier test,
# la rendent hermétique pour de bon :
#   - aucune socket TCP ne sort du processus, loopback COMPRIS. « Local » ne
#     veut pas dire « à moi » : le cerveau de quelqu'un vit sur 127.0.0.1 ;
#   - aucune commande n'interroge la MACHINE — et ce garde-là n'énumère plus ce
#     qu'il interdit, parce qu'une liste d'interdits oublie par construction :
#     celle d'avant ignorait `sudo`, donc laissait passer
#     `sudo -n -u postgres psql -d arac -c 'ALTER TABLE …'`, du DDL sur un
#     cerveau de PRODUCTION, lancé par tests/test_recall_fresh.py à chaque
#     `make test`. Le garde énumère désormais ce qui est LÉGITIME (git, bash,
#     python, et des outils qui lisent des fichiers) et refuse tout le reste.
#     La permission SUIT les descendants : un répertoire de refus est en tête
#     du PATH de tout sous-processus, à n'importe quelle profondeur, et un
#     `sitecustomize` repose les gardes dans tout `python` fils. C'est par là
#     que la suite atteignait vraiment la machine — mesuré : le cluster 5432,
#     l'inventaire des unités du voisin, les ports 8000/8100 ;
#   - aucune connexion ne s'ouvre sur une base qui ne porte pas la MARQUE de
#     base de test. Le garde d'avant ne refusait qu'un NOM — `arac`, le cerveau
#     de l'auteur — et laissait donc passer `camille_brain`, `nadia_brain`, le
#     cerveau de tout autre utilisateur, sur lequel la suite jouait une vraie
#     migration 0006 UP/DOWN et un UPDATE visant les lignes NON-test.
#
# Ce que les gardes arrêtent est IMPRIMÉ en fin de session : une suite
# hermétique en silence n'apprend rien à personne.
#
# Elle tourne donc sur un dépôt fraîchement cloné, avant toute installation.
# C'est ce qui permet de vérifier une modification sans rien déployer. Preuve
# reproductible, sans PostgreSQL, sans réseau et sans clef :
#     unshare -n -- bash -c 'ip link set lo up; make test'
#
# NOTE : ne sourcez PAS `.env` avant de lancer les tests. Les drapeaux de
# comportement armés en production feraient rougir le gate sans qu'une ligne
# de code ait changé — la suite les neutralise, mais autant ne pas les poser.
# -----------------------------------------------------------------------------
test: _exige-venv
	$(PYTEST) tests/ -q

test-fast: _exige-venv
	$(PYTEST) tests/ -q -x

# Sur un dépôt fraîchement cloné, `.venv` n'existe pas encore. Sans ce
# contrôle, `make test` répond « /bin/sh: .venv/bin/python: not found », code 127
# — un rouge qui dit « l'environnement est absent » là où le README promet une
# ligne verte. On le dit en clair, avec le geste qui répare.
#
# LA GARDE REFUSAIT CE QU'ELLE RECOMMANDAIT, ET C'EST MESURÉ.
#
# Elle testait `test -x "$(PY)"`. Avec le défaut — `.venv/bin/python`, un
# chemin RELATIF qui existe — cela marche. Avec l'alternative qu'elle
# proposait elle-même deux lignes plus bas, `PY=python3`, `test -x python3`
# cherche un fichier nommé `python3` dans le répertoire courant : il n'y en a
# pas, et la garde refusait :
#
#     $ make test PY=python3
#     L'environnement Python n'existe pas encore : python3 est introuvable.
#     […] (Ou lancez la suite avec votre interpréteur : make test PY=python3)
#
# Le même message annonçait le geste et le rendait impossible. La cible était
# annoncée deux fois — ici et en tête de fichier — comme l'alternative à
# `.venv`, et elle n'a jamais pu fonctionner. C'est la pire forme de fausseté
# d'un outil : celle qui accuse l'utilisateur de ne pas savoir taper la
# commande qu'on vient de lui donner.
#
# `command -v` répond à la vraie question — « cet interpréteur est-il
# exécutable, par un chemin OU par le PATH ? » — et couvre les deux formes.
_exige-venv:
	@command -v "$(PY)" >/dev/null 2>&1 || test -x "$(PY)" || { \
	  echo "L'environnement Python n'existe pas encore : $(PY) est introuvable."; \
	  echo "C'est normal sur un dépôt fraîchement cloné. Le geste :"; \
	  echo ""; \
	  echo "    make venv"; \
	  echo ""; \
	  echo "Puis relancez. (Ou lancez la suite avec votre interpréteur :"; \
	  echo " make test PY=python3 — il lui faut pytest, httpx, fastapi.)"; \
	  exit 1; }

# -----------------------------------------------------------------------------
# LE SHELL D'INSTALLATION — ET SON ANGLE MORT.
#
# `lint` etait declaree .PHONY sans qu'aucune regle n'existe : `make lint`
# repondait « Nothing to be done », c'est-a-dire un succes. Une cible qui ne
# fait rien et n'echoue jamais est pire qu'une cible absente — on croit
# l'avoir lancee.
#
# Les trois controles, dans l'ordre de ce qu'ils voient :
#   1. bash -n     la syntaxe telle que bash la lit au CHARGEMENT ;
#   2. shellcheck  les pieges connus ;
#   3. le troisieme, qui existe parce que les deux premiers sont AVEUGLES a
#      une classe entiere : un document en ligne ouvert DANS une substitution
#      `$( … )` avec un operateur derriere le delimiteur. Bash ne relit le
#      corps d'une substitution qu'au moment de l'EXECUTER ; l'etape 6 du
#      bootstrap est morte ainsi, avec bash -n et shellcheck au vert.
#
# Ni base, ni reseau : il lit des fichiers.
# -----------------------------------------------------------------------------
lint:
	@./ops/lint_shell.sh

# -----------------------------------------------------------------------------
# Régénère l'énumération Python et le seed SQL depuis VOTRE taxonomie.
# À relancer après toute modification de config/scopes.toml.
# Refuse de retirer un scope qui contient encore des atomes vivants.
# -----------------------------------------------------------------------------
scopes:
	$(PY) bootstrap/generate_scopes.py

# -----------------------------------------------------------------------------
# Le minimum vital : est-ce que ce dépôt peut devenir un cerveau ?
# Aucune connexion, aucun appel : on vérifie que les pièces sont là.
# -----------------------------------------------------------------------------
doctor:
	@$(PY) -c "import arac_runtime as r; print('racine        :', r.home())"
	@$(PY) -c "import arac_runtime as r; \
	          print('identite      :', r.node_id())" \
	  || echo "identite      : ABSENTE — lancez : python3 bootstrap/wizard.py"
	@$(PY) -c "from app.schemas.scope import ROOTS, LEAVES; \
	          print(f'taxonomie     : {len(ROOTS)} racines, {len(LEAVES)} feuilles')" \
	  || echo "taxonomie     : ABSENTE — lancez : make scopes"
	@$(PY) -c "from control_center.cc_v1.projects import load_projects as p; \
	          n=len(p()); \
	          print('projets       :', n if n else 'aucun (config/projects.toml absent — le cockpit le dira)')"
	@$(PY) -c "from app import constitution as c; \
	          print('constitution  :', c.sha256()[:12], f'({c.char_count()} caracteres)')"

# -----------------------------------------------------------------------------
# LE FICHIER CANONIQUE DIT-IL LA VÉRITÉ SUR LE CODE ?
#
# Une variable documentée que rien ne lit est pire qu'une variable absente :
# on la recopie, on la relit, on la vérifie à l'œil — et elle ne fait rien,
# sans jamais produire d'erreur. Une variable lue mais jamais documentée est
# l'autre moitié du même piège : on ne la pose pas, et un jour elle manque.
#
# Ce contrôle échoue dans les deux sens. Il fait partie de `make test` ; cette
# cible ne sert qu'à le lancer seul, quand on vient de toucher `.env.example`.
# Ni base, ni réseau : il lit des fichiers.
# -----------------------------------------------------------------------------
env-audit:
	@$(PY) bootstrap/checks/audit_env.py

# -----------------------------------------------------------------------------
# LE CODE ET LE SCHÉMA DISENT-ILS LA MÊME CHOSE ?
#
# Une table absente ne fait AUCUN bruit. `arac.memory_review_queue` etait lue
# par deux consommateurs de production et creee par aucune migration : les deux
# lecteurs degradaient proprement, donc la panne etait silencieuse, permanente,
# et invisible aux tests comme a l'installation.
#
# Ce controle croise ce que le code NOMME et ce que les migrations BATISSENT.
# Il fait partie de `make test` ; cette cible ne sert qu'a le lancer seul.
# Ni base, ni reseau : il lit des fichiers. Contre une base REELLE, c'est
# `bootstrap/checks/verify_install.sh` (controle 8) qui le rejoue.
# -----------------------------------------------------------------------------
schema-audit:
	@$(PY) bootstrap/checks/audit_schema_refs.py

# -----------------------------------------------------------------------------
# LE CRITÈRE D'ACCEPTATION — la seule cible de ce fichier qui écrit sur disque.
#
# `make test` répond à « le code est-il cassé ? ». Cette cible répond à la
# seule question qui décide si le framework est terminé :
#
#     un inconnu peut-il, SANS INTERVENTION, cloner, suivre la documentation,
#     installer, créer son cerveau, synchroniser ses conversations, LE VOIR
#     APPRENDRE, et utiliser son cockpit ?
#
# Elle installe donc un cerveau POUR DE VRAI, du clone au cockpit, et rend
# sept verdicts avec leurs preuves. Puis elle démonte tout — cluster, unités,
# comptes, dossiers — y compris quand elle échoue, et vérifie qu'elle a bien
# démonté.
#
# CE QU'ELLE NE TOUCHE JAMAIS, et ce n'est pas une promesse mais une garde qui
# refuse de démarrer : le cluster PostgreSQL par défaut (5432, dont les rôles
# sont GLOBAUX), les ports 8000 et 8100, les unités systemd sans son marqueur,
# /var/log/arac, /var/backups/arac, les comptes « arac » et « aracagent ».
# Ces refus sont eux-mêmes testés, dans `make test` :
#     tests/acceptance/test_garde_isolement.py
#
# COÛT : zéro par défaut. Aucune clé n'est demandée, aucun appel payant n'est
# fait, et l'étape 6 rend « PARTIEL » en NOMMANT ce qu'elle n'a pas pu prouver.
# `make acceptance-complet CLE=sk-…` mène la chaîne jusqu'à l'atome porteur
# d'un vecteur, et dépense alors quelques centimes.
#
# Elle N'EST PAS dans `make test`, et ne le sera jamais : la suite de tests
# doit rester hermétique et exécutable sur un dépôt fraîchement cloné.
# -----------------------------------------------------------------------------
acceptance:
	@tests/acceptance/acceptance.sh

acceptance-complet:
	@tests/acceptance/acceptance.sh --complet --cle-embeddings "$(CLE)"

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .coverage htmlcov
