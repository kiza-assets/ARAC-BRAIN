"""Tests ARAC — Control Center : couche sécurité.

Couverture :
  1. Vecteurs TOTP RFC 6238 (Appendix B, secret ASCII '12345678901234567890')
  2. totp_verify fenêtre +/- 1 step
  3. hash_password / verify_password : round-trip + rejet mauvais mdp
  4. sign_session / verify_session : round-trip, rejet signature trafiquée,
     rejet token expiré (via iat ancien)
  5. require_session : 401 sans cookie (via TestClient FastAPI minimal)
  6. Garanties statiques : grep source security.py
       - 0 secret/mot de passe en dur
       - 0 import provider/HTTP externe
       - 0 écriture DB

RFC 6238 — vecteurs Appendix B (TOTP-SHA1, T0=0, step=30) :
  Secret ASCII : '12345678901234567890'
  Secret base32: GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ

  T=59             counter=1           code=287082
  T=1111111109     counter=37037036    code=081804
  T=1111111111     counter=37037037    code=050471
  T=1234567890     counter=41152263    code=005924
  T=2000000000     counter=66666666    code=279037
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_center.security import (
    audit_read_log,
    hash_password,
    require_session,
    sign_session,
    totp_now,
    totp_verify,
    verify_password,
    verify_session,
)
from control_center.config import SESSION_COOKIE_NAME, SESSION_TTL_SECONDS

# ============================================================================
# Constantes de test
# ============================================================================

# Secret RFC 6238 Appendix B : ASCII '12345678901234567890' → base32
_RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

# Vecteurs (timestamp Unix, code attendu 6 digits)
_RFC_VECTORS = [
    (59,          "287082"),
    (1111111109,  "081804"),
    (1111111111,  "050471"),
    (1234567890,  "005924"),
    (2000000000,  "279037"),
]

# Secret de session factice pour les tests (64 chars hex, pas de vraie valeur)
_TEST_SESSION_SECRET = "a" * 64


# ============================================================================
# 1. Vecteurs TOTP RFC 6238
# ============================================================================


@pytest.mark.parametrize("t, expected_code", _RFC_VECTORS)
def test_totp_now_rfc6238_vectors(t: int, expected_code: str) -> None:
    """totp_now() produit les codes exacts définis en RFC 6238 Appendix B."""
    code = totp_now(_RFC_SECRET, t=float(t), step=30, digits=6)
    assert code == expected_code, (
        f"RFC 6238 vector T={t}: expected {expected_code!r}, got {code!r}"
    )


def test_totp_now_two_distinct_vectors() -> None:
    """Au moins deux timestamps distincts produisent des codes différents."""
    code_59 = totp_now(_RFC_SECRET, t=59.0)
    code_1111 = totp_now(_RFC_SECRET, t=1111111109.0)
    assert code_59 != code_1111


# ============================================================================
# 2. totp_verify — fenêtre +/- 1
# ============================================================================


def test_totp_verify_current_step() -> None:
    """Le code du step courant est accepté."""
    t = 59.0
    code = totp_now(_RFC_SECRET, t=t)
    assert totp_verify(_RFC_SECRET, code, t=t, window=1)


def test_totp_verify_previous_step_within_window() -> None:
    """Le code du step précédent est accepté dans la fenêtre window=1."""
    # T=59 → step 1 (counter=1), code=287082
    # T=89 → step 2 (counter=2), code différent
    # On vérifie à T=89 le code du step 1 → doit être accepté (window=1)
    code_step1 = totp_now(_RFC_SECRET, t=59.0)   # counter=1
    assert totp_verify(_RFC_SECRET, code_step1, t=89.0, window=1)


def test_totp_verify_next_step_within_window() -> None:
    """Le code du step suivant est accepté dans la fenêtre window=1."""
    # On vérifie à T=59 le code de T=89 (step suivant) → doit être accepté
    code_step2 = totp_now(_RFC_SECRET, t=89.0)   # counter=2
    assert totp_verify(_RFC_SECRET, code_step2, t=59.0, window=1)


def test_totp_verify_outside_window_rejected() -> None:
    """Un code trop ancien (2 steps d'écart) est rejeté avec window=1."""
    # T=59 → step 1, T=149 → step 4 (counter=4) — écart de 3 steps
    code_old = totp_now(_RFC_SECRET, t=59.0)
    assert not totp_verify(_RFC_SECRET, code_old, t=149.0, window=1)


def test_totp_verify_wrong_code_rejected() -> None:
    """Un code arbitraire erroné est rejeté."""
    assert not totp_verify(_RFC_SECRET, "000000", t=59.0, window=1)


def test_totp_verify_case_insensitive_secret() -> None:
    """Le secret base32 est accepté en minuscules ou majuscules."""
    t = 59.0
    code_upper = totp_now(_RFC_SECRET.upper(), t=t)
    code_lower = totp_now(_RFC_SECRET.lower(), t=t)
    assert code_upper == code_lower == "287082"


# ============================================================================
# 3. hash_password / verify_password
# ============================================================================


def test_hash_password_format() -> None:
    """hash_password() retourne une chaîne au format pbkdf2_sha256$iter$salt$hash."""
    stored = hash_password("mot_de_passe_test")
    parts = stored.split("$")
    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) >= 200_000
    # salt et hash sont des hex strings non-vides
    assert len(parts[2]) > 0
    assert len(parts[3]) > 0
    bytes.fromhex(parts[2])  # ne lève pas si c'est du hex valide
    bytes.fromhex(parts[3])


