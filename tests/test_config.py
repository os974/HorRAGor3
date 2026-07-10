"""Configuration : défauts sûrs et propriété langfuse_enabled."""

from src.config import Settings


def _fresh_settings(**overrides) -> Settings:
    """Construit des Settings sans lire le .env local (tests hermétiques)."""
    return Settings(_env_file=None, **overrides)


def test_secrets_vides_par_defaut():
    """Aucun secret n'a de valeur par défaut dans le code."""
    s = _fresh_settings()
    assert s.database_url == ""
    assert s.tmdb_token == ""
    assert s.langfuse_public_key == ""


def test_reglages_par_defaut():
    """Les réglages non sensibles vivent dans le code (source unique)."""
    s = _fresh_settings()
    assert s.llm_model == "qwen2.5:7b"
    assert s.embedding_dim == 768
    assert s.faiss_index_dir == "data/faiss_index"
    assert s.faiss_score_threshold == 0.75


def test_langfuse_enabled_exige_les_deux_cles():
    """Le monitoring ne s'active qu'avec la paire complète de clés."""
    assert not _fresh_settings().langfuse_enabled
    assert not _fresh_settings(langfuse_public_key="pk").langfuse_enabled
    assert _fresh_settings(langfuse_public_key="pk", langfuse_secret_key="sk").langfuse_enabled
