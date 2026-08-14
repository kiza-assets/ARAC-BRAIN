"""Tests hermétiques de `agents/cortex/dedup_thresholds.py`.

Routage des seuils par espace, KeyError bruyant, et carve-out cérémonie
sur des VECTEURS DE CLÉS RÉELS tirés du census audité
`$ARAC_HOME/mem/dedup-audit-P-N.json` (positifs = clés cérémonie triade
présentes dans les paires étiquetées ; négatifs = clés réelles pièges dont
les familles obs1/obs2 — entités, PAS des variantes cérémonie).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import dedup_thresholds as dt  # noqa: E402
from agents.cortex import dispose  # noqa: E402


# ------------------------------------------------------------------- routage
def test_threshold_v1_is_historical_008():
    assert dt.get_threshold("v1") == 0.08


def test_threshold_fold_space_is_p023_00124():
    assert dt.get_threshold("rm1-fold-a50") == 0.0124


def test_unknown_space_raises_loud_keyerror():
    with pytest.raises(KeyError) as exc:
        dt.get_threshold("rm2-fold-b60")
    # message actionnable : l'espace fautif ET les espaces connus.
    assert "rm2-fold-b60" in str(exc.value)
    assert "rm1-fold-a50" in str(exc.value)


def test_dispose_served_constant_routes_v1_unchanged():
    """Le chemin SERVI (dispose.py) route get_threshold('v1') — la valeur
    servie reste BIT-IDENTIQUE au 0.08 historique (livraison inerte)."""
    assert dispose.SEMANTIC_DISTANCE_MAX == dt.get_threshold("v1") == 0.08


def test_registry_has_exactly_the_two_decided_spaces():
    """Tout espace ajouté ici sans dérivation P-0xx doit faire ÉCHOUER un
    test — le registre est une décision, pas une commodité."""
    assert set(dt.DEDUP_THRESHOLD_BY_SPACE) == {"v1", "rm1-fold-a50"}


# ------------------------------------------------- carve-out cérémonie (I2)
#: POSITIFS — clés RÉELLES du census (mem/dedup-audit-P-N.json), les 4
#: racines couvertes : mission-d1 (1 segment hex), verdict-validation /
#: verdict-alert / delivery-mission (2 segments hex).
CEREMONY_KEYS_REAL = [
    "mission-d1-05ba6993",
    "mission-d1-dc9de894",
    "verdict-alert-952dbac2-2c0d935b",
    "verdict-alert-e17aaf9e-16bfe7e2",
    "verdict-validation-2bfd197c-de80bed8",
    "verdict-validation-fda4f5c6-d5cf108a",
    "delivery-mission-129ed3c7-4ca4832e",
    "delivery-mission-bab22208-c461f78f",
]

#: NÉGATIFS — clés RÉELLES du census qui RESSEMBLENT à de la cérémonie
#: (tokens verdict/alerte/validation/mission, familles obs1/obs2) mais n'en
#: sont PAS : le carve-out ne doit JAMAIS les exempter du backstop.
NON_CEREMONY_KEYS_REAL = [
    # pièges obs1/obs2 : « obs » = entités observation, pas une racine
    # cérémonie — ce sont les paires du SEUL vrai-dup opérant (durcis/durcies).
    "myguestbox-stats-obs1-obs2-durcis-2026-06-25",
    "myguestbox-stats-obs1-obs2-durcies-2026-06-25",
    "myguestbox-stats-obs1-obs2-resolus-login-owner-2026-06-25",
    # token 'verdict'/'alerte'/'validation' hors motif :
    "travail-pos-security-audit-2026-01-02-verdict",
    "myguestbox-fausse-alerte-rbac-cache-navigateur-2026-06-29",
    "mini-plan-validation-before-implementation",
    # préfixe 'mission'/'phase' réel hors motif :
    "phase-d-1-mvp-blocker-claude-cli-permission-2026-05-19",
    "travail-pos-stock-seuils-alertes",
]

#: NÉGATIFS SYNTHÉTIQUES — frontières exactes du motif (fragilité consignée
#: dans la décision : nouvelle racine → PAS matchée, fail-toward-CREATE
#: signifie que le backstop v2 la traiterait normalement, monitoring B).
NON_CEREMONY_KEYS_BOUNDARY = [
    "observabilite-agents-1",       # piège type mentionné au cadrage
    "mission-d1",                   # racine NUE, aucun segment hex
    "mission-d1-xyz",               # segment non-hex
    "mission-d1-05ba6",             # segment hex trop court (5 < 6)
    "mission-d2-05ba6993",          # NOUVELLE racine non couverte (§D)
    "verdict-alert-952dbac2-2c0d935bff0011223344",  # segment > 12 hex
    "triade-verdict-05ba6993",      # candidate future non couverte (§D)
]


@pytest.mark.parametrize("key", CEREMONY_KEYS_REAL)
def test_real_ceremony_keys_match(key):
    assert dt.is_ceremony_key(key) is True
    assert dt.CEREMONY_RE.match(key)


@pytest.mark.parametrize("key", NON_CEREMONY_KEYS_REAL + NON_CEREMONY_KEYS_BOUNDARY)
def test_real_and_boundary_non_ceremony_keys_do_not_match(key):
    assert dt.is_ceremony_key(key) is False


def test_is_ceremony_key_tolerates_non_str_without_raising():
    """Chemin d'observabilité (log d'armement B) : un non-str ne fait
    JAMAIS crasher — False, et côté fold le prédicat key!= bloque avant."""
    assert dt.is_ceremony_key(None) is False
    assert dt.is_ceremony_key(42) is False


# ----------------------------------------------------- key_sha8 (I5/V0.107)
def test_key_sha8_matches_independent_sha256_prefix():
    """Oracle hashlib indépendant : sha8 = 8 premiers hex de sha256(clé)."""
    import hashlib

    key = "alice-prefers-temporal-comparative-views"  # clé RÉELLE à PII
    expected = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    assert dt.key_sha8(key) == expected
    assert len(dt.key_sha8(key)) == 8


def test_key_sha8_never_contains_the_key_and_is_stable():
    """L'empreinte ne révèle rien (pas de sous-chaîne de la clé) et reste
    corrélable : même clé → même sha8, clés différentes → sha8 différents
    (sur les clés réelles du census)."""
    keys = CEREMONY_KEYS_REAL + NON_CEREMONY_KEYS_REAL
    hashes = [dt.key_sha8(k) for k in keys]
    assert len(set(hashes)) == len(keys)          # pas de collision ici
    assert hashes == [dt.key_sha8(k) for k in keys]  # déterministe
    for k, h in zip(keys, hashes):
        assert h not in k and k not in h


def test_key_sha8_tolerates_non_str_without_raising():
    """Mêmes chemins d'observabilité que is_ceremony_key : jamais crasher."""
    assert dt.key_sha8(None) == dt.key_sha8("None")
    assert len(dt.key_sha8(42)) == 8
