"""Authentification JWT access/refresh : le verrou IHM ↔ API IA (brief, couche 2).

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

Le registre des refresh actifs vit en mémoire : l'API tourne en un seul
processus (un redémarrage impose simplement de se reconnecter).
"""

import hmac
import uuid
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


def _require_configured() -> None:
    """Vérifie que l'auth est configurée (secret + compte démo).

    Raises:
        HTTPException: 503 si ``JWT_SECRET``/``APP_USERNAME``/``APP_PASSWORD``
            manquent — jamais de 500 sur une clé de signature vide.
    """
    if not (settings.jwt_secret and settings.app_username and settings.app_password):
        logger.error("Auth non configurée : JWT_SECRET/APP_USERNAME/APP_PASSWORD manquants")
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
    _require_configured()
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
