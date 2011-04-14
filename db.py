import random
import sqlite3

class SQLiteDict(object):
    def __init__(self, db, table):
        self._db = db
        self._table = table
        
        self._db.execute('CREATE TABLE IF NOT EXISTS %s(key BLOB PRIMARY KEY NOT NULL, value BLOB NOT NULL)' % (self._table,))

    def __iter__(self):
        for row in self._db.execute("SELECT key FROM %s" % (self._table,)):
            yield str(row[0])
    def iterkeys(self):
        return iter(self)
    def keys(self):
        return list(self)
    
    def itervalues(self):
        for row in self._db.execute("SELECT value FROM %s" % (self._table,)):
            yield str(row[0])
    def values(self):
        return list(self.itervalues)
    
    def iteritems(self):
        for row in self._db.execute("SELECT key, value FROM %s" % (self._table,)):
            yield (str(row[0]), str(row[1]))
    def items(self):
        return list(self.iteritems())
    
    def __setitem__(self, key, value):
        if self._db.execute("SELECT key FROM %s where key=?" % (self._table,), (buffer(key),)).fetchone() is None:
            self._db.execute('INSERT INTO %s(key, value) VALUES (?, ?)' % (self._table,), (buffer(key), buffer(value)))
        else:
            self._db.execute('UPDATE %s SET value=? WHERE key=?' % (self._table,), (buffer(value), buffer(key)))
    
    def __getitem__(self, key):
        row = self._db.execute('SELECT value FROM %s WHERE key=?' % (self._table,), (buffer(key),)).fetchone()
        if row is None:
            raise KeyError(key)
        else:
            return str(row[0])
    
    def __delitem__(self, key):
        self._db.execute("DELETE FROM %s WHERE key=?" % (self._table,), (buffer(key),))

class CachingDictWrapper(object):
    def __init__(self, inner, cache_size=10000):
        self._inner = inner
        self._cache = {}
        self._cache_size = cache_size
    
    def _add_to_cache(self, key, value):
        self._cache[key] = value
        if len(self._cache) > self._cache_size:
            del self._cache[random.choice(self._cache.keys())]
    
    def __len__(self):
        return len(self._inner)
    
    def __getitem__(self, key):
        try:
            return self._cache[key]
        except KeyError:
            print "cache failed for", repr(key)
            value = self._inner[key]
            self._add_to_cache(key, value)
            return value
    
    def __setitem__(self, key, value):
        self._inner[key] = value
        self._add_to_cache(key, value)
    
    def __delitem__(self, key):
        del self._inner[key]
        if key in self._cache:
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
    def __init__(self, inner, cache_size=10000):
        self._inner = inner
        self._cache = {}
        self._cache_size = cache_size
    
    def _add_to_cache(self, key, value):
        self._cache[key] = value
        if len(self._cache) > self._cache_size:
            del self._cache[random.choice(self._cache.keys())]
    
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

class ValueDictWrapper(object):
    def __init__(self, inner):
        self._inner = inner
    def __len__(self):
        return len(self._inner)
    def __getitem__(self, key):
        return self._decode(key, self._inner[key])
    def __setitem__(self, key, value):
        self._inner[key] = self._encode(key, value)
    def __delitem__(self, key):
        del self._inner[key]
    def __contains__(self, key):
        return key in self._inner
    def __iter__(self):
        return iter(self._inner)
    def keys(self):
        return self._inner.keys()
    def iteritems(self):
        for k, v in self._inner.iteritems():
            yield k, self._decode(k, v)


class JSONValueWrapper(ValueDictWrapper):
    def _encode(self, addr, content):
        return json.dumps(content)
    def _decode(self, addr, data):
        return json.loads(data)

import cPickle

class PickleValueWrapper(ValueDictWrapper):
    def _encode(self, addr, content):
        return cPickle.dumps(content) #, cPickle.HIGHEST_PROTOCOL)
    def _decode(self, addr, data):
        return cPickle.loads(data)
