from __future__ import division

import random
import sys
import json
import time
import traceback
import hashlib

from twisted.internet import reactor, defer, protocol, threads, task, error
from twisted.python import failure
import itertools

import pygame
d = pygame.display.set_mode((512, 512))
def get_coords(o):
    a = hash(o)
    a, x = divmod(a, 512)
    a, y = divmod(a, 512)
    return (x, y)
def circle(c, pos, r):
    pygame.draw.circle(d, c, pos, r)
def line(c, a, b):
    pygame.draw.line(d, c, a, b)
circles = []
def draw():
    for c in circles:
        circle(*c)
    pygame.display.update()
    reactor.callLater(.1, draw)
draw()

def do_work(x, difficulty, stop_flag=[False], start=0):
    for i in itertools.count(start):
        if stop_flag[0]: return
        d = json.dumps((x, i))
        if int(hashlib.sha1(d).hexdigest(), 16) % difficulty == 0:
            return d

def insort(a, x, lo=0, hi=None, key=lambda x: x):
    if lo < 0:
        raise ValueError('lo must be non-negative')
    if hi is None:
        hi = len(a)
    key_x = key(x)
    while lo < hi:
        mid = (lo + hi)//2
        if key_x < key(a[mid]):
            hi = mid
        else:
            lo = mid + 1
    a.insert(lo, x)

DEFAULT_TIMEOUT = 5#s

class RemoteNode(object):
    def __init__(self, protocol, address, id):
        self.protocol = protocol
        self.address = address
        self.id = id
    
    def distance_to_node(self, other):
        return self.distance_to_id(other.id)
    
    def distance_to_id(self, other):
        return self.id ^ other
    def __getattr__(self, attr):
        if attr.startswith("rpc_"):
            def do_rpc(*args, **kwargs):
                timeout = kwargs.pop('timeout') if 'timeout' in kwargs else DEFAULT_TIMEOUT
                if kwargs:
                    raise TypeError('%s() got an unexpected keyword argument %r' % (attr, kwargs.keys()[0]))
                
                tag = random.randrange(2**64)
                d = defer.Deferred()
                def timeout_func():
                    self.protocol.queries.pop(tag)
                    d.errback(defer.TimeoutError())
                t = reactor.callLater(timeout, timeout_func)
                
                self.protocol.queries[tag] = (d, t)
                
                self.protocol.transport.write(json.dumps((self.protocol.id, False, (tag, attr[len("rpc_"):], args))), self.address)
                
                return d
            return do_rpc
        raise AttributeError("%r object has no attribute %r" % (self.__class__.__name__, attr))

class RemoteError(Exception):
    pass

GENESIS_DIFFICULTY = 10000

