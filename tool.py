import sys
import hashlib
import json

from Crypto.PublicKey import RSA
from Crypto import Random

import util

rng = Random.new().read

if sys.argv[1] == "generate":
    RSAkey = RSA.generate(1024, rng)
    print json.dumps(util.key_to_tuple(RSAkey))

elif sys.argv[1] == "info":
    RSApubkey = util.tuple_to_key(json.loads(open(sys.argv[2]).read())).publickey()
    print util.key_to_address(RSApubkey)

elif sys.argv[1] == "encode":
    RSAkey = util.tuple_to_key(json.loads(open(sys.argv[2]).read()))
    if not RSAkey.has_private():
        print "not a private key"
        sys.exit(1)
    RSApubkey = RSAkey.publickey()

    data = open(sys.argv[3]).read()
    
    packet = {'pubkey': util.key_to_tuple(RSApubkey), 'data': data, 'data_hash_signed': RSAkey.sign(hashlib.sha1(data).digest(), rng)}
    print json.dumps(packet)

elif sys.argv[1] == "decode":
    packet = json.loads(open(sys.argv[2]).read())
    RSApubkey = util.tuple_to_key(packet['pubkey'])
    data = packet['data']
    data_hash_signed = packet['data_hash_signed']

    address = sys.argv[3]
    
    print "pubkey matches:", util.key_to_address(RSApubkey) == address
    print "data valid:", RSApubkey.verify(hashlib.sha1(data).digest(), data_hash_signed)
    print "data:", repr(data)
