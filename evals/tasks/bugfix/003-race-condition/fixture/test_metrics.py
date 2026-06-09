import threading

from metrics import MetricsCollector


def test_concurrent_add():
    mc = MetricsCollector()
    n_threads = 8
    per_thread = 2000

    def work():
        for _ in range(per_thread):
            mc.add(1)

    threads = [threading.Thread(target=work) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    expected = n_threads * per_thread
    assert mc.total == expected, f"lost updates: total={mc.total}, expected={expected}"


if __name__ == "__main__":
    test_concurrent_add()
    print("all tests pass")