def test_verify_password_roundtrip() -> None:
    """verify_password() accepte le bon mot de passe après hash_password()."""
    pw = "monSuperMotDePasse!42"
    stored = hash_password(pw)
    assert verify_password(pw, stored) is True


def test_verify_password_wrong_rejected() -> None:
    """verify_password() rejette un mot de passe incorrect."""
    stored = hash_password("correct")
    assert verify_password("incorrect", stored) is False


def test_verify_password_empty_wrong() -> None:
    """verify_password() rejette un mot de passe vide contre un hash valide."""
    stored = hash_password("nonempty")
    assert verify_password("", stored) is False


def test_verify_password_invalid_format() -> None:
    """verify_password() retourne False sur un hash mal formaté."""
    assert verify_password("anything", "not_a_valid_hash") is False
    assert verify_password("anything", "pbkdf2_sha256$abc$def") is False  # 3 parts
    assert verify_password("anything", "bcrypt$1$x$y") is False           # mauvais algo


def test_hash_password_different_salts() -> None:
    """Deux appels à hash_password() produisent des hashes distincts (sel aléatoire)."""
    pw = "same_password"
    h1 = hash_password(pw)
    h2 = hash_password(pw)
    assert h1 != h2  # sels différents → hashes différents
    # Mais les deux sont valides
    assert verify_password(pw, h1)
    assert verify_password(pw, h2)


def test_hash_password_custom_salt() -> None:
    """hash_password() avec sel fixe produit un résultat reproductible."""
    salt = b"\x00" * 16
    h1 = hash_password("pw", salt=salt)
    h2 = hash_password("pw", salt=salt)
    assert h1 == h2


# ============================================================================
# 4. sign_session / verify_session
# ============================================================================


def test_sign_verify_session_roundtrip() -> None:
    """verify_session() décode correctement un token créé par sign_session()."""
    payload = {"sub": "admin"}
    token = sign_session(payload, _TEST_SESSION_SECRET)
    result = verify_session(token, _TEST_SESSION_SECRET)
    assert result is not None
    assert result["sub"] == "admin"
    assert "iat" in result


def test_verify_session_tampered_signature_rejected() -> None:
    """verify_session() rejette un token avec une signature modifiée."""
    token = sign_session({"sub": "admin"}, _TEST_SESSION_SECRET)
    # Modifier le dernier caractère de la signature
    b64_part, sig = token.rsplit(".", 1)
    tampered_sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    tampered_token = f"{b64_part}.{tampered_sig}"
    assert verify_session(tampered_token, _TEST_SESSION_SECRET) is None


def test_verify_session_tampered_payload_rejected() -> None:
    """verify_session() rejette un token avec payload modifié (sig ne correspond plus)."""
    import base64

    token = sign_session({"sub": "admin"}, _TEST_SESSION_SECRET)
    b64_part, sig = token.rsplit(".", 1)
    # Recoder un payload différent avec la même signature → doit être rejeté
    evil_payload = base64.urlsafe_b64encode(b'{"sub":"superadmin","iat":9999999999}').rstrip(b"=").decode()
    evil_token = f"{evil_payload}.{sig}"
    assert verify_session(evil_token, _TEST_SESSION_SECRET) is None


