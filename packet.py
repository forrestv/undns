import json
import hashlib
import zlib

from Crypto.PublicKey import RSA
from twisted.names import authority, common

import util

class BindStringAuthority(authority.BindAuthority):
    def __init__(self, contents, origin):
        common.ResolverBase.__init__(self)
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
        return cls(RSA.generate(4096, rng))
    
    @classmethod
    def from_binary(cls, x):
        return cls(util.tuple_to_key(json.loads(zlib.decompress(x))))
    
    def __init__(self, private_key):
        if not private_key.has_private():
            raise ValueError("key not private")
        
        self._private_key = private_key
    
    def to_binary(self):
        return zlib.compress(json.dumps(util.key_to_tuple(self._private_key)))
    
    def get_name(self):
        return util.key_to_name(self._private_key.publickey())
    
    def get_name_hash(self):
        return util.key_to_name_hash(self._private_key.publickey())
    
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
        assert isinstance(record, DomainRecord)
        signature = tuple(signature)
        
        self._public_key = public_key
        self._record = record
        self._signature = signature
    
    def to_binary(self):
        return zlib.compress(json.dumps(dict(public_key=util.key_to_tuple(self._public_key), record=self._record.to_obj(), signature=self._signature)))
    
    def verify_signature(self):
        return self._public_key.verify(self._record.get_hash(), self._signature)
    
    def get_name(self):
        return util.key_to_name(self._public_key)
    
    def get_name_hash(self):
        return util.key_to_name_hash(self._public_key)
    
    def get_record(self):
        return self._record

class DomainRecord(object):
    "Information about a domain"
    
    @classmethod
    def from_obj(cls, (zone_file, end_time)):
        return cls(zone_file, end_time)
    
    def __init__(self, zone_file, end_time):
        assert isinstance(zone_file, unicode)
        assert isinstance(end_time, (int, long))
        
        self._zone_file = zone_file
        self._end_time = end_time
    
    def to_obj(self):
        return (self._zone_file, self._end_time)
    
    def to_binary(self):
        return json.dumps(dict(zone_file=self._zone_file, end_time=self._end_time))
    
    def get_zone_file(self):
        return self._zone_file
    
    def get_zone(self, address):
        assert not address.endswith('.')
        return BindStringAuthority(self._zone_file.encode('utf8'), address + '.')
    
    def get_end_time(self):
        return self._end_time
    
    def get_hash(self):
        b = self.to_binary()
        return util.ripemd160(b).digest() + hashlib.sha512(b).digest()

if __name__ == '__main__':
    from Crypto import Random
    rng = Random.new().read
    
    a = DomainKey.generate(rng)
    
    print a.get_name()
    print util.name_hash_to_name(a.get_name_hash())
    
    print util.name_to_name_hash(a.get_name()).encode('hex')
    print a.get_name_hash().encode('hex')
