"""Control Center — collecteurs du cockpit PERCEPTION (V5 vague 1, READ-ONLY).

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY. + IMPORT-NOT-REWRITE.

Moule identique à ``db_metrics.py`` : chaque fonction publique ouvre sa
connexion read-only (double couche rôle arac_readonly + session
``default_transaction_read_only=on``), n'exécute QUE des SELECT (uniquement
des constantes du module ``control_center.sql.perception_queries``), ne lève
JAMAIS — retour ``{"error": "unavailable", ...}`` en dégradé.

Protocole d'honnêteté 3 états (round1-synthese.json) — sonde ``to_regclass``
LIVE, jamais codée en dur :
  - ``deployed``    : table présente ET >= 1 ligne ;
  - ``armed_empty`` : table présente, 0 ligne (état LÉGITIME, ex. shadow OFF) ;
  - ``not_deployed``: ``to_regclass`` NULL (migration en attente de GO) —
                      le SQL est alors AFFICHÉ en documentaire, NON exécuté ;
  - ``partial``     : panneau multi-étages dont SEULE une partie du substrat
                      est présente (rollback/restore partiel) — les étages
                      manquants restent affichés, jamais comblés ;
  - ``unavailable`` : collecte en échec (DB/journal injoignable — sentinel du
                      pattern collecteur, jamais un zéro fabriqué).

Chaque panneau retourne un dict UNIFORME consommé par ``perception_routes`` :
    {"panel": str, "status": str, "as_of": iso8601,
     "tiles": [{"label", "value", "drill"?}],
     "tables": [{"title", "headers", "rows"}],
     "sql": [{"label", "text", "executed": bool, "params": str}],
     "limits": [str, ...]}
"""

from __future__ import annotations

import json
import os
import re
import subprocess  # noqa: S404 — UNIQUEMENT journalctl figé (lecture journald)
from datetime import datetime, timezone
from typing import Any

from control_center.collectors import db_metrics as _dbm
from control_center.sql import perception_queries as pq

_UNAVAILABLE = "unavailable"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    """Connexion read-only — délègue au connecteur commun (monkeypatchable)."""
    return _dbm._connect_readonly()


def _rows(cur, sql: str, params: dict | None = None) -> list[list[Any]]:
    """SELECT (constante du module pq uniquement) → liste de lignes str-ables."""
    cur.execute(sql, params)
    return [list(r) for r in cur.fetchall()]


# ============================================================================
# Sondes d'organe (to_regclass 3 états — jamais comblées)
# ============================================================================

# Tables sondées (identifiants CONSTANTS — jamais une entrée externe).
_ORGAN_TABLES = (
    "ingest_sources",        # 0020
    "capture_manifests",     # 0026
    "ingest_receipts",       # 0021
    "conversations",         # prod
    "raw_messages",          # prod
    "run_receipts",          # prod
    "digestion_review_queue",  # 0028
    "memory_atoms",          # prod
    "context_receipts",      # 0030
    "arac_config",           # prod
    "audit_log",             # prod
)

# Bandeau d'organes (emprunt minimal à la vision A) : état de DÉPLOIEMENT
# uniquement (jamais un feu de santé). Organe → tables requises + table clé
# pour la sonde de lignes.
ORGAN_BANNER = (
    ("SENS (Q1)", ("ingest_sources", "capture_manifests"), "capture_manifests"),
    ("IMMUNITÉ (Q3)", ("ingest_receipts",), "ingest_receipts"),
    ("ESTOMAC (Q2)", ("conversations", "run_receipts"), "run_receipts"),
    ("REVUE (Q5)", ("digestion_review_queue",), "digestion_review_queue"),
    ("NEURONES (Q4)", ("memory_atoms",), "memory_atoms"),
    ("RAPPEL (Q6)", ("context_receipts",), "context_receipts"),
    ("MÉTABOLISME (Q7)", ("run_receipts", "arac_config"), "run_receipts"),
    ("PREUVES (Q8)", ("conversations", "raw_messages"), "raw_messages"),
)


def _probe_tables(cur, tables: tuple[str, ...] = _ORGAN_TABLES) -> dict[str, dict[str, Any]]:
    """Sonde to_regclass + EXISTS par table (identifiants constants).

    EXISTS(SELECT 1 …) et non count(*) : le protocole 3 états n'a besoin que
    de « au moins une ligne » — un count plein par table et par panneau était
    un coût redondant sur la page maître (finding perf round 1)."""
    out: dict[str, dict[str, Any]] = {}
    for t in tables:
        cur.execute("SELECT to_regclass(%(t)s)", {"t": f"arac.{t}"})
        present = cur.fetchone()[0] is not None
        has_rows: bool | None = None
        if present:
            cur.execute(f"SELECT EXISTS (SELECT 1 FROM arac.{t})")  # noqa: S608 — t issu de la liste constante
            has_rows = bool(cur.fetchone()[0])
        out[t] = {
            "present": present,
            "has_rows": has_rows,
            "state": ("not_deployed" if not present
                      else ("deployed" if has_rows else "armed_empty")),
        }
    return out


def organs_overview() -> dict[str, Any]:
    """Bandeau d'organes : état de déploiement LIVE + as_of. Jamais un feu de
    santé — uniquement déployé / armé-vide / non-déployé."""
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                probe = _probe_tables(cur)
        finally:
            conn.close()
        organs = []
        for label, required, key_table in ORGAN_BANNER:
            if any(not probe[t]["present"] for t in required):
                state = "not_deployed"
            else:
                state = probe[key_table]["state"]
            organs.append({"label": label, "state": state})
        return {"organs": organs, "tables": probe, "as_of": _now_iso()}
    except Exception:
        return {"error": _UNAVAILABLE, "organs": [], "tables": {},
                "as_of": _now_iso()}


def _panel(panel: str, status: str, **kw: Any) -> dict[str, Any]:
    return {"panel": panel, "status": status, "as_of": _now_iso(),
            "tiles": kw.get("tiles", []), "tables": kw.get("tables", []),
            "sql": kw.get("sql", []), "limits": kw.get("limits", [])}


def _sql_entry(label: str, text: str, executed: bool, params: str = "") -> dict[str, Any]:
    return {"label": label, "text": text, "executed": executed, "params": params}


