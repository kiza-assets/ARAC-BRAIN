#!/usr/bin/env python3
"""
run_eval.py — banc d'évaluation retrieval ARAC (READ-ONLY).

Pour chaque requête de queries.json, appelle l'endpoint live `/v1/atoms/recall`
(kNN dense) et mesure si le scope attendu apparaît dans les top-k résultats.

Métriques (v2) :
  - recall_at_k       : expect_scope présent dans les top-k
  - mrr               : mean reciprocal rank sur le 1er hit du scope attendu
  - avg_top1_distance : distance kNN moyenne du top-1
  - precision_at_1    : fraction de requêtes dont le top-1 EST le scope attendu
  - superseded_rate   : fraction d'atomes retournés en status='superseded' (≈0 attendu)
  - provenance_rate   : fraction d'atomes portant un source_ref non vide
  - source_diversity  : nb moyen de scopes distincts dans le top-k
Sert de PREUVE + garde anti-régression.

GARANTIES : lecture seule (POST /recall n'écrit rien), n'affiche pas les `value`
(scopes/kinds/distances/status uniquement). Les fonctions `score()`, `score_atoms()`
et `aggregate()` sont PURES (testables sans API).

Usage :
  sudo -E .venv/bin/python tests/evals/run_eval.py [--k 5] [--baseline FILE] [--min-recall 0.6] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
RECALL_URL = os.environ.get("ARAC_RECALL_URL", "http://127.0.0.1:8000/v1/atoms/recall")


# ----------------------------------------------------------------- PUR
def score(results_scopes: list[str], expect_scope: str) -> dict:
    """PUR : à partir de la liste ordonnée des scopes retournés + scope attendu,
    calcule hit (présent ?) et rank (1-based du 1er match, 0 si absent)."""
    rank = 0
    for i, sc in enumerate(results_scopes, start=1):
        if sc == expect_scope:
            rank = i
            break
    return {"hit": rank > 0, "rank": rank, "rr": (1.0 / rank) if rank > 0 else 0.0}


def _has_provenance(atom: dict) -> bool:
    """PUR : un atome porte une provenance si source_ref est un dict non vide."""
    sr = atom.get("source_ref")
    return isinstance(sr, dict) and len(sr) > 0


def score_atoms(results: list[dict], expect_scope: str) -> dict:
    """PUR : à partir des atomes ordonnés retournés par /recall + scope attendu,
    calcule les métriques de base (hit/rank/rr) ET les métriques v2 par-requête :
      - top1_correct  : le top-1 EST le scope attendu (precision@1)
      - n_returned    : nombre d'atomes retournés
      - n_superseded  : atomes avec status='superseded'
      - n_provenance  : atomes avec source_ref non vide
      - n_distinct_scopes : scopes distincts présents
    Aucun appel réseau : 100% testable sur des résultats synthétiques."""
    scopes = [a.get("scope") for a in results]
    base = score(scopes, expect_scope)
    return {
        **base,
        "top1_correct": bool(results) and results[0].get("scope") == expect_scope,
        "n_returned": len(results),
        "n_superseded": sum(1 for a in results if a.get("status") == "superseded"),
        "n_provenance": sum(1 for a in results if _has_provenance(a)),
        "n_distinct_scopes": len({s for s in scopes if s is not None}),
    }


def aggregate(per_query: list[dict]) -> dict:
    """PUR : agrège les métriques par-requête en métriques globales.

    Rétro-compat : recall_at_k / mrr / avg_top1_distance inchangés. Les métriques
    v2 ne sont émises que si les champs sources existent (sinon None = non mesuré,
    jamais fabriqué). Les requêtes anti-hallucination (category='anti-hallucination')
    sont EXCLUES de recall@k/MRR/precision@1 (le succès y est l'absence de hit) mais
    restent comptées dans superseded/provenance/diversity et dans `n`."""
    # rows "scorables" pour recall/MRR : tout sauf anti-hallucination.
    scorable = [q for q in per_query if q.get("category") != "anti-hallucination"]
    ns = len(scorable) or 1
    hits = sum(1 for q in scorable if q.get("hit"))
    mrr = sum(q.get("rr", 0.0) for q in scorable) / ns
    d1 = [q["top1_distance"] for q in per_query if q.get("top1_distance") is not None]

    out = {
        "n": len(per_query),
        "n_scored": len(scorable),
        "recall_at_k": round(hits / ns, 3),
        "mrr": round(mrr, 3),
        "avg_top1_distance": round(sum(d1) / len(d1), 3) if d1 else None,
    }

    # --- métriques v2 (omises proprement si donnée absente) ---
    p1 = [q for q in per_query if q.get("top1_correct") is not None]
    if p1:
        out["precision_at_1"] = round(sum(1 for q in p1 if q["top1_correct"]) / len(p1), 3)

    ret = [q for q in per_query if q.get("n_returned") is not None]
    total_ret = sum(q["n_returned"] for q in ret)
    if total_ret > 0:
        out["superseded_rate"] = round(sum(q.get("n_superseded", 0) for q in ret) / total_ret, 3)
        out["provenance_rate"] = round(sum(q.get("n_provenance", 0) for q in ret) / total_ret, 3)
    if ret:
        out["source_diversity"] = round(sum(q.get("n_distinct_scopes", 0) for q in ret) / len(ret), 3)

    return out


# ----------------------------------------------------------------- live I/O
def recall(query: str, k: int) -> list[dict]:
    body = json.dumps({"query": query, "k": k}).encode()
    req = urllib.request.Request(RECALL_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data if isinstance(data, list) else data.get("results", [])


def run(queries: list[dict], k: int) -> dict:
    per = []
    for q in queries:
        expect_empty = bool(q.get("expect_empty"))
        expect_scope = q.get("expect_scope", "")
        try:
            res = recall(q["query"], k)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            per.append({"id": q["id"], "error": type(e).__name__, "hit": False, "rank": 0, "rr": 0.0})
            continue
        m = score_atoms(res, expect_scope)
        scopes = [a.get("scope") for a in res]
        top1_distance = (round(res[0].get("distance"), 3)
                         if res and res[0].get("distance") is not None else None)
        row = {
            "id": q["id"], "expect_scope": expect_scope,
            "top_scopes": scopes[:k], "top1_distance": top1_distance,
            # métriques v2 par-requête (toujours mesurées sur les atomes retournés)
            "n_returned": m["n_returned"], "n_superseded": m["n_superseded"],
            "n_provenance": m["n_provenance"], "n_distinct_scopes": m["n_distinct_scopes"],
        }
        if expect_empty:
            # anti-hallucination : succès = AUCUN atome proche (distance haute / vide).
            # Exclu de recall@k/MRR/precision@1 ; on garde la distance top-1 comme preuve.
            row["category"] = "anti-hallucination"
            row["top1_correct_scope"] = m["top1_correct"]  # informatif, non scoré
        else:
            row.update({
                "hit": m["hit"], "rank": m["rank"], "rr": round(m["rr"], 3),
                "top1_correct": m["top1_correct"],
            })
        per.append(row)
    return {"k": k, "summary": aggregate(per), "per_query": per}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Eval retrieval ARAC (read-only).")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--queries", default=os.path.join(HERE, "queries.json"))
    p.add_argument("--baseline", help="comparer à un baseline JSON")
    p.add_argument("--min-recall", type=float, default=None, help="exit 1 si recall_at_k < seuil")
    p.add_argument("--max-superseded", type=float, default=None,
                   help="exit 1 si superseded_rate > seuil (anti-régression : /recall ne doit "
                        "JAMAIS remonter d'atomes obsolètes — attendu 0.0)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    qspec = json.load(open(args.queries, encoding="utf-8"))
    rep = run(qspec["queries"], args.k)

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        s = rep["summary"]
        print(f"=== ARAC retrieval eval (k={rep['k']}) ===")
        print(f"recall@{rep['k']}={s['recall_at_k']}  MRR={s['mrr']}  "
              f"P@1={s.get('precision_at_1')}  avg_top1_dist={s['avg_top1_distance']}  n={s['n']}")
        print(f"superseded_rate={s.get('superseded_rate')}  "
              f"provenance_rate={s.get('provenance_rate')}  "
              f"source_diversity={s.get('source_diversity')}")
        for q in rep["per_query"]:
            if q.get("category") == "anti-hallucination":
                ok = "✓" if not q.get("top1_correct_scope") else "?"
                print(f"  {ok} {q['id']:4} [anti-halluc] top1_dist={q.get('top1_distance')}  top={q.get('top_scopes')}")
            else:
                mark = "✓" if q.get("hit") else "✗"
                print(f"  {mark} {q['id']:4} rank={q.get('rank')} expect={q.get('expect_scope')}  top={q.get('top_scopes')}")
        if args.baseline and os.path.exists(args.baseline):
            base = json.load(open(args.baseline))["summary"]
            print(f"--- vs baseline : recall {base['recall_at_k']}→{s['recall_at_k']}  "
                  f"MRR {base['mrr']}→{s['mrr']}")

    rc = 0
    if args.min_recall is not None and rep["summary"]["recall_at_k"] < args.min_recall:
        print(f"REGRESSION: recall {rep['summary']['recall_at_k']} < seuil {args.min_recall}",
              file=sys.stderr)
        rc = 1
    ss = rep["summary"].get("superseded_rate")
    if args.max_superseded is not None and ss is not None and ss > args.max_superseded:
        print(f"REGRESSION: superseded_rate {ss} > seuil {args.max_superseded} "
              "(fuite d'atomes obsolètes via /recall)", file=sys.stderr)
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
