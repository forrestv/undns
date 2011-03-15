#!/usr/bin/python

import os
import sys
import random
import hashlib
import optparse
import subprocess

import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server, twisted.names.error, twisted.names.authority
del twisted
from twisted import names
from twisted.internet import reactor, defer
from twisted.python import failure
from entangled.kademlia import node, datastore

import packet

try:
    __version__ = subprocess.Popen(["svnversion", os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except IOError:
    __version__ = "unknown"

name = "UnDNS server (version %s)" % (__version__,)

parser = optparse.OptionParser(version=__version__, description=name)
parser.add_option("-a", "--authoritative-dns", metavar="PORT",
    help="run an authoritative dns server; you likely don't want this - this is for _the_ public nameserver",
    type="int", action="append", default=[], dest="authoritative_dns_ports")
parser.add_option("-r", "--recursive-dns", metavar="PORT",
    help="run a recursive dns server on PORT; you likely do want this - this is for clients",
    type="int", action="append", default=[], dest="recursive_dns_ports")
parser.add_option("-p", "--packet", metavar="FILE",
    help="read FILE every few seconds and sent its contained packet",
    type="string", action="append", default=[], dest="packet_filenames")
parser.add_option("-d", "--dht-port", metavar="PORT",
    help="use UDP port PORT to connect to other DHT nodes and listen for connections (if not specified a random high port is chosen)",
    type="int", action="store", default=random.randrange(49152, 65536), dest="dht_port")
parser.add_option("-n", "--node", metavar="ADDR:PORT",
    help="connect to existing DHT node at ADDR listening on UDP port PORT",
    type="string", action="append", default=[], dest="dht_nodes")
(options, args) = parser.parse_args()
if args:
    parser.error("takes no arguments")

print name

port = options.dht_port
print "PORT:", port

def parse(x):
    ip, port = x.split(':')
    return ip, int(port)
knownNodes = map(parse, options.dht_nodes)

packets = [packet.Packet.from_binary(open(filename).read()) for filename in options.packet_filenames]

# DHT

dbFilename = '/tmp/undns%i.db' % (port,)
if os.path.isfile(dbFilename):
    os.remove(dbFilename)
dataStore = datastore.SQLiteDataStore(dbFile=dbFilename)

class UnDNSNode(node.Node):
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        print repr((self, key, value, originalPublisherID, age, kwargs))

        packet.Packet.from_binary(value, address_hash=key) # will throw an exception if not valid
        
        node.Node.store(self, key, value, originalPublisherID, age, **kwargs)

n = UnDNSNode(udpPort=port, dataStore=dataStore)
n.joinNetwork(knownNodes)

print "ID:", n.id.encode('hex')

def store(*args):
    for packet in packets:
        print "publishing", packet.get_address()
        n.iterativeStore(packet.get_address_hash(), packet.to_binary())
    reactor.callLater(13.23324141, store)
n._joinDeferred.addCallback(store)

def print_loop():
    n.printContacts()
    reactor.callLater(10.5984312, print_loop)
print_loop()

# DNS

class UnDNSResolver(names.common.ResolverBase):
    def __init__(self, dht):
        names.common.ResolverBase.__init__(self)
        self.dht = dht
    def _lookup(self, name, cls, type, timeout):
        if not name.endswith('.undns.forre.st'):
            return defer.fail(failure.Failure(names.dns.DomainError(name)))
        
        name_alone = '.'.join(name.split('.')[-len('.undns.forre.st'.split('.')):])
        print name_alone
        
        name_hash = hashlib.sha1(name_alone).digest()
        
        #print name, names.dns.QUERY_CLASSES[cls], names.dns.QUERY_TYPES[type], timeout
        
        def callback(result):
            if isinstance(result, list):
                print result
                return defer.fail(failure.Failure(names.dns.AuthoritativeDomainError(name)))
            
            assert isinstance(result, dict), result
            packet = packet.Packet.from_binary(result[name_hash])
            
            if packet.get_address() != name_alone:
                return defer.fail(failure.Failure(names.dns.AuthoritativeDomainError(name)))
            
            zone = UnDNSAuthority(packet.get_data().encode('utf8'), packet.get_address() + '.')
            
            return zone._lookup(name, cls, type, timeout)
        return self.dht.iterativeFindValue(name_hash).addCallback(callback)

resolver = UnDNSResolver(n)

authoritative_dns = names.server.DNSServerFactory(authorities=[resolver])
for port in options.authoritative_dns_ports:
    reactor.listenTCP(port, authoritative_dns)
    reactor.listenUDP(port, names.dns.DNSDatagramProtocol(authoritative_dns))

recursive_dns = names.server.DNSServerFactory(authorities=[resolver], clients=[names.client.createResolver()])
for port in options.recursive_dns_ports:
    reactor.listenTCP(port, recursive_dns)
    reactor.listenUDP(port, names.dns.DNSDatagramProtocol(recursive_dns))

# global

reactor.run()
