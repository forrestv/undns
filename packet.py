import json
import hashlib
import zlib

from Crypto.PublicKey import RSA
from twisted.names import authority

import util

class BindStringAuthority(authority.BindAuthority):
    def __init__(self, contents, origin):
        names.common.ResolverBase.__init__(self)
        self.origin = origin
        lines = contents.splitlines(True)
        lines = self.stripComments(lines)
        lines = self.collapseContinuations(lines)
        self.parseLines(lines)
        self._cache = {}

class DomainKey(object):
    "All that is needed to control a domain"
    
    @classmethod
    def generate(cls, rng):
        return cls(RSA.generate(1024, rng))
    
    @classmethod
    def from_binary(cls, x):
        return cls(util.tuple_to_key(json.loads(zlib.decompress(x))))
    
    def __init__(self, private_key):
        if not private_key.has_private():
            raise ValueError("key not private")
        
        self._private_key = private_key
    
    def to_binary(self):
        return zlib.compress(json.dumps(util.key_to_tuple(self._private_key)))
    
    def get_address(self):
        return util.key_to_address(self._private_key.publickey())
    
    def encode(self, record, rng):
        return DomainPacket(self._private_key.publickey(), record, self._private_key.sign(record.get_hash(), rng))

class DomainPacket(object):
    "All that is needed to securely convey a DomainRecord"
    
    @classmethod
    def from_binary(cls, x):
        d = json.loads(zlib.decompress(x))
        return cls(util.tuple_to_key(d['public_key']), DomainRecord.from_obj(d['record']), d['signature'])
    
    def __init__(self, public_key, record, signature):
        if public_key.has_private():
            raise ValueError("key not public")
        
        self._public_key = public_key
        self._record = record
        self._signature = signature
        
        self._address = util.key_to_address(self._public_key)
        self._address_hash = util.hash_address_hash(self._address).digest()
        self._zone = None
    
    def to_binary(self):
        return zlib.compress(json.dumps(dict(public_key=util.key_to_tuple(self._public_key), record=self._record.to_obj(), signature=self._signature)))
    
    def verify_signature(self):
        return public_key.verify(self._record.get_hash(), signature)
    
    def get_address(self):
        return self._address
    
    def get_address_hash(self):
        return self._address_hash
    
    def get_record(self):
        return self._record

class DomainRecord(object):
    "Information about a domain"
    
    @classmethod
    def from_obj(cls, (zone_file, start_time, end_time)):
        return cls(zone_file, start_time, end_time)
    
    def __init__(self, zone_file, start_time, end_time):
        assert isinstance(zone_file, unicode)
        assert isinstance(start_time, (int, long))
        assert isinstance(end_time, (int, long))
        
        self._zone_file = zone_file
        self._start_file = start_time
        self._end_time = end_time
    
    def to_obj(self):
        return (self._zone_file, self._start_time, self._end_time)
    
    def to_binary(self):
        return json.dumps(dict(zone_file=self._zone_file, start_time=self._start_time, end_time=self._end_time))
    
    def get_zone_file(self):
        return self._zone_file
    
    def get_zone(self, address):
        assert not address.endswith('.')
        return BindStringAuthority(self._zone_file.encode('utf8'), address + '.')
    
    def get_start_time(self):
        return self._start_time
    
    def get_end_time(self):
        return self._end_time
    
    def get_hash(self):
        return util.hash_sign(self.to_binary()).digest()

if __name__ == '__main__':
    from Crypto import Random
    rng = Random.new().read
    
    h = "hello, world!"
    
    a = MyIdentity.generate(rng)
    
    print repr(a.to_binary())
    print repr(a.get_id())
    print repr(a.to_binary_public())
    
    print
    d = a.sign(h, rng)
    print repr(d)
    
    b = TheirIdentity.from_binary(a.to_binary_public())
    
    print repr(b.get_id())
    print b.verify(h, d)

