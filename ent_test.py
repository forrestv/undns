import os
import sys
import random
import hashlib

from twisted.internet import reactor
from entangled.kademlia import node, datastore

def parse(x):
    ip, port = x.split(':')
    return ip, int(port)
knownNodes = map(parse, sys.argv[1:])

port = random.randrange(49152, 65535)

dbFilename = '/tmp/undns%i.db' % (port,)
if os.path.isfile(dbFilename):
    os.remove(dbFilename)
dataStore = datastore.SQLiteDataStore(dbFile=dbFilename)

n = node.Node(udpPort=port, dataStore=dataStore)
n.joinNetwork(knownNodes)

my_data = ("i live at port %i" % (port,), "teehee port %i is the place to be" % (port,))

def joined(*args):
    n.iterativeStore(hashlib.sha1(my_data[0]).digest(), my_data[1])
    reactor.callLater(5, joined)
n._joinDeferred.addCallback(joined)

print port, knownNodes, repr(n.id)

def f():
    n.printContacts()
    reactor.callLater(10, f)
f()

reactor.run()
