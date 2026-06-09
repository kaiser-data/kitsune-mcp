from invoice import line_total


def _close(got, expected):
    return abs(got - expected) < 0.0001


def test_simple_no_tax():
    assert _close(line_total(19.99, 3, 0.0), 59.97)


def test_half_up_boundary():
    result = line_total(2.675, 1, 0.0)
    assert _close(result, 2.68), f"expected 2.68, got {result}"


def test_with_tax():
    assert _close(line_total(10.00, 1, 0.085), 10.85)


if __name__ == "__main__":
    test_simple_no_tax()
    test_half_up_boundary()
    test_with_tax()
    print("all tests pass")