def _drill(t: str, **params: str) -> str:
    qs = "".join(f"&{k}={v}" for k, v in params.items())
    return f"/cc/perception/receipts?t={t}{qs}"


# ============================================================================
# Q1 → Q8 — panneaux arrêtés (round1-synthese.json panels_arretes)
# ============================================================================


def panel_q1() -> dict[str, Any]:
    """Q1 PERÇU — registre des sources (SQL AUTORITAIRE importé, autorité de
    lag = capture_manifests.run_ended_at) + volume 24h. Tables absentes du
    schéma → NON DÉPLOYÉ, point. Jamais dégradé à received_at : un message reçu tard
    n'est pas un capteur en retard, et confondre les deux fabrique un
    faux-positif permanent."""
    limits = [
        "Autorité de lag = capture_manifests.run_ended_at (le capteur a tourné) ; "
        "message_lag_minutes (received_at) = contexte SECONDAIRE, jamais l'état.",
        "L'exportateur Mac v2 n'écrit pas encore de capture_manifest → "
        "last_run peut rester vide même table déployée (armé-vide légitime).",
        "statut dérivé = source_registry.derive_source_status IMPORTÉE "
        "(fonction pure, partagée avec le moteur), appliquée ligne à ligne "
        "sur (policy, lag "
        "capteur, seuil) — la déclaration coverage_policy seule ne compte "
        "jamais comme « capté ».",
    ]
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                probe = _probe_tables(cur, ("ingest_sources", "capture_manifests",
                                            "ingest_receipts"))
                if not (probe["ingest_sources"]["present"]
                        and probe["capture_manifests"]["present"]):
                    return _panel(
                        "q1", "not_deployed",
                        sql=[_sql_entry("registre des sources (documentaire, NON exécuté)",
                                        pq.SOURCE_REGISTRY_SQL, False)],
                        # « head prod 0019 » nommait la révision Alembic d'UNE
                        # installation. Le constat (les tables sont absentes) est
                        # juste, puisqu'il vient d'être fait ; sa CAUSE supposée
                        # ne l'est pas — chez un lecteur qui vient d'installer, la
                        # chaîne est à sa tête et les deux tables existent. On
                        # garde le constat, on rend le geste vérifiable.
                        limits=limits + ["arac.ingest_sources et arac.capture_manifests "
                                         "sont absentes de ce schéma : appliquez les "
                                         "migrations en attente (alembic upgrade head)."])
                reg = _rows(cur, pq.SOURCE_REGISTRY_SQL)
                vol_sql, vol_executed = [], False
                inserted = posts = None
                if probe["ingest_receipts"]["present"]:
                    r = _rows(cur, pq.INGEST_VOLUME_24H_SQL)
                    inserted, posts = (r[0] if r else (0, 0))
                    vol_executed = True
        finally:
            conn.close()
        # Statut DÉRIVÉ autoritaire (fonction pure importée) — jamais
        # la seule déclaration coverage_policy (r[3]) : une source « captured »
        # au capteur tari doit apparaître MUTE, pas capté.
        derived = [pq.derive_source_status(
            r[3],
            float(r[8]) if r[8] is not None else None,
            float(r[4]) if r[4] is not None else None) for r in reg]
        reg = [list(r) + [d] for r, d in zip(reg, derived)]
        captured = sum(1 for r in reg if r[3] == "captured")
        ok = sum(1 for d in derived if d == pq.STATUS_OK)
        mute = sum(1 for d in derived if d == pq.STATUS_MUTE)
        pb = sum(1 for d in derived if d == pq.STATUS_PENDING_BOOTSTRAP)
        tiles = [
            {"label": "statut dérivé (derive_source_status importée) — "
                      "OK / MUTE / PENDING_BOOTSTRAP",
             "value": f"{ok} / {mute} / {pb}",
             "drill": _drill("ingest_sources")},
            {"label": "sources captured (politique DÉCLARÉE) / total",
             "value": f"{captured} / {len(reg)}",
             "drill": _drill("ingest_sources")},
        ]
        if vol_executed:
            tiles.append({"label": "messages insérés 24h (accepted+duplicate_noop)",
                          "value": inserted,
                          "drill": _drill("ingest_receipts", window="24")})
            tiles.append({"label": "POST ingest 24h", "value": posts,
                          "drill": _drill("ingest_receipts", window="24")})
        headers = ["source_key", "node_id", "source_type", "policy",
                   "seuil (min)", "exclusion", "active",
                   "dernier run capteur", "lag capteur (min)",
                   "dernier msg reçu", "lag msg (min, secondaire)",
                   "statut dérivé"]
        status = "armed_empty" if all(r[7] is None for r in reg) else "deployed"
        return _panel(
            "q1", status, tiles=tiles,
            tables=[{"title": "Registre des sources (autorité importée)",
                     "headers": headers, "rows": reg}],
            sql=[_sql_entry("source_registry._SOURCE_REGISTRY_SQL (importé)",
                            pq.SOURCE_REGISTRY_SQL, True),
                 _sql_entry("volume 24h (ingest_receipts 0021)",
                            pq.INGEST_VOLUME_24H_SQL, vol_executed)],
            limits=limits)
    except Exception:
        return _panel("q1", _UNAVAILABLE, limits=limits)


