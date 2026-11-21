from app.config import load_settings
from tests.test_server_core import make_client


def test_demo_dir_is_unset_unless_given():
    assert load_settings({}).demo_dir is None
    assert load_settings({"DEMO_DIR": "  "}).demo_dir is None


def test_demo_media_is_served_only_when_demo_dir_is_set(settings_for, tmp_path):
    demo = tmp_path / "tour"
    demo.mkdir()
    (demo / "tour.json").write_text('{"video": "tour.mp4", "segments": []}', encoding="utf-8")
    assert make_client(settings_for()).get("/demo-media/tour.json").status_code == 404
    r = make_client(settings_for(DEMO_DIR=str(demo))).get("/demo-media/tour.json")
    assert r.status_code == 200
    assert r.json()["video"] == "tour.mp4"
