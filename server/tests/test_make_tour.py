import json
from pathlib import Path

import pytest

from scripts.make_tour import Part, ffmpeg_args, read_cuts, timeline


def write_cuts(tmp_path: Path, segments: list[dict], video: str = "clip.mp4") -> Path:
    path = tmp_path / "tour-cuts.json"
    path.write_text(json.dumps({"clips": [{"video": video, "segments": segments}]}), encoding="utf-8")
    return path


def test_read_cuts_resolves_videos_beside_the_cut_list(tmp_path):
    parts = read_cuts(write_cuts(tmp_path, [
        {"kind": "walk", "start": 0, "end": 2},
        {"kind": "hover", "start": 2, "end": 5, "piece": "487620"},
    ]))
    assert parts == [
        Part(tmp_path / "clip.mp4", "walk", 0.0, 2.0, None),
        Part(tmp_path / "clip.mp4", "hover", 2.0, 5.0, "487620"),
    ]


@pytest.mark.parametrize("segments, message", [
    ([{"kind": "pan", "start": 0, "end": 1}], "unknown segment kind"),
    ([{"kind": "walk", "start": 3, "end": 1}], "ends before it starts"),
    ([{"kind": "walk", "start": 0, "end": 4}, {"kind": "walk", "start": 3, "end": 5}], "overlaps"),
    ([{"kind": "hover", "start": 0, "end": 2}], "names no piece"),
    ([], "no segments"),
])
def test_read_cuts_refuses_a_bad_cut_list(tmp_path, segments, message):
    with pytest.raises(ValueError, match=message):
        read_cuts(write_cuts(tmp_path, segments))


def test_a_walk_is_cut_and_scaled_and_a_hover_is_a_ping_pong_loop(tmp_path):
    walk = ffmpeg_args(Part(tmp_path / "c.mp4", "walk", 1.5, 4.0, None), tmp_path / "w.mp4")
    assert walk[walk.index("-ss") + 1] == "1.500"
    assert walk[walk.index("-t") + 1] == "2.500"
    assert "-an" in walk
    assert "scale=1080:1920" in walk[walk.index("-vf") + 1]
    assert walk[-1] == str(tmp_path / "w.mp4")
    hover = ffmpeg_args(Part(tmp_path / "c.mp4", "hover", 2.0, 5.0, "x"), tmp_path / "h.mp4")
    graph = hover[hover.index("-filter_complex") + 1]
    assert "reverse" in graph
    assert "concat=n=2" in graph


def test_timeline_lays_parts_end_to_end_and_names_the_hovered_piece():
    parts = [Part(Path("c.mp4"), "walk", 0, 2, None), Part(Path("c.mp4"), "hover", 2, 5, "487620")]
    assert timeline(parts, [2.0, 6.0]) == [
        {"kind": "walk", "start": 0.0, "end": 2.0},
        {"kind": "hover", "start": 2.0, "end": 8.0, "piece": "487620"},
    ]
