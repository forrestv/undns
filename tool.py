import sys
import hashlib

from Crypto import Random

import packet

rng = Random.new().read

if sys.argv[1] == "generate":
    print packet.PrivateKey.generate(rng).to_binary()

elif sys.argv[1] == "info":
    private_key = packet.PrivateKey.from_binary(open(sys.argv[2]).read())
    
    print private_key.get_address()

elif sys.argv[1] == "encode":
    private_key = packet.PrivateKey.from_binary(open(sys.argv[2]).read())
    zone_file = open(sys.argv[3]).read()
    
    print private_key.encode(zone_file, rng).to_binary()

elif sys.argv[1] == "decode":
    pkt = packet.Packet.from_binary(open(sys.argv[2]).read())
    
    print pkt.get_address()
    print
    print pkt.get_zone_file(),

elif sys.argv[1] == "view":
    import json
    import zlib
    print json.loads(zlib.decompress(open(sys.argv[2]).read()))
