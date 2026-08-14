"""Couche de liens atome<->atome — TROIS types d'arêtes, dont une INFÉRÉE.

CE QUE CE FICHIER DISAIT, ET QUI ÉTAIT FAUX
-------------------------------------------
Cette docstring se contredisait d'une ligne à l'autre. Elle s'ouvrait sur
« increment 1 : arêtes CERTAINES only », puis annonçait dix-huit lignes plus
bas que « `semantic_neighbor` est DÉFÉRÉ à l'increment 2 ». Or l'increment 2
est ARRIVÉ, dans ce fichier même : `mutual_knn_edges`, `_UPSERT_SEMANTIC_SQL`,
les constantes calibrées `SEMANTIC_THRESHOLD` / `SEMANTIC_TOPK`, et le
compteur `semantic_neighbor` que `recompute` rend à chaque tour. Le texte
décrivait un état du code qui avait cessé d'exister, et il le décrivait deux
fois — c'est la forme habituelle de cette panne : on ajoute la fonctionnalité,
on oublie que l'en-tête la niait.

Conséquence concrète, et c'est ce qui rend la fausseté coûteuse : quelqu'un
qui lit « arêtes CERTAINES only » ne se demande pas quel SEUIL a été retenu,
ni si une arête peut être un faux positif. Il en existe pourtant, par
construction — θ=0.25 n'est pas zéro.

CE QUE LE CODE FAIT VRAIMENT
----------------------------
`arac.atom_links` = cache dérivé (comme `project_registry`), recalculé au tick
cortex AVANT le spend gate (frais même IA OFF, coût IA 0 — aucune donnée
nouvelle, tout est déjà en base ; l'embedding utilisé est celui que l'atome
porte déjà).

DEUX types CERTAINS (seuil-free, ~0 faux positif) :

  - `supersedes`  (dirigée, src=remplaçant, dst=retiré) : dérivée de la colonne
    `superseded_by`. SPAN les statuts — l'atome retiré est `status='superseded'`,
    donc AUCUN filtre `status='active'` du côté retiré (vérifié en prod : les 15
    lignes `superseded_by` sont toutes `superseded`).
  - `same_thread` (dirigée, chaîne chronologique) : au sein d'un groupe de
    provenance (conversation), on relie chaque atome ACTIF au SUIVANT par
    `created_at`. LINÉAIRE (N-1 arêtes par groupe), JAMAIS une clique (N²) — c'est
    le garde-fou anti-hairball : une conversation « monstre » de 71 atomes produit
    70 arêtes, pas 2485.

UN type INFÉRÉ, et il faut le lire comme tel :

  - `semantic_neighbor` (NON dirigée, canonique src<dst) : mutual-kNN sur les
    embeddings. Un lien n'existe que si chacun des deux atomes est dans les
    `SEMANTIC_TOPK` (=6) plus proches voisins de l'autre ET que leur distance
    cosinus est ≤ `SEMANTIC_THRESHOLD` (=0.25). Les paires dont les DEUX
    extrémités sont de kind triade (`mission`, `delivery`) sont exclues.
    `score = 1 - distance`.

    C'est le seul type qui peut se tromper. La mutualité est ce qui borne le
    dégât : elle plafonne structurellement le degré à K, donc aucun atome ne
    devient un hub qui relierait tout à tout. La calibration (lift plat ~8.3×,
    couverture ~46-48 %) est consignée à l'endroit des constantes, avec la
    consigne de ne pas la re-dériver à la légère.

Les fonctions `same_thread_pairs` / `supersede_pairs` / `mutual_knn_edges` sont
PURES (zéro I/O) : elles sont la source de vérité de la dérivation ; le SQL de
`recompute` les MIROITE, et le benchmark offline (p0/nrb_links_benchmark.py)
les réutilise sur un snapshot read-only.

Zéro LLM — « déterministe » serait maintenant trop dire : `semantic_neighbor`
dépend des embeddings et d'un seuil. Additif ; recall / context_router /
curateur GELÉS.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# ----------------------------------------------------------------------------
# Helpers PURS (mirroir exact du SQL) — testables sans DB, réutilisables offline.
# ----------------------------------------------------------------------------


def _grp(atom: dict[str, Any]) -> str | None:
    """Clé de groupe de provenance bi-format (V2 conversation_uid prioritaire,
    sinon V1 'raw:'||curator_raw_id). None si l'atome n'a aucune provenance.

    Accepte les deux formes de dict :
      - snapshot aplati : clés `conv_uid` / `raw_id` ;
      - row DB          : clé `source_ref` (jsonb -> dict) avec `conversation_uid`
        / `curator_raw_id`.
    """
    conv = atom.get("conv_uid")
    raw = atom.get("raw_id")
    if conv is None and raw is None:
        sr = atom.get("source_ref") or {}
        if isinstance(sr, dict):
            conv = sr.get("conversation_uid")
            raw = sr.get("curator_raw_id")
    if conv:
        return str(conv)
    if raw:
        return "raw:" + str(raw)
    return None


def same_thread_pairs(atoms: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Arêtes `same_thread` (src, dst, grp) : chaîne temporelle intra-groupe.

    ACTIFS seulement, provenance requise. Ordre `(created_at, id::text)`
    déterministe — même tie-break que le SQL (`ORDER BY created_at, id::text`).
    LINÉAIRE : (taille_groupe - 1) arêtes par groupe, jamais une clique.
    """
    live = [a for a in atoms if a.get("status") == "active" and _grp(a) is not None]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in live:
        groups[_grp(a)].append(a)  # type: ignore[index]
    pairs: list[tuple[str, str, str]] = []
    for grp, members in groups.items():
        members.sort(key=lambda a: (a["created_at"], str(a["id"])))
        for i in range(len(members) - 1):
            pairs.append((str(members[i]["id"]), str(members[i + 1]["id"]), grp))
    return pairs