def panel_q2() -> dict[str, Any]:
    """Q2 EN DIGESTION — backlog actionnable (gate curateur IMPORTÉ via
    watchdog, jamais le count naïf) + runs ouverts + revue humaine."""
    limits = [
        "Backlog DÉRIVÉ (pas une file matérialisée), pas d'ETA.",
        "Le count naïf 'NOT acked AND EXISTS' est REFUSÉ : il omet retry_count<5, "
        "next_retry_at, exclusion_category et les 3 seuils _gate_params.",
        # Le rôle administrateur porte le nom de CE cerveau (arac_<base>_admin) :
        # nommer « arac_admin » ici enverrait le lecteur ouvrir une session sur
        # le rôle d'un autre cerveau — quand ce nom existe encore.
        "La revue humaine s'observe ici, se traite en psql sous le rôle admin "
        "de ce cerveau (hors cockpit).",
    ]
    gp = pq.gate_params()
    params_desc = f"gate_params() importé = {gp}"
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                probe = _probe_tables(cur, ("run_receipts", "digestion_review_queue"))
                backlog = _rows(cur, pq.ACTIONABLE_BACKLOG_SQL, gp)
                open_runs = _rows(cur, pq.RUNS_OPEN_SQL)
                review_rows, review_executed = [], False
                if probe["digestion_review_queue"]["present"]:
                    review_rows = _rows(cur, pq.REVIEW_PENDING_SQL)
                    review_executed = True
        finally:
            conn.close()
        count, oldest_h, oldest_wait_h = (backlog[0] if backlog else (0, None, None))
        tiles = [
            {"label": "backlog actionnable (gate curateur importé)",
             "value": count, "drill": _drill("backlog_detail")},
            {"label": "âge doyenne — contenu / attente (h)",
             "value": f"{oldest_h if oldest_h is not None else '—'} / "
                      f"{oldest_wait_h if oldest_wait_h is not None else '—'}",
             "drill": _drill("backlog_detail")},
            {"label": "run(s) ouvert(s)", "value": len(open_runs),
             "drill": _drill("run_receipts")},
            {"label": "revue humaine pending",
             "value": (sum(int(r[1]) for r in review_rows)
                       if review_executed else "NON DÉPLOYÉ (0028)"),
             "drill": _drill("review_queue")},
        ]
        tables = [{"title": "Runs ouverts",
                   "headers": ["slot_key", "status", "progress", "started_at"],
                   "rows": open_runs}]
        if review_executed:
            tables.append({"title": "Revue humaine pending par motif",
                           "headers": ["drop_reason", "n"], "rows": review_rows})
        return _panel(
            "q2", "deployed", tiles=tiles, tables=tables,
            sql=[_sql_entry("ingest_watchdog._ACTIONABLE_BACKLOG_SQL (importé)",
                            pq.ACTIONABLE_BACKLOG_SQL, True, params_desc),
                 _sql_entry("runs ouverts", pq.RUNS_OPEN_SQL, True),
                 _sql_entry("revue pending (0028)", pq.REVIEW_PENDING_SQL,
                            review_executed)],
            limits=limits)
    except Exception:
        return _panel("q2", _UNAVAILABLE, limits=limits)


def _sum_counts(rows: list[list[Any]]) -> int:
    """Volume d'un agrégat GROUP BY (colonne 1 = count) — la tuile porte le
    VOLUME de rejets, jamais le nombre de motifs distincts (finding round 1)."""
    return sum(int(r[1] or 0) for r in rows)


def _sum_filtered_manifests(rows: list[list[Any]]) -> int:
    """Volume filtré amont : somme des counts du jsonb motif→count
    (messages_filtered, colonne 3) des derniers manifestes par source."""
    total = 0
    for r in rows:
        mf = r[3]
        if isinstance(mf, str):
            try:
                mf = json.loads(mf)
            except ValueError:
                mf = None
        if isinstance(mf, dict):
            total += sum(int(v) for v in mf.values()
                         if isinstance(v, (int, float)))
    return total


def panel_q3() -> dict[str, Any]:
    """Q3 REJETÉ — pile des 4 étages de rejet. L'absence est LE message :
    étage non déployé = « rejet invisible aujourd'hui », JAMAIS « 0 rejet » ;
    substrat partiel = badge PARTIEL, jamais DÉPLOYÉ (finding round 1)."""
    limits = [
        "Refus v1 historiques (endpoint 410) jamais journalisés — trou passé "
        "irrécupérable.",
        "refusal_detail = masquage best-effort, PAS une anonymisation garantie (0021).",
        "L'abstention du recall SERVI n'est tracée nulle part → Q6/Q8.",
        "Les tuiles portent le VOLUME (somme des counts), pas le nombre de "
        "motifs distincts — le détail par motif est dans les tables/drills.",
    ]
    stages = (
        ("Étage 1 — amont scanner (capture_manifests 0026)", "capture_manifests",
         pq.CAPTURE_FILTERED_SQL,
         ["node_id", "source_type", "run_started_at", "messages_filtered"],
         _drill("capture_manifests"), _sum_filtered_manifests,
         "msgs filtrés (derniers runs)"),
        ("Étage 2 — refus ingest 7j (ingest_receipts 0021)", "ingest_receipts",
         pq.REJECTED_INGEST_7D_SQL, ["outcome", "n"],
         _drill("ingest_receipts", window="168"), _sum_counts,
         "volume 7j"),
        ("Étage 3 — exclusions tracées (conversations 0023/0029)", "conversations",
         pq.EXCLUSIONS_BY_CATEGORY_SQL, ["exclusion_category", "n"],
         _drill("conversations_excluded"), _sum_counts,
         "conversations acked"),
        ("Étage 4 — écartés en digestion (review_queue 0028)",
         "digestion_review_queue", pq.REVIEW_DROPS_SQL, ["drop_reason", "n"],
         _drill("review_queue"), _sum_counts, "atomes écartés"),
        ("Audit — actions conversation_* (audit_log)", "audit_log",
         pq.AUDIT_CONVERSATION_ACTIONS_SQL, ["action", "n"],
         _drill("audit_log"), _sum_counts, "actions journalisées"),
    )
    stage_tables = tuple(dict.fromkeys(s[1] for s in stages))
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                # Sonde LIMITÉE aux 5 tables consommées ici (jamais les 11 —
                # finding perf round 1 : comptages redondants sur la maître).
                probe = _probe_tables(cur, stage_tables)
                tables, sql_entries, tiles = [], [], []
                for title, table, sql, headers, drill, agg, unit in stages:
                    prefix = title.split(" — ")[0]
                    if probe[table]["present"]:
                        rows = _rows(cur, sql)
                        tables.append({"title": title, "headers": headers,
                                       "rows": rows})
                        tiles.append({"label": f"{prefix} — {unit}",
                                      "value": agg(rows), "drill": drill})
                        sql_entries.append(_sql_entry(title, sql, True))
                    else:
                        tables.append({"title": title + " — INVISIBLE AUJOURD'HUI "
                                       "(organe non déployé, vide que la dérivation comble)",
                                       "headers": headers, "rows": []})
                        tiles.append({"label": f"{prefix} — {unit}",
                                      "value": "INVISIBLE (non déployé)",
                                      "drill": None})
                        sql_entries.append(_sql_entry(
                            title + " (documentaire, NON exécuté)", sql, False))
        finally:
            conn.close()
        n_present = sum(1 for t in stage_tables if probe[t]["present"])
        status = ("deployed" if n_present == len(stage_tables)
                  else ("not_deployed" if n_present == 0 else "partial"))
        return _panel("q3", status,
                      tiles=tiles, tables=tables, sql=sql_entries, limits=limits)
    except Exception:
        return _panel("q3", _UNAVAILABLE, limits=limits)


