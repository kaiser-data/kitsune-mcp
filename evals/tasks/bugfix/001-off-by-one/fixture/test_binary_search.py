from binary_search import binary_search


def test_found_middle():
    assert binary_search([1, 2, 3, 4, 5], 3) == 2


def test_not_found_larger_than_all():
    result = binary_search([1, 2, 3], 10)
    assert result == -1, f"expected -1, got {result}"


def test_found_first():
    assert binary_search([10, 20, 30], 10) == 0


if __name__ == "__main__":
    test_found_middle()
    test_not_found_larger_than_all()
    test_found_first()
    print("all tests pass")
