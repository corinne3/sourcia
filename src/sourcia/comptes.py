"""Comptes enseignants et sessions, pour les dossiers pédagogiques.

Un compte = une adresse e-mail et un JETON secret (43 caractères aléatoires), qui sert de mot de passe personnel.
Deux sources de comptes, toutes deux acceptées :
- ``data/comptes.json``, géré par la commande ``sourcia comptes`` : on n'y range que l'EMPREINTE du jeton
  (SHA-256). Le jeton lui-même n'est affiché qu'une fois, à la création : si le fichier fuit, les jetons restent
  secrets. Le fichier est relu dès qu'il change : pas besoin de relancer le serveur ;
- la variable d'environnement ``SOURCIA_DOSSIER_ACCOUNTS`` (JSON adresse → jeton), comme avant.

Session : après avoir saisi son jeton UNE fois, l'enseignant reçoit un cookie signé (HMAC-SHA256) que le
navigateur renvoie tout seul pendant 12 heures, et que le JavaScript de la page ne peut pas lire (HttpOnly).
Le cookie contient l'adresse, l'heure d'expiration et le début de l'empreinte du jeton utilisé : si le compte
est retiré ou son jeton remplacé, les sessions ouvertes avec l'ancien jeton ne marchent plus.
La clé de signature vient de ``SOURCIA_SESSION_SECRET`` ; sans elle, une clé est tirée au démarrage (les sessions
ne survivent alors pas à un redémarrage du serveur : il suffit de se reconnecter).

Accès libre (``acces_libre: true``, pour un prototype) : un visiteur sans jeton reçoit un compte anonyme, tout entier
dans son cookie signé (``visiteur-<hasard>@visiteur.sourcia``, 30 jours) : rien n'est ajouté à ``comptes.json``.
Chacun ne voit que ses dossiers. Les ``Quotas`` limitent ce qu'un visiteur lance par jour (corpus, supports), pour
protéger la clé du modèle en ligne.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import date, datetime
from pathlib import Path

ENV_ACCOUNTS = "SOURCIA_DOSSIER_ACCOUNTS"
ENV_SECRET = "SOURCIA_SESSION_SECRET"
COOKIE = "sourcia_session"
SESSION_HOURS = 12
DEMO_EMAIL = "demo@sourcia.local"
VISITEUR_DOMAINE = "@visiteur.sourcia"
VISITEUR_MARQUE = "visiteur"                   # à la place de l'empreinte d'un jeton, dans le cookie d'un visiteur
VISITEUR_HEURES = 30 * 24                      # un visiteur garde ses dossiers un mois dans le même navigateur


def is_visitor(email: str | None) -> bool:
    return bool(email) and email.endswith(VISITEUR_DOMAINE)


def new_token() -> str:
    """43 caractères aléatoires (256 bits) : impossible à deviner, même en essayant longtemps."""
    return secrets.token_urlsafe(32)


def fingerprint(token: str) -> str:
    # un jeton tiré au hasard sur 256 bits n'a pas besoin d'un hachage lent (bcrypt) : SHA-256 suffit
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    email = str(email).strip().casefold()
    if email.count("@") != 1 or any(c.isspace() for c in email) or "|" in email or len(email) > 254 \
            or email.startswith("@") or email.endswith("@"):
        raise ValueError(f"Adresse e-mail invalide : « {email} »")
    return email


def parse_env(raw: str) -> dict[str, str]:
    """Comptes de la variable d'environnement (adresse → jeton), avec les contrôles d'origine."""
    accounts = json.loads(raw or "{}")
    if (not isinstance(accounts, dict)
            or any(not isinstance(token, str) or not token.isascii() or len(token) < 32 for token in accounts.values())
            or len(set(accounts.values())) != len(accounts)):
        raise ValueError(f"{ENV_ACCOUNTS} doit associer chaque adresse à un jeton ASCII unique d'au moins 32 caractères.")
    try:
        normalized = {normalize_email(email): token for email, token in accounts.items()}
    except ValueError:
        raise ValueError("Adresses de comptes SourcIA invalides ou en double.") from None
    if len(normalized) != len(accounts):
        raise ValueError("Adresses de comptes SourcIA invalides ou en double.")
    return normalized


class Comptes:
    def __init__(self, path: Path, env: str | None = None):
        self.path = Path(path)
        self.env = {email: fingerprint(token) for email, token in
                    parse_env(os.environ.get(ENV_ACCOUNTS, "{}") if env is None else env).items()}
        self._mtime: int | None = None
        self._file: dict[str, dict] = {}

    # ------------------------------------------------------------------ fichier
    def _load(self) -> dict[str, dict]:
        """Relit data/comptes.json s'il a changé depuis la dernière lecture."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except FileNotFoundError:
            self._mtime, self._file = None, {}
            return self._file
        if mtime != self._mtime:
            self._file = json.loads(self.path.read_text(encoding="utf-8")).get("comptes", {})
            self._mtime = mtime
        return self._file

    def _save(self, comptes: dict[str, dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "comptes": comptes}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)                       # écriture d'un bloc : jamais de fichier à moitié écrit
        self._mtime = None

    # ------------------------------------------------------------------ comptes
    def fingerprints(self, email: str) -> list[str]:
        out = [self.env[email]] if email in self.env else []
        entry = self._load().get(email)
        return out + ([entry["empreinte"]] if entry else [])

    def identify(self, token: str) -> str | None:
        """L'adresse du compte de ce jeton, sinon None (comparaison en temps constant)."""
        if not token:
            return None
        fp = fingerprint(token)
        found = None
        for email, entry_fp in list(self.env.items()) + [(e, x["empreinte"]) for e, x in self._load().items()]:
            if hmac.compare_digest(fp, entry_fp):
                found = email
        return found

    def ajouter(self, email: str, remplacer: bool = False, demo: bool = False) -> str:
        """Crée le compte (ou remplace son jeton) ; renvoie le jeton, à transmettre par un moyen privé."""
        email = normalize_email(email)
        comptes = dict(self._load())
        if email in comptes and not remplacer:
            raise ValueError(f"Le compte {email} existe déjà (--remplacer pour lui donner un nouveau jeton).")
        token = new_token()
        comptes[email] = {"empreinte": fingerprint(token), "cree_le": datetime.now().isoformat(timespec="seconds"),
                          "demo": demo}
        self._save(comptes)
        return token

    def retirer(self, email: str) -> bool:
        email = normalize_email(email)
        comptes = dict(self._load())
        if email not in comptes:
            return False
        del comptes[email]
        self._save(comptes)
        return True

    def lister(self) -> list[dict]:
        rows = [{"email": e, "source": "fichier", "cree_le": x.get("cree_le", ""), "demo": x.get("demo", False)}
                for e, x in self._load().items()]
        rows += [{"email": e, "source": "variable", "cree_le": "", "demo": False} for e in self.env]
        return sorted(rows, key=lambda r: r["email"])


