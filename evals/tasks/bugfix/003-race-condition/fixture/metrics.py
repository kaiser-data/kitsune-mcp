import time


class MetricsCollector:
    def __init__(self):
        self.total = 0
        self.history = []

    def add(self, value):
        current = self.total
        self._persist(current)
        self.total = current + value

    def _persist(self, snapshot):
        time.sleep(0)
        self.history.append(snapshot)
