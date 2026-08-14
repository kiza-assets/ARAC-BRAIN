"""Control Center v1 — la vue « Aujourd'hui » et la SYNTHÈSE NARRATIVE.

Le cockpit V1 affichait des états. Cette vue-ci affiche une JOURNÉE : ce que le
cerveau a appris, enrichi, remplacé, absorbé, raté et dépensé depuis une fenêtre
glissante. La question n'est plus « où en est-on ? » mais « que s'est-il passé ? ».

Routes exposées :

  GET /cc/v1/today?window=24h|7d|30d   les deltas, les faits saillants, la synthèse
  GET /cc/v1/today/narrative?window=…  la seule synthèse, pour le bandeau d'accueil

============================================================================
DOCTRINE ANTI-FABULATION — le point dur de ce fichier
============================================================================

On attend de ce cockpit que « le cerveau vous parle » :

    « Aujourd'hui j'ai appris 18 conversations. Le projet <un de vos projets>
      progresse. »

Un serveur qui GÉNÈRE cette phrase peut lui faire dire n'importe quoi : il suffit
d'un `if` mal placé pour que le cockpit annonce une bonne nouvelle qu'aucune donnée
ne soutient. Ce module ne génère donc **aucune phrase**. Il produit une liste de

    {template_key, args, sources}

Les gabarits vivent dans ``NARRATIVE_TEMPLATES``, servi par la route : **le client
compose**. Un gabarit inconnu s'affiche ``[phrase inconnue : clé]`` — jamais un
texte inventé pour boucher le trou. Les trois garde-fous qui en découlent :

1. **Une phrase sans source est refusée.** ``_Draft.say`` ignore silencieusement
   toute phrase dont la liste ``sources`` est vide. Chaque source porte son ``href``
   de preuve : de la phrase on atteint le chiffre, du chiffre on atteint la ligne.
2. **Une phrase n'est émise que si sa condition chiffrée est vraie**, et la condition
   ne porte que sur des valeurs DÉJÀ SERVIES — jamais sur une estimation.
3. **Trois phrases sont interdites** : « aucune contradiction », « aucune régression »,
   « aucun lien créé ». Ces mesures n'existent pas ; l'absence de mesure se dit
   ``measure_unavailable``, avec sa raison et le geste qui la débloquerait.

Une journée vide EST une information : ``nothing_learned`` la dit en toutes lettres
plutôt que d'afficher un bandeau vide qu'on prendrait pour un chargement en cours.

============================================================================
AUCUNE ARITHMÉTIQUE HORS SQL
============================================================================

Les deltas viennent des ``Spec`` de ``families/aujourdhui.py`` — les mêmes objets
que le registre publie, projetés sur la fenêtre demandée. Les faits saillants sont
six requêtes agrégées en SQL. Python ne fait ici que trois choses, toutes non
arithmétiques : comparer deux valeurs déjà servies (``>``, ``== 0``), **trier** une
liste par un rang déclaré, et la tronquer à six. Aucune somme, aucune division,
aucun pourcentage n'est calculé dans ce fichier.

Le tri mérite un mot : les phrases sont ordonnées par un rang d'importance DÉCLARÉ
(``_P``), et le tri de Python étant stable, l'ordre interne à un rang reste celui
que le SQL a produit — c'est-à-dire le delta décroissant (``ORDER BY … DESC``).
« Le delta le plus fort d'abord » est donc obtenu par le moteur, pas par le BFF.
Trier globalement sur la valeur brute n'aurait aucun sens : 2 563 messages
écraseraient toujours 9 atomes, et le bandeau ne parlerait plus jamais du savoir.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from typing import Any, Callable, Iterator
from urllib.parse import quote

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from app.journal import raison, sha8
from control_center.cc_v1 import service
from control_center.cc_v1.families import aujourdhui as A

__all__ = [
    "register",
    "NARRATIVE_TEMPLATES",
    "UNKNOWN_TEMPLATE",
    "SENTENCE_RULES",
    "today",
    "narrative",
]

logger = logging.getLogger("arac.cc.v1.today")

_PREFIX = "/cc/v1"

#: Plafond dur du bandeau. Au-delà, ce n'est plus une synthèse : c'est une liste.
MAX_SENTENCES = 6


# ============================================================================
# Garde lecture seule — troisième couche, après le rôle et la transaction
# ============================================================================

FORBIDDEN_SQL: tuple[str, ...] = (
    "insert", "update", "delete", "truncate", "drop", "alter", "create",
    "grant", "revoke", "copy", "vacuum", "refresh", "call", "do",
)

_WORD = re.compile(r"[a-z_]+")
_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _assert_read_only(sql: str, where: str) -> None:
    """Lève si le SQL contient une instruction mutante (littéraux exclus)."""
    body = _LITERAL.sub(" ", sql.lower())
    hit = set(_WORD.findall(body)) & set(FORBIDDEN_SQL)
    if hit:
        raise ValueError(f"{where}: instruction mutante interdite : {sorted(hit)}")


@contextmanager
def _readonly() -> Iterator[Any]:
    conn = service._connect_readonly()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _rows(conn: Any, sql: str, *, where: str = "requête") -> list[dict[str, Any]]:
    """Exécute une requête littérale et rend des lignes JSON-ables.

    Aucun paramètre n'est lié : tout le SQL de ce module est statique, la seule
    variable étant l'intervalle, choisi par clé dans ``aujourdhui.WINDOWS``. Une
    requête sans paramètre est aussi une requête **rejouable telle quelle**, motifs
    ``LIKE '%/%'`` compris.
    """
    _assert_read_only(sql, where)
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in (cur.description or [])]
        raw = cur.fetchall()
    return [{c: service._jsonable(v) for c, v in zip(cols, r)} for r in raw]


def _strip_line_comments(sql: str) -> str:
    """Retire les commentaires ``--`` en respectant les littéraux.

    Un ``--`` porte jusqu'à la fin de sa LIGNE. Il survit donc parfaitement à
    l'exécution multi-lignes, et ne meurt qu'à la mise sur une ligne — où il
    avale tout ce qui suit. Le scan est fait à la main plutôt qu'en expression
    régulière parce qu'un ``LIKE '%--%'`` est de la donnée, pas un commentaire :
    seul un état « dans un littéral » sait faire la différence.
    """
    out: list[str] = []
    i, n, dans_litteral = 0, len(sql), False
    while i < n:
        c = sql[i]
        if dans_litteral:
            out.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":   # '' échappé : reste dedans
                    out.append(sql[i + 1])
                    i += 2
                    continue
                dans_litteral = False
            i += 1
            continue
        if c == "'":
            dans_litteral = True
            out.append(c)
            i += 1
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            saut = sql.find("\n", i)
            if saut == -1:
                break
            i = saut                                   # le \n est gardé par la boucle
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _flat(sql: str) -> str:
    """La requête sur une ligne : copiable dans ``psql`` sans retouche.

    CE QUI ÉTAIT FAUX : cette fonction se contentait de ``" ".join(sql.split())``.
    Quatre ``value_sql`` servis par /cc/v1/today portaient des commentaires
    ``--`` ; recopiés dans psql comme le produit y invite, ils rendaient un
    chiffre DIFFÉRENT de la valeur affichée (today_atoms_superseded : 1 servi,
    19 en psql ; today_scopes_touched : 3 servi, 38 en psql) ou rien du tout
    (today_atoms_created : les quatre lignes de commentaire précédaient le
    SELECT, toute la requête était commentée).

    CE QUE CETTE VERSION GARANTIT : la chaîne rendue est du SQL RÉELLEMENT
    rejouable, quoi qu'écrive l'auteur d'une famille — les commentaires de ligne
    sont retirés avant la mise sur une ligne, et la garde qui suit refuse de
    servir une preuve où il en resterait un. C'est la règle absolue n°9 du
    mandat, rendue exécutable ici plutôt que confiée à la discipline d'autrui.
    """
    plat = " ".join(_strip_line_comments(sql).split())
    if "--" in _LITERAL.sub(" ", plat):
        raise ValueError(
            "preuve injouable : commentaire SQL '--' survivant à la mise sur une "
            "ligne (il masquerait tout ce qui suit)")
    return plat


def _run_evidence(spec: Any, window: str, limit: int) -> dict[str, Any]:
    """Exécute la preuve d'une ``Spec`` sur la fenêtre demandée.

    Ne lève jamais : une source injoignable rend ``unavailable`` avec sa raison,
    comme partout ailleurs dans ce cockpit. Le SQL exécuté est rendu avec le
    résultat, pour que la preuve reste opposable depuis un terminal.
    """
    sql = spec.evidence_sql(window)
    # Identifiant de MÉTRIQUE (littéral du registre), pas clé d'atome : le
    # journal le nomme comme tel, et le garde du journal cesse d'avoir à
    # deviner.
    metric_id = spec.key
    try:
        with _readonly() as conn:
            rows = _rows(conn, sql, where=f"preuve {spec.key}/{window}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("cc_v1.today_evidence_failed",
                       extra={"metric_id": metric_id, "window": window,
                              "error": type(exc).__name__})
        return {"key": spec.key, "state": "unavailable", "rows": [], "columns": [],
                "window": window, "reason": f"source indisponible ({type(exc).__name__})"}

    shown = rows[:limit]
    return {
        "key": spec.key,
        "label": spec.label,
        "state": "ok",
        "window": window,
        "window_label": A.WINDOW_LABELS.get(window, window) if hasattr(A, "WINDOW_LABELS") else window,
        "definition": spec.definition,
        "formula": spec.formula,
        "evidence_label": spec.evidence_label,
        "sql": _flat(sql),
        "value_sql": _flat(spec.sql(window)),
        "columns": list(shown[0].keys()) if shown else [],
        "rows": [list(r.values()) for r in shown],
        "row_count": len(shown),
        "truncated": len(rows) > len(shown),
        "limit": limit,
    }


def _window(value: Any) -> str:
    """Valide la fenêtre. Une valeur inconnue retombe sur 24 h ; elle ne construit
    jamais de SQL — c'est une clé de dictionnaire, pas un fragment."""
    key = str(value or "").strip()
    return key if key in A.WINDOWS else A.DEFAULT_WINDOW