def panel_q4() -> dict[str, Any]:
    """Q4 APPRIS — mémoire durable + RATIO anti-fossilisation (une tuile ne
    comptant que 'created' masquerait la fossilisation — REFUSÉ)."""
    limits = [
        "Maillon central manquant : memory_atoms sans run_ref → atome↔run non "
        "traçable directement (lien BRISÉ n°1, cf Q8).",
        # « hétérogène selon l'époque de l'atome » racontait l'histoire d'UN
        # corpus. Un cerveau neuf n'a pas d'époques. Ce qui est vrai partout,
        # et vérifiable dans le schéma, c'est que la colonne est facultative :
        # rien n'oblige un producteur à la renseigner.
        "confidence_score est une colonne FACULTATIVE : un atome peut vivre "
        "sans, et la distribution ne porte que sur ceux qui en ont un.",
    ]
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                by_day = _rows(cur, pq.ATOMS_BY_DAY_KIND_SQL)
                ratio = _rows(cur, pq.ATOMS_LIFECYCLE_RATIO_SQL)
                runs = _rows(cur, pq.RUNS_LEARNING_SQL)
        finally:
            conn.close()
        total, actifs, sup_atoms, r_created, r_sup, r_conf = (
            ratio[0] if ratio else (0, 0, 0, 0, 0, 0))
        tiles = [
            {"label": "atomes actifs / total", "value": f"{actifs} / {total}",
             "drill": _drill("memory_atoms")},
            {"label": "RATIO run created:superseded:confirmed",
             "value": f"{r_created}:{r_sup}:{r_conf}",
             "drill": _drill("run_receipts")},
            {"label": "atomes status=superseded (anti-fossilisation)",
             "value": sup_atoms, "drill": _drill("memory_atoms")},
        ]
        return _panel(
            "q4", "deployed", tiles=tiles,
            tables=[{"title": "Atomes actifs par jour × kind (14 j)",
                     "headers": ["jour", "kind", "n"], "rows": by_day},
                    {"title": "5 derniers runs — apprentissage",
                     "headers": ["slot_key", "created", "superseded", "confirmed",
                                 "coverage_covered", "coverage_presented"],
                     "rows": runs}],
            sql=[_sql_entry("atomes par jour × kind", pq.ATOMS_BY_DAY_KIND_SQL, True),
                 _sql_entry("ratio anti-fossilisation",
                            pq.ATOMS_LIFECYCLE_RATIO_SQL, True),
                 _sql_entry("runs — apprentissage", pq.RUNS_LEARNING_SQL, True)],
            limits=limits)
    except Exception:
        return _panel("q4", _UNAVAILABLE, limits=limits)


def panel_q5(atom_id: str | None = None) -> dict[str, Any]:
    """Q5 POURQUOI — drill-down d'UN atome (rationale + source_ref bruts) +
    ses perdants (0028). Sans id → mode d'emploi du drill."""
    limits = [
        "rationale n'est NOT NULL nulle part (obligatoire seulement "
        "kind=decision via logique app) → '— rationale absente', jamais interpolée.",
        "Pas de 'pourquoi' pour le recall SERVI : raison persistée côté shadow "
        "uniquement (context_receipts 0030).",
    ]
    sql_entries = [_sql_entry("détail atome", pq.ATOM_DETAIL_SQL, atom_id is not None,
                              "id = <uuid>"),
                   _sql_entry("perdants de l'incumbent (0028)", pq.ATOM_LOSERS_SQL,
                              False, "id = <uuid>")]
    if not atom_id:
        return _panel(
            "q5", "deployed",
            tiles=[{"label": "mode d'emploi",
                    "value": "cliquer un id d'atome (Q4 → drill) pour son pourquoi",
                    "drill": _drill("memory_atoms")}],
            sql=sql_entries, limits=limits)
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                atom = _rows(cur, pq.ATOM_DETAIL_SQL, {"id": atom_id})
                probe = _probe_tables(cur, ("digestion_review_queue",))
                losers, losers_executed = [], False
                if probe["digestion_review_queue"]["present"]:
                    losers = _rows(cur, pq.ATOM_LOSERS_SQL, {"id": atom_id})
                    losers_executed = True
        finally:
            conn.close()
        rows = [[c if c is not None else "— rationale absente" if i == 4 else "—"
                 for i, c in enumerate(r)] for r in atom]
        sql_entries[1]["executed"] = losers_executed
        return _panel(
            "q5", "deployed",
            tables=[{"title": "Atome (lignes brutes)",
                     "headers": ["id", "kind", "scope", "key", "rationale",
                                 "source_ref", "confidence_score", "status",
                                 "created_at"], "rows": rows},
                    {"title": "Perdants (incumbent_atom_id = cet atome)"
                     + ("" if losers_executed else " — NON DÉPLOYÉ (0028)"),
                     "headers": ["drop_reason", "proposed_atom", "run_ref",
                                 "created_at"], "rows": losers}],
            sql=sql_entries, limits=limits)
    except Exception:
        return _panel("q5", _UNAVAILABLE, limits=limits)


