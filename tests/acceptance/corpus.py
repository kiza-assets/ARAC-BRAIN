#!/usr/bin/env python3
"""corpus.py — des conversations fictives, aux formats RÉELS, sur un faux Mac.

POURQUOI CE FICHIER EXISTE
==========================
L'étape 5 du critère d'acceptation dit : « synchroniser ses premières
conversations ». Le pont Mac ne peut pas exister dans un test automatique — il
n'y a ni macOS, ni launchd, ni Claude Desktop, ni tunnel SSH sur un serveur
d'intégration. Deux façons de traiter ce fait :

  · sauter l'étape en silence, et déclarer le test « réussi ». C'est ce que
    fait un test qui ne vérifie rien de difficile ;
  · construire un corpus fictif AUX FORMATS RÉELS, et le faire entrer par LE
    VRAI CHEMIN — le vrai exporteur (``mac/arac-sync.py``), la vraie API, les
    vraies gardes, le vrai node_id.

Ce fichier fait le second. Il n'invente aucun format : les deux structures
qu'il écrit sont celles que ``mac/arac-sync.py`` sait lire, et c'est ce même
programme, non modifié, qui les relira et les enverra.

CE QUI RESTE NON TESTÉ, ET QUI DOIT ÊTRE DIT
============================================
Écrire ces fichiers ne prouve pas que Claude Desktop les écrit ainsi sur un
vrai Mac, ni que ``launchd`` déclenche la synchronisation, ni que le tunnel SSH
transporte. Ces trois maillons restent **non testés**, et le harnais les nomme
comme tels dans son rapport. Ce que le corpus prouve, lui, est réel : les
formats sont lus, les gardes s'appliquent, les messages arrivent en base.

LES DEUX FORMATS, TELS QUE LE PONT LES LIT
==========================================
1. **Claude Code CLI** — ``$HOME/.claude/projects/<projet>/<session>.jsonl``.
   Une ligne JSON par événement. Le pont retient celles qui portent un rôle
   (``type`` ∈ {user, assistant}, ou ``message.role``), et lit
   ``uuid`` / ``parentUuid`` / ``message.content`` / ``timestamp`` / ``cwd``.
   Le fichier contient AUSSI des lignes de contrôle sans rôle — c'est le cas
   réel, et le corpus en pose exprès : un exporteur qui les compterait comme
   des messages gonflerait les chiffres de tout le monde.

2. **Export claude.ai** — ``conversations.json``. Un instantané : une liste de
   conversations, chacune avec ``uuid`` / ``name`` / ``chat_messages``, et
   dans chaque message ``uuid`` / ``sender`` (``human`` ou ``assistant``) /
   ``text`` ou ``content`` / ``created_at``, plus d'éventuelles pièces jointes.
   Le corpus pose une pièce jointe SANS contenu extrait, parce que c'est le cas
   qui produit un marqueur plutôt qu'un trou muet — et qu'un test qui ne voit
   jamais ce cas ne protège pas contre sa disparition.

LE JETON DE TRAÇABILITÉ
=======================
Chaque corpus porte un ``jeton`` — une chaîne unique par exécution, présente
dans le contenu des messages. C'est lui qui permet, à l'étape 7, d'affirmer que
le cockpit parle bien de CE cerveau-là et pas d'un autre : les chiffres qu'il
sert doivent compter ces messages-ci, et l'on peut remonter jusqu'à eux.

Contenu volontairement générique et synthétique : aucune personne, aucune
société, aucun lieu réels. Ce corpus ne doit ressembler au cerveau de personne.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ===========================================================================
# La matière : quatre conversations fictives, deux par format
# ===========================================================================
#
# Elles sont écrites pour être CURABLES : chacune contient une décision
# explicite, datée, avec sa raison. C'est ce qu'un curateur doit savoir
# extraire. Un corpus de bavardage ne prouverait rien du mode complet — il
# rendrait « zéro atome » ambigu : le cerveau n'a-t-il rien appris, ou n'y
# avait-il rien à apprendre ?

_SESSIONS_CODE: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "outillage-sauvegardes",
        "/travail/infra",
        (
            ("user",
             "On garde les sauvegardes de la base combien de temps ? "
             "Aujourd'hui c'est 14 jours et je trouve ça court."),
            ("assistant",
             "Quatorze jours couvre une panne matérielle, pas une corruption "
             "logique découverte tardivement. Si la restauration n'a jamais été "
             "rejouée, la durée de rétention n'est pas le premier problème."),
            ("user",
             "Décision : on passe la rétention à 30 jours, et on rejoue une "
             "restauration complète le premier lundi de chaque mois. "
             "Raison : une sauvegarde jamais restaurée n'est pas une sauvegarde."),
            ("assistant",
             "Noté. La bascule se fait par la variable de rétention de l'unité "
             "de sauvegarde ; le test de restauration, lui, demande une base "
             "jetable — sinon personne ne le fera."),
            ("user",
             "Exact. On monte une base jetable pour ça. Point suivant la "
             "semaine prochaine."),
        ),
    ),
    (
        "outillage-supervision",
        "/travail/infra",
        (
            ("user",
             "Le tableau de bord affiche un service « actif » alors qu'il "
             "redémarre en boucle. Comment c'est possible ?"),
            ("assistant",
             "Une unité en Type=simple est déclarée active dès le fork, avant "
             "que le programme ait tenté d'ouvrir sa socket. « Actif » ne dit "
             "donc rien de « répond »."),
            ("user",
             "Décision : la supervision ne se fiera plus au seul état systemd. "
             "Elle vérifiera que la socket est bien tenue par le processus de "
             "l'unité attendue. Raison : un port peut être tenu par un autre "
             "programme, et la sonde répond alors 200 pour le mauvais service."),
            ("assistant",
             "C'est la seule façon de distinguer « mon service répond » de "
             "« quelque chose répond sur ce port »."),
        ),
    ),
)

_CONVERSATIONS_DESKTOP: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Rythme de digestion et coût",
        (
            ("human",
             "Est-ce que je dois faire tourner la digestion en continu ou par "
             "cycles ?"),
            ("assistant",
             "Penser coûte. Une digestion continue coûte en continu, pour un "
             "gain de fraîcheur que personne ne mesure. Des cycles espacés "
             "accumulent puis traitent d'un coup."),
            ("human",
             "Décision : trois cycles par jour, pas de digestion continue. "
             "Raison : le coût de curation domine la facture, et la fraîcheur "
             "à la minute n'a aucune valeur pour de la mémoire longue."),
            ("assistant",
             "Conséquence à accepter : ce qui est dit à 14 h n'est pas "
             "mémorisé à 14 h 01. Un cerveau au repos n'est pas un cerveau en "
             "panne."),
        ),
    ),
    (
        "Où rangent les souvenirs",
        (
            ("human",
             "Je peux ranger un souvenir directement sur un domaine racine ?"),
            ("assistant",
             "En base, oui. Au rappel, non : les racines sont des conteneurs, "
             "et un souvenir posé dessus ne remonte jamais. Il existe et reste "
             "invisible."),
            ("human",
             "Décision : tout souvenir se range sur une feuille, jamais sur "
             "une racine. Raison : un souvenir invisible coûte autant qu'un "
             "souvenir utile et ne sert à rien."),
        ),
    ),
)


# ===========================================================================
# Écriture — format Claude Code CLI
# ===========================================================================


def _ecrire_claude_code(racine: Path, jeton: str, depart: datetime) -> dict:
    """Écrit les sessions .jsonl comme le CLI les écrit, une ligne par événement.

    Deux détails qui ne sont pas de la décoration :

    · les lignes SANS rôle (``type='summary'``, ``type='system'``) sont posées
      exprès. Le vrai fichier en contient ; le pont doit les écarter. Sans
      elles, on ne testerait que le cas facile.
    · ``parentUuid`` chaîne les messages. Il part à l'ingestion et n'est pas
      utilisé aujourd'hui — le déclarer ici plutôt que de le taire garde le
      corpus fidèle au format, pas au consommateur du moment.
    """
    attendus = 0
    sessions: list[dict] = []
    horloge = depart

    for index, (projet, cwd, echanges) in enumerate(_SESSIONS_CODE):
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"arac-acceptation/{jeton}/code/{index}"))
        dossier = racine / "projects" / projet
        dossier.mkdir(parents=True, exist_ok=True)
        fichier = dossier / f"{session_id}.jsonl"

        lignes: list[dict] = [
            # Une ligne de contrôle, sans rôle : elle ne doit PAS être comptée.
            {
                "type": "summary",
                "sessionId": session_id,
                "summary": f"session d'acceptation {jeton}",
                "cwd": cwd,
                "timestamp": horloge.isoformat().replace("+00:00", "Z"),
            }
        ]
        parent: str | None = None
        for rang, (role, texte) in enumerate(echanges):
            horloge = horloge + timedelta(minutes=2)
            mid = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                 f"arac-acceptation/{jeton}/code/{index}/{rang}"))
            contenu = texte if rang else f"[acceptation {jeton}] {texte}"
            lignes.append({
                "type": role,
                "uuid": mid,
                "parentUuid": parent,
                "sessionId": session_id,
                "cwd": cwd,
                "timestamp": horloge.isoformat().replace("+00:00", "Z"),
                # Le CLI écrit tantôt une chaîne, tantôt une liste de blocs.
                # On alterne : le lecteur doit savoir faire les deux.
                "message": {
                    "role": role,
                    "content": (
                        contenu if rang % 2 == 0
                        else [{"type": "text", "text": contenu}]
                    ),
                },
            })
            parent = mid
            attendus += 1

        # Une seconde ligne de contrôle, en fin de fichier.
        lignes.append({
            "type": "system",
            "sessionId": session_id,
            "content": "fin de session",
            "timestamp": horloge.isoformat().replace("+00:00", "Z"),
        })

        fichier.write_text(
            "\n".join(json.dumps(l, ensure_ascii=False) for l in lignes) + "\n",
            encoding="utf-8",
        )
        sessions.append({
            "conversation_uid": session_id,
            "fichier": str(fichier),
            "messages": len(echanges),
        })

    return {"source_type": "claude_code", "conversations": sessions, "messages": attendus}


# ===========================================================================
# Écriture — format export claude.ai
# ===========================================================================


def _ecrire_export_desktop(fichier: Path, jeton: str, depart: datetime) -> dict:
    """Écrit `conversations.json` comme l'export officiel le rend.

    La pièce jointe SANS ``extracted_content`` est délibérée : c'est le cas qui
    doit laisser un marqueur nommé dans le contenu plutôt qu'un trou muet.
    Un souvenir incomplet dont on ignore la raison est pire qu'un souvenir
    incomplet qui dit pourquoi.
    """
    fichier.parent.mkdir(parents=True, exist_ok=True)
    attendus = 0
    conversations: list[dict] = []
    horloge = depart

    for index, (titre, echanges) in enumerate(_CONVERSATIONS_DESKTOP):
        conv_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                 f"arac-acceptation/{jeton}/desktop/{index}"))
        messages: list[dict] = []
        for rang, (sender, texte) in enumerate(echanges):
            horloge = horloge + timedelta(minutes=3)
            mid = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                 f"arac-acceptation/{jeton}/desktop/{index}/{rang}"))
            contenu = texte if rang else f"[acceptation {jeton}] {texte}"
            message = {
                "uuid": mid,
                "sender": sender,
                "created_at": horloge.isoformat().replace("+00:00", "Z"),
                "updated_at": horloge.isoformat().replace("+00:00", "Z"),
                # L'export mélange `text` et `content` en blocs selon l'âge de
                # la conversation. On pose les deux formes.
                **(
                    {"text": contenu}
                    if rang % 2 == 0
                    else {"content": [{"type": "text", "text": contenu}]}
                ),
                "attachments": [],
                "files": [],
            }
            if index == 0 and rang == 1:
                message["attachments"] = [{
                    "file_name": "tableau-des-couts.csv",
                    "file_type": "text/csv",
                    # Volontairement sans `extracted_content`.
                }]
            messages.append(message)
            attendus += 1

        conversations.append({
            "uuid": conv_id,
            "name": titre,
            "created_at": depart.isoformat().replace("+00:00", "Z"),
            "updated_at": horloge.isoformat().replace("+00:00", "Z"),
            "chat_messages": messages,
        })

    fichier.write_text(json.dumps(conversations, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    return {
        "source_type": "desktop_chat",
        "conversations": [
            {"conversation_uid": c["uuid"], "titre": c["name"],
             "messages": len(c["chat_messages"])}
            for c in conversations
        ],
        "messages": attendus,
        "fichier": str(fichier),
    }


# ===========================================================================
# Point d'entrée
# ===========================================================================


#: L'ÂGE DU CORPUS N'EST PAS UN DÉTAIL — c'est ce qui décide s'il sera digéré.
#:
#: Le gate de curation (`agents/lib/curator_lib_v2.select_eligible_conversations`)
#: refuse une conversation encore CHAUDE. Une conversation n'entre dans un pack
#: que si l'une des deux conditions tient :
#:   · elle est calme depuis ARAC_CURATOR_QUIET_HOURS (défaut 2 h) et porte au
#:     moins ARAC_CURATOR_MIN_NEW_MSGS nouveaux messages (défaut 3) ;
#:   · ou son plus vieux message non curé date de plus de
#:     ARAC_CURATOR_AGE_CAP_HOURS (défaut 24 h).
#:
#: Ce n'est pas un défaut : c'est la doctrine « trois cycles par jour, pas un
#: flux continu ». Un corpus daté d'il y a deux heures produisait donc un pack
#: VIDE, et le test accusait la chaîne de digestion d'être rompue alors qu'elle
#: faisait exactement ce qu'elle promet.
#:
#: Trois jours : au-delà des deux seuils, avec de la marge, et fidèle à ce
#: qu'est une PREMIÈRE synchronisation — elle remonte un historique existant,
#: pas une conversation en cours.
AGE_PAR_DEFAUT_HEURES = 72


def construire(racine: Path, jeton: str, age_heures: float = AGE_PAR_DEFAUT_HEURES) -> dict:
    """Pose un faux « Mac » sous `racine` et rend le manifeste de ce qui doit
    arriver en base.

    Le manifeste est le contrat du test : c'est LUI que l'étape 5 confronte à
    ce que le serveur a réellement accepté. Un test qui compterait les
    messages après coup, en base, ne vérifierait que sa propre lecture.
    """
    racine.mkdir(parents=True, exist_ok=True)
    depart = datetime.now(timezone.utc) - timedelta(hours=age_heures)

    code = _ecrire_claude_code(racine / "claude", jeton, depart)
    desktop = _ecrire_export_desktop(
        racine / "arac" / "export-desktop" / "conversations.json", jeton, depart
    )

    return {
        "jeton": jeton,
        "claude_code_dir": str(racine / "claude" / "projects"),
        "desktop_export": str(racine / "arac" / "export-desktop" / "conversations.json"),
        "sources": [code, desktop],
        "messages_attendus": code["messages"] + desktop["messages"],
        "conversations_attendues": (
            len(code["conversations"]) + len(desktop["conversations"])
        ),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--racine", type=Path, required=True,
                   help="dossier où poser le faux Mac")
    p.add_argument("--jeton", required=True,
                   help="chaîne unique de traçabilité, présente dans les messages")
    p.add_argument("--manifeste", type=Path, default=None,
                   help="où écrire le manifeste JSON (défaut : sortie standard)")
    p.add_argument("--age-heures", type=float, default=AGE_PAR_DEFAUT_HEURES,
                   help="ancienneté du corpus, en heures (défaut : "
                        f"{AGE_PAR_DEFAUT_HEURES}, au-delà des seuils du gate de curation)")
    args = p.parse_args(argv)

    manifeste = construire(args.racine, args.jeton, args.age_heures)
    texte = json.dumps(manifeste, ensure_ascii=False, indent=2)
    if args.manifeste:
        args.manifeste.write_text(texte + "\n", encoding="utf-8")
    else:
        print(texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