# ============================================================================
# LES GABARITS — le seul endroit où des mots sont écrits
# ============================================================================
#
# Le serveur ne les remplit jamais. Il désigne une clé et fournit ses arguments ;
# le client compose. Ajouter une phrase, c'est ajouter un gabarit ICI et une règle
# dans `_draft_sentences` — jamais une concaténation ailleurs.

NARRATIVE_TEMPLATES: dict[str, str] = {

    # --- l'apprentissage du jour -------------------------------------------
    "learning_today":
        "Depuis {window}, j'ai appris {conversations} conversation(s) "
        "et créé {atoms} atome(s) de savoir.",
    "learning_without_conversation":
        "Depuis {window}, j'ai créé {atoms} atome(s) sans qu'aucune conversation neuve "
        "ne me parvienne : j'ai fini de digérer ce qui restait.",
    "nothing_learned":
        "Le cerveau n'a rien appris depuis {window}.",

    # --- le territoire ------------------------------------------------------
    "project_progress":
        "Le projet {project} progresse : {atoms} atome(s) de plus depuis {window}.",
    "scope_enriched":
        "Le domaine {scope} est celui qui s'est le plus enrichi : "
        "{created} atome(s) créé(s) depuis {window}.",
    "scope_root_debt":
        "Attention : {atoms} atome(s) de la fenêtre ont été posés sur la racine {scope}, "
        "où le rappel ne les verra jamais.",

    # --- le savoir lui-même -------------------------------------------------
    "notable_atom":
        "Le dernier souvenir retenu est un {kind} dans {scope} : « {key} ».",
    "atoms_enriched":
        "{atoms} atome(s) existants ont été réécrits depuis {window} : "
        "j'ai affiné plutôt qu'ajouté.",
    "atoms_superseded":
        "{atoms} atome(s) ont été remplacés depuis {window} : j'ai changé d'avis.",

    # --- l'ingestion --------------------------------------------------------
    "conversation_absorbed":
        "J'ai absorbé {messages} message(s) depuis {window}, "
        "dont {top_messages} pour la seule conversation « {title} ».",
    "queue_growing":
        "La file grandit : {received} conversation(s) reçue(s) depuis {window} "
        "pour {curated} entièrement curée(s).",
    "queue_shrinking":
        "La file se résorbe : {curated} conversation(s) entièrement curée(s) depuis {window} "
        "pour {received} reçue(s).",

    # --- la machine ---------------------------------------------------------
    # Dire « 2 sur 4 en quarantaine » laissait déduire que 2 avaient réussi. Les
    # cycles peuvent aussi échouer au spawn ou être ignorés : seul le compte des
    # cycles ABOUTIS dit la vérité. On énonce donc les deux bouts.
    "cycle_quarantined":
        "{quarantined} cycle(s) sur {total} sont partis en quarantaine depuis {window} ; "
        "cycles réellement aboutis : {done}. Ce que les autres portaient n'a pas été retenu.",
    "candidates_dropped":
        "{dropped} candidat(s) ont été écartés avant d'entrer en mémoire depuis {window}.",

    # --- l'usage ------------------------------------------------------------
    "recall_served":
        "J'ai servi {receipts} rappel(s) depuis {window}.",
    "recall_idle":
        "Personne ne m'a rien demandé depuis {window} : aucun rappel servi.",
    "dormant_knowledge":
        "{atoms} atome(s) actifs n'ont jamais été servis à personne : ce savoir dort.",

    # --- le coût ------------------------------------------------------------
    "cost_today":
        "J'ai dépensé {tokens} jetons depuis {window}, soit {per_atom} jetons par atome retenu.",
    "cost_without_yield":
        "J'ai dépensé {tokens} jetons depuis {window} sans retenir un seul atome.",

    # --- ce que je ne sais pas mesurer --------------------------------------
    "measure_unavailable":
        "Je ne sais pas mesurer {measure} : {reason}.",
}

