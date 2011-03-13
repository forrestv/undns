import sys
import hashlib
import json

from Crypto import Random

import util
import packet

rng = Random.new().read

if sys.argv[1] == "generate":
    print packet.PrivateKey.generate(rng).to_json()

elif sys.argv[1] == "info":
    private_key = packet.PrivateKey.from_json(open(sys.argv[2]).read())
    
    print private_key.get_address()

elif sys.argv[1] == "encode":
    private_key = packet.PrivateKey.from_json(open(sys.argv[2]).read())
    zone_file = open(sys.argv[3]).read()
    
    print private_key.encode(zone_file, rng).to_json()

elif sys.argv[1] == "decode":
    pkt = packet.Packet.from_json(open(sys.argv[2]).read())
    
    print pkt.get_address()
    print
    print pkt.get_zone_file(),
