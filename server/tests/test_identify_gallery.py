import io
import json

from fastapi.testclient import TestClient
from PIL import Image

from app.gallery import gallery_slides
from app.main import create_app
from app.packs import load_pack
from tests.helpers import ColourEmbedder, jpeg_bytes


def client_for(settings):
    return TestClient(create_app(settings, embedder=ColourEmbedder()))


def post_photo(client, data, url="/api/identify"):
    return client.post(url, files={"image": ("frame.jpg", data, "image/jpeg")})


def test_identify_accepts_a_matching_photo(settings_for):
    r = post_photo(client_for(settings_for()), jpeg_bytes((200, 10, 10)))
    body = r.json()
    assert r.status_code == 200
    assert body["accepted"] is True and body["object_id"] == "1.1"
    assert [c["object_id"] for c in body["candidates"]] == ["1.1", "2.2"]


def test_identify_rejects_an_object_outside_the_pack(settings_for):
    body = post_photo(client_for(settings_for()), jpeg_bytes((10, 200, 10))).json()
    assert body["accepted"] is False and body["object_id"] is None


def test_identify_rejects_a_non_image(settings_for):
    assert post_photo(client_for(settings_for()), b"not an image").status_code == 400


def test_identify_wants_the_image_field(settings_for):
    r = client_for(settings_for()).post("/api/identify", files={"photo": ("frame.jpg", jpeg_bytes((200, 10, 10)), "image/jpeg")})
    assert r.status_code == 400


def test_identify_rejects_a_picture_with_too_many_pixels(settings_for):
    out = io.BytesIO()
    Image.new("L", (6000, 5000)).save(out, format="PNG")  # 30 megapixels in a few kilobytes
    assert post_photo(client_for(settings_for()), out.getvalue()).status_code == 413


def test_identify_requires_the_code(settings_for):
    client = client_for(settings_for(ACCESS_CODES="secret"))
    assert post_photo(client, jpeg_bytes((200, 10, 10))).status_code == 401
    assert post_photo(client, jpeg_bytes((200, 10, 10)), "/api/identify?code=secret").status_code == 200


def test_gallery_shows_test_photos_and_distractors_but_never_references(settings_for):
    page = client_for(settings_for()).get("/test-gallery").text
    assert "/pack-assets/images/1.1_02.jpg" in page
    assert "/pack-assets/distractors/9.9_01.jpg" in page
    assert "Not in the pack: Gamma" in page
    assert "/pack-assets/images/1.1_01.jpg" not in page


def test_identify_accepts_the_code_in_a_header_and_refuses_a_wrong_one(settings_for):
    client = client_for(settings_for(ACCESS_CODES="secret"))
    files = {"image": ("frame.jpg", jpeg_bytes((200, 10, 10)), "image/jpeg")}
    assert client.post("/api/identify", files=files, headers={"X-Access-Code": "secret"}).status_code == 200
    assert client.post("/api/identify?code=nope", files=files).status_code == 401


def test_identify_refuses_an_upload_over_the_size_limit(settings_for):
    assert post_photo(client_for(settings_for()), b"0" * 2_100_000).status_code == 413


def test_a_rejected_frame_still_lists_its_candidates(settings_for):
    body = post_photo(client_for(settings_for()), jpeg_bytes((10, 200, 10))).json()
    assert body["accepted"] is False and len(body["candidates"]) == 2
    assert set(body["candidates"][0]) == {"object_id", "score"}


def test_gallery_slides_follow_the_pack_order_and_tag_the_synthetic_photo(test_pack):
    beta_path = test_pack / "objects" / "2.2.json"
    beta = json.loads(beta_path.read_text(encoding="utf-8"))
    beta["images"].append({"file": "images/2.2_synthetic_test.jpg", "role": "test", "source_url": None, "synthetic": True})
    beta_path.write_text(json.dumps(beta), encoding="utf-8")
    slides = gallery_slides(load_pack(test_pack))
    assert [s["name"] for s in slides] == ["1.1_02", "2.2_synthetic_test", "9.9_01"]
    assert [s["object_id"] for s in slides] == ["1.1", "2.2", None]
    assert slides[1]["label"].endswith("[synthetic]")


def test_gallery_escapes_titles_inside_the_page(settings_for, test_pack):
    alpha_path = test_pack / "objects" / "1.1.json"
    alpha = json.loads(alpha_path.read_text(encoding="utf-8"))
    alpha["title"] = "</script><script>alert(1)</script>"
    alpha_path.write_text(json.dumps(alpha), encoding="utf-8")
    page = client_for(settings_for()).get("/test-gallery").text
    assert "</script><script>alert(1)" not in page