#: Ce que le client affiche pour une clé absente du dictionnaire. Il n'invente
#: jamais de texte de remplacement : il montre le trou.
UNKNOWN_TEMPLATE = "[phrase inconnue : {key}]"


# ============================================================================
# Rangs d'importance — déclarés, pas déduits
# ============================================================================
#
# Plus bas = plus important. Le tri est stable : à rang égal, l'ordre est celui
# que le SQL a produit, donc le delta décroissant.

_P = {
    "nothing_learned": 10,
    "learning_today": 20,
    "learning_without_conversation": 20,
    "project_progress": 30,
    # Un échec passe avant un succès de plus : deux cycles perdus en disent plus
    # long sur la journée qu'un troisième projet qui avance.
    "cycle_quarantined": 36,
    "scope_root_debt": 40,
    "recall_served": 44,
    "recall_idle": 44,
    "scope_enriched": 48,
    "notable_atom": 52,
    "conversation_absorbed": 56,
    "atoms_enriched": 60,
    "atoms_superseded": 61,
    "queue_growing": 65,
    "queue_shrinking": 66,
    "candidates_dropped": 70,
    "cost_without_yield": 74,
    "cost_today": 75,
    "dormant_knowledge": 85,
    "measure_unavailable": 95,
}

#: Au plus deux projets nommés : au troisième, le bandeau devient une liste de
#: projets et cesse de parler de la journée.
MAX_PROJECT_SENTENCES = 2

#: La règle de chaque phrase, SERVIE au client : il doit pouvoir lire pourquoi
#: telle phrase est là et telle autre non, sans ouvrir ce fichier.
SENTENCE_RULES: dict[str, str] = {
    "nothing_learned": "aucune conversation reçue, aucun message absorbé, aucun atome créé ni enrichi",
    "learning_today": "au moins une conversation reçue ET au moins un atome créé",
    "learning_without_conversation": "au moins un atome créé alors qu'aucune conversation n'est arrivée",
    "project_progress": "le projet a gagné au moins 1 atome sur la fenêtre (2 projets au plus, delta décroissant)",
    "scope_enriched": "le scope de tête a gagné au moins 1 atome sur la fenêtre",
    "scope_root_debt": "au moins 1 atome de la fenêtre est posé sur un scope racine (sans « / »)",
    "notable_atom": "au moins un atome créé — le plus récent de la fenêtre",
    "conversation_absorbed": "au moins un message absorbé ET une conversation identifiable en tête",
    "atoms_enriched": "au moins un atome réécrit sur la fenêtre",
    "atoms_superseded": "au moins un atome remplacé sur la fenêtre",
    "cycle_quarantined": "au moins un cycle en quarantaine sur la fenêtre",
    "queue_growing": "conversations reçues > conversations entièrement curées",
    "queue_shrinking": "conversations entièrement curées > conversations reçues",
    "candidates_dropped": "au moins un candidat écarté sur la fenêtre",
    "recall_served": "au moins un rappel servi sur la fenêtre",
    "recall_idle": "zéro rappel servi sur la fenêtre (mesure disponible et nulle)",
    "dormant_knowledge": "au moins un atome actif jamais servi",
    "cost_today": "des jetons dépensés ET un coût par atome défini",
    "cost_without_yield": "des jetons dépensés ET aucun atome produit",
    "measure_unavailable": "une mesure demandée dont la dépendance manque en base",
}


# ============================================================================
# LES FAITS SAILLANTS — six requêtes, toute l'agrégation en SQL
# ============================================================================

_HL_NEW_ATOMS = """
    SELECT a.id,
           a.kind,
           a.scope,
           a.key,
           left(a.value, 240)                        AS extrait,
           a.confidence_score,
           a.status,
           a.created_at,
           a.source_ref ->> 'conversation_uid'       AS conversation_uid,
           (a.scope NOT LIKE '%/%')                  AS pose_sur_une_racine
      FROM arac.memory_atoms a
     WHERE a.kind <> 'agent_message'
       AND a.created_at > now() - interval '{win}'
     ORDER BY a.created_at DESC
     LIMIT 20
"""

