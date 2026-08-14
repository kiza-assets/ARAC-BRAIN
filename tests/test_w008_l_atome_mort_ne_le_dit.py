"""W-008 — l'atome qui naît hors du rappel doit le dire, et le dire seul.

CE QUE CE FICHIER ÉPROUVE, ET POURQUOI IL EST HORS-LIGNE
========================================================
`_check_w008_ne_nait_pas_actif` est une fonction PURE : elle lit la ligne que
la base vient de rendre et décide. C'est délibéré — un warning qui exigerait
une base pour être éprouvé ne le serait que dans `make acceptance`, une fois
sur dix, et c'est ainsi qu'un garde s'endort.

LE DÉFAUT QU'IL EXISTE POUR NOMMER — mesuré, pas déduit
=======================================================
Cerveau réel « vide1brain » (grappe 5496, API 8320), 9 août 2026 :

    atome « suggestion d'agent » (audit_source=autonomous_agent_suggest),
    confidence_score = 30, status = active
    POST /v1/atoms/<id>/supersede {"new_value": "…"}          → 201
      ancien   : status = superseded
      nouveau  : status = low_confidence_archive
      SELECT count(*) … scope/key … status='active'           → 0
      POST /v1/atoms/recall                                    → []

Personne n'avait rien demandé au chiffre : la supersédure HÉRITE le score
quand l'appelant n'en parle pas, et `arac.tg_auto_archive_low_confidence`
(BEFORE INSERT, seuil 70) archive le remplaçant. Réponse 201, `warnings: []`,
et un souvenir en moins.

Le seuil est VOULU. Le silence ne l'était pas.
"""

from __future__ import annotations

import uuid

from app.routers.atoms import _check_w008_ne_nait_pas_actif


def _ligne(statut: str, **extra) -> dict:
    """Une ligne telle que `RETURNING *` la rend."""
    base = {
        "id": uuid.uuid4(),
        "status": statut,
        "scope": "travail/strategie",
        "key": "fournisseur",
        "confidence": "agent_suggest",
        "audit_source": "autonomous_agent_suggest",
        "confidence_score": 30,
    }
    base.update(extra)
    return base


def test_un_atome_actif_ne_declenche_rien() -> None:
    """Le cas normal, et c'est l'immense majorité : aucun bruit."""
    assert _check_w008_ne_nait_pas_actif(_ligne("active")) is None


def test_l_atome_archive_a_la_naissance_est_nomme() -> None:
    """Le cas mesuré : 201, statut autre qu'actif, et maintenant un mot."""
    w = _check_w008_ne_nait_pas_actif(_ligne("low_confidence_archive"))
    assert w is not None, (
        "la supersédure d'une suggestion d'agent sous le seuil redevient une "
        "perte silencieuse")
    assert w.code == "W-008"
    assert w.severity == "warning", (
        "`info` serait trop faible — un souvenir sort du rappel ; `critical` "
        "serait faux — l'archivage est le comportement voulu du seuil")
    assert "low_confidence_archive" in w.message
    assert w.context["confidence_score"] == 30
    assert w.context["seuil_archivage_basse_confiance"] == 70


def test_le_warning_dit_les_deux_gestes_qui_reparent() -> None:
    """Un warning qui nomme le mal sans nommer le remède coûte une soirée."""
    w = _check_w008_ne_nait_pas_actif(_ligne("low_confidence_archive"))
    assert w is not None
    aide = w.remediation_hint or ""
    assert "PATCH" in aide, "le geste qui remonte un score sans archiver"
    assert "new_confidence_score" in aide, "le geste qui supersède sans perdre"
    assert "BEFORE INSERT" in aide or "INSERT" in aide, (
        "l'asymétrie INSERT/UPDATE est TOUTE l'explication : sans elle le "
        "lecteur croit que PATCH archive aussi")


def test_il_ne_juge_pas_la_cause_mais_le_resultat() -> None:
    """Le garde lit le STATUT rendu, pas le motif supposé.

    C'est ce qui le rend durable : si un autre trigger, une autre migration ou
    une autre règle décide un jour qu'un atome naît `draft` ou `archived`, le
    warning sort quand même — alors qu'un test sur `confidence_score < 70`
    n'aurait vu que le cas d'aujourd'hui.
    """
    for statut in ("draft", "archived", "superseded", "low_confidence_archive"):
        w = _check_w008_ne_nait_pas_actif(
            _ligne(statut, audit_source=None, confidence_score=95,
                   confidence="producer"))
        assert w is not None, statut
        assert statut in w.message, statut
