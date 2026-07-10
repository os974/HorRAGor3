"""Calcul des embeddings via Ollama (local). Repris de HorRAGor2.

Module unique : le modèle d'embeddings (``settings.embedding_model``) doit être
le MÊME à la construction de l'index et à la requête, sinon les similarités
cosinus n'ont aucun sens. Centraliser ici garantit cette cohérence.

Ollama expose deux endpoints d'embeddings :
    - ``/api/embed`` : moderne, accepte un batch (``input``: liste) ;
    - ``/api/embeddings`` : legacy, un texte à la fois (repli).
"""

from concurrent.futures import ThreadPoolExecutor

import httpx

from src.config import settings


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embedde une liste de textes (ordre préservé).

    Args:
        texts: Textes à embedder. Liste vide acceptée.

    Returns:
        Un vecteur par texte, dans le même ordre.

    Raises:
        ValueError: Si la dimension renvoyée ne correspond pas à
            ``settings.embedding_dim`` (incohérence index/pgvector).
        httpx.HTTPError: Si Ollama est injoignable (l'appelant décide).
    """
    if not texts:
        return []

    vectors = _embed_batch(texts)

    # Garde-fou : une dimension inattendue casserait silencieusement FAISS et la reco.
    if vectors and len(vectors[0]) != settings.embedding_dim:
        raise ValueError(
            f"Dimension d'embedding inattendue : {len(vectors[0])} "
            f"(attendu {settings.embedding_dim} pour '{settings.embedding_model}')."
        )
    return vectors


def embed_text(text: str) -> list[float]:
    """Embedde un seul texte (raccourci pour les requêtes unitaires).

    Args:
        text: Texte à embedder.

    Returns:
        Le vecteur d'embedding (dimension ``settings.embedding_dim``).
    """
    return embed_texts([text])[0]


def embed_texts_concurrent(
    texts: list[str], workers: int = 10, chunk_size: int = 32
) -> list[list[float]]:
    """Embedde une grande liste via plusieurs requêtes parallèles (ordre préservé).

    Ollama parallélise sur le GPU : bien plus rapide qu'un seul gros batch.
    Sert au (re)build de l'index FAISS des titres.

    Args:
        texts: Textes à embedder.
        workers: Nombre de requêtes simultanées.
        chunk_size: Taille de chaque batch envoyé à Ollama.

    Returns:
        Un vecteur par texte, dans le même ordre.
    """
    chunks = [texts[i : i + chunk_size] for i in range(0, len(texts), chunk_size)]
    vectors: list[list[float]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for chunk_vectors in ex.map(embed_texts, chunks):  # map préserve l'ordre
            vectors.extend(chunk_vectors)
    return vectors


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Appel Ollama ``/api/embed`` (batch), repli sur le legacy ``/api/embeddings``.

    Args:
        texts: Textes du batch.

    Returns:
        Les vecteurs du batch.

    Raises:
        RuntimeError: Réponse Ollama sans champ ``embeddings``.
        httpx.HTTPError: Erreur réseau ou statut HTTP d'échec.
    """
    url = f"{settings.ollama_base_url}/api/embed"
    resp = httpx.post(
        url,
        json={"model": settings.embedding_model, "input": texts},
        timeout=300,  # large : un gros batch sur CPU peut être long
    )
    if resp.status_code == 404:
        # Instance Ollama ancienne : endpoint legacy, un texte à la fois.
        return [_embed_legacy(t) for t in texts]
    resp.raise_for_status()
    embeddings = resp.json().get("embeddings")
    if embeddings is None:
        raise RuntimeError(f"Réponse Ollama inattendue (pas de 'embeddings') : {resp.text[:200]}")
    return embeddings


def _embed_legacy(text: str) -> list[float]:
    """Appel legacy ``/api/embeddings`` (un seul texte).

    Args:
        text: Texte à embedder.

    Returns:
        Le vecteur d'embedding.
    """
    resp = httpx.post(
        f"{settings.ollama_base_url}/api/embeddings",
        json={"model": settings.embedding_model, "prompt": text},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]