_HL_ENRICHED_ATOMS = """
    SELECT a.id,
           a.kind,
           a.scope,
           a.key,
           a.version,
           a.status,
           a.created_at,
           a.updated_at
      FROM arac.memory_atoms a
     WHERE a.kind <> 'agent_message'
       AND a.superseded_by IS NULL
       AND a.updated_at > a.created_at
       AND a.updated_at > now() - interval '{win}'
     ORDER BY a.updated_at DESC
     LIMIT 20
"""

_HL_PROJECTS = f"""
    WITH {A.PROJECT_CTE}
    SELECT p.id                                                    AS project_id,
           p.label,
           count(a.id) FILTER (
               WHERE a.created_at > now() - interval '{{win}}')      AS atomes_gagnes,
           count(a.id) FILTER (
               WHERE a.updated_at > now() - interval '{{win}}'
                 AND a.updated_at > a.created_at)                  AS atomes_enrichis,
           count(a.id) FILTER (WHERE a.status = 'active')          AS atomes_actifs,
           max(a.created_at)                                       AS dernier_atome
      FROM proj p
      LEFT JOIN arac.memory_atoms a
        ON {A.PROJECT_MATCH}
       AND {A.NOT_TRANSPORT}
     GROUP BY p.id, p.label
    HAVING count(a.id) FILTER (
               WHERE a.created_at > now() - interval '{{win}}') > 0
     ORDER BY 3 DESC, 6 DESC
"""

# La dette de racine a sa PROPRE requête, agrégée et NON BORNÉE.
# La tirer de `_HL_SCOPES` (LIMIT 30) faisait disparaître silencieusement
# l'avertissement dès qu'une racine tombait au-delà du rang 30 : un atome posé
# là où le rappel ne le verra jamais devenait invisible au récit aussi.
# Une alerte qui dépend du rang de tri n'est pas une alerte.
_HL_ROOT_DEBT = """
    SELECT a.scope,
           count(*) AS atomes_crees
      FROM arac.memory_atoms a
     WHERE a.kind <> 'agent_message'
       AND a.status = 'active'
       AND a.scope NOT LIKE '%/%'
       AND a.created_at > now() - interval '{win}'
     GROUP BY a.scope
     ORDER BY 2 DESC
"""

_HL_SCOPES = """
    SELECT a.scope,
           count(*) FILTER (
               WHERE a.created_at > now() - interval '{win}')      AS atomes_crees,
           count(*) FILTER (
               WHERE a.updated_at > now() - interval '{win}'
                 AND a.updated_at > a.created_at)                  AS atomes_enrichis,
           count(*) FILTER (WHERE a.status = 'active')             AS atomes_actifs,
           (a.scope NOT LIKE '%/%')                                AS scope_racine
      FROM arac.memory_atoms a
     WHERE a.kind <> 'agent_message'
       AND (a.created_at > now() - interval '{win}'
            OR a.updated_at > now() - interval '{win}')
     GROUP BY a.scope
     ORDER BY 2 DESC, 3 DESC, 4 DESC
     LIMIT 30
"""

_HL_CONVERSATIONS = """
    SELECT c.conversation_uid                                       AS uid,
           c.title,
           c.source_type,
           c.created_at,
           c.curated_at,
           c.atoms_generated,
           s.messages_fenetre,
           s.messages_total,
           (COALESCE(c.curated_through_message_id, 0) >= s.dernier_message
            AND c.exclusion_reason IS NULL
            AND c.last_curation_error IS NULL)                      AS entierement_curee,
           (c.created_at > now() - interval '{win}')                AS conversation_neuve
      FROM arac.conversations c
      CROSS JOIN LATERAL (
          SELECT count(*) FILTER (
                     WHERE m.received_at > now() - interval '{win}') AS messages_fenetre,
                 count(*)                                            AS messages_total,
                 max(m.id)                                           AS dernier_message
            FROM arac.raw_messages m
           WHERE m.conversation_id = c.id
      ) s
     WHERE s.messages_fenetre > 0
        OR c.created_at > now() - interval '{win}'
        OR c.curated_at > now() - interval '{win}'
     ORDER BY s.messages_fenetre DESC, c.curated_at DESC NULLS LAST
     LIMIT 20
"""

_HL_CYCLES = """
    SELECT r.id,
           r.slot_key,
           r.trigger,
           r.model,
           r.status,
           r.skip_reason,
           r.stop_reason,
           r.items,
           r.atoms_created,
           r.atoms_superseded,
           r.atoms_quarantined,
           r.est_input_tokens,
           r.started_at,
           r.ended_at
      FROM arac.run_receipts r
     WHERE r.started_at > now() - interval '{win}'
     ORDER BY r.started_at DESC
     LIMIT 30
"""

_BOUNDS = "SELECT now() - interval '{win}' AS since, now() AS until"

_HIGHLIGHTS: tuple[tuple[str, str], ...] = (
    ("new_atoms", _HL_NEW_ATOMS),
    ("enriched_atoms", _HL_ENRICHED_ATOMS),
    ("progressed_projects", _HL_PROJECTS),
    ("touched_scopes", _HL_SCOPES),
    ("root_debt", _HL_ROOT_DEBT),
    ("absorbed_conversations", _HL_CONVERSATIONS),
    ("cycles", _HL_CYCLES),
)


# ============================================================================
# Chemins de preuve — servis, jamais déduits par le client
# ============================================================================