def test_verify_session_expired_rejected() -> None:
    """verify_session() rejette un token dont l'iat est trop ancien."""
    old_iat = int(time.time()) - SESSION_TTL_SECONDS - 1
    payload = {"sub": "admin", "iat": old_iat}
    # Signer manuellement avec iat ancien (signer sans auto-iat)
    import base64, json, hmac as _hmac, hashlib as _hashlib

    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    b64_payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    sig = _hmac.new(
        _TEST_SESSION_SECRET.encode(), b64_payload.encode(), _hashlib.sha256
    ).hexdigest()
    old_token = f"{b64_payload}.{sig}"
    assert verify_session(old_token, _TEST_SESSION_SECRET) is None


def test_verify_session_wrong_secret_rejected() -> None:
    """verify_session() rejette un token signé avec un secret différent."""
    token = sign_session({"sub": "admin"}, _TEST_SESSION_SECRET)
    assert verify_session(token, "b" * 64) is None


def test_verify_session_malformed_token() -> None:
    """verify_session() retourne None sur des tokens malformés."""
    assert verify_session("", _TEST_SESSION_SECRET) is None
    assert verify_session("nodot", _TEST_SESSION_SECRET) is None
    assert verify_session("not.valid.token.extra", _TEST_SESSION_SECRET) is None


def test_sign_session_auto_iat() -> None:
    """sign_session() ajoute automatiquement le champ 'iat' si absent."""
    before = int(time.time())
    token = sign_session({"sub": "admin"}, _TEST_SESSION_SECRET)
    after = int(time.time())
    payload = verify_session(token, _TEST_SESSION_SECRET)
    assert payload is not None
    assert before <= payload["iat"] <= after


def test_sign_session_preserves_explicit_iat() -> None:
    """sign_session() préserve un 'iat' explicitement fourni."""
    explicit_iat = int(time.time()) - 10
    token = sign_session({"sub": "admin", "iat": explicit_iat}, _TEST_SESSION_SECRET)
    payload = verify_session(token, _TEST_SESSION_SECRET)
    assert payload is not None
    assert payload["iat"] == explicit_iat


# ============================================================================
# 5. require_session — 401 sans cookie
# ============================================================================


def _make_test_app() -> FastAPI:
    """Crée une mini-app FastAPI avec une route protégée par require_session."""
    from fastapi import Depends

    app = FastAPI()

    @app.get("/cc/protected")
    async def protected(session=Depends(require_session)):
        return {"status": "ok", "sub": session["sub"]}

    return app


def test_require_session_401_without_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_session lève 401 quand aucun cookie n'est présent."""
    monkeypatch.setenv("CC_SESSION_SECRET", _TEST_SESSION_SECRET)
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/cc/protected")
    assert resp.status_code == 401


def test_require_session_401_with_invalid_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_session lève 401 avec un cookie invalide."""
    monkeypatch.setenv("CC_SESSION_SECRET", _TEST_SESSION_SECRET)
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False, cookies={SESSION_COOKIE_NAME: "invalid.token"})
    resp = client.get("/cc/protected")
    assert resp.status_code == 401


def test_require_session_200_with_valid_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_session passe avec un cookie de session valide."""
    monkeypatch.setenv("CC_SESSION_SECRET", _TEST_SESSION_SECRET)
    token = sign_session({"sub": "admin"}, _TEST_SESSION_SECRET)

    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False, cookies={SESSION_COOKIE_NAME: token})
    resp = client.get("/cc/protected")
    assert resp.status_code == 200
    assert resp.json()["sub"] == "admin"


def test_require_session_503_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """require_session retourne 503 si CC_SESSION_SECRET n'est pas configurée."""
    monkeypatch.delenv("CC_SESSION_SECRET", raising=False)
    token = sign_session({"sub": "admin"}, _TEST_SESSION_SECRET)
    app = _make_test_app()
    client = TestClient(app, raise_server_exceptions=False, cookies={SESSION_COOKIE_NAME: token})
    resp = client.get("/cc/protected")
    assert resp.status_code == 503


# ============================================================================
# 6. Garanties statiques sur security.py
# ============================================================================

_SECURITY_SOURCE = (Path(__file__).parent.parent / "control_center" / "security.py").read_text()


