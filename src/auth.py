"""Authentification JWT access/refresh : le verrou des échanges entre services.

Mécanique classique à deux jetons :
    - **access token** (courte durée, ~15 min) : présenté en ``Authorization:
      Bearer`` à chaque appel métier (``/chat``) — s'il fuite, il expire vite ;
    - **refresh token** (~12 h) : sert UNIQUEMENT à obtenir une paire neuve via
      ``/auth/refresh`` — jamais envoyé aux routes métier. Rotation à chaque
      usage, et **révocation** : seul le dernier refresh émis (son ``jti``) est
      valide ; présenter un ancien refresh trahit un vol et révoque la session.

Un seul compte de démonstration (``APP_USERNAME``/``APP_PASSWORD`` du ``.env``) :
le brief exige le verrou des échanges, pas une gestion d'utilisateurs.
Signature HS256 avec ``JWT_SECRET`` (secret, jamais commité).

Toute la chaîne est liée au compte : l'IHM présente l'access token à l'API IA,
qui le **relaie** à l'API Données pour chaque appel fait au nom de la requête
(:func:`forwarding_access_token`) ; l'API Données le vérifie avec le même
secret (:func:`require_access`). Aucun service ne parle à un autre sans le
jeton de l'utilisateur.

Le registre des refresh actifs vit en mémoire : l'API tourne en un seul
processus (un redémarrage impose simplement de se reconnecter).
"""

import hmac
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel

from src.config import settings

_ALGORITHM = "HS256"
router = APIRouter(prefix="/auth", tags=["auth"])

# auto_error=False : on veut renvoyer NOS 401 explicites, pas le 403 par défaut.
_bearer = HTTPBearer(auto_error=False)

# Le jeton d'accès de la requête en cours, relayé aux appels inter-services
# (même mécanisme que la trace : un ContextVar suit la requête jusque dans le
# thread du graphe et ses outils).
_forwarded_token: ContextVar[str | None] = ContextVar("forwarded_access_token", default=None)

# Sujet → jti du SEUL refresh token actuellement valide.
_active_refresh: dict[str, str] = {}


class LoginRequest(BaseModel):
    """Identifiants envoyés par le Front à ``POST /auth/login``.

    Attributes:
        username: Nom du compte (démo : ``APP_USERNAME`` du .env).
        password: Mot de passe associé.
    """

    username: str
    password: str


class RefreshRequest(BaseModel):
    """Demande de renouvellement (``POST /auth/refresh``).

    Attributes:
        refresh_token: Le jeton longue durée obtenu au login.
    """

    refresh_token: str


