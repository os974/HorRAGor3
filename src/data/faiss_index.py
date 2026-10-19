"""Index FAISS des titres (routeur Nom → ID). Repris de HorRAGor2.

Choix techniques :
    - ``IndexFlatIP`` (produit scalaire) sur des vecteurs **L2-normalisés** =
      similarité cosinus exacte. Flat (force brute) suffit pour ~34k titres en
      RAM et évite tout réglage d'index approximatif.
    - Mapping ``position -> (id, title)`` aligné sur l'ordre d'ajout.

La recherche (:meth:`TitleIndex.search_vector`) ne fait PAS d'embedding : elle
prend un vecteur déjà calculé — c'est l'outil ``validate_film`` qui embedde la
requête. Le module est donc testable sans Ollama.
"""

import json
from pathlib import Path

import faiss
import numpy as np

from src.config import _PROJECT_ROOT, settings
from src.data.embed import embed_texts_concurrent


def normalize_title(title: str) -> str:
    """Normalise légèrement un titre pour stabiliser le matching.

    Args:
        title: Titre brut saisi ou stocké.

    Returns:
        Le titre en minuscules, sans espaces de bord.
    """
    return title.strip().lower()


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    """Normalise chaque ligne à la norme L2 (division par zéro protégée).

    Args:
        mat: Matrice (n, d) de vecteurs.

    Returns:
        La matrice normalisée ligne à ligne.
    """
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def _resolve_dir(index_dir: str | None) -> Path:
    """Résout le dossier de l'index (relatif à la racine du projet).

    Args:
        index_dir: Dossier explicite, ou None pour ``settings.faiss_index_dir``.

    Returns:
        Le chemin absolu du dossier.
    """
    raw = index_dir or settings.faiss_index_dir
    p = Path(raw)
    return p if p.is_absolute() else (_PROJECT_ROOT / p)


class TitleIndex:
    """Index FAISS des titres + mapping vers ``(id, title)``.

    Attributes:
        index: L'index FAISS (IndexFlatIP sur vecteurs normalisés).
        ids: Identifiants base, alignés sur les positions de l'index.
        titles: Titres originaux, alignés sur les positions de l'index.
    """

    INDEX_FILE = "titles.index"
    MAP_FILE = "titles_map.json"

    def __init__(self, index: faiss.Index, ids: list[int], titles: list[str]):
        """Assemble un index déjà construit et son mapping.

        Args:
            index: L'index FAISS (vecteurs normalisés, dans l'ordre d'ajout).
            ids: Identifiants base, alignés sur les positions de l'index.
            titles: Titres originaux, alignés sur les positions de l'index.
        """
        self.index = index
        self.ids = ids
        self.titles = titles

    # --- Construction ---------------------------------------------------------
    @classmethod
    def from_vectors(cls, vectors, ids, titles) -> "TitleIndex":
        """Construit l'index à partir de vecteurs déjà calculés.

        Args:
            vectors: Matrice (n, d) des embeddings de titres.
            ids: Identifiants base correspondants.
            titles: Titres originaux correspondants.

        Returns:
            L'index prêt à la recherche.
        """
        mat = _l2_normalize(np.asarray(vectors, dtype="float32"))
        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)
        return cls(index, list(ids), list(titles))

    @classmethod
    def build_from_pairs(cls, pairs, workers: int = 10, chunk_size: int = 32) -> "TitleIndex":
        """Construit l'index à partir de couples ``(id, title)`` (embedding inclus).

        Args:
            pairs: Couples (id, titre) issus de la base.
            workers: Requêtes d'embedding simultanées.
            chunk_size: Taille des batchs d'embedding.

        Returns:
            L'index prêt à la recherche.
        """
        ids = [int(i) for i, _ in pairs]
        titles = [str(t) for _, t in pairs]
        normalized = [normalize_title(t) for t in titles]
        vectors = embed_texts_concurrent(normalized, workers, chunk_size)
        return cls.from_vectors(vectors, ids, titles)

    # --- Recherche ------------------------------------------------------------
    def search_vector(self, vector, k: int = 1) -> list[tuple[float, int, str]]:
        """Cherche les k plus proches voisins d'un vecteur déjà calculé.

        Args:
            vector: Vecteur requête (dimension de l'index).
            k: Nombre de voisins.

        Returns:
            Triplets ``(score_cosinus, id, title)`` triés du plus proche au
            plus lointain (les positions -1 de FAISS sont filtrées).
        """
        q = _l2_normalize(np.asarray([vector], dtype="float32"))
        scores, idx = self.index.search(q, k)
        results = []
        for score, pos in zip(scores[0], idx[0], strict=True):
            if pos == -1:
                continue
            results.append((float(score), self.ids[pos], self.titles[pos]))
        return results

    def __len__(self) -> int:
        """Nombre de titres indexés.

        Returns:
            Le nombre de vecteurs présents dans l'index FAISS.
        """
        return self.index.ntotal

    # --- Persistance ----------------------------------------------------------
    def save(self, index_dir: str | None = None) -> Path:
        """Persiste l'index et son mapping sur disque.

        Args:
            index_dir: Dossier cible, ou None pour la config.

        Returns:
            Le dossier dans lequel l'index a été écrit.
        """
        d = _resolve_dir(index_dir)
        d.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(d / self.INDEX_FILE))
        (d / self.MAP_FILE).write_text(
            json.dumps({"ids": self.ids, "titles": self.titles}), encoding="utf-8"
        )
        return d

    @classmethod
    def load(cls, index_dir: str | None = None) -> "TitleIndex":
        """Charge l'index et son mapping depuis le disque.

        Args:
            index_dir: Dossier source, ou None pour la config.

        Returns:
            L'index prêt à la recherche.
        """
        d = _resolve_dir(index_dir)
        index = faiss.read_index(str(d / cls.INDEX_FILE))
        data = json.loads((d / cls.MAP_FILE).read_text(encoding="utf-8"))
        return cls(index, data["ids"], data["titles"])

    @classmethod
    def exists(cls, index_dir: str | None = None) -> bool:
        """Indique si un index persisté est présent sur disque.

        Args:
            index_dir: Dossier à inspecter, ou None pour la config.

        Returns:
            True si les deux fichiers (index + mapping) existent.
        """
        d = _resolve_dir(index_dir)
        return (d / cls.INDEX_FILE).exists() and (d / cls.MAP_FILE).exists()
