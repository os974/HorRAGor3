"""Connecteur SQL sur une vraie base SQLite en mémoire (même schéma que Part 1)."""

from datetime import date

import pytest
from sqlalchemy import create_engine, text

from src.data.repository import SupabaseFilmRepository, _pick_rating, _year_from


@pytest.fixture
def repository():
    """Repository branché sur une SQLite en mémoire, peuplée d'un film."""
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "create table movies (id integer primary key, tmdb_id integer, "
                "title text, release_date text, overview text)"
            )
        )
        conn.execute(text("create table genres (id integer primary key, name text)"))
        conn.execute(text("create table movie_genres (movie_id integer, genre_id integer)"))
        conn.execute(text("create table ratings (movie_id integer, source text, score real)"))
        conn.execute(
            text("insert into movies values (41, 493922, 'Hereditary', '2018-06-06', 'Deuil.')")
        )
        conn.execute(text("insert into genres values (1, 'Horror'), (2, 'Drama')"))
        conn.execute(text("insert into movie_genres values (41, 1), (41, 2)"))
        conn.execute(
            text(
                "insert into ratings values (41, 'imdb', 7.3), (41, 'tmdb', 8.0), "
                "(41, 'rotten_tomatoes', 89.0)"
            )
        )
    return SupabaseFilmRepository(engine=engine)


def test_get_metadata_assemble_le_lore(repository):
    """movies + genres + ratings → FilmMetadata complet."""
    meta = repository.get_metadata(41)
    assert meta.title == "Hereditary"
    assert meta.release_year == 2018
    assert meta.genres == ["Drama", "Horror"]  # tri alphabétique
    assert meta.rating == 7.3  # imdb prioritaire sur tmdb
    assert meta.synopsis == "Deuil."


def test_get_metadata_film_inconnu(repository):
    """Id absent → None, sans exception."""
    assert repository.get_metadata(999) is None


def test_validate_film_est_le_role_de_faiss(repository):
    """La validation floue n'appartient pas au SQL."""
    with pytest.raises(NotImplementedError):
        repository.validate_film("Hereditary")


def test_year_from_tolere_les_formats():
    """Postgres renvoie une date, SQLite une chaîne ISO, parfois rien."""
    assert _year_from(date(2018, 6, 6)) == 2018
    assert _year_from("2019-07-03") == 2019
    assert _year_from(None) is None
    assert _year_from("n/a") is None


def test_pick_rating_priorise_imdb():
    """imdb > tmdb ; Rotten (0-100) est ignoré ; rien → None."""
    assert _pick_rating([("tmdb", 8.0), ("imdb", 7.3)]) == 7.3
    assert _pick_rating([("tmdb", 8.0)]) == 8.0
    assert _pick_rating([("rotten_tomatoes", 89.0)]) is None
    assert _pick_rating([]) is None