def _src_metric(key: str, window: str = A.DEFAULT_WINDOW) -> dict[str, Any]:
    """La source d'une phrase, POUR LA FENÊTRE de cette phrase.

    ``/cc/v1/evidence/{key}`` exécute toujours la projection canonique 24 h du
    registre. Y renvoyer une phrase composée sur 7 j ou 30 j servait une preuve
    qui CONTREDISAIT la phrase — le pire défaut possible sur un produit dont la
    promesse est la traçabilité. La source porte donc sa fenêtre, son href
    fenêtré, et le SQL réellement rejouable pour cette fenêtre-là.
    """
    spec = A.SPEC_BY_KEY[key]
    # `_flat` et non un `" ".join(split())` local : la mise sur une ligne doit
    # passer par la MÊME garde que partout ailleurs, sans quoi un commentaire
    # `--` ressortirait ici après avoir été chassé de `_run_evidence`.
    return {"kind": "metric", "ref": key, "label": spec.label, "window": window,
            "href": f"{_PREFIX}/today/evidence/{key}?window={window}",
            "sql": _flat(spec.evidence_sql(window))}


def _src_atom(atom: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "atom", "ref": atom.get("id"), "label": atom.get("key"),
            "href": f"{_PREFIX}/atoms/{atom.get('id')}"}


def _src_project(project: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "project", "ref": project.get("project_id"), "label": project.get("label"),
            "href": f"{_PREFIX}/projects/{project.get('project_id')}"}


def _src_scope(scope: str) -> dict[str, Any]:
    return {"kind": "scope", "ref": scope, "label": scope,
            "href": f"{_PREFIX}/atoms?scope={quote(str(scope), safe='')}"}


def _src_conversation(conv: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "conversation", "ref": conv.get("uid"), "label": conv.get("title"),
            "href": f"{_PREFIX}/conversations/{quote(str(conv.get('uid')), safe='')}"}


# ============================================================================
# LES DELTAS — les Spec du registre, projetées sur la fenêtre demandée
# ============================================================================


def _deltas(conn: Any, window: str) -> list[dict[str, Any]]:
    """Exécute chaque ``Spec`` et rend son enveloppe complète.

    L'état est évalué par ``service._state_for`` — la MÊME fonction que le
    registre : un seuil dépassé se lit pareil ici et sur la page des métriques.
    """
    out: list[dict[str, Any]] = []
    for spec in A.SPECS:
        metric = spec.metric(window)
        item: dict[str, Any] = {
            "key": spec.key,
            "label": spec.label,
            "unit": spec.unit,
            "definition": spec.definition,
            "formula": spec.formula,
            "window": window,
            "direction": spec.direction,
            "target": spec.target,
            "measurable": spec.measurable,
            "evidence": {
                "kind": "metric",
                "ref": spec.key,
                "label": spec.evidence_label,
                # CE QUI ÉTAIT FAUX : `href` pointait sur `/cc/v1/evidence/{key}`,
                # qui exécute TOUJOURS la projection canonique 24 h du registre.
                # Sur ?window=30d le cockpit affichait 116 944 messages et ouvrait
                # une preuve à 403 lignes : un facteur 30 entre le chiffre et sa
                # preuve, sur le produit dont la promesse est la traçabilité.
                # C'est exactement le défaut consigné par le cerveau lui-même
                # (atome `cockpit-preuve-narrative-ignorait-fenetre`), corrigé
                # pour la narration (`_src_metric`) et oublié ici.
                #
                # CE QUE CETTE VERSION GARANTIT : le chemin de preuve d'un delta
                # porte la fenêtre du delta. `href`, `href_window`, `sql` et
                # `value_sql` parlent tous de la MÊME fenêtre — il n'y a plus de
                # lecture de ce bloc qui puisse contredire la valeur servie.
                "href": f"{_PREFIX}/today/evidence/{spec.key}?window={window}",
                "sql": _flat(spec.evidence_sql(window)),
                "href_window": window,
                # La projection canonique du registre reste atteignable, mais
                # NOMMÉE comme telle : elle ne prouve que la fenêtre de 24 h.
                "canonical_href": f"{_PREFIX}/evidence/{spec.key}",
                "canonical_window": A.DEFAULT_WINDOW,
            },
            "value_sql": _flat(spec.sql(window)),
        }
        metric_id = spec.key  # identifiant de métrique, cf. `_run_evidence`
        try:
            rows = _rows(conn, spec.sql(window), where=f"delta {spec.key}")
        except Exception as exc:  # noqa: BLE001 — une panne se dit, elle ne fait pas 500
            logger.warning("cc_v1.today_delta_failed",
                           extra={"metric_id": metric_id, "error": type(exc).__name__})
            out.append(item | {"value": None, "state": "unavailable",
                               "reason": f"source indisponible ({type(exc).__name__})"})
            continue

        row = rows[0] if rows else {}
        value = row.get("value")
        if value is None:
            # Règle I2 : jamais un zéro. Une mesure déclarée non mesurable porte
            # SA raison, pas la raison générique du service.
            #
            # Et si la REQUÊTE a projeté une raison, c'est elle qui prime — même
            # ordre de priorité que `service.metric_value`. POURQUOI : une raison
            # écrite dans la Spec affirme l'état d'une base qu'elle n'a pas
            # regardée, et continue de l'affirmer quand cet état change. Celle
            # que la requête rend a été CONSTATÉE à l'instant où on l'a lue.
            reason = row.get("reason") or spec.unavailable_reason or (
                "la requête n'a retourné aucune ligne" if not rows
                else "valeur nulle retournée par la source")
            out.append(item | {"value": None, "state": "unavailable", "reason": reason,
                               "detail": row.get("detail"),
                               "gesture": row.get("gesture") or spec.unavailable_gesture or None,
                               "substitute": spec.unavailable_substitute or None})
            continue

        out.append(item | {"value": value, "detail": row.get("detail"),
                           "state": service._state_for(metric, value), "reason": None})
    return out


# ============================================================================
# LA SYNTHÈSE — des clés de gabarit et des sources, jamais des phrases
# ============================================================================


