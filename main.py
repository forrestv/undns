import subprocess
import os
import argparse
import random
import sys
import sqlite3

import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server, twisted.names.error, twisted.names.authority
del twisted
from twisted import names
from twisted.internet import protocol, reactor
from Crypto import Random

import server

try:
    __version__ = subprocess.Popen(["svnversion", os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except IOError:
    __version__ = "unknown"

name = "UnDNS server (version %s)" % (__version__,)

parser = argparse.ArgumentParser(description=name)
parser.add_argument('--version', action='version', version=__version__)
parser.add_argument("-a", "--authoritative-dns", metavar="PORT",
    help="run a TCP+UDP authoritative dns server on PORT; you likely don't want this - this is for _the_ public nameserver",
    type=int, action="append", default=[], dest="authoritative_dns_ports")
parser.add_argument("-r", "--recursive-dns", metavar="PORT",
    help="run a TCP+UDP recursive dns server on PORT; you likely do want this - this is for clients",
    type=int, action="append", default=[], dest="recursive_dns_ports")
parser.add_argument("-d", "--dht-port", metavar="PORT",
    help="use UDP port PORT to connect to other DHT nodes and listen for connections (default: last used or random if never used)",
    type=int, action="store", default=None, dest="dht_port")
parser.add_argument("-n", "--node", metavar="ADDR:PORT",
    help="connect to existing DHT node at ADDR listening on UDP port PORT",
    action="append", default=[], dest="dht_nodes")
parser.add_argument("-l", "--listen", metavar="PORT",
    help="listen on PORT for RPC connections to manage server",
    type=int, action="append", default=[], dest="rpc_ports")

config_default = os.path.join(os.path.expanduser('~'), '.undns')
parser.add_argument("-c", "--config", metavar="PATH",
    help="use configuration database at PATH (default: %s)" % (config_default,),
    action="store", default=config_default, dest="config")

args = parser.parse_args()

rng = Random.new().read

def parse(x):
    if ':' not in x:
        return ('127.0.0.1', int(x))
    ip, port = x.split(':')
    return ip, int(port)
knownNodes = map(parse, args.dht_nodes)

n = server.UnDNSNode(udpPort=args.dht_port, config_db=sqlite3.connect(args.config, isolation_level=None), rng=rng)
n.joinNetwork(knownNodes)

print name, "on port", n.port

resolver = server.UnDNSResolver(n)

authoritative_dns = names.server.DNSServerFactory(authorities=[resolver])
for port in args.authoritative_dns_ports:
    reactor.listenTCP(port, authoritative_dns)
    reactor.listenUDP(port, names.dns.DNSDatagramProtocol(authoritative_dns))

recursive_dns = names.server.DNSServerFactory(authorities=[resolver], clients=[names.client.createResolver()])
for port in args.recursive_dns_ports:
    reactor.listenTCP(port, recursive_dns)
    reactor.listenUDP(port, names.dns.DNSDatagramProtocol(recursive_dns))

rpc_factory = protocol.ServerFactory()
rpc_factory.protocol = server.RPCProtocol
rpc_factory.node = n
rpc_factory.rng = rng
for port in args.rpc_ports:
    reactor.listenTCP(port, rpc_factory, interface="127.0.0.1")

reactor.run()
