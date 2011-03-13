import json
import hashlib

from Crypto.PublicKey import RSA
import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server, twisted.names.error, twisted.names.authority
del twisted
from twisted import names

import util

class BindStringAuthority(names.authority.BindAuthority):
    def __init__(self, contents, origin):
        names.common.ResolverBase.__init__(self)
        self.origin = origin
        lines = contents.splitlines(True)
        lines = self.stripComments(lines)
        lines = self.collapseContinuations(lines)
        self.parseLines(lines)
        self._cache = {}

class Packet(object):
    @classmethod
    def from_json(cls, x, address=None, address_hash=None):
        d = json.loads(x)
        return cls(util.tuple_to_key(d['public_key']), d['zone_file'], d['signature'], address, address_hash)
    
    def __init__(self, public_key, zone_file, signature, address=None, address_hash=None):
        if public_key.has_private():
            raise ValueError("key not public")
        if not public_key.verify(hashlib.sha1(zone_file).digest(), signature):
            raise ValueError("signature invalid")
        
        self._public_key = public_key
        self._zone_file = zone_file
        self._signature = signature
        
        self._address = util.key_to_address(self._public_key)
        self._address_hash = hashlib.sha1(self._address).digest()
        self._zone = BindStringAuthority(self._zone_file.encode('utf8'), self._address + '.')
        
        if address is not None and self.get_address() != address:
            raise ValueError("address not correct")
        if address_hash is not None and self.get_address_hash() != address_hash:
            raise ValueError("address hash hot correct")
    
    def to_json(self):
        return json.dumps(dict(public_key=util.key_to_tuple(self._public_key), zone_file=self._zone_file, signature=self._signature))
    
    def get_address(self):
        return self._address
    
    def get_address_hash(self):
        return self._address_hash
    
    def get_zone_file(self):
        return self._zone_file
    
    def get_zone(self):
        return self._zone

class PrivateKey(object):
    @classmethod
    def generate(cls, rng):
        return cls(RSA.generate(1024, rng))
    
    @classmethod
    def from_json(cls, x):
        return cls(util.tuple_to_key(json.loads(x)))
    
    def __init__(self, private_key):
        if not private_key.has_private():
            raise ValueError("key not private")
        
        self._private_key = private_key
    
    def to_json(self):
        return json.dumps(util.key_to_tuple(self._private_key))
    
    def get_address(self):
        return util.key_to_address(self._private_key.publickey())
    
    def encode(self, zone_file, rng):
        return Packet(self._private_key.publickey(), zone_file, self._private_key.sign(hashlib.sha1(zone_file).digest(), rng))