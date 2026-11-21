from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.packs import client_view, load_pack, object_of
from tests.helpers import ColourEmbedder, needs_pack


def make_client(settings):
    return TestClient(create_app(settings, embedder=ColourEmbedder()))


def test_settings_defaults_and_codes():
    s = load_settings({"ACCESS_CODES": " abc, def ,", "GEMINI_API_KEY": "k"})
    assert s.access_codes == frozenset({"abc", "def"})
    assert (s.llm_api_key, s.llm_model, s.llm_reasoning_effort) == ("k", "gemini-3.5-flash-lite", "minimal")
    assert (s.tts_provider, s.gemini_tts_model, s.gemini_tts_voice) == ("gemini", "gemini-3.8-flash-lite-tts", "Sulafat")


def test_load_pack_indexes_passages_and_relations(test_pack):
    pack = load_pack(test_pack)
    assert set(pack.objects) == {"1.1", "2.2"}
    assert pack.passages["2.2#p1"].text == "Beta guarded a temple."
    assert pack.relations[0].key == "1.1|2.2"
    assert pack.relations[0].other("1.1") == "2.2"
    assert pack.threshold == 0.9


def test_client_view_exposes_titles_parts_and_passages(test_pack):
    alpha = client_view(load_pack(test_pack))["objects"][0]
    assert alpha["display_image"] == "/pack-assets/images/1.1_01.jpg"
    assert alpha["parts"][0] == {"title": "Who it is", "passages": ["1.1#p1", "1.1#p2"]}
    assert alpha["passages"]["1.1#p3"] == "It came to Glasgow in 1950."


def test_health_is_open(settings_for):
    r = make_client(settings_for(ACCESS_CODES="secret")).get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "pack": "test-pack", "objects": 2}


def test_pack_requires_the_code_when_codes_are_set(settings_for):
    client = make_client(settings_for(ACCESS_CODES="secret"))
    assert client.get("/api/pack").status_code == 401
    assert client.get("/api/pack?code=secret").status_code == 200
    assert client.get("/api/pack", headers={"X-Access-Code": "secret"}).status_code == 200


def test_pack_images_are_served(settings_for):
    r = make_client(settings_for()).get("/pack-assets/images/1.1_01.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"


def test_blank_settings_fall_back_to_their_defaults():
    s = load_settings({"WEB_DIST": "", "LLM_API_KEY": " ", "GEMINI_API_KEY": "secret-key-123", "LLM_BASE_URL": "",
                       "STRICT_CITATIONS": "true", "ACCESS_CODES": "door-code-9"})
    assert s.web_dist.name == "dist"
    assert s.llm_api_key == "secret-key-123"
    assert s.llm_base_url.startswith("https://")
    assert s.strict_citations is True
    assert "secret-key-123" not in repr(s) and "door-code-9" not in repr(s)


def test_the_web_app_is_served_without_caching_and_leaves_the_api_alone(settings_for, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    client = make_client(settings_for(WEB_DIST=str(dist)))
    page = client.get("/")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
    assert client.get("/api/pack").status_code == 200
    assert client.get("/docs").status_code == 404


def test_a_wrong_code_is_refused(settings_for):
    assert make_client(settings_for(ACCESS_CODES="secret")).get("/api/pack?code=nope").status_code == 401


@needs_pack("burrell-pilot")
def test_the_pilot_pack_loads_and_every_cited_passage_exists():
    pack = load_pack(Path(__file__).resolve().parents[2] / "packs" / "burrell-pilot")
    assert len(pack.objects) == 5
    for obj in pack.objects.values():
        for part in obj.story:
            assert all(pid in pack.passages for pid in part.passage_ids)
    for relation in pack.relations:
        assert all(pid in pack.passages for pid in relation.passage_ids)
        assert {object_of(pid) for pid in relation.passage_ids} == {relation.a, relation.b}
    assert {r.key for r in pack.relations_of("13.181")} == {"13.181|28.37", "13.181|13.257"}
