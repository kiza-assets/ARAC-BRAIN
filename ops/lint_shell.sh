#!/usr/bin/env bash
# ===========================================================================
# lint_shell.sh — les trois contrôles du shell d'installation.
#
# POURQUOI CE FICHIER EXISTE
#
# L'étape 6 du bootstrap est morte pendant des semaines sur ceci :
#
#     declares="$(cd "$X" && python3 - fichier <<'PY' 2>/dev/null || true
#     …
#     PY
#     )"
#
# Bash délimite d'abord le `$( … )` en cherchant la parenthèse fermante, PUIS
# analyse le texte extrait comme un script. Ce second passage consomme le corps
# du document en ligne jusqu'à `PY`, et retrouve derrière lui le `|| true`
# devenu orphelin, collé au `)`. À L'EXÉCUTION, et seulement là :
#
#     command substitution: syntax error near unexpected token `||'
#
# `bash -n` rend 0. `shellcheck -S error` rend 0. Les deux sont AVEUGLES, et
# structurellement : aucun des deux ne relit le corps d'une substitution — cela
# n'arrive qu'au moment de l'évaluer. Les deux garde-fous que le dépôt citait
# comme preuves de qualité ne pouvaient donc pas attraper ce défaut.
#
# D'où le troisième contrôle ci-dessous. Il ne remplace pas les deux autres :
# il couvre exactement l'angle mort qu'ils laissent.
#
# RÈGLE : sur la ligne qui ouvre un `<<'EOF'` À L'INTÉRIEUR d'un `$( … )`,
#         rien après le délimiteur. Les redirections se posent AVANT,
#         les opérateurs APRÈS la parenthèse fermante.
# ===========================================================================

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

FICHIERS=(bootstrap/bootstrap.sh bootstrap/lib/*.sh bootstrap/checks/*.sh ops/*.sh)
echec=0

titre() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$1"; }
ko()    { printf '  \033[31m✗\033[0m %s\n' "$1"; echec=1; }

# --- 1. La syntaxe, telle que bash la voit au chargement -------------------
titre "1. bash -n — la syntaxe au chargement"
for f in "${FICHIERS[@]}"; do
    [[ -f "$f" ]] || continue
    if bash -n "$f" 2>/dev/null; then ok "$f"; else ko "$f — $(bash -n "$f" 2>&1 | head -1)"; fi
done

# --- 2. shellcheck, s'il est là --------------------------------------------
titre "2. shellcheck — les pièges connus"
if command -v shellcheck >/dev/null 2>&1; then
    for f in "${FICHIERS[@]}"; do
        [[ -f "$f" ]] || continue
        if shellcheck -S error "$f" >/dev/null 2>&1; then ok "$f"
        else ko "$f — $(shellcheck -S error "$f" 2>&1 | sed -n '3p')"; fi
    done
else
    printf '  (shellcheck absent — contrôle sauté, ce n'\''est pas un échec)\n'
fi

# --- 3. L'angle mort des deux précédents -----------------------------------
titre "3. document en ligne ouvert DANS une substitution, avec un opérateur derrière"
python3 - "${FICHIERS[@]}" <<'PY'
import pathlib, re, sys

# Une ligne qui ouvre un here-document alors qu'une substitution est en cours,
# ET qui porte encore quelque chose après le délimiteur. C'est cette « queue »
# qui devient orpheline au second passage de bash.
OUVRE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\1(?P<queue>.*)$")
# Une queue inoffensive : uniquement des redirections. Un `||`, `&&`, `;`, `|`
# ou un `)` après le délimiteur est le défaut qu'on cherche.
INOFFENSIF = re.compile(r"^(?:\s*\d?>[>&]?\s*[^\s|&;)]+)*\s*$")

faute = 0
for chemin in sys.argv[1:]:
    p = pathlib.Path(chemin)
    if not p.is_file():
        continue
    for n, ligne in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        nu = ligne.lstrip()
        if nu.startswith("#"):
            continue
        # La substitution doit être ouverte SUR CETTE LIGNE et non refermée.
        if "$(" not in ligne or ligne.count("(") <= ligne.count(")"):
            continue
        m = OUVRE.search(ligne)
        if not m or INOFFENSIF.match(m.group("queue")):
            continue
        print(f"  \033[31m✗\033[0m {chemin}:{n}")
        print(f"      {nu}")
        print(f"      « {m.group('queue').strip()} » sera relu APRÈS le délimiteur "
              f"{m.group(2)}, donc collé au ')'.")
        print( "      Geste : redirections avant le <<, opérateurs après la parenthèse fermante.")
        faute = 1

if not faute:
    print("  \033[32m✓\033[0m aucun document en ligne piégé dans une substitution")
sys.exit(faute)
PY
(( $? )) && echec=1

printf '\n'
if (( echec )); then
    printf '\033[31mLe shell d'\''installation ne passe pas.\033[0m\n'
    exit 1
fi
printf '\033[32mLe shell d'\''installation passe les trois contrôles.\033[0m\n'
