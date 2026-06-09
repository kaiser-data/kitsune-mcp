import os
import tempfile

from stats import compute_and_report


def _write(content):
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def test_basic():
    path = _write("1 2 3 4")
    try:
        result = compute_and_report(path)
        assert result["total"] == 10
        assert result["count"] == 4
        assert result["mean"] == 2.5
        assert result["max"] == 4
    finally:
        os.remove(path)


def test_single():
    path = _write("42")
    try:
        result = compute_and_report(path)
        assert result == {"total": 42, "mean": 42.0, "max": 42, "count": 1}
    finally:
        os.remove(path)


if __name__ == "__main__":
    test_basic()
    test_single()
    print("all tests pass")
