"""Tests politique de seuils du curateur.

Tests pierre-angulaire T1-T5 du brief I9 + bonus T6-T8.

Cible : `agents/curator/policy.py` (module pur fonctionnel, sans I/O).
Stratégie : test direct des helpers — `check_policy`, `compute_adjusted_confidence`,
`detect_secret`, `is_small_talk`, `threshold_for`. Pas de mock subprocess
Claude CLI : ces tests valident la POLITIQUE Python testable. Le LLM
Sonnet 4.5 dans le subprocess est instruit d'appliquer cette politique
via le prompt système (cf agents/curator/prompt.py).

Ces tests sont compatibles avec l'API exportée par `agents/curator/policy.py`
(livré par I4) :

  - THRESHOLDS_BY_KIND, CONFIDENCE_DELTAS, FORBIDDEN_KINDS
  - check_policy(candidate) -> (accepted, reason)
  - threshold_for(kind) -> float | None
  - compute_adjusted_confidence(base, *, flags) -> float
  - detect_secret(text), is_small_talk(text), is_stack_trace(text),
    is_generated_code(text)
"""

from __future__ import annotations

import pytest

from agents.curator import policy


# ===========================================================================
# T1-T5 — Tests pierre-angulaire (brief I9 §A.2)
# ===========================================================================