def panel_q6() -> dict[str, Any]:
    """Q6 CONFIANCE — bandes shadow 7j + abstentions receipt-grade +
    distribution confidence_score + calibration R3 (fichier git, lecture)."""
    limits = [
        "raw_band ET final_band sont classées sur la distance FINALE "
        "post-modifiers — le cockpit NE re-classe JAMAIS top1_distance_raw.",
        "Les bandes ne gouvernent QUE le shadow ; le chemin SERVI reste kNN pur "
        "sans bande tant que serve R3 n'a pas de GO.",
        "Calibration en git (pas DB) : pas d'historique de versions requêtable.",
    ]
    calib: dict[str, Any] | None = None
    try:
        calib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "..", "app", "context",
                                  "r3_calibration.json")
        with open(os.path.abspath(calib_path), encoding="utf-8") as f:
            calib = json.load(f)
    except Exception:
        calib = None
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                probe = _probe_tables(cur, ("context_receipts", "memory_atoms"))
                conf, conf_executed = [], False
                if probe["memory_atoms"]["present"]:  # la sonde décide, toujours
                    conf = _rows(cur, pq.CONFIDENCE_BUCKETS_SQL)
                    conf_executed = True
                bands, abstain, bands_executed = [], None, False
                cr_state = probe["context_receipts"]["state"]
                if probe["context_receipts"]["present"]:
                    bands = _rows(cur, pq.BANDS_7D_SQL)
                    cur.execute(pq.ABSTAIN_7D_SQL)
                    abstain = int(cur.fetchone()[0])
                    bands_executed = True
        finally:
            conn.close()
        tiles = []
        if bands_executed:
            tiles.append({"label": "abstentions 7j (stop_reason=no_confident_context)",
                          "value": abstain, "drill": _drill("context_receipts")})
        else:
            tiles.append({"label": "context_receipts (0030)",
                          "value": "NON DÉPLOYÉ", "drill": None})
        if calib:
            b = calib.get("bands", {})
            tiles.append({"label": "calibration R3 (high/medium/abstain)",
                          "value": f"<= {b.get('high_max')} / <= {b.get('medium_max')}"
                                   f" / >= {b.get('abstain_min')}", "drill": None})
        tables = [{"title": "Bandes final_band 7j (shadow)"
                   + ("" if bands_executed else " — NON DÉPLOYÉ (0030)")
                   + (" — ARMÉ, 0 reçu (shadow OFF légitime)"
                      if cr_state == "armed_empty" else ""),
                   "headers": ["final_band", "n", "avg(top1_distance_final)"],
                   "rows": bands},
                  {"title": "Distribution confidence_score par kind (buckets 0-100)"
                   + ("" if conf_executed else " — NON DÉPLOYÉ (memory_atoms)"),
                   "headers": ["kind", "bucket", "n"], "rows": conf}]
        # Statut HONNÊTE sur substrat partiel (finding round 1) : le badge ne
        # reflète l'état de context_receipts que si TOUT le substrat du
        # panneau est là ; un seul étage présent = PARTIEL, aucun = NON DÉPLOYÉ.
        cr_present = probe["context_receipts"]["present"]
        ma_present = probe["memory_atoms"]["present"]
        if cr_present and ma_present:
            status = cr_state
        elif not cr_present and not ma_present:
            status = "not_deployed"
        else:
            status = "partial"
        return _panel(
            "q6", status,
            tiles=tiles, tables=tables,
            sql=[_sql_entry("bandes 7j (0030)", pq.BANDS_7D_SQL, bands_executed),
                 _sql_entry("abstentions 7j", pq.ABSTAIN_7D_SQL, bands_executed),
                 _sql_entry("confidence buckets", pq.CONFIDENCE_BUCKETS_SQL,
                            conf_executed)],
            limits=limits)
    except Exception:
        return _panel("q6", _UNAVAILABLE, limits=limits)


def panel_q7() -> dict[str, Any]:
    """Q7 COÛT — ledger 14j (run_receipts write-ahead) + les 3 freins lus
    LIVE + caps BudgetConfig importés (jamais codés en dur ici)."""
    limits = [
        "tokens = ESTIMATION INPUT seulement — aucun output, aucun $ réel.",
        "Ressource RÉELLEMENT rare = quota de SESSION abonnement Claude OAuth : "
        "NON mesurée nulle part (tuile explicite, pas de fabrication).",
        # Le renvoi à `ai_spend_ledger.json` désignait un fichier d'une
        # installation précise, qu'aucune étape de ce dépôt ne crée : le
        # lecteur ne peut ni le trouver ni savoir ce qu'il contient.
        "Embeddings OpenAI non tracés (négligeable, doctrine) : la seule "
        "source de coût faisant foi est arac.run_receipts.",
    ]
    cfg = pq.BudgetConfig.from_env()
    env_allow = os.environ.get("ARAC_ALLOW_PAID_AI", "") == "1"
    kill_file = os.path.exists(pq.DEFAULT_KILL_SWITCH)
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                ledger = _rows(cur, pq.LEDGER_14D_SQL)
                cur.execute(pq.BRAKE_DB_SQL)
                row = cur.fetchone()
                db_flag: Any = (row[0] if row is not None else "— (clé absente)")
        finally:
            conn.close()
        tiles = [
            {"label": "frein 1 — env ARAC_ALLOW_PAID_AI",
             "value": "on" if env_allow else "off", "drill": None},
            {"label": "frein 2 — arac_config.paid_ai_enabled",
             "value": db_flag, "drill": None},
            {"label": "frein 3 — kill-switch fichier KILL_PAID_AI",
             "value": "PRÉSENT (STOP)" if kill_file else "absent", "drill": None},
            {"label": "caps (BudgetConfig importé, env-driven)",
             "value": f"{cfg.daily_token_budget} tok/j · "
                      f"{cfg.max_tokens_per_run} tok/run · "
                      f"{cfg.max_runtime_sec}s/run · "
                      f"{cfg.max_spawns_per_day} spawns/j", "drill": None},
            {"label": "quota session abonnement Claude (OAuth)",
             "value": "NON mesuré", "drill": None},
        ]
        return _panel(
            "q7", "deployed", tiles=tiles,
            tables=[{"title": "Ledger 14 j (est. input, pas de $)",
                     "headers": ["utc_day", "est_input_tokens", "spawns",
                                 "items", "runs skipped"], "rows": ledger}],
            sql=[_sql_entry("ledger 14j", pq.LEDGER_14D_SQL, True),
                 _sql_entry("frein DB", pq.BRAKE_DB_SQL, True)],
            limits=limits)
    except Exception:
        return _panel("q7", _UNAVAILABLE, limits=limits)


