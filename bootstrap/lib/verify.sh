# shellcheck shell=bash
# ---------------------------------------------------------------------------
# verify.sh — étape 10 (le contrôle) et étape 11 (la suite).
#
# L'étape 10 délègue à bootstrap/checks/verify_install.sh, qui est écrit pour
# vivre seul : on le relance des mois plus tard, sans rejouer l'installation,
# pour répondre à une seule question — « ce cerveau est-il toujours sain ? ».
# ---------------------------------------------------------------------------

etape_controle() {
    etape_entete "$(rang_etape controle)" "$TOTAL_ETAPES" "${TITRE_ETAPE[controle]}" \
"Une installation qui se déclare réussie sans se contrôler n'est qu'une
suite de commandes qui n'ont pas planté. Ce n'est pas la même chose." \
"Un rapport lisible : la base et ses tables, la taxonomie semée, les quatre
rôles et la lecture seule du cockpit réellement vérifiée, les services qui
répondent, les secrets et leurs permissions, l'état des sauvegardes." \
"Vous saurez ce qui marche, ce qui manque, et ce qui est dégradé. Le même
contrôle se relance à tout moment, sans rien réinstaller."

    local script="$ARAC_HOME/bootstrap/checks/verify_install.sh"
    if [[ ! -x "$script" ]]; then
        alerte "Contrôleur introuvable : $script"
        return 8
    fi

    plan "$script"
    vide

    local rc=0
    local args=()
    reel || args+=(--simulation)
    ARAC_HOME="$ARAC_HOME" ARAC_DB="$ARAC_DB" ARAC_SCHEMA="$ARAC_SCHEMA" \
    ARAC_ETC="$ARAC_ETC" ARAC_ENV_FILE="$ARAC_ENV_FILE" \
    ARAC_SECRETS_ROLES="$ARAC_SECRETS_ROLES" ARAC_SECRETS_COCKPIT="$ARAC_SECRETS_COCKPIT" \
    ARAC_ROLE_PREFIX="$ARAC_ROLE_PREFIX" ARAC_DB_HOTE="$ARAC_DB_HOTE" \
    ARAC_DB_PORT="$ARAC_DB_PORT" ARAC_PG_SUPERUSER="$ARAC_PG_SUPERUSER" \
    ARAC_API_PORT="$ARAC_API_PORT" ARAC_COCKPIT_PORT="$ARAC_COCKPIT_PORT" \
    ARAC_BACKUP_DIR="$ARAC_BACKUP_DIR" ARAC_UI_COULEUR="$ARAC_UI_COULEUR" \
    ARAC_UNITE_PREFIXE="$PREFIXE_UNITE" ARAC_SANS_BANNIERE=1 \
    "$script" "${args[@]}" || rc=$?
    return "$rc"
}

# ===========================================================================
# ÉTAPE 11 — la suite
# ===========================================================================