def test_t1_decision_explicit_phrasing_high_confidence_accepted():
    """T1 — Phrasing explicite « je décide » + confidence 0.92.

    Message : "je décide qu'on bascule sur CAPI côté Shopify"
    → kind=decision scope=travail/strategie, confidence=0.92
    → seuil STRICT 0.85 → ACCEPTÉ.
    """
    candidate = {
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "test-bascule-capi-shopify",
        "value": "je décide qu'on bascule sur CAPI côté Shopify",
        "confidence": 0.92,
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is True
    assert reason == "ok"
    # Et le seuil STRICT vaut bien 0.85
    assert policy.threshold_for("decision") == 0.85


def test_t2_decision_conditional_low_confidence_rejected():
    """T2 — « peut-être qu'on devrait essayer X » + confidence 0.55.

    Sous seuil STRICT (0.85). Atome decision REJETÉ.
    """
    candidate = {
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "test-peutetre-X",
        "value": "peut-être qu'on devrait essayer X",
        "confidence": 0.55,
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is False
    assert reason == "below_threshold"


def test_t3_idea_brute_confidence_above_large_threshold_accepted():
    """T3 — « tiens, et si on ajoutait une feature Y » + confidence 0.62.

    kind=idea seuil LARGE 0.50. 0.62 > 0.50 → ACCEPTÉ.
    """
    candidate = {
        "kind": "idea",
        "scope": "travail/strategie",
        "key": "test-feature-y",
        "value": "tiens, et si on ajoutait une feature Y",
        "confidence": 0.62,
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is True
    assert reason == "ok"
    assert policy.threshold_for("idea") == 0.50


def test_t4_small_talk_rejected_pre_threshold():
    """T4 — small talk "ok merci parfait" → rejet pré-seuil anti-bruit.

    Doit être catché par `is_small_talk` AVANT la vérif confidence.
    `check_policy` retourne reason="small_talk".
    """
    # Test direct du détecteur
    assert policy.is_small_talk("ok merci parfait")
    assert policy.is_small_talk("ok")
    assert policy.is_small_talk("merci")
    assert policy.is_small_talk("parfait")
    # Et via check_policy : même si confidence haute, anti-bruit gagne.
    candidate = {
        "kind": "note",
        "scope": "savoir/references",
        "key": "test-small-talk",
        "value": "ok merci parfait",
        "confidence": 0.95,  # même haute confidence → rejet anti-bruit
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is False
    assert reason == "small_talk"


def test_t5_secret_alert_kind_with_redacted_marker_accepted():
    """T5 — secret détecté (password= ou sk-ant-...) :
       - si kind=alert ET value contient marqueur masqué → ACCEPTÉ
       - si kind != alert OU value contient secret en clair → REJETÉ

    Cohérent avec spec brief : « kind=alert créé + contenu sanitisé en stockage ».
    """
    # Cas 1 : secret en clair, kind=note → reject "secret_in_clear"
    candidate_clear = {
        "kind": "note",
        "scope": "outillage/infrastructure",
        "key": "test-password-leak",
        "value": "le password=foo123 du serveur Hetzner",
        "confidence": 0.95,
    }
    accepted, reason = policy.check_policy(candidate_clear)
    assert accepted is False
    assert reason == "secret_in_clear"

    # Cas 2 : secret en clair MAIS kind=alert sans marqueur masqué → reject
    candidate_alert_clear = {
        "kind": "alert",
        "scope": "outillage/infrastructure",
        "key": "test-alert-secret-clear",
        "value": "secret détecté : password=foo123 dans message",
        "confidence": 0.95,
    }
    accepted2, reason2 = policy.check_policy(candidate_alert_clear)
    assert accepted2 is False
    assert reason2 == "secret_in_clear"

    # Cas 3 : kind=alert AVEC marqueur masqué [REDACTED] → ACCEPTÉ
    candidate_alert_masked = {
        "kind": "alert",
        "scope": "outillage/infrastructure",
        "key": "test-alert-secret-masked",
        "value": "Secret détecté dans conversation, contenu masqué [REDACTED].",
        "confidence": 0.95,
    }
    accepted3, reason3 = policy.check_policy(candidate_alert_masked)
    assert accepted3 is True
    assert reason3 == "ok"

    # Cas 4 : test direct du détecteur sk-ant-...
    assert policy.detect_secret("clé api claude sk-ant-abc123def456ghi789")
    assert policy.detect_secret("password=foo123")
    assert not policy.detect_secret("juste du texte normal")


# ===========================================================================
# Bonus T6-T8 — extensions politique (brief I9 §A.2)
# ===========================================================================


def test_t6_forbidden_kind_rejected_immediately():
    """T6 (variante bonus T6 brief : dedup) — kind interdit refusé fail-fast.

    Note : la spec brief mentionne « dedup positif » via recall_for_dedup
    qui appartient au LLM curator (prompt-level), pas à policy.py (qui n'a
    pas accès à la BDD / embeddings). On valide ici la couche policy : les
    kinds réservés agents triade (delivery, validation, contradiction,
    suggestion, agent_message) ne sont JAMAIS posés par le curator.

    Cohérent avec FORBIDDEN_KINDS de policy.py (kinds interdits).
    """
    for forbidden in ("delivery", "validation", "contradiction", "suggestion", "agent_message"):
        candidate = {
            "kind": forbidden,
            "scope": "savoir/references",
            "key": f"test-forbidden-{forbidden}",
            "value": "contenu quelconque",
            "confidence": 0.99,
        }
        accepted, reason = policy.check_policy(candidate)
        assert accepted is False, f"forbidden kind {forbidden} should reject"
        assert reason == "forbidden_kind"
        assert policy.threshold_for(forbidden) is None


def test_t7_multi_kind_distinct_atoms_independent_policy_evaluation():
    """T7 — un message peut conceptuellement produire plusieurs atomes
    (decision + idea). On valide ici que la politique s'évalue
    INDÉPENDAMMENT pour chaque atome candidat.
    """
    msg = "OK je décide qu'on bascule CAPI Shopify. À explorer : un funnel mobile-first."

    decision_candidate = {
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "test-multi-decision",
        "value": msg,
        "confidence": 0.91,
    }
    idea_candidate = {
        "kind": "idea",
        "scope": "travail/strategie",
        "key": "test-multi-idea",
        "value": msg,
        "confidence": 0.62,
    }

    accepted_dec, reason_dec = policy.check_policy(decision_candidate)
    accepted_idea, reason_idea = policy.check_policy(idea_candidate)

    assert accepted_dec is True
    assert reason_dec == "ok"
    assert accepted_idea is True
    assert reason_idea == "ok"


def test_t8_large_threshold_relaxed_058_passes():
    """T8 — seuil LARGE relâché : confidence 0.51 sur kind=note (seuil 0.50)
    PASSE. Vérifie que la limite est inclusive (>=).
    """
    # kind=note seuil 0.50 → 0.51 passe
    candidate = {
        "kind": "note",
        "scope": "savoir/references",
        "key": "test-large-passes",
        "value": "Une note libre captée par curator, utile pour relecture future.",
        "confidence": 0.51,
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is True
    assert reason == "ok"

    # Et même tout pile au seuil 0.50 doit passer
    candidate_at = dict(candidate)
    candidate_at["confidence"] = 0.50
    candidate_at["key"] = "test-large-at-threshold"
    accepted_at, reason_at = policy.check_policy(candidate_at)
    assert accepted_at is True
    assert reason_at == "ok"

    # Juste en-dessous 0.49 rejette
    candidate_below = dict(candidate)
    candidate_below["confidence"] = 0.49
    candidate_below["key"] = "test-large-below-threshold"
    accepted_below, reason_below = policy.check_policy(candidate_below)
    assert accepted_below is False
    assert reason_below == "below_threshold"


# ===========================================================================
# Tests heuristiques confidence — compute_adjusted_confidence
# ===========================================================================


def test_confidence_explicit_phrasing_pushes_above_strict():
    """Heuristique : base 0.5 + explicit_phrasing(+0.30) + context(+0.10)
    + coherent(+0.05) = 0.95 → couvre seuil STRICT 0.85.
    """
    score = policy.compute_adjusted_confidence(
        0.5,
        flags={
            "explicit_phrasing": True,
            "context_identifiable": True,
            "coherent_existing": True,
        },
    )
    assert score == pytest.approx(0.95, abs=1e-6)
    assert score >= policy.threshold_for("decision")  # 0.85


def test_confidence_small_talk_clipped_to_zero():
    """Heuristique : base 0.5 + small_talk(-0.80) = clip 0.0."""
    score = policy.compute_adjusted_confidence(0.5, flags={"small_talk": True})
    assert score == 0.0


def test_confidence_conditional_below_strict_threshold():
    """Heuristique : base 0.5 + conditional(-0.20) = 0.30 → sous tout seuil."""
    score = policy.compute_adjusted_confidence(0.5, flags={"conditional": True})
    assert score == pytest.approx(0.30, abs=1e-6)
    assert score < policy.threshold_for("decision")
    assert score < policy.threshold_for("idea")  # 0.50 aussi


# ===========================================================================
# Tests anti-bruit positif (couverture supplémentaire)
# ===========================================================================


def test_stack_trace_rejected_even_with_high_confidence():
    """Stack trace détectée → reject "stack_trace" indépendamment du kind."""
    stack = (
        "Traceback (most recent call last):\n"
        '  File "foo.py", line 42, in <module>\n'
        "    raise ValueError('boom')"
    )
    assert policy.is_stack_trace(stack)
    candidate = {
        "kind": "gotcha",  # même un kind STRICT n'efface pas anti-bruit
        "scope": "savoir/references",
        "key": "test-stack-trace",
        "value": stack,
        "confidence": 0.99,
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is False
    assert reason == "stack_trace"


def test_generated_code_block_rejected():
    """Bloc ```python ... → rejet "generated_code"."""
    code_msg = "Voici le snippet :\n```python\nx = 1\nprint(x)\n```"
    assert policy.is_generated_code(code_msg)
    candidate = {
        "kind": "idea",
        "scope": "savoir/references",
        "key": "test-generated-code",
        "value": code_msg,
        "confidence": 0.99,
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is False
    assert reason == "generated_code"


def test_unknown_kind_rejected():
    """kind non listé dans THRESHOLDS_BY_KIND → reject "unknown_kind"."""
    candidate = {
        "kind": "fictional_kind",
        "scope": "savoir/references",
        "key": "test-unknown",
        "value": "x",
        "confidence": 0.99,
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is False
    assert reason == "unknown_kind"


def test_confidence_label_curator_strict_resolves_to_085():
    """Confidence sous forme de label `curator_strict` → 0.85, accepté
    pile au seuil decision.
    """
    candidate = {
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "test-label-strict",
        "value": "je décide d'un truc clair et net",
        "confidence": "curator_strict",  # label, pas float
    }
    accepted, reason = policy.check_policy(candidate)
    assert accepted is True
    assert reason == "ok"
