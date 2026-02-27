from unittest.mock import patch

import app.builder as builder


def _episode(item_id: str):
    return {"Id": item_id, "Type": "Episode", "Name": item_id}


def test_generate_items_tv_interleaves_multiple_shows():
    blocks = [{
        "type": "tv",
        "shows": [
            {"name": "Show A", "season": 1, "episode": 1},
            {"name": "Show B", "season": 1, "episode": 1},
        ],
        "mode": "count",
        "count": 2,
        "interleave": True,
    }]
    logs = []

    def fake_series_id(name, _hdr):
        return {"Show A": "sid-a", "Show B": "sid-b"}[name]

    def fake_episodes(sid, *_args, **_kwargs):
        return {
            "sid-a": [_episode("A1"), _episode("A2")],
            "sid-b": [_episode("B1"), _episode("B2")],
        }[sid]

    with patch("app.builder.series_id", side_effect=fake_series_id), patch(
        "app.builder.episodes", side_effect=fake_episodes
    ):
        items = builder.generate_items_from_blocks("u1", blocks, {}, logs)

    assert [i["Id"] for i in items] == ["A1", "B1", "A2", "B2"]
    assert any("interleaved episodes" in line for line in logs)


def test_generate_items_tv_sequential_when_interleave_disabled():
    blocks = [{
        "type": "tv",
        "shows": [
            {"name": "Show A", "season": 1, "episode": 1},
            {"name": "Show B", "season": 1, "episode": 1},
        ],
        "mode": "count",
        "count": 2,
        "interleave": False,
    }]
    logs = []

    def fake_series_id(name, _hdr):
        return {"Show A": "sid-a", "Show B": "sid-b"}[name]

    def fake_episodes(sid, *_args, **_kwargs):
        return {
            "sid-a": [_episode("A1"), _episode("A2")],
            "sid-b": [_episode("B1"), _episode("B2")],
        }[sid]

    with patch("app.builder.series_id", side_effect=fake_series_id), patch(
        "app.builder.episodes", side_effect=fake_episodes
    ):
        items = builder.generate_items_from_blocks("u1", blocks, {}, logs)

    assert [i["Id"] for i in items] == ["A1", "A2", "B1", "B2"]
    assert any("sequential episodes" in line for line in logs)


def test_generate_items_logs_unprocessed_show_entry_and_skips_it():
    blocks = [{"type": "tv", "shows": [{"season": 1, "episode": 1}], "count": 1}]
    logs = []

    items = builder.generate_items_from_blocks("u1", blocks, {}, logs)

    assert items == []
    assert any("Could not process show entry" in line for line in logs)


def test_generate_items_movie_block_adds_movies_and_logs_count():
    blocks = [{"type": "movie", "filters": {"genres_any": ["Action"]}}]
    logs = []
    fake_movies = [{"Id": "m1", "Type": "Movie"}, {"Id": "m2", "Type": "Movie"}]

    with patch("app.builder.find_movies", return_value=fake_movies) as mock_find:
        items = builder.generate_items_from_blocks("u1", blocks, {}, logs)

    assert items == fake_movies
    mock_find.assert_called_once()
    assert any("Added 2 movies" in line for line in logs)


def test_generate_items_music_album_mode_uses_album_lookup():
    blocks = [{"type": "music", "music": {"mode": "album", "albumId": "alb-1"}}]
    logs = []
    fake_songs = [{"Id": "s1", "Type": "Audio"}]

    with patch("app.builder.get_songs_by_album", return_value=fake_songs) as mock_album:
        items = builder.generate_items_from_blocks("u1", blocks, {}, logs)

    assert items == fake_songs
    mock_album.assert_called_once_with("alb-1", {})
    assert any("Added 1 songs" in line for line in logs)


def test_create_mixed_playlist_returns_error_when_no_items_found():
    with patch("app.builder.generate_items_from_blocks", return_value=[]):
        result = builder.create_mixed_playlist("u1", "Mix", [{"type": "movie"}], {})

    assert result["status"] == "error"
    assert "No items were found" in " ".join(result["log"])


def test_create_mixed_playlist_success_calls_create_playlist_with_item_ids():
    built_items = [{"Id": "e1"}, {"Id": "m2"}]
    with patch("app.builder.generate_items_from_blocks", return_value=built_items), patch(
        "app.builder.create_playlist", return_value="new-playlist-id"
    ) as mock_create:
        result = builder.create_mixed_playlist("u1", "Mix", [{"type": "movie"}], {"H": "V"})

    assert result["status"] == "ok"
    assert result["new_item_id"] == "new-playlist-id"
    mock_create.assert_called_once_with(
        name="Mix",
        user_id="u1",
        ids=["e1", "m2"],
        hdr={"H": "V"},
        log=result["log"],
    )