class Node(protocol.DatagramProtocol):
    def __init__(self, port, bootstrap_addresses):
        #protocol.DatagramProtocol.__init__(self)
        self.peers = []
        self.contacts = {} # address -> RemoteNode()
        self.queries = {}
        self.port = port
        self.bootstrap_addresses = bootstrap_addresses
        self.id = random.randrange(2**128)
        self.seen = set()
        
        self.blocks = {} # hash -> data
        self.longest_chain_head_hash = None
        self.longest_chain_head_callbacks = []
        
        # we rely on do_work being deterministic here ...
        if self.accept(do_work((None, 0, "genesis", GENESIS_DIFFICULTY), GENESIS_DIFFICULTY)) is not None:
            raise ValueError
    
    def startProtocol(self):
        circles.append(((255, 0, 0), get_coords(self.id), 5))
        reactor.callLater(random.expovariate(1/.1), self.think)
        reactor.callLater(random.uniform(10, 12), self.try_to_do_something)
    
    def think(self):
        reactor.callLater(random.expovariate(1/.1), self.think)
        
        if self.bootstrap_addresses:
            self.add_contact(random.choice(self.bootstrap_addresses))
        
        self.ask_random_contact_for_peers()
        #print len(self.peers)
    
    @defer.inlineCallbacks
    def try_to_do_something(self):
        while True:
            previous_hash = self.longest_chain_head_hash
            if previous_hash is None:
                d = defer.Deferred()
                self.longest_chain_head_callbacks.append(d.callback)
                yield d
                continue
            previous_contents, previous_nonce = json.loads(self.blocks[previous_hash])
            previous_previous_hash, previous_pos, previous_message, previous_difficulty = previous_contents
            
            pos = previous_pos + 1
            message = random.randrange(2**64)
            difficulty = previous_difficulty + (previous_difficulty + 999) // 1000
            
            contents = previous_hash, pos, message, difficulty
            
            stop_flag = [False]
            def abort():
                stop_flag[0] = True
            self.longest_chain_head_callbacks.append(abort)
            
            print self.port, "start", pos
            
            result = yield threads.deferToThread(do_work, contents, difficulty, stop_flag, random.randrange(2**64))
            
            if result is None: # we aborted because of a new longest chain
                print self.port, "aborted", pos
                continue
            
            print self.port, "generated", pos
            
            self.rpc_gossip(None, result)
            
            d = defer.Deferred()
            reactor.callLater(random.expovariate(1/1), d.callback, None)
            yield d
    
    def add_contact(self, address, remote_id=None):
        if address in self.contacts:
            return
        if remote_id is None:
            RemoteNode(self, address, None).rpc_ping() # response will contain id and add_contact will be called
            return
        if remote_id == self.id:
            return
        rn = RemoteNode(self, address, remote_id)
        self.contacts[address] = rn
        insort(self.peers, rn, key=self.distance_to_node)
        line((self.distance_to_node(rn)/(2.**128)*255, 0, self.distance_to_node(rn)/(2.**128)*255), get_coords(self.id), get_coords(remote_id))
    
    @defer.inlineCallbacks
    def ask_random_contact_for_peers(self):
        if not self.contacts:
            return
        #c = random.choice(self.contacts.values())
        c = self.peers[0] # closest
        for address, id in (yield c.rpc_get_close_nodes(self.id, 2)):
            address = tuple(address) # list -> tuple
            self.add_contact(address, id)
    
    def distance_to_node(self, other):
        return self.distance_to_id(other.id)
    
    def distance_to_id(self, other):
        return self.id ^ other
    
    @defer.inlineCallbacks
    def datagramReceived(self, datagram, addr):
        remote_id, is_answer, contents = json.loads(datagram)
        self.add_contact(addr, remote_id)
        if is_answer:
            tag, is_error, response = contents
            d, t = self.queries.pop(tag)
            
            t.cancel()
            
            if is_error:
                d.errback(RemoteError(response))
            else:
                d.callback(response)
        else: # question
            tag, method_name, args = contents
            
            method = getattr(self, "rpc_" + method_name)
            
            try:
                v = yield method((addr, remote_id), *args)
            except Exception, e:
                is_error = True
                response = str(e)
            else:
                is_error = False
                response = v
            self.transport.write(json.dumps((self.id, True, (tag, is_error, response))), addr)
    
    def rpc_ping(self, _):
        return defer.succeed("pong")
    
    def rpc_get_contacts(self, _):
        return defer.succeed([(c.address, c.id) for c in self.contacts.itervalues()])
    
    def rpc_get_my_address(self, (address, id)):
        return defer.succeed(address)
    
    def rpc_get_close_nodes(self, _, dest, n):
        return defer.succeed([(close_peer.address, close_peer.id) for close_peer in sorted(self.peers, key=lambda peer: peer.distance_to_id(dest))[:n]])
    
    def rpc_get_longest_chain_head_hash(self, _):
        return self.longest_chain_head_hash
    
    def rpc_gossip(self, _, x):
        if _ is not None:
            address, id = _
            line((255-self.distance_to_id(id)/(2.**128)*255, 255, 255-self.distance_to_id(id)/(2.**128)*255), get_coords(self.id), get_coords(id))
            reactor.callLater(.1, line, (255-self.distance_to_id(id)/(2.**128)*255, 0, 255-self.distance_to_id(id)/(2.**128)*255), get_coords(self.id), get_coords(id))
        result = self.accept(x)
        #print self.port, "RECEIVED BLOCK"
        #print "    BLOCK:", x
        #print "    RESULT:", result
        if result is not None:
            return
        for peer in self.peers:
            peer.rpc_gossip(x)
    
    def rpc_get_block(self, hash):
        return defer.succeed(self.blocks[hash])
    
    def accept(self, block):
        try:
            res = self.accept2(block)
        except Exception, e:
            #traceback.print_exc()
            return str(e)
            #return False
        if res is not None:
            return res
    
    def accept2(self, block):
        hash = int(hashlib.sha1(block).hexdigest(), 16)
        
        if hash in self.blocks:
            return "already accepted"
        
        contents, nonce = json.loads(block)
        
        previous_hash, pos, message, difficulty = contents
        
        if hash % difficulty != 0:
            return "invalid nonce"
        
        if pos == 0:
            if previous_hash is not None:
                return "genesis block can't refer to previous..."
            
            if difficulty != GENESIS_DIFFICULTY:
                return "genesis difficulty"
        else:
            if previous_hash not in self.blocks:
                random.choice(self.peers).get_block(previous_hash).addCallback(self.accept).addCallback(print_line)
                return "chain not formed, XXX maybe use deferred ..."
            
            previous_block = self.blocks[previous_hash]
            previous_contents, previous_nonce = json.loads(previous_block)
            prevous_hash, previous_pos, previous_message, previous_difficulty = previous_contents
            
            if pos != previous_pos + 1:
                return "pos needs to advance by 1"
            
            if difficulty != previous_difficulty + (previous_difficulty + 999) // 1000:
                return "difficulty must follow pattern"
        
        self.blocks[hash] = block
        #print self.port, "received", pos
        
        if self.longest_chain_head_hash is None or pos > self.longest_chain_head_pos:
            self.longest_chain_head_hash = hash
            self.longest_chain_head_pos = pos
            cbs = self.longest_chain_head_callbacks
            self.longest_chain_head_callbacks = []
            for cb in cbs:
                cb()


def parse(x):
    ip, port = x.split(':')
    return ip, int(port)

if 0:
    last = None
    for i in xrange(100):
        port = random.randrange(49152, 65536)
        reactor.listenUDP(port, Node(port, [] if last is None else [("127.0.0.1", last)]))
        print port
        last = port

if 1:
    pool = []
    for i in xrange(1):
        main = random.randrange(49152, 65536)
        try:
            reactor.listenUDP(main, Node(main, []))
        except error.CannotListenError:
            pass
        else:
            pool.append(main)
    for i in xrange(30):
        port = random.randrange(49152, 65536)
        try:
            reactor.listenUDP(port, Node(port, [("127.0.0.1", random.choice(pool))]))
        except error.CannotListenError:
            pass
        else:
            print port

print "---"

#port = random.randrange(49152, 65536)
#reactor.listenUDP(port, Node(port, map(parse, sys.argv[1:])))
#print port

@defer.inlineCallbacks
def x():
    print (yield threads.deferToThread(do_work, "hello", 2**20))

#x()
#def print_line(x):
#    print x
#task.LoopingCall(print_line, "").start(.25)

reactor.run()