def supersede_pairs(atoms: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Arêtes `supersedes` (src=remplaçant, dst=retiré) dérivées de `superseded_by`.

    SPAN les statuts : aucun filtre — l'atome porteur de `superseded_by` EST le
    retiré (`status='superseded'`), son `superseded_by` pointe le remplaçant.
    """
    out: list[tuple[str, str]] = []
    for a in atoms:
        sb = a.get("superseded_by")
        if sb:
            out.append((str(sb), str(a["id"])))
    return out


# --- semantic_neighbor (increment 2) : paramètres CALIBRÉS (lift-vs-θ, read-only) ---
# Calibration : lift plat ~8.3× sur θ (pas de pic de précision) ; θ=0.25 -> ~46-48%
# de couverture, degré STRUCTURELLEMENT plafonné à K=6 (mutual-kNN sur les 6 NN
# propres -> aucun hub). Actifs seulement. NE PAS re-dériver ces valeurs.
SEMANTIC_THRESHOLD = 0.25
SEMANTIC_TOPK = 6
TRIADE_KINDS = ("mission", "delivery")


def mutual_knn_edges(
    knn_rows,
    *,
    theta: float = SEMANTIC_THRESHOLD,
    triade_kinds: tuple[str, ...] = TRIADE_KINDS,
) -> list[tuple[str, str, float, float]]:
    """Combine des candidats kNN DIRIGÉS en arêtes `semantic_neighbor` FINALES —
    MIROIR EXACT de la CTE `mutual` du SQL de population (helper pur, testé, et
    réutilisé par le benchmark offline).

    `knn_rows` : itérable de (src, dst, dist, src_kind, dst_kind) = les voisins
    top-K de chaque atome (déjà bornés à K par la source). Règle :
      - garder `dist <= theta` ;
      - MUTUEL : (src,dst) ET (dst,src) présents (chacun dans le top-K de l'autre) ;
      - EXCLURE si les DEUX endpoints sont de kind triade (mission/delivery) ;
      - canonique `src < dst`, une seule ligne ; score = 1 - dist.
    Retourne (src, dst, score, dist), src < dst.
    """
    directed: dict[tuple[str, str], float] = {}
    kind: dict[str, str | None] = {}
    for row in knn_rows:
        src, dst, dist, sk, dk = row
        if dist is None or dist > theta:
            continue
        src, dst = str(src), str(dst)
        directed[(src, dst)] = float(dist)
        kind[src] = sk
        kind[dst] = dk
    triade = set(triade_kinds)
    out: list[tuple[str, str, float, float]] = []
    for (src, dst), dist in directed.items():
        if src >= dst:  # canonique
            continue
        if (dst, src) not in directed:  # mutuel requis
            continue
        if kind.get(src) in triade and kind.get(dst) in triade:  # both-triade exclu
            continue
        out.append((src, dst, 1.0 - dist, dist))
    return out


# ----------------------------------------------------------------------------
# Population (tick cortex) — pur SQL, idempotent (UPSERT + stale sweep), atomique.
# ----------------------------------------------------------------------------

# NB direction supersedes : src = superseded_by (le remplaçant), dst = id (le
# retiré). AUCUN filtre de statut (le retiré est 'superseded').
_UPSERT_SUPERSEDES_SQL = """
INSERT INTO arac.atom_links (src_atom_id, dst_atom_id, relation_type, directed, score, evidence, updated_at)
SELECT superseded_by, id, 'supersedes', true, 1.0,
       jsonb_build_object('source', 'superseded_by_col'), now()
FROM arac.memory_atoms
WHERE superseded_by IS NOT NULL
ON CONFLICT (src_atom_id, relation_type, dst_atom_id)
    DO UPDATE SET score = EXCLUDED.score, evidence = EXCLUDED.evidence, updated_at = now()
"""

# Chaîne temporelle intra-groupe : LEAD par (created_at, id::text). ACTIFS seulement,
# provenance requise (COALESCE V2 conversation_uid -> V1 raw). LINÉAIRE.
_UPSERT_SAME_THREAD_SQL = """
WITH prov AS (
    SELECT id, created_at,
           COALESCE(source_ref->>'conversation_uid',
                    'raw:' || (source_ref->>'curator_raw_id')) AS grp
    FROM arac.memory_atoms
    WHERE status = 'active'
      AND COALESCE(source_ref->>'conversation_uid', source_ref->>'curator_raw_id') IS NOT NULL
),
chain AS (
    SELECT id AS src,
           LEAD(id) OVER (PARTITION BY grp ORDER BY created_at, id::text) AS dst,
           grp
    FROM prov
)
INSERT INTO arac.atom_links (src_atom_id, dst_atom_id, relation_type, directed, score, evidence, updated_at)
SELECT src, dst, 'same_thread', true, 1.0, jsonb_build_object('grp', grp), now()
FROM chain
WHERE dst IS NOT NULL
ON CONFLICT (src_atom_id, relation_type, dst_atom_id)
    DO UPDATE SET score = EXCLUDED.score, evidence = EXCLUDED.evidence, updated_at = now()
"""

# semantic_neighbor (increment 2) : mutual-kNN, K=6, θ=0.25, UNDIRECTED (canonique
# src<dst), score=1-dist. MIROIR de mutual_knn_edges. LATERAL = 1 probe HNSW par
# atome actif (~1 s @1.6k) ; self-join sur knn = mutuel ; exclusion both-triade.
# LIMIT est un entier de confiance (constante), θ/triade sont des paramètres liés.
_UPSERT_SEMANTIC_SQL = f"""
WITH knn AS (
    SELECT a.id AS src, a.kind AS src_kind, n.id AS dst, n.kind AS dst_kind,
           (a.embedding <=> n.embedding)::float8 AS dist
    FROM arac.memory_atoms a
    CROSS JOIN LATERAL (
        SELECT m.id, m.embedding, m.kind
        FROM arac.memory_atoms m
        WHERE m.status = 'active' AND m.embedding IS NOT NULL AND m.id <> a.id
        ORDER BY m.embedding <=> a.embedding
        LIMIT {SEMANTIC_TOPK}
    ) n
    WHERE a.status = 'active' AND a.embedding IS NOT NULL
      AND (a.embedding <=> n.embedding) <= %(theta)s
),
mutual AS (
    SELECT k1.src, k1.dst, k1.dist
    FROM knn k1
    JOIN knn k2 ON k2.src = k1.dst AND k2.dst = k1.src
    WHERE k1.src < k1.dst
      AND NOT (k1.src_kind = ANY(%(triade)s) AND k1.dst_kind = ANY(%(triade)s))
)
INSERT INTO arac.atom_links (src_atom_id, dst_atom_id, relation_type, directed, score, evidence, updated_at)
SELECT src, dst, 'semantic_neighbor', false, (1.0 - dist)::real,
       jsonb_build_object('distance', round(dist::numeric, 6)), now()
FROM mutual
ON CONFLICT (src_atom_id, relation_type, dst_atom_id)
    DO UPDATE SET score = EXCLUDED.score, evidence = EXCLUDED.evidence, updated_at = now()
"""

# Sweep : supprime les arêtes NON retouchées ce run (endpoint retiré, provenance
# disparue, voisin qui sort du mutual-kNN/θ…). `run_ts` = now() figé au début de la
# transaction ; les UPSERT ci-dessus posent aussi now() (même valeur) -> `< run_ts`
# ne vise QUE les lignes plus vieilles.
_DELETE_STALE_SQL = "DELETE FROM arac.atom_links WHERE updated_at < %(run_ts)s"

_COUNT_BY_TYPE_SQL = (
    "SELECT relation_type, count(*) FROM arac.atom_links GROUP BY relation_type"
)


async def recompute(conn) -> dict[str, Any]:
    """Recalcule les TROIS types d'arêtes — dont `semantic_neighbor`, qui est INFÉRÉ.

    Cette ligne disait « la couche de liens CERTAINS », et c'était faux depuis
    que l'increment 2 est arrivé : les trois UPSERT ci-dessous en font foi, et
    le dictionnaire rendu compte les trois.

    Idempotent (UPSERT + stale sweep),
    ATOMIQUE (une transaction — le serve ne voit jamais un graphe partiel), 0 coût IA.

    Fonctionne que la connexion soit autocommit (hook cortex) ou non (tests) :
    `conn.transaction()` ouvre un bloc explicite dans les deux cas.
    """
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute("SELECT now()")
            run_ts = (await cur.fetchone())[0]
            await cur.execute(_UPSERT_SUPERSEDES_SQL)
            upserted_sup = cur.rowcount or 0
            await cur.execute(_UPSERT_SAME_THREAD_SQL)
            upserted_thr = cur.rowcount or 0
            await cur.execute(
                _UPSERT_SEMANTIC_SQL,
                {"theta": SEMANTIC_THRESHOLD, "triade": list(TRIADE_KINDS)},
            )
            upserted_sem = cur.rowcount or 0
            await cur.execute(_DELETE_STALE_SQL, {"run_ts": run_ts})
            deleted = cur.rowcount or 0
            await cur.execute(_COUNT_BY_TYPE_SQL)
            by_type = {r[0]: int(r[1]) for r in await cur.fetchall()}
    return {
        "supersedes": int(by_type.get("supersedes", 0)),
        "same_thread": int(by_type.get("same_thread", 0)),
        "semantic_neighbor": int(by_type.get("semantic_neighbor", 0)),
        "upserted": int(upserted_sup + upserted_thr + upserted_sem),
        "deleted": int(deleted),
        "total": int(sum(by_type.values())),
    }


# ----------------------------------------------------------------------------
# Serve (/resume) — 1 requête indexée, zéro LLM, FAIL-OPEN.
# ----------------------------------------------------------------------------

_SUBGRAPH_SQL = """
SELECT src_atom_id::text AS src, dst_atom_id::text AS dst, relation_type, score
FROM arac.atom_links
WHERE src_atom_id = ANY(%(ids)s::uuid[]) OR dst_atom_id = ANY(%(ids)s::uuid[])
"""

_RELATED_ATOMS_SQL = """
SELECT id::text AS id, kind, scope, key, value
FROM arac.memory_atoms
WHERE id = ANY(%(ids)s::uuid[]) AND status IN ('active', 'superseded')
"""


def _build_threads(
    same_thread_edges: list[dict[str, Any]], id_set: set[str]
) -> list[list[str]]:
    """Reconstruit les fils (chaînes ordonnées) à partir des arêtes `same_thread`
    RESTREINTES aux atomes retournés. `same_thread` est linéaire par construction :
    on suit les successeurs depuis les têtes (nœuds sans prédécesseur dans l'ensemble).
    """
    succ: dict[str, str] = {}
    has_pred: set[str] = set()
    nodes: set[str] = set()
    for e in same_thread_edges:
        s, d = e["src"], e["dst"]
        if s in id_set and d in id_set:
            succ[s] = d
            has_pred.add(d)
            nodes.add(s)
            nodes.add(d)
    threads: list[list[str]] = []
    for n in sorted(nodes):
        if n in has_pred:
            continue  # pas une tête
        chain = [n]
        seen = {n}
        cur = n
        while cur in succ and succ[cur] not in seen:
            cur = succ[cur]
            chain.append(cur)
            seen.add(cur)
        if len(chain) > 1:
            threads.append(chain)
    return threads


async def enrich_resume(
    conn, routed_atoms: list[dict[str, Any]], *, enabled: bool, max_related: int = 5
) -> dict[str, Any]:
    """Enrichit /resume avec le sous-graphe de liens (fail-open).

    « CERTAINS » était de trop, et trompeur : `_SUBGRAPH_SQL` ne filtre AUCUN
    `relation_type`. Le /resume sert donc aussi les arêtes `semantic_neighbor`,
    qui sont inférées et peuvent se tromper. Qui lit ce sous-graphe doit le
    savoir — c'est le `relation_type` de chaque arête qui le dit.

    Retourne {links, related_atoms, threads}. Si `enabled` est False, ou aucun
    atome routé, ou table vide, ou TOUTE erreur -> structure VIDE (le /resume de
    base reste bit-identique — jamais casser une reprise). Zéro LLM, 1 requête
    indexée (+1 pour les détails des voisins pris).
    """
    empty = {"links": [], "related_atoms": [], "threads": []}
    if not enabled or not routed_atoms:
        return empty
    ids = [str(a["id"]) for a in routed_atoms]
    id_set = set(ids)
    try:
        from psycopg.rows import dict_row  # lazy : garde le module importable sans psycopg

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SUBGRAPH_SQL, {"ids": ids})
            edges = await cur.fetchall()
            if not edges:
                return empty

            links = [
                {
                    "src": e["src"],
                    "dst": e["dst"],
                    "relation_type": e["relation_type"],
                    "score": float(e["score"]),
                }
                for e in edges
            ]

            # Voisins 1-hop hors bag, classés par meilleur score d'arête, cap.
            best: dict[str, tuple[float, str]] = {}
            for e in edges:
                for endpoint in (e["src"], e["dst"]):
                    if endpoint in id_set:
                        continue
                    sc = float(e["score"])
                    if endpoint not in best or sc > best[endpoint][0]:
                        best[endpoint] = (sc, e["relation_type"])
            ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))
            picked = ranked[:max_related]
            picked_ids = [nid for nid, _ in picked]

            related_atoms: list[dict[str, Any]] = []
            if picked_ids:
                await cur.execute(_RELATED_ATOMS_SQL, {"ids": picked_ids})
                detail = {r["id"]: r for r in await cur.fetchall()}
                for nid, (sc, via) in picked:
                    r = detail.get(nid)
                    if r is None:
                        continue
                    related_atoms.append(
                        {
                            "id": r["id"],
                            "kind": r["kind"],
                            "scope": r["scope"],
                            "key": r["key"],
                            "value": r["value"],
                            "via": via,
                            "score": sc,
                        }
                    )

            # Fils : composantes de same_thread sur bag ∪ voisins pris.
            full_set = id_set | set(picked_ids)
            st_edges = [e for e in links if e["relation_type"] == "same_thread"]
            threads = _build_threads(st_edges, full_set)

            return {"links": links, "related_atoms": related_atoms, "threads": threads}
    except Exception:  # noqa: BLE001 — fail-open : jamais casser une reprise
        return empty
