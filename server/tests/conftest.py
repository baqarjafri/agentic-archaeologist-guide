import pytest

from app.config import load_settings
from tests.helpers import write_test_pack


@pytest.fixture
def test_pack(tmp_path):
    return write_test_pack(tmp_path / "pack")


@pytest.fixture
def settings_for(test_pack, tmp_path):
    def make(**overrides):
        env = {"PACK_DIR": str(test_pack), "WEB_DIST": str(tmp_path / "no-web"), "MODEL_PATH": str(tmp_path / "none.onnx")}
        env.update(overrides)
        return load_settings(env)
    return make