def panel_q8(uid: str | None = None) -> dict[str, Any]:
    """Q8 PREUVES — chaîne bout-en-bout d'UNE conversation + les 4 liens
    BRISÉS affichés nommément (le cockpit visualise ses lacunes de preuve)."""
    limits = [
        "Lien brisé n°1 : memory_atoms sans run_ref → atome↛run direct.",
        "Lien brisé n°2 : request_id non propagé jusqu'à raw_messages → "
        "corrélation POST↛rows par node_id+fenêtre temporelle, pas clé directe.",
        "Lien brisé n°3 : capture_manifests↔ingest_receipts sans clé de jointure.",
        "Lien brisé n°4 : recall SERVI sans shadow armé ne laisse AUCUN reçu.",
    ]
    sql_entries = [_sql_entry("chaîne conversation", pq.CHAIN_SQL,
                              uid is not None, "uid = <conversation_uid>")]
    if not uid:
        return _panel(
            "q8", "deployed",
            tiles=[{"label": "mode trace",
                    "value": "fournir ?uid=<conversation_uid> "
                             "(drill depuis États expliqués)",
                    "drill": _drill("explained_states")}],
            sql=sql_entries, limits=limits)
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                # posts/dropped best-effort : sous-SELECT sur tables 0021/0028
                # potentiellement absentes → la sonde décide.
                probe = _probe_tables(cur, ("ingest_receipts",
                                            "digestion_review_queue"))
                if (probe["ingest_receipts"]["present"]
                        and probe["digestion_review_queue"]["present"]):
                    chain = _rows(cur, pq.CHAIN_SQL, {"uid": uid})
                    executed = True
                else:
                    chain, executed = [], False
        finally:
            conn.close()
        sql_entries[0]["executed"] = executed
        return _panel(
            "q8", "deployed" if executed else "not_deployed",
            tables=[{"title": f"Chaîne pour conversation_uid={uid}"
                     + ("" if executed else
                        " — maillons 0021/0028 non déployés (chaîne NON exécutable)"),
                     "headers": ["conversation_uid", "source_type", "node_id",
                                 "acked", "exclusion_category", "retry_count",
                                 "curseur", "msgs", "posts", "dropped"],
                     "rows": chain}],
            sql=sql_entries, limits=limits)
    except Exception:
        return _panel("q8", _UNAVAILABLE, limits=limits)


# ============================================================================
# Panneaux STABILISATION (audit V5)
# ============================================================================


def panel_explained_states() -> dict[str, Any]:
    """S1 — ÉTATS DE CONVERSATION EXPLICABLES : chaque conversation avec
    travail non curé reçoit sa raison mécanique NOMMÉE, dérivée des colonnes
    réelles + gate importé (le prédicat d'éligibilité de la CTE est la
    constante conservation_audit._ACTIONABLE_BACKLOG_DETAIL_SQL elle-même)."""
    limits = [
        "Le prédicat 'actionable' de la CTE EST la constante importée du "
        "bulletin (composition, pas ré-écriture) ; seuils = _gate_params().",
        "'inclassée[divergence]' est un fail-loud : classification et gate ont "
        "divergé — à investiguer, jamais masqué.",
        "Borné à 200 conversations (drill pour le détail au-delà).",
    ]
    params = pq.explained_states_params()
    doc_sql = _sql_entry(
        "états expliqués (CTE actionable = "
        "conservation_audit._ACTIONABLE_BACKLOG_DETAIL_SQL importée) — "
        "documentaire, NON exécuté",
        pq.EXPLAINED_STATES_SQL, False)
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                # Sonde to_regclass AVANT exécution (finding round 1) : la
                # constante importée référence raw_message_revisions (0022) —
                # substrat absent = NON DÉPLOYÉ, jamais « DB injoignable ».
                probe = _probe_tables(cur, pq.EXPLAINED_STATES_TABLES)
                missing = [t for t in pq.EXPLAINED_STATES_TABLES
                           if not probe[t]["present"]]
                if missing:
                    return _panel(
                        "etats", "not_deployed", sql=[doc_sql],
                        limits=limits + [
                            "Substrat absent : arac."
                            + ", arac.".join(missing)
                            + " (migration GO-gatée) — trou affiché, "
                              "jamais comblé ni maquillé en indisponibilité."])
                rows = _rows(cur, pq.EXPLAINED_STATES_SQL, params)
        finally:
            conn.close()
        by_reason: dict[str, int] = {}
        for r in rows:
            key = re.sub(r"\[.*\]", "", str(r[6]))
            by_reason[key] = by_reason.get(key, 0) + 1
        tiles = [{"label": f"raison : {k}", "value": n,
                  "drill": _drill("explained_states")}
                 for k, n in sorted(by_reason.items(), key=lambda x: -x[1])]
        return _panel(
            "etats", "deployed", tiles=tiles,
            tables=[{"title": "Conversations non digérées — raison mécanique nommée",
                     "headers": ["conversation_uid", "source_type", "nouveaux msgs",
                                 "non vides", "retry", "dernière activité (h)",
                                 "raison"], "rows": rows}],
            sql=[_sql_entry(
                "états expliqués (CTE actionable = "
                "conservation_audit._ACTIONABLE_BACKLOG_DETAIL_SQL importée)",
                pq.EXPLAINED_STATES_SQL, True,
                f"gate_params() importé + grace_hours="
                f"{pq.STARVATION_GRACE_HOURS_DEFAULT} + marqueur "
                f"{pq.FULL_OMISSION_MARKER!r} importé")],
            limits=limits)
    except Exception:
        return _panel("etats", _UNAVAILABLE, limits=limits)


