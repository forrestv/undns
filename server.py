import os
import sys
import random
import hashlib

import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server
del twisted
from twisted import names
from twisted.internet import reactor, defer
from twisted.python import failure

from entangled.kademlia import node, datastore

# config

port = random.randrange(49152, 65535)
print "PORT:", port

def parse(x):
    ip, port = x.split(':')
    return ip, int(port)
knownNodes = map(parse, sys.argv[1:])

my_data = ("i live at port %i" % (port,), "teehee port %i is the place to be" % (port,))

# DHT

dbFilename = '/tmp/undns%i.db' % (port,)
if os.path.isfile(dbFilename):
    os.remove(dbFilename)
dataStore = datastore.SQLiteDataStore(dbFile=dbFilename)

n = node.Node(udpPort=port, dataStore=dataStore)
n.joinNetwork(knownNodes)

print "ID:", n.id.encode('hex')

def store(*args):
    n.iterativeStore(hashlib.sha1(my_data[0]).digest(), my_data[1])
    reactor.callLater(15, store)
n._joinDeferred.addCallback(store)

def print_loop():
    n.printContacts()
    reactor.callLater(10, print_loop)
print_loop()

# DNS

class UnDNSResolver(names.common.ResolverBase):
    def __init__(self, dht):
        names.common.ResolverBase.__init__(self)
        self.dht = dht
    def _lookup(self, name, cls, type, timeout):
        if not name.endswith('.undns.forre.st'):
            return defer.fail(failure.Failure(names.dns.DomainError(name)))
        name2 = name[:-len('.undns.forre.st')]
        print name2, names.dns.QUERY_CLASSES[cls], names.dns.QUERY_TYPES[type], timeout
        return defer.fail(failure.Failure(names.dns.AuthoritativeDomainError(name)))

f = names.server.DNSServerFactory(authorities=[UnDNSResolver(n)], clients=[names.client.createResolver()])
reactor.listenTCP(53, f)
reactor.listenUDP(53, names.dns.DNSDatagramProtocol(f))

# global

reactor.run()