epilogue() {
    # L'ÉPILOGUE EST LE DERNIER RANG, ET IL SE COMPTE : c'est exactement
    # `TOTAL_ETAPES`, puisque celui-ci vaut « toutes les étapes + la suite ».
    etape_entete "$TOTAL_ETAPES" "$TOTAL_ETAPES" "La suite : brancher le Mac" \
"Un cerveau installé sur un serveur ne sait encore rien de vous. Il lui
manque la seule chose qui compte : vos conversations." \
"Rien de plus, ici. Cette section décrit les trois gestes qui restent, et
ce qu'ils font." \
"À la fin de cette suite, ce que vous direz à Claude sur votre Mac
deviendra, quelques heures plus tard, un savoir que le cerveau saura vous
rendre."

    dire "$(_c 1 'La chaîne complète, pour que rien ne reste inexpliqué')"
    vide
    dire "   Claude Desktop"
    dire "      │  vos conversations, stockées localement sur le Mac"
    dire "      ▼"
    dire "   synchronisation locale (launchd, toutes les N minutes)"
    dire "      │  lit les conversations nouvelles ou modifiées"
    dire "      ▼"
    dire "   tunnel SSH  Mac → serveur"
    dire "      │  l'API n'écoute que sur 127.0.0.1 : le tunnel est la seule porte"
    dire "      │  DEPUIS L'EXTÉRIEUR. Sur la machine elle-même, la porte est le"
    dire "      │  jeton : il est exigé aussi en boucle locale (app/auth.py)"
    dire "      ▼"
    dire "   ingestion (API, port $ARAC_API_PORT)"
    dire "      │  vérifie le poste source, refuse l'inconnu, écrit le brut"
    dire "      │  AUCUN vecteur ici : le message reste du texte, et ne coûte rien"
    dire "      ▼"
    dire "   choix de la tranche à digérer"
    dire "      │  ce qui n'a pas encore été lu, par curseur et par date —"
    dire "      │  jamais par ressemblance : aucun vecteur dans ce choix"
    dire "      ▼"
    dire "   extraction (cycle, $ARAC_CYCLES)"
    dire "      │  la curation lit ce texte, décide, propose"
    dire "      ▼"
    dire "   atomes"
    dire "      │  une affirmation, un domaine, une confiance, une provenance"
    dire "      ▼"
    dire "   embeddings"
    dire "      │  c'est L'ATOME qui devient un vecteur (3072 nombres),"
    dire "      │  jamais le message. Un atome = un appel, pas un message = un appel."
    dire "      ▼"
    dire "   voisinage sémantique"
    dire "      │  les atomes proches en sens se retrouvent — par distance"
    dire "      │  vectorielle et par domaine partagé, PAS par des liens écrits"
    dire "      ▼"
    dire "   mémoire"
    dire "      │  interrogeable par similarité, filtrable par domaine"
    dire "      ├──────────────▶ cockpit  (127.0.0.1:$ARAC_COCKPIT_PORT, lecture seule)"
    dire "      └──────────────▶ Claude Code  (rappel au moment d'écrire du code)"
    vide
    alerte "$(_c 1 'Ce que cette chaîne ne fait PAS — dit maintenant, pas dans six mois')"
    note "Le « voisinage sémantique » ci-dessus n'est pas un graphe de sens.
AUCUN mécanisme ne détecte une contradiction, et aucun n'écrit « cet
atome confirme celui-là ». Une couche de liens dérivés existe bien en
base (arac.atom_links, recalculée à chaque cycle), mais elle ne porte
que trois relations MÉCANIQUES — succession, enchaînement dans une même
conversation, voisinage vectoriel réciproque — et aucun chemin servi ne
la lit aujourd'hui : ni le rappel, ni le bundle de contexte. Ce que le
cerveau sait faire, c'est rapprocher ce qui se ressemble et le filtrer
par domaine : cela suffit au rappel, cela ne suffit pas à raisonner.
De même, la vérification et la péremption d'un savoir existent comme
colonnes et ne sont alimentées par rien : 98 % du savoir du cerveau de
référence n'a jamais été audité, et il n'y avait pas de bogue à
corriger — personne ne l'avait fait."
    vide

    sous_titre "1. Ouvrir le tunnel depuis votre Mac"
    note "Le cockpit et l'API n'écoutent que sur la boucle locale du serveur :
depuis l'extérieur, le tunnel est la seule porte. Il dit d'où vient une
requête, jamais qui l'envoie — c'est pourquoi le jeton porteur reste
exigé une fois le tunnel ouvert, et le mot de passe du cockpit aussi.
On creuse le tunnel ainsi :"
    vide
    cmd "ssh -N -L $ARAC_COCKPIT_PORT:127.0.0.1:$ARAC_COCKPIT_PORT \\"
    cmd "       -L $ARAC_API_PORT:127.0.0.1:$ARAC_API_PORT  <utilisateur>@<votre-serveur>"
    vide
    note "Puis ouvrez http://127.0.0.1:$ARAC_COCKPIT_PORT dans votre navigateur.
Le cockpit demandera votre mot de passe, puis le code à six chiffres de
l'application que vous avez appairée à l'étape 7."
    vide

    sous_titre "2. Déclarer le poste source"
    note "Le cerveau refuse les conversations d'un poste qu'il ne connaît pas.
Le vôtre s'appelle « $ARAC_NODE_ID » — c'est ce que vous avez répondu à
l'entretien. Le jeton porteur de l'API doit être installé sur le Mac,
et lui seul. Il est ici, lisible par root uniquement :"
    vide
    cmd "sudo grep '^ARAC_API_BEARER_TOKEN=' $ARAC_ENV_FILE"
    vide

    sous_titre "3. Lancer la première synchronisation"
    note "La première synchronisation remonte l'historique existant. Elle est
plus longue que les suivantes, et c'est le bon moment pour regarder le
cockpit se remplir."
    vide

    # LE GESTE QUI SUIT SE SABORDAIT, ET C'EST MESURÉ.
    #
    # « sudo systemctl start …-cycle.service » sur un cerveau NEUF est REFUSÉ :
    # l'IA payante n'est armée ni côté service, ni côté cerveau. Le cycle
    # sortait sans un mot utile, et l'écran qui prescrivait ce geste ne disait
    # ni pourquoi, ni quoi faire d'abord. Trois choses doivent être vraies
    # avant, elles sont nommées ici, et le contrôle de l'étape 10 les vérifie.
    dire "$(_c 1 'Trois choses doivent être vraies avant — sinon le cycle refuse, et il le dira')"
    vide
    dire "   $(_c 1 'a. le binaire de curation, sur CE serveur')"
    note "     La digestion n'appelle aucune API : elle lance \`claude\` en
     sous-processus. S'il manque, l'étape 1 vous l'a dit et le contrôle
     de l'étape 10 le redit — rien ne sera jamais digéré sans lui."
    vide
    dire "   $(_c 1 'b. de quoi authentifier ce binaire, SOUS LE COMPTE AGENT')"
    note "     C'est son dossier personnel à lui qui est lu, pas le vôtre :"
    cmd "sudo -u $ARAC_AGENT_USER -H env HOME=$ARAC_AGENT_HOME/data/agent-home claude auth login"
    note "     Inutile si vous avez donné une clé Anthropic à l'étape 8 : le
     binaire la lira dans l'environnement du service."
    vide
    dire "   $(_c 1 'c. les DEUX interrupteurs de dépense — il y en a deux, et le second est en base')"
    cmd "sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' $ARAC_ENV_FILE"
    cmd "cd $ARAC_HOME && sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm --coffre $ARAC_ENV_FILE"
    note "     Le premier autorise le SERVICE à dépenser, le second est votre
     accord, révocable sans toucher à un fichier d'unité. Tant que l'un
     des deux est fermé, le cycle refuse — en nommant lequel."
    vide
    dire "$(_c 1 'Alors, et alors seulement :')"
    cmd "sudo systemctl start ${PREFIXE_UNITE}-cycle.service   # digérer sans attendre"
    cmd "journalctl -u ${PREFIXE_UNITE}-cycle.service -f       # regarder penser"
    note "Un cycle refusé n'est plus muet : le journal porte la raison ET le
geste. Et un refus ne consomme plus le créneau du jour — vous réparez,
vous relancez, il repart."
    vide

    sous_titre "Ce qu'il faut savoir avant de juger votre cerveau"
    lecon "36 % des cycles en quarantaine, zéro atome produit" \
"Sur le cerveau de référence, plus d'un cycle sur trois s'est terminé sans
rien produire. La cause n'était PAS le volume de la tranche : c'était un
désaccord d'identifiants entre le paquet de messages SERVI au modèle de
curation et la RÉPONSE qu'il a rendue. Le modèle citait, comme preuve
d'un atome, des identifiants de messages absents du paquet qu'on lui
avait donné. Le contrat de sortie est strict et refuse tout le cycle
plutôt que d'écrire un souvenir dont la provenance est fausse — mieux
vaut ne rien retenir que retenir une chose qu'on ne saura pas prouver.
Ce que cela vous apprend : un cycle stérile ne se soigne pas en
réduisant la tranche. On lit le corps mis en quarantaine, qui est
conservé en base exactement pour ça."
    vide
    lecon "96 % des rappels rendus en confiance basse" \
"Le rappel trouve, mais doute. Un cerveau qui vous répond « je crois, à
40 % » n'est pas cassé : il est honnête.

CE QUE CE CHIFFRE MESURE, ET CE QU'IL NE MESURE PAS. Les 96 % ne portent
pas sur vos souvenirs : c'est la part des RAPPELS dont la bande finale est
« basse » ou « nulle », et une bande se calcule sur la DISTANCE entre
votre question et ce qui a été trouvé. Un cerveau jeune, qui sait peu de
choses, répond forcément de loin. Ce chiffre descend quand la matière
s'accumule, pas quand on tourne un bouton.

DEUX CHOSES DIFFÉRENTES S'APPELLENT « CONFIANCE », ET UNE SEULE EST
IMMUABLE. Le NIVEAU déclaré — producteur, suggestion d'agent, validé par
un auditeur — et la trace d'audit qui l'accompagne sont fixés à la
naissance : le PATCH de l'API les refuse, la supersédure les recopie.
Le NOMBRE de 0 à 100, lui, se corrige : PATCH le sert, et la supersédure
porte sa propre valeur. C'est un aveu : il dit ce que VOUS savez de ce
souvenir. Le corriger quand il a tort, c'est le travail.

CE QUE CE NOMBRE NE FAIT PAS. Cet écran a longtemps promis que le chiffre
pesait sur l'ordre des rappels. C'était faux, et c'est mesuré : deux
souvenirs au texte IDENTIQUE, l'un à 95, l'autre à 10, sortent du même
rappel à la MÊME distance, jusqu'au dernier chiffre. Ce qui est servi est
une pure similarité de sens. L'organe qui pèserait la confiance existe
dans le code, mais il est tenu fermé par un drapeau d'expérimentation que
votre installation ne pose pas, et ne concerne que deux consommateurs
internes. Monter une confiance ne changera donc RIEN à ce qui vous est
rendu, ni à l'ordre dans lequel ça l'est.

CE QUE CE NOMBRE FAIT VRAIMENT, ET C'EST BRUTAL. Un seuil, un seul, et il
ne se déclenche qu'à la NAISSANCE d'un atome : à l'instant où un atome
portant la trace d'audit « suggestion d'agent autonome » est ÉCRIT avec
un score inférieur à 70, la base le range en archive basse-confiance —
donc hors de tout rappel, qui ne lit que les atomes actifs. À 69 il est
archivé, à 70 il vit.

LE PIÈGE QUI COÛTE UN SOUVENIR, ET IL NE PRÉVIENT PAS ASSEZ. Ce seuil ne
regarde que les ÉCRITURES. Descendre un score par PATCH ne déclenche
rien : l'atome reste actif, même à 10. Mais une SUPERSÉDURE écrit un
atome neuf, qui hérite du score de l'ancien — donc superséder une
suggestion d'agent déjà sous 70, ne serait-ce que pour corriger une
faute de frappe, archive le remplaçant à la seconde où il naît, alors
que l'original vient d'être marqué remplacé. Mesuré : réponse 201,
aucune erreur, et plus AUCUN atome actif sur ce domaine et cette clé.
Depuis cette version l'API le DIT — la réponse porte un avertissement
W-008 nommé, et le journal du service le garde. Si vous descendez une
confiance, descendez-la par PATCH ; si vous devez superséder un atome
sous 70, remontez d'abord son score par PATCH.

CE QUE VOUS POUVEZ FAIRE, ET CE QUE COÛTE CHAQUE GESTE : PATCH pour
retoucher un atome, supersede pour le remplacer en gardant la filiation,
DELETE pour l'archiver. Seule la réécriture du TEXTE a besoin du vecteur,
donc de la clé d'embeddings : sans clé, supersede rend 503, PATCH aussi
s'il touche au texte — mais le reste du PATCH passe, la confiance
comprise. Un cerveau en mode dégradé n'est pas réduit à la lecture."
    vide
    lecon "98 % du savoir jamais audité" \
"Le cerveau est confiant sur ce qu'il n'a jamais vérifié — et il n'a
aujourd'hui aucun organe pour le vérifier. Cet écran vous a longtemps
demandé « d'ouvrir le cockpit et de trancher quelques propositions » :
c'était faux, et le prix de cette phrase, c'est un lecteur qui cherche le
bouton pendant vingt minutes et conclut que son installation est cassée.
Le cockpit est en LECTURE SEULE — sa seule route qui écrit est celle qui
vous connecte, et elle ne pose qu'un cookie.
Ce qui existe, et qui est déjà un vrai travail : lire dans le cockpit ce
qui a été appris, et corriger par l'API ce qui a tort. Ce qui n'existe
pas : marquer un savoir comme vérifié. C'est un chantier ouvert, pas un
réglage à trouver."
    vide

    # SANS SUDO, ET C'EST DÉLIBÉRÉ — MAIS ALORS IL FAUT LE DIRE.
    #
    # Ce script est le seul des trois contrôles qui rende quelque chose
    # d'utile depuis un compte ordinaire : il mesure ce qu'il peut voir, et
    # marque « NON CONTRÔLÉ » ce que le coffre en 0700 root lui cache — jamais
    # « absent ». Le prescrire sans `sudo` est donc juste ; le prescrire sans
    # dire que le rapport sera PARTIEL laissait le lecteur compter des
    # avertissements qui ne parlent pas de son installation.
    sous_titre "Contrôler, plus tard"
    cmd "./bootstrap/checks/verify_install.sh     # ce cerveau est-il sain ?"
    dire "     Sans sudo, il répond quand même : rapport PARTIEL, et il DIT ce"
    dire "     qu'il n'a pas pu voir. Avec sudo, il voit le coffre, les ports et"
    dire "     les sauvegardes — c'est le rapport complet."
    cmd "$(geste_bootstrap "--scopes-only")   # après avoir changé la taxonomie"
    vide
}
