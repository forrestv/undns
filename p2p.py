import random
import sys
import json
import time

from twisted.internet import reactor, defer, protocol
from twisted.python import failure

import pygame
d = pygame.display.set_mode((512, 512))
def get_coords(o):
    a = hash(o)
    a, x = divmod(a, 512)
    a, y = divmod(a, 512)
    return (x, y)
def circle(c, pos, r):
    pygame.draw.circle(d, c, pos, r)
    pygame.display.update()
def line(c, a, b):
    pygame.draw.line(d, c, a, b)
    pygame.display.update()


class RemoteNode(object):
    def __init__(self, protocol, address):
        self.protocol = protocol
        self.address = address
    def __getattr__(self, attr):
        if attr.startswith("rpc_"):
            def do_rpc(*args):
                tag = random.randrange(2**64)
                d = defer.Deferred()
                
                self.protocol.queries[tag] = d
                
                self.protocol.transport.write(json.dumps((self.protocol.id, False, (tag, attr[len("rpc_"):], args))), self.address)
                
                return d
            return do_rpc
        raise AttributeError("%r object has no attribute %r" % (self.__class__.__name__, attr))

class Node(protocol.DatagramProtocol):
    def __init__(self, port, bootstrap_addresses):
        #protocol.DatagramProtocol.__init__(self)
        self.contacts = {} # address -> RemoteNode()
        self.queries = {}
        self.port = port
        self.bootstrap_addresses = bootstrap_addresses
        self.id = random.randrange(2**128)
        circle((255, 0, 0), get_coords(self.id), 5)
    
    @defer.inlineCallbacks
    def add_contact(self, address, remote_id=None):
        if address in self.contacts:
            return
        if remote_id is None:
            remote_id = yield RemoteNode(self, address).rpc_ping()
        if remote_id == self.id:
            return
        line((0, (self.id^remote_id)/2.**128*255, 255), get_coords(self.id), get_coords(remote_id))
        self.contacts[address] = RemoteNode(self, address)
    
    def startProtocol(self):
        reactor.callLater(random.expovariate(5), self.think)
    
    @defer.inlineCallbacks
    def think(self):
        reactor.callLater(random.expovariate(5), self.think)
        
        if self.bootstrap_addresses:
            self.add_contact(random.choice(self.bootstrap_addresses))
        
        if self.contacts:
            c = random.choice(self.contacts.values())
            contacts = yield c.rpc_get_contacts()
            #print self.port, [x[1] for x in self.contacts.keys()], c.address[1]
            #print self.port, "contacted", c.address[1], "and got", [x[1] for x in contacts]
            #print self.port, "GOT2", contacts, self.contacts
            #print contacts
            for contact in contacts:
                contact = tuple(contact) # list -> tuple
                #print "B", contact
                self.add_contact(contact)
        
        print self.port, len(self.contacts)
    
    @defer.inlineCallbacks
    def datagramReceived(self, datagram, addr):
        
        remote_id, answer, contents = json.loads(datagram)
        self.add_contact(addr, remote_id)
        if answer:
            tag, response = contents
            self.queries.pop(tag).callback(response)
        else: # question
            tag, method_name, args = contents
            
            resp = yield getattr(self, "rpc_" + method_name)(*args)
            self.transport.write(json.dumps((self.id, True, (tag, resp))), addr)
    
    def rpc_ping(self):
        #print "pinged!"
        return defer.succeed(self.id)
    
    def rpc_get_time(self):
        return time.time()
    
    def rpc_get_contacts(self):
        return defer.succeed(self.contacts.keys())


def parse(x):
    ip, port = x.split(':')
    return ip, int(port)

last = None

for i in xrange(20):
    port = random.randrange(49152, 65536)
    reactor.listenUDP(port, Node(port, [] if last is None else [("127.0.0.1", last)]))
    print port
    last = port

print "---"

#port = random.randrange(49152, 65536)
#reactor.listenUDP(port, Node(port, map(parse, sys.argv[1:])))
#print port


reactor.run()
