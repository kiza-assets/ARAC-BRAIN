#!/usr/bin/env python3
"""sonde_apprentissage.py — jusqu'où va la chaîne, et où elle s'arrête.

L'étape 6 du critère d'acceptation — « voir son cerveau apprendre » — est la
seule qui coûte de l'argent : embeddings chez un fournisseur, curation chez un
autre. Un test qui la déclarerait « réussie » sans avoir produit un atome
MENTIRAIT ; un test qui la sauterait ne dirait rien.

Cette sonde mesure exactement ce qui est mesurable SANS DÉPENSER UN CENTIME, et
nomme le reste. Elle ne fait aucun appel réseau, n'arme aucun interrupteur de
dépense, et n'écrit rien : toutes ses requêtes sont des lectures, et elle se
connecte avec le rôle du CYCLE — celui qui a le moins de droits de tous ceux
qui touchent à la digestion.

CE QU'ELLE PROUVE
=================
1. **La matière est arrivée et le cerveau la voit comme non digérée.**
   Le curseur ``curated_through_message_id`` de chaque conversation est en
   deçà des messages reçus : la digestion a du travail devant elle. C'est le
   contraire d'un cerveau qui aurait tout avalé sans rien retenir.

2. **La sélection fonctionne, et elle sélectionne CES messages-là.**
   ``agents.cortex.pack.build_pack`` est le maillon qui décide de la tranche à
   digérer. C'est une construction PURE (lectures seules, aucune dépense) : on
   peut donc l'exercer pour de bon. S'il rend un pack vide alors que des
   messages non curés existent, la chaîne est rompue à un endroit qu'aucun
   contrôle d'installation ne regarde — et la panne ne se déclarerait qu'à
   quatre heures du matin, sous la forme d'un cycle qui ne produit rien.

3. **L'état réel de la mémoire**, sans interprétation : combien d'atomes,
   combien portent un vecteur, combien de liens explicites. Les trois chiffres
   sont rendus tels quels. En mode gratuit, ils valent zéro — et c'est cette
   valeur zéro, DITE, qui empêche le harnais de prétendre que le cerveau a
   appris.

CE QU'ELLE NE PROUVE PAS, ET QUI DOIT ÊTRE NOMMÉ
=================================================
Elle ne produit aucun atome, ne calcule aucun embedding, ne fait aucun rappel.
Sans clé, ces trois maillons ne sont pas « en panne » : ils sont **non testés**.
Le harnais les rapporte comme tels. C'est la différence entre *prouvé*,
*prouvé partiellement* et *non testé*, et elle n'est pas cosmétique : un
tableau d'état qui coche une case jamais exercée décourage exactement le
contributeur dont ce framework a besoin.

Sortie : un objet JSON sur la sortie standard. Aucune décision ici — c'est le
harnais qui juge, cette sonde ne fait que mesurer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


async def _sonder(dsn: str, schema: str) -> dict:
    """Les compteurs bruts, puis le pack.

    Une requête par question, aucune jointure astucieuse : ces chiffres seront
    confrontés à ceux que le cockpit sert (étape 7), et il faut qu'une
    divergence accuse le cockpit, pas cette sonde.
    """
    import psycopg

    resultat: dict[str, object] = {}

    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor() as cur:

            async def un(sql: str, defaut: int = 0) -> int:
                try:
                    await cur.execute(sql)
                    ligne = await cur.fetchone()
                    return int(ligne[0]) if ligne and ligne[0] is not None else defaut
                except Exception as exc:  # noqa: BLE001
                    # Une table absente est une INFORMATION, pas un plantage :
                    # la sonde doit pouvoir dire « cette source n'existe pas »
                    # plutôt que mourir et laisser croire à une panne de base.
                    resultat.setdefault("erreurs", []).append(f"{sql.strip()[:60]} → {exc}")
                    await conn.rollback()
                    return -1

            resultat["conversations"] = await un(
                f"SELECT count(*) FROM {schema}.conversations")
            resultat["messages_bruts"] = await un(
                f"SELECT count(*) FROM {schema}.raw_messages")
            resultat["messages_non_cures"] = await un(
                f"SELECT count(*) FROM {schema}.raw_messages m "
                f"JOIN {schema}.conversations c ON c.id = m.conversation_id "
                f"WHERE m.id > c.curated_through_message_id")
            resultat["atomes"] = await un(
                f"SELECT count(*) FROM {schema}.memory_atoms")
            resultat["atomes_avec_vecteur"] = await un(
                f"SELECT count(*) FROM {schema}.memory_atoms WHERE embedding IS NOT NULL")
            resultat["atomes_actifs"] = await un(
                f"SELECT count(*) FROM {schema}.memory_atoms WHERE status = 'active'")
            # `atom_links` : ce commentaire a dit pendant quatre manches que
            # « rien ne l'alimente ». C'est FAUX depuis l'increment 2 :
            # `app/services/atom_links.recompute()` est appelé à chaque tour
            # de cycle (`agents/cortex/cycle.py`), AVANT le garde-dépense —
            # donc même IA coupée — et il écrit les trois relations, dont
            # `semantic_neighbor` (mutual-kNN, K=6, θ=0.25).
            # Si ce chiffre est zéro sur un cerveau d'essai, la raison n'est
            # pas une table orpheline : c'est qu'il n'y a AUCUN atome, parce
            # que la curation est payante et que cette épreuve n'a pas de clé.
            # Ce qui manque réellement, ce n'est pas l'écriture, c'est la
            # LECTURE : aucun chemin servi ne lit ces arêtes — ni le rappel,
            # ni le bundle de contexte.
            resultat["liens_entre_atomes"] = await un(
                f"SELECT count(*) FROM {schema}.atom_links")
            resultat["recus_de_cycle"] = await un(
                f"SELECT count(*) FROM {schema}.run_receipts")
            resultat["domaines"] = await un(f"SELECT count(*) FROM {schema}.scopes")

        # --- Le pack : la sélection de la tranche à digérer -----------------
        #
        # On l'exerce VRAIMENT, avec la même fonction que le cycle appelle. La
        # docstring de `build_pack` le dit : « ce module reste une construction
        # pure (lectures seules) ». C'est ce qui rend cette preuve gratuite.
        try:
            from agents.cortex import pack as pack_mod

            construit = await pack_mod.build_pack(conn)
            presentes = construit.get("presented") or {}
            # ATTENTION AU NOM DU CHAMP — il a coûté un diagnostic entier.
            # `messages_reported` ne compte PAS les messages présentés : il
            # compte ceux qui ont été REPORTÉS (trop gros pour le restant du
            # budget, remis au cycle suivant). Le lire comme « messages
            # présentés » faisait annoncer « 0 message » sur un pack de quatre
            # conversations parfaitement construit, et accusait la chaîne de
            # digestion d'une rupture qui n'existait pas.
            # Ce qui a réellement été mis sous les yeux du curateur, ce sont
            # les `message_ids` de `presented`.
            resultat["pack"] = {
                "conversations_retenues": len(construit.get("pack_meta") or []),
                "messages_presentes": sum(
                    len(v.get("message_ids") or []) for v in presentes.values()
                ),
                "messages_reportes": int(construit.get("messages_reported") or 0),
                "jetons_estimes": int(construit.get("est_tokens") or 0),
                "identifiants": sorted(str(u) for u in presentes),
            }
        except Exception as exc:  # noqa: BLE001
            resultat["pack"] = {"erreur": f"{type(exc).__name__}: {exc}"}

    return resultat


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dsn", default=os.environ.get("DATABASE_URL_AGENT", ""),
                   help="DSN du rôle des cycles (défaut : DATABASE_URL_AGENT)")
    p.add_argument("--schema", default=os.environ.get("ARAC_SCHEMA", "arac"))
    p.add_argument("--racine", type=Path, default=None,
                   help="racine du dépôt à mettre sur sys.path")
    args = p.parse_args(argv)

    if args.racine:
        sys.path.insert(0, str(args.racine))
    if not args.dsn:
        print(json.dumps({"erreur": "aucun DSN : DATABASE_URL_AGENT est vide"}))
        return 2

    try:
        mesure = asyncio.run(_sonder(args.dsn, args.schema))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"erreur": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 3

    print(json.dumps(mesure, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
