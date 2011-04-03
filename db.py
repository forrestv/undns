import random

class CachingDictWrapper(object):
    def __init__(self, inner, cache_size=100):
        self._inner = inner
        self._cache = {}
        self._cache_size = cache_size
    
    def _add_to_cache(self, key, value):
        self._cache[key] = value
        if len(self._cache) > self._cache_size:
            del self._cache[random.choice(self.cache.keys())]
    
    def __len__(self):
        return len(self._inner)
    
    def __getitem__(self, key):
        try:
            return self._cache[key]
        except KeyError:
            value = self._inner[key]
            self._add_to_cache(key, value)
            return value
    
    def __setitem__(self, key, value):
        self._inner[key] = value
        self._add_to_cache(key, value)
    
    def __delitem__(self, key):
        del self._inner[key]
        if key in self.cache:
            del self._cache[key]
    
    def __contains__(self, key):
        if key in self._cache:
            return True
        return key in self._inner
    
    def __iter__(self):
        return iter(self._inner)
    
    def keys(self):
        return self._inner.keys()
    def iterkeys(self):
        return self._inner.iterkeys()
    def values(self):
        return self._inner.values()
    def itervalues(self):
        return self._inner.itervalues()
    def items(self):
        return self._inner.items()
    def iteritems(self):
        return self._inner.iteritems()

class SetDictWrapper(object):
    def __init__(self, inner):
        self._inner = inner
    def add(self, item):
        self._inner[item] = ""
    def remove(self, item):
        self._inner.pop(item) # raises KeyError if not present
    def __contains__(self, item):
        return item in self._inner
    def __iter__(self):
        return iter(self._inner)

class CachingSetWrapper(object):
    def __init__(self, inner, cache_size=1000):
        self._inner = inner
        self._cache = {}
        self._cache_size = cache_size
    
    def _add_to_cache(self, key, value):
        self._cache[key] = value
        if len(self._cache) > self._cache_size:
            del self._cache[random.choice(self.cache.keys())]
    
    def __len__(self):
        return len(self._inner)
    
    def add(self, item):
        self._inner.add(item)
        self._add_to_cache(item, True)
    
    def remove(self, item):
        self._inner.remove(item)
        self._add_to_cache(item, False)
    
    def __contains__(self, item):
        try:
            return self._cache[item]
        except KeyError:
            return item in self._inner
    
    def __iter__(self):
        return iter(self._inner)