def panel_inflow_capacity() -> dict[str, Any]:
    """S2 — JAUGE INFLOW vs CAPACITÉ : kt/j entrés par source (7j, estimateur
    CHARS_PER_TOKEN importé du value-gate) vs caps BudgetConfig importés vs
    consommation MESURÉE (run_receipts)."""
    limits = [
        "Inflow = ESTIMATION chars/CHARS_PER_TOKEN (même estimateur que le "
        "value-gate), pas un comptage tiktoken.",
        "Capacité = caps BudgetConfig (env-driven) ; la vraie rareté (quota "
        "session OAuth) reste NON mesurée (cf Q7).",
    ]
    cfg = pq.BudgetConfig.from_env()
    cap_ktok_day = cfg.daily_token_budget / 1000.0
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                inflow = _rows(cur, pq.INFLOW_7D_BY_SOURCE_SQL,
                               {"chars_per_token": pq.CHARS_PER_TOKEN})
                consumed = _rows(cur, pq.CONSUMED_7D_SQL)
        finally:
            conn.close()
        total_in = sum(float(r[4] or 0) for r in inflow)
        total_consumed = sum(int(r[1] or 0) for r in consumed)
        tiles = [
            {"label": "inflow total (kt/j estimés, 7j)",
             "value": round(total_in, 1), "drill": _drill("ingest_receipts",
                                                          window="168")},
            {"label": "capacité (cap tokens/j BudgetConfig)",
             "value": f"{cap_ktok_day:.0f} kt/j", "drill": None},
            {"label": "ratio inflow/capacité",
             "value": (f"{total_in / cap_ktok_day:.2f}" if cap_ktok_day else "—"),
             "drill": None},
            {"label": "consommé MESURÉ 7j (run_receipts, est. input)",
             "value": f"{total_consumed / 1000.0:.1f} kt",
             "drill": _drill("run_receipts")},
        ]
        return _panel(
            "inflow", "deployed", tiles=tiles,
            tables=[{"title": "Inflow 7 j par source (estimation value-gate)",
                     "headers": ["node_id", "source_type", "msgs 7j", "ktok 7j",
                                 "ktok/jour"], "rows": inflow},
                    {"title": "Consommation mesurée 7 j (reçus write-ahead)",
                     "headers": ["utc_day", "est_input_tokens", "spawns",
                                 "items"], "rows": consumed}],
            sql=[_sql_entry("inflow par source",
                            pq.INFLOW_7D_BY_SOURCE_SQL, True,
                            f"chars_per_token = CHARS_PER_TOKEN importé "
                            f"({pq.CHARS_PER_TOKEN})"),
                 _sql_entry("consommé 7j", pq.CONSUMED_7D_SQL, True)],
            limits=limits)
    except Exception:
        return _panel("inflow", _UNAVAILABLE, limits=limits)


# --- S3 — journal des alertes émises ----------------------------------------

# Chaque envoi d'alerte écrit son résultat — succès compris — sur stderr, en
# une ligne JSON, donc dans journald. C'est ce journal que ce panneau relit :
# il répond à « l'alerte a-t-elle été émise, et est-elle arrivée ? », question
# à laquelle l'état interne du chien de garde ne peut pas répondre seul.
_ALERT_EVENTS = ("cortex.alert_sent", "conservation.alert_sent",
                 "tg_send.result", "telegram.send_failed",
                 "telegram.send_attempt_failed", "telegram.send_recovered",
                 "telegram.text_truncated")

# Commande FIGÉE (aucune entrée externe, lecture seule du journal systemd).
#
# CE PANNEAU LISAIT LE JOURNAL DE TOUTE LA MACHINE, PAS CELUI DE CE CERVEAU.
# La commande n'a jamais porté de `-u` : `journalctl --since -7 days -g
# 'cortex\.alert_sent|…'` balaie le journal ENTIER. Sur un serveur qui porte
# deux cerveaux — le cas que tout ce dépôt travaille — le cockpit de l'un
# affichait les envois d'alerte de l'AUTRE : ses `slot_key`, ses identifiants
# de conversation, ses échecs Telegram, sous le titre « JOURNAL DES ALERTES
# ÉMISES » d'un cockpit qui n'est pas le sien. C'est la même faute que le
# moniteur avait corrigée chez lui, et il l'avait écrite en toutes lettres :
# « ON NE SURVEILLE RIEN PLUTÔT QUE DE SURVEILLER LE VOISIN ».
#
# Le filtre est donc l'unité, et il vient de `ARAC_UNIT_PREFIX` — la variable
# que le bootstrap écrit dans le coffre, que l'unité du cockpit charge, et dont
# le moniteur se sert déjà pour la même question. Sans elle, ce panneau ne
# fabrique pas un « 0 événement » : il devient INDISPONIBLE, exactement comme
# quand le journal n'est pas visible. Ne pas savoir de quel cerveau on est le
# cockpit n'autorise pas à montrer celui d'un autre.
_ALERT_JOURNAL_GREP = "|".join(e.replace(".", r"\.") for e in _ALERT_EVENTS)


def _prefixe_unite() -> str:
    """Le préfixe des unités de CE cerveau, ou la chaîne vide si on l'ignore."""
    return (os.environ.get("ARAC_UNIT_PREFIX") or "").strip()


def _journalctl_cmd() -> list[str]:
    prefixe = _prefixe_unite()
    if not prefixe:
        raise RuntimeError(
            "ARAC_UNIT_PREFIX absent : ce cockpit ne sait pas de quel cerveau "
            "il est le cockpit. Il ne lit pas le journal plutôt que de montrer "
            "les alertes d'un voisin.")
    return [
        "journalctl", "--no-pager", "--since", "-7 days", "-o", "short-iso",
        "-u", f"{prefixe}-*", "-g", _ALERT_JOURNAL_GREP,
    ]

_JSON_RE = re.compile(r"\{.*\}")

# Marqueurs stderr d'un journal système NON VISIBLE depuis ce process
# (finding round 1) : rc=1 « No journal files were opened due to insufficient
# permissions » (aucun fichier lisible) et rc=0 avec hint « not seeing
# messages from other users » (journal user seul) sont tous deux
# INDISCERNABLES d'une absence de match par le seul returncode — ils doivent
# rendre le panneau INDISPONIBLE, jamais un « 0 événement » fabriqué.
_JOURNAL_BLINDNESS_HINTS = (
    "no journal files were opened",
    "insufficient permissions",
    "not seeing messages from other users",
)


def _read_alert_journal() -> list[str]:
    """Lit le journal des envois via journalctl (figé, read-only). Monkeypatchable.

    Lève si le journal SYSTÈME n'est pas visible depuis ce process (déficit
    de permissions — SupplementaryGroups=systemd-journal requis au service) :
    un déficit de visibilité n'est JAMAIS rendu comme « aucun événement »."""
    proc = subprocess.run(  # noqa: S603 — commande constante ci-dessus
        _journalctl_cmd(), capture_output=True, text=True, timeout=10, check=False)
    stderr = (proc.stderr or "").lower()
    if any(h in stderr for h in _JOURNAL_BLINDNESS_HINTS):
        raise RuntimeError(
            "journal système NON VISIBLE depuis ce process (permissions "
            "journald — SupplementaryGroups=systemd-journal requis)")
    if proc.returncode not in (0, 1):  # 1 = aucun match (légitime)
        raise RuntimeError(f"journalctl rc={proc.returncode}")
    return proc.stdout.splitlines()


