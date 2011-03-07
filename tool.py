import sys
import hashlib
import json

from Crypto.PublicKey import RSA
from Crypto import Random

import util

rng = Random.new().read

def key_to_tuple(k):
    if k.has_private():
        return (k.n, k.e, k.d, k.p, k.q, k.u)
    else:
        return (k.n, k.e)

def tuple_to_key(t):
    return RSA.construct(map(long, t))

def key_to_address(k):
    hash = int(hashlib.sha1(RSApubkey.exportKey()).hexdigest(), 16)
    return util.int_to_string(hash, util.alphabet) + ".undns.forre.st"

if sys.argv[1] == "generate":
    RSAkey = RSA.generate(1024, rng)
    print json.dumps(key_to_tuple(RSAkey.key))

elif sys.argv[1] == "info":
    RSApubkey = tuple_to_key(json.loads(open(sys.argv[2]).read())).publickey()
    print key_to_address(RSApubkey)

elif sys.argv[1] == "encode":
    RSAkey = tuple_to_key(json.loads(open(sys.argv[2]).read()))
    if not RSAkey.has_private():
        print "not a private key"
        sys.exit(1)
    RSApubkey = RSAkey.publickey()

    data = open(sys.argv[3]).read()
    
    packet = {'pubkey': key_to_tuple(RSApubkey.key), 'data': data, 'data_hash_signed': RSAkey.sign(hashlib.sha1(data).digest(), rng)}
    print json.dumps(packet)

elif sys.argv[1] == "decode":
    packet = json.loads(open(sys.argv[2]).read())
    RSApubkey = tuple_to_key(packet['pubkey'])
    data = packet['data']
    data_hash_signed = packet['data_hash_signed']

    address = sys.argv[3]
    
    print "pubkey matches:", key_to_address(RSApubkey) == address
    print "data valid:", RSApubkey.verify(hashlib.sha1(data).digest(), data_hash_signed)
    print "data:", repr(data)