class Sessions:
    """Cookie signé : « adresse | expiration | début de l'empreinte du jeton », puis la signature HMAC."""

    def __init__(self, comptes: Comptes, secret: str | None = None, hours: int = SESSION_HOURS):
        self.comptes = comptes
        self.hours = hours
        self.key = (secret or os.environ.get(ENV_SECRET) or secrets.token_urlsafe(32)).encode()

    def _sign(self, data: str) -> str:
        return hmac.new(self.key, data.encode(), hashlib.sha256).hexdigest()

    def create(self, email: str, token: str) -> str:
        payload = f"{email}|{int(time.time()) + self.hours * 3600}|{fingerprint(token)[:16]}"
        data = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        return f"{data}.{self._sign(data)}"

    def create_visitor(self) -> tuple[str, str]:
        """Un compte visiteur anonyme : (adresse, cookie). Rien n'est enregistré : le cookie signé suffit."""
        email = f"visiteur-{secrets.token_hex(6)}{VISITEUR_DOMAINE}"
        payload = f"{email}|{int(time.time()) + VISITEUR_HEURES * 3600}|{VISITEUR_MARQUE}"
        data = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        return email, f"{data}.{self._sign(data)}"

    def verify(self, value: str | None) -> str | None:
        """L'adresse de la session si le cookie est intact, pas expiré, et que le compte a toujours ce jeton."""
        if not value or "." not in value:
            return None
        data, _, signature = value.rpartition(".")
        if not hmac.compare_digest(signature, self._sign(data)):
            return None
        try:
            email, expires, fp = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode().rsplit("|", 2)
            if int(expires) < time.time():
                return None
        except (ValueError, UnicodeDecodeError):
            return None
        if is_visitor(email):                    # signé par ce serveur : le visiteur n'a pas de jeton à vérifier
            return email if fp == VISITEUR_MARQUE else None
        return email if any(hmac.compare_digest(fp, x[:16]) for x in self.comptes.fingerprints(email)) else None


class Quotas:
    """Ce qu'un visiteur lance par jour (corpus, supports), dans ``<data_dir>/quotas.json``. Les comptes avec jeton
    ne sont pas comptés. On ne garde que le jour en cours."""

    def __init__(self, path: Path, limits: dict[str, int]):
        self.path = Path(path)
        self.limits = limits
        self.lock = threading.Lock()

    def use(self, email: str, kind: str) -> int | None:
        """Compte un lancement ; renvoie ce qui reste, ou None si la limite du jour est déjà atteinte."""
        if not is_visitor(email):
            return self.limits.get(kind, 0)
        today = date.today().isoformat()
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if data.get("jour") != today:
                data = {"jour": today, "comptes": {}}
            used = data["comptes"].setdefault(email, {}).get(kind, 0)
            if used >= self.limits.get(kind, 0):
                return None
            data["comptes"][email][kind] = used + 1
            self._write(data)
            return self.limits[kind] - used - 1

    def refund(self, email: str, kind: str) -> None:
        """Rend un lancement compté pour rien (le lancement a été refusé ensuite)."""
        if not is_visitor(email):
            return
        with self.lock:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                n = data["comptes"][email][kind]
            except (OSError, ValueError, KeyError):
                return
            data["comptes"][email][kind] = max(0, n - 1)
            self._write(data)

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
