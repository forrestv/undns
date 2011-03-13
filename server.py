#!/usr/bin/python

import os
import sys
import random
import hashlib
import optparse
import json

import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server, twisted.names.error, twisted.names.authority
del twisted
from twisted import names
from twisted.internet import reactor, defer
from twisted.python import failure
from entangled.kademlia import node, datastore

import util
import packet

parser = optparse.OptionParser()
parser.add_option("-a", "--authoritative", metavar="PORT",
    help="run an authoritative dns server; you likely don't want this - this is for _the_ public nameserver",
    type="int", action="append", default=[], dest="authoritative_dns_ports")
parser.add_option("-r", "--recursive", metavar="PORT",
    help="run a recursive dns server on PORT; you likely do want this - this is for clients",
    type="int", action="append", default=[], dest="recursive_dns_ports")
parser.add_option("-p", "--packet", metavar="FILE",
    help="read FILE every few seconds and sent its contained packet",
    type="string", action="append", default=[], dest="packet_filenames")
(options, args) = parser.parse_args()

port = random.randrange(49152, 65536)
print "PORT:", port

def parse(x):
    ip, port = x.split(':')
    return ip, int(port)
knownNodes = map(parse, args)

packets = [packet.Packet.from_json(open(filename).read()) for filename in options.packet_filenames]

# DHT

dbFilename = '/tmp/undns%i.db' % (port,)
if os.path.isfile(dbFilename):
    os.remove(dbFilename)
dataStore = datastore.SQLiteDataStore(dbFile=dbFilename)

class UnDNSNode(node.Node):
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        print repr((self, key, value, originalPublisherID, age, kwargs))

        packet.Packet.from_json(value, address_hash=key) # will throw an exception if not valid
        
        node.Node.store(self, key, value, originalPublisherID, age, **kwargs)

n = UnDNSNode(udpPort=port, dataStore=dataStore)
n.joinNetwork(knownNodes)

print "ID:", n.id.encode('hex')

def store(*args):
    for packet in packets:
        print "publishing", packet.get_address()
        n.iterativeStore(packet.get_address_hash(), packet.to_json())
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
            packet = packet.Packet.from_json(result[name_hash])
            
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