class _Draft:
    """Accumulateur de phrases. Refuse ce qui n'est pas sourcé.

    C'est le point d'application de R-18 : une phrase sans source ne peut pas
    entrer, donc ne peut pas sortir. La contrainte est ici, pas dans une consigne.
    """

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.refused: list[str] = []

    def say(self, template_key: str, args: dict[str, Any],
            sources: list[dict[str, Any]]) -> None:
        clean = [s for s in sources if s and s.get("href")]
        if not clean:
            self.refused.append(template_key)
            logger.warning("cc_v1.today_sentence_without_source",
                           extra={"template": template_key})
            return
        self.items.append({
            "template_key": template_key,
            "priority": _P.get(template_key, 999),
            "rule": SENTENCE_RULES.get(template_key, ""),
            "args": args,
            "sources": clean,
        })


def _value(deltas: dict[str, dict[str, Any]], key: str) -> Any:
    """La valeur déjà servie d'un delta, ou ``None`` si la mesure a échoué."""
    return (deltas.get(key) or {}).get("value")


def _draft_sentences(window: str, deltas: list[dict[str, Any]],
                     highlights: dict[str, list[dict[str, Any]]],
                     dormant: dict[str, Any]
                     ) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Sélectionne les phrases. Chaque condition porte sur une valeur DÉJÀ SERVIE.

    Aucune heuristique, aucun seuil inventé : un projet « progresse » s'il a gagné
    au moins un atome, point. La règle de chaque phrase est publiée dans
    ``SENTENCE_RULES`` et servie au client avec la phrase.

    Rend ``(kept, refused, omitted)`` : ce qui est servi, ce qui a été refusé
    faute de source, et ce que le plafond a écarté — les trois sont publiés.
    """
    d = {x["key"]: x for x in deltas}
    win = A.WINDOW_LABELS[window]
    draft = _Draft()

    convs = _value(d, "today_conversations_received")
    curated = _value(d, "today_conversations_curated")
    atoms = _value(d, "today_atoms_created")
    enriched = _value(d, "today_atoms_enriched")
    superseded = _value(d, "today_atoms_superseded")
    messages = _value(d, "today_messages_absorbed")
    cycles = _value(d, "today_cycles_run")
    quarantined = _value(d, "today_cycles_quarantined")
    dropped = _value(d, "today_candidates_dropped")
    recalls = _value(d, "today_recall_served")
    tokens = _value(d, "today_tokens_spent")
    per_atom = _value(d, "today_cost_per_atom")

    # --- La journée vide se DIT. C'est une information, pas un vide à masquer. --
    if convs == 0 and messages == 0 and atoms == 0 and enriched == 0:
        draft.say("nothing_learned", {"window": win},
                  [_src_metric("today_atoms_created", window),
                   _src_metric("today_conversations_received", window),
                   _src_metric("today_messages_absorbed", window)])

    # --- L'apprentissage du jour ------------------------------------------
    if atoms:
        if convs:
            draft.say("learning_today",
                      {"window": win, "conversations": convs, "atoms": atoms},
                      [_src_metric("today_conversations_received", window),
                       _src_metric("today_atoms_created", window)])
        else:
            draft.say("learning_without_conversation",
                      {"window": win, "atoms": atoms},
                      [_src_metric("today_atoms_created", window),
                       _src_metric("today_conversations_received", window)])

    # --- Les projets qui progressent (déjà triés par delta décroissant) ----
    for project in (highlights.get("progressed_projects") or [])[:MAX_PROJECT_SENTENCES]:
        if not project.get("atomes_gagnes"):
            continue
        draft.say("project_progress",
                  {"project": project.get("label"), "window": win,
                   "atoms": project.get("atomes_gagnes")},
                  [_src_project(project), _src_metric("today_projects_progressed", window)])

    # --- La dette de racine, quand elle mord DANS la fenêtre ----------------
    for scope in (highlights.get("root_debt") or []):
        if scope.get("atomes_crees"):
            draft.say("scope_root_debt",
                      {"scope": scope.get("scope"), "atoms": scope.get("atomes_crees")},
                      [_src_scope(scope.get("scope")), _src_metric("today_scopes_touched", window)])
            break

    # --- Le scope de tête ---------------------------------------------------
    top_scope = next((s for s in (highlights.get("touched_scopes") or [])
                      if s.get("atomes_crees")), None)
    if top_scope:
        draft.say("scope_enriched",
                  {"scope": top_scope.get("scope"), "window": win,
                   "created": top_scope.get("atomes_crees")},
                  [_src_scope(top_scope.get("scope")), _src_metric("today_scopes_touched", window)])

    # --- Le dernier souvenir retenu ----------------------------------------
    newest = (highlights.get("new_atoms") or [None])[0]
    if newest:
        draft.say("notable_atom",
                  {"kind": newest.get("kind"), "scope": newest.get("scope"),
                   "key": newest.get("key")},
                  [_src_atom(newest), _src_metric("today_atoms_created", window)])

    # --- L'ingestion --------------------------------------------------------
    top_conv = next((c for c in (highlights.get("absorbed_conversations") or [])
                     if c.get("messages_fenetre")), None)
    if messages and top_conv:
        draft.say("conversation_absorbed",
                  {"messages": messages, "window": win,
                   "top_messages": top_conv.get("messages_fenetre"),
                   "title": top_conv.get("title") or top_conv.get("uid")},
                  [_src_conversation(top_conv), _src_metric("today_messages_absorbed", window)])

    if enriched:
        draft.say("atoms_enriched", {"atoms": enriched, "window": win},
                  [_src_metric("today_atoms_enriched", window)])
    if superseded:
        draft.say("atoms_superseded", {"atoms": superseded, "window": win},
                  [_src_metric("today_atoms_superseded", window)])

    # --- La machine ---------------------------------------------------------
    if quarantined:
        draft.say("cycle_quarantined",
                  {"quarantined": quarantined, "total": cycles,
                   "done": _value(d, "today_cycles_done"), "window": win},
                  [_src_metric("today_cycles_quarantined", window),
                   _src_metric("today_cycles_run", window),
                   _src_metric("today_cycles_done", window)])

    if isinstance(convs, (int, float)) and isinstance(curated, (int, float)):
        if convs > curated:
            draft.say("queue_growing",
                      {"received": convs, "curated": curated, "window": win},
                      [_src_metric("today_conversations_received", window),
                       _src_metric("today_conversations_curated", window)])
        elif curated > convs:
            draft.say("queue_shrinking",
                      {"received": convs, "curated": curated, "window": win},
                      [_src_metric("today_conversations_curated", window),
                       _src_metric("today_conversations_received", window)])

    if dropped:
        draft.say("candidates_dropped", {"dropped": dropped, "window": win},
                  [_src_metric("today_candidates_dropped", window)])

    # --- L'usage ------------------------------------------------------------
    if recalls:
        draft.say("recall_served", {"receipts": recalls, "window": win},
                  [_src_metric("today_recall_served", window)])
    elif recalls == 0:
        draft.say("recall_idle", {"window": win}, [_src_metric("today_recall_served", window)])

    # --- Le coût ------------------------------------------------------------
    if tokens:
        if per_atom is not None:
            draft.say("cost_today",
                      {"tokens": tokens, "window": win, "per_atom": per_atom},
                      [_src_metric("today_tokens_spent", window), _src_metric("today_cost_per_atom", window)])
        else:
            draft.say("cost_without_yield", {"tokens": tokens, "window": win},
                      [_src_metric("today_tokens_spent", window), _src_metric("today_atoms_created", window)])

    # --- Le savoir dormant --------------------------------------------------
    if isinstance(dormant.get("value"), (int, float)) and dormant["value"]:
        draft.say("dormant_knowledge", {"atoms": dormant["value"]},
                  [{"kind": "metric", "ref": "dormant_knowledge",
                    "label": dormant.get("label") or "Savoir jamais rappelé",
                    "href": f"{_PREFIX}/evidence/dormant_knowledge"}])

    # --- Ce que je ne sais PAS mesurer -------------------------------------
    # Jamais « aucune contradiction », jamais « aucune régression » : l'absence de
    # mesure se dit comme telle, avec sa raison. C'est la phrase la moins
    # prioritaire — sa place dans le bandeau est donc RÉSERVÉE avant la
    # troncature (cf. la fin de cette fonction), et non laissée au hasard du
    # nombre de nouvelles du jour.
    #
    # `_src_metric(item["key"])` sans fenêtre servait le href canonique 24 h sous
    # une phrase composée sur 7 ou 30 jours : la même erreur que sur les deltas,
    # au même endroit du document. La fenêtre est passée ici aussi.
    for item in deltas:
        if item.get("measurable") is False and item.get("state") == "unavailable":
            draft.say("measure_unavailable",
                      {"measure": item.get("label"), "reason": item.get("reason")},
                      [_src_metric(item["key"], window)])

    # Tri stable : le rang déclaré décide, et à rang égal l'ordre du SQL
    # (delta décroissant) est conservé. Aucune arithmétique.
    draft.items.sort(key=lambda s: s["priority"])

    # CE QUI ÉTAIT FAUX : `kept = draft.items[:MAX_SENTENCES]` tronquait APRÈS le
    # tri, sans rien dire. Sur cette instance 16 à 18 phrases sont tirées et 6
    # servies ; les TROIS `measure_unavailable` (rang 95, le plus faible) étaient
    # coupées aux trois fenêtres, systématiquement. Or ce sont elles, et elles
    # seules, qui empêchent le bandeau de laisser croire « aucune contradiction,
    # aucune régression, aucun lien créé » : la doctrine en tête de ce fichier les
    # désigne comme l'antidote aux trois phrases interdites, et le plafond les
    # supprimait toutes. Le commentaire qui promettait qu'elles « remontent les
    # jours calmes » était faux : au plus calme observé, 13 phrases les précèdent.
    #
    # CE QUE CETTE VERSION GARANTIT : les mesures impossibles sont servies
    # d'abord — leur place est RÉSERVÉE, le plafond mord sur le reste — et ce que
    # le plafond a écarté est PUBLIÉ (`omitted_by_cap`), avec sa règle et sa
    # priorité. Le bandeau ne peut plus passer pour exhaustif alors qu'il ne
    # montre qu'un tiers de ce que le moteur a tiré.
    impossibles = [s for s in draft.items if s["template_key"] == "measure_unavailable"]
    autres = [s for s in draft.items if s["template_key"] != "measure_unavailable"]
    place = max(0, MAX_SENTENCES - len(impossibles))
    kept = sorted(autres[:place] + impossibles[:MAX_SENTENCES],
                  key=lambda s: s["priority"])
    gardees = {id(s) for s in kept}
    # Les phrases écartées sont servies ENTIÈRES — sources comprises. Une phrase
    # que le client peut annoncer (« 10 phrases de plus ») mais pas ouvrir serait
    # une affirmation sans preuve, c'est-à-dire précisément ce que ce module
    # refuse d'émettre.
    omitted = [{"template_key": s["template_key"], "priority": s["priority"],
                "rule": s["rule"], "args": s["args"], "sources": s["sources"]}
               for s in draft.items if id(s) not in gardees]
    for i, sentence in enumerate(kept):
        sentence["order"] = i
    return kept, draft.refused, omitted


# ============================================================================
# API publique
# ============================================================================


def today(window: str = A.DEFAULT_WINDOW) -> dict[str, Any]:
    """La journée du cerveau : deltas, faits saillants, synthèse.

    Ne lève jamais : une panne rend ``state='unavailable'`` avec sa raison.
    """
    win = _window(window)
    bounds_sql = _BOUNDS.format(win=A.WINDOWS[win])
    executed: dict[str, str] = {"bornes": _flat(bounds_sql)}

    try:
        with _readonly() as conn:
            bounds = (_rows(conn, bounds_sql, where="bornes") or [{}])[0]

            deltas = _deltas(conn, win)

            highlights: dict[str, Any] = {}
            for name, template in _HIGHLIGHTS:
                sql = template.format(win=A.WINDOWS[win])
                executed[name] = _flat(sql)
                try:
                    highlights[name] = _rows(conn, sql, where=name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("cc_v1.today_highlight_failed",
                                   extra={"block": name, "error": type(exc).__name__})
                    highlights[name] = []
                    highlights.setdefault("unavailable", {})[name] = (
                        f"source indisponible ({type(exc).__name__})")

            dormant = service.metric_value("dormant_knowledge", conn=conn)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cc_v1.today_failed", extra={"error": type(exc).__name__})
        return {"window": win, "state": "unavailable",
                "reason": f"source indisponible ({type(exc).__name__})",
                "deltas": [], "highlights": {}, "narrative": {"sentences": []},
                "computed_at": service._now()}

    sentences, refused, omitted = _draft_sentences(win, deltas, highlights, dormant)

    return {
        "window": win,
        "window_label": A.WINDOW_LABELS[win],
        "windows": sorted(A.WINDOWS),
        "since": bounds.get("since"),
        "until": bounds.get("until"),
        "state": "ok",
        "deltas": deltas,
        "highlights": highlights,
        "narrative": {
            "sentences": sentences,
            "templates": NARRATIVE_TEMPLATES,
            "unknown_template": UNKNOWN_TEMPLATE,
            "max_sentences": MAX_SENTENCES,
            "refused_without_source": refused,
            # Ce que le plafond a écarté. Sans ces deux clés, un bandeau de six
            # phrases sur dix-huit tirées passait pour la totalité de ce que le
            # cerveau avait à dire de sa fenêtre.
            "drafted": len(sentences) + len(omitted),
            "omitted_by_cap": omitted,
        },
        # Ce qui n'est pas déjà couvert par la preuve de chaque delta : les six
        # requêtes de faits saillants et les bornes de la fenêtre, telles
        # qu'exécutées. Copiables dans psql, donc opposables.
        "evidence": {"kind": "sql", "sql": ";\n\n".join(executed.values()),
                     "blocks": executed},
        "computed_at": service._now(),
    }


def narrative(window: str = A.DEFAULT_WINDOW) -> dict[str, Any]:
    """La seule synthèse, pour le bandeau d'accueil.

    Même sélection, même sources, mêmes gabarits que ``today()`` — il n'existe
    qu'UNE synthèse. Deux implémentations de la même phrase finiraient par se
    contredire, et le bandeau cesserait d'être opposable.
    """
    full = today(window)
    block = full.get("narrative") or {}
    return {
        "window": full.get("window"),
        "window_label": full.get("window_label"),
        "windows": full.get("windows"),
        "since": full.get("since"),
        "until": full.get("until"),
        "state": full.get("state", "unavailable"),
        "reason": full.get("reason"),
        "sentences": block.get("sentences", []),
        "templates": NARRATIVE_TEMPLATES,
        "unknown_template": UNKNOWN_TEMPLATE,
        "rules": SENTENCE_RULES,
        "max_sentences": MAX_SENTENCES,
        "refused_without_source": block.get("refused_without_source", []),
        "drafted": block.get("drafted"),
        "omitted_by_cap": block.get("omitted_by_cap", []),
        "doctrine": ("le serveur ne compose aucune phrase : il désigne un gabarit et "
                     "fournit ses arguments et ses sources ; un gabarit inconnu "
                     "s'affiche « [phrase inconnue : clé] », jamais un texte inventé"),
        "evidence": full.get("evidence"),
        "computed_at": full.get("computed_at"),
    }


# ============================================================================
# Enregistrement
# ============================================================================


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre ``/cc/v1/today`` et ``/cc/v1/today/narrative``.

    GET uniquement, garde de session sur chaque route, journal de lecture sur
    chaque accès, handlers synchrones (threadpool) — doctrine identique au socle.
    """

    @a.get(f"{_PREFIX}/today")
    def cc_v1_today(
        principal: dict = Depends(session_api),
        window: str = Query(default=A.DEFAULT_WINDOW, max_length=8),
    ) -> JSONResponse:
        """La journée du cerveau : ce qu'il a appris, retenu, remplacé, raté, coûté.

        ``window`` est une CLÉ (24h · 7d · 30d), pas un intervalle : une valeur
        inconnue retombe sur 24 h et ne construit aucun SQL.
        """
        audit_read_log(f"{_PREFIX}/today", principal.get("sub", "?"))
        return JSONResponse(today(window=window))

    @a.get(f"{_PREFIX}/today/evidence/{{key}}")
    def cc_v1_today_evidence(
        key: str,
        principal: dict = Depends(session_api),
        window: str = Query(default=A.DEFAULT_WINDOW),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> JSONResponse:
        """La preuve d'un delta POUR LA FENÊTRE demandée.

        Le registre ne connaît que la projection 24 h ; cette route projette la
        même ``Spec`` sur la fenêtre voulue, de sorte que la preuve ouverte
        depuis une phrase de 30 jours parle bien de 30 jours. Le SQL exécuté est
        rendu avec le résultat : la preuve reste rejouable en psql.
        """
        audit_read_log(f"{_PREFIX}/today/evidence/{key}", principal.get("sub", "?"))
        spec = A.SPEC_BY_KEY.get(key)
        if spec is None or window not in A.WINDOWS:
            return JSONResponse({"key": key, "state": "unavailable", "rows": [],
                                 "reason": "mesure ou fenêtre inconnue du registre"})
        return JSONResponse(_run_evidence(spec, window, limit))

    @a.get(f"{_PREFIX}/today/narrative")
    def cc_v1_today_narrative(
        principal: dict = Depends(session_api),
        window: str = Query(default=A.DEFAULT_WINDOW, max_length=8),
    ) -> JSONResponse:
        """La synthèse du bandeau : des gabarits, des arguments, des sources.

        Aucune phrase n'est composée ici. Le client assemble
        ``templates[template_key].format(**args)`` et retombe sur
        ``unknown_template`` si la clé lui est inconnue.
        """
        audit_read_log(f"{_PREFIX}/today/narrative", principal.get("sub", "?"))
        return JSONResponse(narrative(window=window))
