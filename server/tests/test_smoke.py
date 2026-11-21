import sys


def test_runs_on_python_312_or_313():
    assert sys.version_info[:2] in {(3, 12), (3, 13)}