def test_no_hardcoded_secret_or_password() -> None:
    """security.py ne contient aucun secret, mot de passe ou clé en dur.

    Patterns prohibés : chaînes qui ressemblent à des secrets réels
    (longueur > 20 chars avec caractères aléatoires dans des affectations).
    Vérification : aucune occurrence de variables nommées *secret*, *password*,
    *token*, *key* avec une valeur string longue en dur.
    """
    # Recherche de patterns d'assignation avec secret en dur (heuristique)
    # Ex : secret = "abc123..." ou password = "hunter2"
    pattern = re.compile(
        r'(?:secret|password|passwd|token|apikey|api_key)\s*=\s*["\'][^"\']{8,}["\']',
        re.IGNORECASE,
    )
    # Exclure les chaînes dans les commentaires et docstrings qui utilisent
    # des noms de variables ou des exemples fictifs documentés
    # (on cherche uniquement en dehors des commentaires '#')
    non_comment_lines = [
        line for line in _SECURITY_SOURCE.splitlines()
        if not line.strip().startswith("#")
        and not line.strip().startswith('"""')
        and not line.strip().startswith("'''")
    ]
    for line in non_comment_lines:
        m = pattern.search(line)
        if m:
            # Tolérer les valeurs qui sont clairement des noms de variable
            # (ex : SESSION_COOKIE_NAME, CC_SESSION_SECRET_ENV)
            value = m.group(0)
            # Si la "valeur" contient ENV, NAME, SECONDS, DIR, FORMAT → ok (constante)
            if not re.search(r'(ENV|NAME|SECONDS|DIR|FORMAT|LOG)', value, re.IGNORECASE):
                pytest.fail(
                    f"Possible secret hardcodé détecté dans security.py: {value!r}\n"
                    f"Ligne: {line!r}"
                )


def test_no_http_provider_imports() -> None:
    """security.py n'importe aucun provider HTTP ou LLM externe.

    Prohibé : requests, httpx, aiohttp, openai, anthropic, boto3, urllib3,
    grpc, etc.
    """
    forbidden_patterns = [
        r"^\s*import\s+requests",
        r"^\s*import\s+httpx",
        r"^\s*import\s+aiohttp",
        r"^\s*import\s+openai",
        r"^\s*import\s+anthropic",
        r"^\s*import\s+boto3",
        r"^\s*import\s+urllib3",
        r"^\s*from\s+requests\s+",
        r"^\s*from\s+httpx\s+",
        r"^\s*from\s+openai\s+",
        r"^\s*from\s+anthropic\s+",
    ]
    for line in _SECURITY_SOURCE.splitlines():
        for pat in forbidden_patterns:
            if re.match(pat, line):
                pytest.fail(
                    f"Import provider/HTTP interdit dans security.py: {line!r}"
                )


def test_no_db_write_imports_or_calls() -> None:
    """security.py ne contient aucune écriture en base de données.

    Vérifie l'absence de psycopg, sqlalchemy, alembic, et de toute instruction
    INSERT/UPDATE/DELETE/TRUNCATE en SQL.
    """
    db_write_patterns = [
        r"^\s*import\s+psycopg",
        r"^\s*from\s+psycopg",
        r"^\s*import\s+sqlalchemy",
        r"^\s*from\s+sqlalchemy",
        r"\bINSERT\s+INTO\b",
        r"\bUPDATE\s+\w+\s+SET\b",
        r"\bDELETE\s+FROM\b",
        r"\bTRUNCATE\b",
        r"\.execute\s*\(",
        r"\.cursor\s*\(",
    ]
    for line in _SECURITY_SOURCE.splitlines():
        for pat in db_write_patterns:
            if re.search(pat, line, re.IGNORECASE):
                pytest.fail(
                    f"Écriture DB interdite détectée dans security.py: {line!r}"
                )


