"""Langfuse côté HTTP : une trace par requête métier, sur les deux API.

Le brief exige que les requêtes reçues par FastAPI produisent une trace
exploitable dans Langfuse. :class:`LangfuseRequestMiddleware` ouvre une span
racine par requête (méthode, route, statut, service) et tout ce qui se passe
pendant la requête s'y imbrique : pour ``/chat``, le graphe multi-agent tracé
par le ``CallbackHandler`` (nœuds, routeurs, outils, tokens). Les sondes
techniques (``/health``, ``/metrics``) et la doc OpenAPI ne sont pas tracées :
elles mesurent la machine, pas l'usage, et Prometheus s'en charge.

Fail-open, comme tout le monitoring du projet : clés absentes, SDK ou serveur
indisponible → les requêtes passent à l'identique, sans trace.
"""

from contextlib import ExitStack
from functools import lru_cache

from fastapi import Request, Response
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.config import settings

# Ce qui n'est pas de l'usage : sondes de santé, métriques, documentation.
_UNTRACED_PREFIXES = ("/health", "/metrics", "/docs", "/redoc", "/openapi.json")


@lru_cache(maxsize=1)
def langfuse_client():
    """Initialise le client Langfuse v3 une seule fois depuis ``settings``.

    SDK v3 : le client est configuré explicitement (pas de ``os.environ`` en
    dur) ; le ``CallbackHandler`` du graphe réutilise ce client global.

    Returns:
        Le client Langfuse, ou None si les clés manquent ou si le SDK est
        inutilisable (fail-open).
    """
    if not settings.langfuse_enabled:
        logger.info("Langfuse désactivé (clés absentes du .env)")
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception:  # noqa: BLE001 — le monitoring ne doit jamais bloquer le métier
        logger.warning("Langfuse indisponible : monitoring désactivé (fail-open)")
        return None
    logger.info("Langfuse activé → {}", settings.langfuse_host)
    return client


def tag_current_trace(**attributes) -> None:
    """Complète la trace de la requête en cours (compte, conversation, entrée…).

    Args:
        **attributes: Attributs de trace Langfuse (``user_id``, ``session_id``,
            ``input``, ``output``…).
    """
    client = langfuse_client()
    if client is None:
        return
    try:
        client.update_current_trace(**attributes)
    except Exception:  # noqa: BLE001
        logger.debug("Trace Langfuse non complétée (fail-open)")


class LangfuseRequestMiddleware(BaseHTTPMiddleware):
    """Ouvre une trace Langfuse par requête métier reçue par l'API."""

    def __init__(self, app, service: str):
        """Branche le middleware sur une application.

        Args:
            app: L'application ASGI.
            service: Le nom du service, étiquette de chaque trace
                (``api-ia``, ``api-donnees``).
        """
        super().__init__(app)
        self._service = service

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Trace la requête, puis la laisse suivre son cours.

        Args:
            request: La requête entrante.
            call_next: La suite de la chaîne ASGI (la route).

        Returns:
            La réponse de la route, inchangée.
        """
        client = langfuse_client()
        if client is None or request.url.path.startswith(_UNTRACED_PREFIXES):
            return await call_next(request)
        name = f"{request.method} {request.url.path}"
        with ExitStack() as stack:
            span = self._open_span(stack, client, name, request)
            response = await call_next(request)
            if span is not None:
                self._close_span(span, name, response.status_code)
            return response

    @staticmethod
    def _open_span(stack: ExitStack, client, name: str, request: Request):
        """Ouvre la span racine de la requête, sans jamais lever.

        Args:
            stack: La pile qui refermera la span à la fin de la requête.
            client: Le client Langfuse.
            name: Le nom de la trace (« méthode route »).
            request: La requête entrante.

        Returns:
            La span ouverte, ou None si Langfuse a échoué.
        """
        try:
            return stack.enter_context(
                client.start_as_current_span(
                    name=name,
                    input={"method": request.method, "path": request.url.path},
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning("Span Langfuse non ouverte pour {} (fail-open)", name)
            return None

    def _close_span(self, span, name: str, status_code: int) -> None:
        """Consigne le statut de la réponse dans la span et la trace.

        Args:
            span: La span racine de la requête.
            name: Le nom de la trace.
            status_code: Le statut HTTP renvoyé.
        """
        try:
            span.update(
                output={"status_code": status_code},
                **({"level": "ERROR"} if status_code >= 500 else {}),
            )
            span.update_trace(
                name=name,
                tags=[self._service],
                metadata={"service": self._service, "status_code": status_code},
            )
        except Exception:  # noqa: BLE001
            logger.debug("Span Langfuse non complétée pour {} (fail-open)", name)
