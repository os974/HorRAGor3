"""Authentification JWT access/refresh : le verrou IHM ↔ API IA (brief, couche 2).

Mécanique classique à deux jetons :
    - **access token** (courte durée, ~15 min) : présenté en ``Authorization:
      Bearer`` à chaque appel métier (``/chat``) — s'il fuite, il expire vite ;
    - **refresh token** (longue durée, ~7 j) : sert UNIQUEMENT à obtenir un
      nouvel access token via ``/auth/refresh`` — jamais envoyé aux routes
      métier.

Un seul compte de démonstration (``APP_USERNAME``/``APP_PASSWORD`` du ``.env``) :
le brief exige le verrou des échanges, pas une gestion d'utilisateurs.
Signature HS256 avec ``JWT_SECRET`` (secret, jamais commité).
"""

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


def _create_token(subject: str, token_type: str, lifetime: timedelta) -> str:
    """Fabrique un JWT signé.

    Args:
        subject: L'identité portée par le jeton (username).
        token_type: "access" ou "refresh" — vérifié à la validation pour
            interdire d'utiliser un refresh comme access (et inversement).
        lifetime: Durée de validité.

    Returns:
        Le JWT encodé (HS256).
    """
    now = datetime.now(UTC)
    payload = {"sub": subject, "type": token_type, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def _decode_token(token: str, expected_type: str) -> str:
    """Valide un JWT et renvoie son sujet.

    Args:
        token: Le JWT présenté.
        expected_type: Le type attendu ("access" ou "refresh").

    Returns:
        Le username porté par le jeton.

    Raises:
        HTTPException: 401 si le jeton est invalide, expiré ou du mauvais type.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="jeton expiré",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="jeton invalide",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    if payload.get("type") != expected_type:
        raise HTTPException(
            status_code=401,
            detail=f"jeton de type inattendu (attendu : {expected_type})",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return str(payload.get("sub", ""))


def _issue_pair(subject: str) -> TokenPair:
    """Émet une paire access + refresh pour un sujet authentifié.

    Args:
        subject: Le username authentifié.

    Returns:
        La paire de jetons neufs.
    """
    return TokenPair(
        access_token=_create_token(
            subject, "access", timedelta(minutes=settings.access_token_minutes)
        ),
        refresh_token=_create_token(
            subject, "refresh", timedelta(days=settings.refresh_token_days)
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
    if not (settings.jwt_secret and settings.app_username and settings.app_password):
        logger.error("Auth non configurée : JWT_SECRET/APP_USERNAME/APP_PASSWORD manquants")
        raise HTTPException(status_code=503, detail="authentification non configurée")
    if not (req.username == settings.app_username and req.password == settings.app_password):
        logger.warning("Tentative de connexion refusée pour {!r}", req.username)
        raise HTTPException(status_code=401, detail="identifiants invalides")
    logger.info("Connexion réussie : {}", req.username)
    return _issue_pair(req.username)


@router.post("/refresh", response_model=TokenPair)
async def refresh(req: RefreshRequest) -> TokenPair:
    """Renouvelle la paire à partir d'un refresh token valide.

    Rotation complète : un nouveau refresh est émis à chaque appel (limite la
    fenêtre d'exploitation d'un jeton volé).

    Args:
        req: Le refresh token courant.

    Returns:
        Une paire de jetons neufs.

    Raises:
        HTTPException: 401 si le refresh est invalide, expiré ou d'un autre type.
    """
    subject = _decode_token(req.refresh_token, expected_type="refresh")
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
        raise HTTPException(
            status_code=401,
            detail="jeton d'accès requis",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_token(credentials.credentials, expected_type="access")
