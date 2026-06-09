"""Small TTL/LRU cache."""

import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, capacity, ttl_seconds, now=None):
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self._now = now or time.monotonic
        self._items = OrderedDict()

    def get(self, key):
        if key not in self._items:
            return None
        value, expires_at = self._items[key]
        return value

    def set(self, key, value):
        if key in self._items:
            del self._items[key]
        elif self.capacity > 0 and len(self._items) >= self.capacity:
            self._items.popitem(last=False)
        self._items[key] = (value, self._now() + self.ttl_seconds)

    def __len__(self):
        return len(self._items)