def panel_alerts() -> dict[str, Any]:
    """S3 — JOURNAL DES ALERTES ÉMISES + détail d'envoi. Source : les lignes
    JSON d'envoi d'alerte dans journald (7 j) + le dernier état persisté du
    chien de garde (var/ingest_watchdog_state.json)."""
    limits = [
        "Couvre les envois tracés en une ligne (cortex.alert_sent, "
        "conservation.alert_sent, tg_send.result, telegram.*) — le rapport "
        "multi-ligne du watchdog n'est pas re-parsé (son dernier état persisté "
        "est affiché à la place).",
        "Fenêtre 7 jours, journald (rétention système).",
    ]
    rows: list[list[Any]] = []
    status = "deployed"
    try:
        for line in _read_alert_journal():
            m = _JSON_RE.search(line)
            if not m:
                continue
            try:
                payload = json.loads(m.group(0))
            except ValueError:
                continue
            event = payload.get("event", "?")
            if event not in _ALERT_EVENTS:
                continue
            ts = line.split(" ", 1)[0]
            rows.append([ts, event,
                         payload.get("ok", "—"),
                         payload.get("detail", payload.get("http", "—"))])
    except Exception as exc:  # noqa: BLE001 — résilience cockpit
        status = _UNAVAILABLE
        limits = [f"journal des envois illisible : {exc}"] + limits
    state: dict[str, Any] = {}
    try:
        import ingest_watchdog as _iw  # sys.path posé par perception_queries
        with open(os.environ.get("ARAC_INGEST_WATCHDOG_STATE",
                                 _iw.STATE_FILE_DEFAULT), encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    tiles = [
        {"label": "envois d'alerte (7 j)", "value": len(rows), "drill": None},
        {"label": "échecs d'envoi (7 j)",
         "value": sum(1 for r in rows if r[2] is False
                      or r[1] == "telegram.send_failed"), "drill": None},
        {"label": "watchdog — dernier niveau notifié",
         "value": state.get("level", "—"), "drill": None},
        {"label": "watchdog — last_notified_at",
         "value": state.get("last_notified_at", "—"), "drill": None},
        {"label": "watchdog — codes notifiés",
         "value": ", ".join(state.get("notified_codes") or []) or "—",
         "drill": None},
    ]
    return _panel(
        "alertes", status, tiles=tiles,
        tables=[{"title": "Journal des envois (7 j, journald)",
                 "headers": ["horodatage", "event", "ok", "detail"],
                 "rows": rows[-200:]}],
        limits=limits)


# ============================================================================
# Drill-to-receipt générique — whitelist STATIQUE {t: (sql, spec params)}
# ============================================================================

_WINDOW_RE = re.compile(r"^\d{1,4}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,40}$")
_UID_RE = re.compile(r"^[\w@.:-]{1,200}$")

# t → (constante SQL du module pq, {param: (validateur, obligatoire)},
#      fabrique de params fixes). AUCUN SQL construit depuis l'input :
# uniquement des placeholders psycopg validés.
DRILL_WHITELIST: dict[str, dict[str, Any]] = {
    "ingest_sources": {"sql": pq.DRILL_INGEST_SOURCES_SQL, "params": {}},
    "ingest_receipts": {"sql": pq.DRILL_INGEST_RECEIPTS_SQL,
                        "params": {"window": (_WINDOW_RE, True)},
                        "map": {"window": "window_hours"}},
    "capture_manifests": {"sql": pq.DRILL_CAPTURE_MANIFESTS_SQL, "params": {}},
    "conversations_excluded": {"sql": pq.DRILL_CONVERSATIONS_EXCLUDED_SQL,
                               "params": {}},
    "run_receipts": {"sql": pq.DRILL_RUN_RECEIPTS_SQL, "params": {}},
    "review_queue": {"sql": pq.DRILL_REVIEW_QUEUE_SQL, "params": {}},
    "memory_atoms": {"sql": pq.DRILL_MEMORY_ATOMS_SQL, "params": {}},
    "context_receipts": {"sql": pq.DRILL_CONTEXT_RECEIPTS_SQL, "params": {}},
    "audit_log": {"sql": pq.DRILL_AUDIT_LOG_SQL, "params": {}},
    "backlog_detail": {"sql": pq.ACTIONABLE_BACKLOG_DETAIL_SQL, "params": {},
                       "fixed": pq.backlog_detail_params},
    "explained_states": {"sql": pq.EXPLAINED_STATES_SQL, "params": {},
                         "fixed": pq.explained_states_params},
    "atom": {"sql": pq.ATOM_DETAIL_SQL,
             "params": {"id": (_UUID_RE, True)}},
    "chain": {"sql": pq.CHAIN_SQL, "params": {"uid": (_UID_RE, True)}},
}


def drill_rows(t: str, args: dict[str, str]) -> dict[str, Any]:
    """Exécute la requête whitelistée `t` avec des params VALIDÉS.

    Retour nominal : {"sql", "headers", "rows", "as_of"} ;
    refus/erreur : {"error": "bad_request"|"unavailable", "detail": ...}.
    """
    entry = DRILL_WHITELIST.get(t)
    if entry is None:
        return {"error": "bad_request", "detail": f"t inconnu : {t!r}"}
    params: dict[str, Any] = dict(entry.get("fixed", dict)() or {})
    for name, (rx, required) in entry.get("params", {}).items():
        raw = args.get(name)
        if raw is None or not rx.match(str(raw)):
            if required:
                return {"error": "bad_request",
                        "detail": f"param {name!r} manquant/invalide"}
            continue
        params[entry.get("map", {}).get(name, name)] = raw
    try:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(entry["sql"], params or None)
                headers = [d.name for d in cur.description]
                rows = [list(r) for r in cur.fetchall()]
        finally:
            conn.close()
        return {"sql": entry["sql"], "headers": headers, "rows": rows,
                "as_of": _now_iso()}
    except Exception as exc:  # noqa: BLE001 — résilience cockpit
        # UndefinedTable = substrat NON DÉPLOYÉ (0020→0030 GO-gaté), pas une
        # DB injoignable — les deux états ne sont jamais conflés (round 1).
        detail = type(exc).__name__
        err = "not_deployed" if detail == "UndefinedTable" else _UNAVAILABLE
        return {"error": err, "detail": detail, "sql": entry["sql"]}