class TokenPair(BaseModel):
    """La paire de jetons renvoyée au Front.

    Attributes:
        access_token: Jeton court pour les routes métier (Bearer).
        refresh_token: Jeton long pour ``/auth/refresh``.
        token_type: Toujours "bearer" (convention OAuth2).
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _unauthorized(detail: str) -> HTTPException:
    """Fabrique la 401 standard (en-tête ``WWW-Authenticate: Bearer``).

    Args:
        detail: Message explicite renvoyé au client.

    Returns:
        L'exception prête à être levée.
    """
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _require_secret() -> None:
    """Vérifie que le secret de signature est configuré (seul besoin pour valider).

    Raises:
        HTTPException: 503 si ``JWT_SECRET`` manque — jamais de 500 sur une clé
            de signature vide.
    """
    if not settings.jwt_secret:
        logger.error("Auth non configurée : JWT_SECRET manquant")
        raise HTTPException(status_code=503, detail="authentification non configurée")


def _require_configured() -> None:
    """Vérifie que l'émission de jetons est possible (secret + compte démo).

    Raises:
        HTTPException: 503 si ``JWT_SECRET``/``APP_USERNAME``/``APP_PASSWORD``
            manquent.
    """
    _require_secret()
    if not (settings.app_username and settings.app_password):
        logger.error("Auth non configurée : APP_USERNAME/APP_PASSWORD manquants")
        raise HTTPException(status_code=503, detail="authentification non configurée")


def _create_token(
    subject: str, token_type: str, lifetime: timedelta, jti: str | None = None
) -> str:
    """Fabrique un JWT signé.

    Args:
        subject: L'identité portée par le jeton (username).
        token_type: "access" ou "refresh" — vérifié à la validation pour
            interdire d'utiliser un refresh comme access (et inversement).
        lifetime: Durée de validité.
        jti: Identifiant unique du jeton (refresh : sert à la révocation).

    Returns:
        Le JWT encodé (HS256).
    """
    now = datetime.now(UTC)
    payload = {"sub": subject, "type": token_type, "iat": now, "exp": now + lifetime}
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def _decode_token(token: str, expected_type: str) -> dict:
    """Valide un JWT et renvoie ses claims.

    Args:
        token: Le JWT présenté.
        expected_type: Le type attendu ("access" ou "refresh").

    Returns:
        Les claims du jeton (``sub`` garanti ; ``jti`` pour un refresh).

    Raises:
        HTTPException: 503 si l'auth n'est pas configurée ; 401 si le jeton
            est invalide, expiré, incomplet ou du mauvais type.
    """
    _require_secret()
    required = ["exp", "sub", "type"] + (["jti"] if expected_type == "refresh" else [])
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[_ALGORITHM], options={"require": required}
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("jeton expiré") from None
    except jwt.InvalidTokenError:
        raise _unauthorized("jeton invalide") from None
    if payload["type"] != expected_type:
        raise _unauthorized(f"jeton de type inattendu (attendu : {expected_type})")
    return payload


def _issue_pair(subject: str) -> TokenPair:
    """Émet une paire access + refresh et enregistre le refresh comme seul actif.

    Args:
        subject: Le username authentifié.

    Returns:
        La paire de jetons neufs.
    """
    jti = uuid.uuid4().hex
    _active_refresh[subject] = jti
    return TokenPair(
        access_token=_create_token(
            subject, "access", timedelta(minutes=settings.access_token_minutes)
        ),
        refresh_token=_create_token(
            subject, "refresh", timedelta(hours=settings.refresh_token_hours), jti=jti
        ),
    )


@router.post("/login", response_model=TokenPair)
async def login(req: LoginRequest) -> TokenPair:
    """Authentifie le compte démo et émet la paire de jetons.

    Args:
        req: Identifiants saisis dans le Front.

    Returns:
        Access (court) + refresh (long).

    Raises:
        HTTPException: 503 si l'auth n'est pas configurée ; 401 si les
            identifiants sont invalides.
    """
    _require_configured()
    # compare_digest : temps constant, pas d'indice de longueur commune.
    user_ok = hmac.compare_digest(req.username.encode(), settings.app_username.encode())
    password_ok = hmac.compare_digest(req.password.encode(), settings.app_password.encode())
    if not (user_ok and password_ok):
        logger.warning("Tentative de connexion refusée pour {!r}", req.username)
        raise HTTPException(status_code=401, detail="identifiants invalides")
    logger.info("Connexion réussie : {}", req.username)
    return _issue_pair(req.username)


@router.post("/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest) -> TokenPair:
    """Renouvelle la paire à partir du refresh token actif.

    Rotation complète : chaque usage invalide le refresh présenté. Un refresh
    déjà consommé qui revient signale un vol : la session du sujet est
    révoquée (y compris le refresh légitime le plus récent).

    Args:
        req: Le refresh token courant.

    Returns:
        Une paire de jetons neufs.

    Raises:
        HTTPException: 401 si le refresh est invalide, expiré, d'un autre type
            ou révoqué ; 503 si l'auth n'est pas configurée.
    """
    claims = _decode_token(req.refresh_token, expected_type="refresh")
    subject = claims["sub"]
    if _active_refresh.get(subject) != claims["jti"]:
        _active_refresh.pop(subject, None)
        logger.warning("Refresh déjà consommé ou inconnu pour {} : session révoquée", subject)
        raise _unauthorized("jeton révoqué")
    logger.info("Jetons renouvelés pour {}", subject)
    return _issue_pair(subject)


async def require_access(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Dépendance FastAPI : exige un access token valide sur une route métier.

    Args:
        credentials: L'en-tête ``Authorization: Bearer ...`` (ou None).

    Returns:
        Le username authentifié (injectable dans la route).

    Raises:
        HTTPException: 401 si l'en-tête manque ou si le jeton est invalide.
    """
    if credentials is None:
        raise _unauthorized("jeton d'accès requis")
    return _decode_token(credentials.credentials, expected_type="access")["sub"]


async def bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Dépendance FastAPI : le jeton brut présenté (à relayer aux autres services).

    À combiner avec :func:`require_access`, qui l'a déjà validé.

    Args:
        credentials: L'en-tête ``Authorization: Bearer ...`` (ou None).

    Returns:
        Le JWT tel que reçu, ou une chaîne vide s'il est absent.
    """
    return credentials.credentials if credentials else ""


@contextmanager
def forwarding_access_token(token: str) -> Iterator[None]:
    """Relaie le jeton d'accès de la requête aux appels inter-services.

    Args:
        token: Le jeton d'accès validé de la requête en cours.

    Yields:
        La main, le jeton étant disponible via :func:`forwarded_access_token`.
    """
    reset = _forwarded_token.set(token)
    try:
        yield
    finally:
        _forwarded_token.reset(reset)


def forwarded_access_token() -> str | None:
    """Le jeton d'accès à relayer pour la requête en cours.

    Returns:
        Le jeton, ou None hors d'une requête authentifiée.
    """
    return _forwarded_token.get()