def test_no_new_pip_dependencies() -> None:
    """Les imports de security.py n'utilisent que la stdlib ou les deps existantes.

    Deps existantes autorisées : fastapi, psycopg (config.py l'utilise mais
    security.py ne doit PAS l'importer). security.py : stdlib + fastapi uniquement.
    """
    # Lister les imports de security.py
    import_lines = [
        line.strip()
        for line in _SECURITY_SOURCE.splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]
    allowed_prefixes = (
        "import base64",
        "import binascii",   # stdlib — ajouté red-team 2.F3 : except ciblé dans verify_session
        "import hashlib",
        "import hmac",
        "import ipaddress",  # stdlib — ajouté V1.7D : is_loopback() pour bypass tunnel SSH
        "import json",
        "import os",
        "import pathlib",
        "import secrets",
        "import stat",
        "import struct",
        "import time",
        "import re",
        "from __future__",
        "from typing",
        "from fastapi",
        "from control_center",
    )
    for line in import_lines:
        if not any(line.startswith(p) for p in allowed_prefixes):
            pytest.fail(
                f"Import non autorisé dans security.py: {line!r}\n"
                f"security.py doit n'utiliser que la stdlib + fastapi."
            )


# ============================================================================
# 7. audit_read_log — test de non-blocage
# ============================================================================


def test_audit_read_log_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """audit_read_log() ne lève jamais d'exception, même si le log est inaccessible."""
    import control_center.security as sec

    # Pointer vers un chemin temporaire pour ne pas écrire en /var/log/ pendant les tests
    monkeypatch.setattr(sec, "_CC_LOG_PRIMARY", str(tmp_path / "cc_access.log"))
    monkeypatch.setattr(sec, "_CC_LOG_FALLBACK", str(tmp_path / "fallback" / "access.log"))
    monkeypatch.setattr(sec, "_CC_LOG_FALLBACK_DIR", str(tmp_path / "fallback"))

    # Ne doit pas lever d'exception
    audit_read_log("/cc/atoms", "admin")
    audit_read_log("/cc/health", "admin")

    # Le fichier doit exister et contenir les entrées
    log_file = tmp_path / "cc_access.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "CC_ACCESS" in content
    assert "admin" in content
    assert "/cc/atoms" in content


# ============================================================================
# Red-team V1.7B — nouveaux tests de durcissement (3 LOW corrigés)
# ============================================================================


def test_verify_session_empty_secret_returns_none() -> None:
    """verify_session() échoue fermé si le secret est vide (garde fail-closed V1.7B).

    Un secret vide signerait et vérifierait contre lui-même — permettant à un
    futur appelant sans garde d'env d'accepter silencieusement des sessions forgées.
    Le garde en tête de verify_session doit retourner None immédiatement.
    """
    token = sign_session({"sub": "admin"}, "")
    result = verify_session(token, "")
    assert result is None, (
        "verify_session avec secret='' doit retourner None (fail-closed), "
        f"a retourné : {result!r}"
    )


def test_audit_read_log_newline_in_principal_no_second_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un principal contenant \\n ne crée pas de 2e ligne CC_ACCESS dans le log.

    Vérifie que le sanitize de audit_read_log() (red-team V1.7B) empêche
    l'injection de ligne de log via un principal malveillant.
    """
    import control_center.security as sec

    monkeypatch.setattr(sec, "_CC_LOG_PRIMARY", str(tmp_path / "cc_access.log"))
    monkeypatch.setattr(sec, "_CC_LOG_FALLBACK", str(tmp_path / "fallback" / "access.log"))
    monkeypatch.setattr(sec, "_CC_LOG_FALLBACK_DIR", str(tmp_path / "fallback"))

    # Principal avec injection de saut de ligne
    evil_principal = "admin\nFAKE_ENTRY | CC_ACCESS | ghost | /pwn"
    audit_read_log("/cc/overview", evil_principal)

    log_file = tmp_path / "cc_access.log"
    content = log_file.read_text()
    lines = [ln for ln in content.splitlines() if ln.strip()]

    # UNE SEULE ligne de log doit avoir été écrite : le \n est remplacé par un
    # espace, donc la partie injectée est aplatie dans la même ligne — ce qui
    # est la garantie recherchée (pas de 2e entrée CC_ACCESS forgée comme
    # nouvelle ligne de log autonome parseable par fail2ban).
    assert len(lines) == 1, (
        f"Injection de ligne de log détectée — {len(lines)} lignes écrites "
        f"au lieu d'une :\n{content!r}"
    )
    # La ligne unique ne doit pas contenir de saut de ligne brut
    assert "\n" not in lines[0]
    # La seule ligne doit commencer par un timestamp ISO8601 (ligne légitime)
    # et non par "FAKE_ENTRY" ou le contenu injecté directement
    assert lines[0].startswith("20"), (
        f"La ligne de log doit commencer par un timestamp, pas par le contenu injecté : {lines[0]!r}"
    )
