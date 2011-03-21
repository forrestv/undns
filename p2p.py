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
d = None
d = pygame.display.set_mode((512, 512))
def get_coords(o):
    a = hash(o)
    a, x = divmod(a, 512)
    a, y = divmod(a, 512)
    return (x, y)
def circle(c, pos, r):
    if d is None: return
    pygame.draw.circle(d, c, pos, r)
def line(c, a, b):
    if d is None: return
    pygame.draw.line(d, c, a, b)
circles = []
def draw():
    if d is None: return
    for c in circles:
        circle(*c)
    pygame.display.update()
    reactor.callLater(.1, draw)
draw()

def do_work(x, difficulty, stop_flag):
    for i in itertools.count(random.randrange(2**63)):
        if stop_flag[0]:
            return None
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

DEFAULT_TIMEOUT = 10#s

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
                
                tag = random.randrange(2**160)
                d = defer.Deferred()
                def timeout_func():
                    d, t = self.protocol.queries.pop(tag)
                    d.errback(defer.TimeoutError())
                t = reactor.callLater(timeout, timeout_func)
                
                self.protocol.queries[tag] = (d, t)
                
                self.protocol.transport.write(json.dumps((self.protocol.id, False, (tag, attr[len("rpc_"):], args))), self.address)
                
                return d
            return do_rpc
        raise AttributeError("%r object has no attribute %r" % (self.__class__.__name__, attr))

class RemoteError(Exception):
    pass

GENESIS_DIFFICULTY = 10

class Block(object):
    @classmethod
    def generate(cls, previous_hash, pos, message, difficulty):
        contents = (previous_hash, pos, message, difficulty)
        stop_flag = [False]
        def abort(d):
            stop_flag[0] = True
        d = defer.Deferred(abort)
        t = threads.deferToThread(do_work, contents, difficulty, stop_flag)
        def f(result):
            if stop_flag[0]:
                return
            d.callback(cls(result))
        t.addBoth(f)
        return d
    def __init__(self, data):
        self.data = data
        self.hash = int(hashlib.sha1(data).hexdigest(), 16)
        (self.previous_hash, self.pos, self.message, self.difficulty), nonce = json.loads(data)

tags = set()

class Node(protocol.DatagramProtocol):
    
    # characteristics
    
    def distance_to_node(self, other):
        return self.distance_to_id(other.id)
    
    def distance_to_id(self, other_id):
        return self.id ^ other_id
    
    # initialization
    
    def __init__(self, port, bootstrap_addresses):
        #protocol.DatagramProtocol.__init__(self)
        self.peers = []
        self.contacts = {} # (address, id) -> RemoteNode()
        self.queries = {}
        self.port = port
        self.bootstrap_addresses = bootstrap_addresses
        self.id = random.randrange(2**160)
        self.seen = set()
        
        self.blocks = {} # hash -> data
        self.verified = set() # hashes of blocks that can be tracked to a genesis block
        self.referrers = {} # hash -> list of hashes
        self.best_block = None
        self.best_block_callbacks = []
    
    def startProtocol(self):
        circles.append(((255, 0, 0), get_coords(self.id), 5))
        self.think()
        self.try_to_do_something()
    
    # utility functions
    
    def say(self, *x):
        print " " * (self.port%200), self.port, ' '.join(map(str,x))
    
    def think(self):
        if self.bootstrap_addresses:
            self.add_contact(random.choice(self.bootstrap_addresses))
        self.ask_random_contact_for_peers()
        
        reactor.callLater(random.expovariate(1/1), self.think)
    
    @defer.inlineCallbacks
    def try_to_do_something(self):
        while True:
            previous_block = self.best_block
            if previous_block is None:
                previous_hash = None
                pos = 0
                message = [self.port]
                difficulty = GENESIS_DIFFICULTY
            else:
                previous_hash = previous_block.hash
                pos = previous_block.pos + 1
                message = previous_block.message + [self.port]
                difficulty = previous_block.difficulty + (previous_block.difficulty + 999) // 1000
            
            d = Block.generate(previous_hash, pos, message, difficulty)
            def abort(d=d):
                if not d.called:
                    d.cancel()
            self.best_block_callbacks.append(abort)
            
            try:
                result = yield d
            except defer.CancelledError:
                continue # we aborted because of a new longest chain
            
            self.say("generated", result.message)
            
            self.received_block(result, self)
            
            d2 = defer.Deferred()
            reactor.callLater(random.expovariate(1/3), d2.callback, "pineapple")
            yield d2
            del d2
    
    def received_block(self, block, from_node=None):
        if block.hash in self.verified:
            return "already verified"
        
        if block.hash % block.difficulty != 0:
            return "invalid nonce"
        
        if self.best_block is not None and block.pos < self.best_block.pos - 16:
            return "you lose"
        
        if block.pos == 0:
            if block.previous_hash is not None:
                return "genesis block can't refer to previous..."
            
            if block.difficulty != GENESIS_DIFFICULTY:
                return "genesis difficulty"
            
            self.blocks[block.hash] = block
            self.verified_block(block, from_node)
        else:
            if block.previous_hash not in self.blocks or block.previous_hash not in self.verified:
                self.blocks[block.hash] = block
                
                self.referrers.setdefault(block.hash, []).append(block)
                if from_node is None:
                    from_node = random.choice(self.peers)
                def got_block(data):
                    if data is None: return
                    self.received_block(Block(data))
                from_node.rpc_get_block(block.previous_hash).addCallback(got_block)
                
                return "chain not formed, XXX maybe use deferred ..."
            else:
                previous_block = self.blocks[block.previous_hash]
                
                if block.pos != previous_block.pos + 1:
                    return "pos needs to advance by 1"
                
                if block.difficulty != previous_block.difficulty + (previous_block.difficulty + 999) // 1000:
                    return "difficulty must follow pattern"
                
                self.blocks[block.hash] = block
                self.verified_block(block)
    
    def verified_block(self, block, from_node=None):
        assert block.hash in self.blocks
        
        self.verified.add(block.hash)
        
        for referring_block in self.referrers.pop(block.hash, []):
            self.received_block(referring_block) # no from_node here because we might send the newly released block back
        
        for peer in self.peers:
            if peer == from_node:
                continue
            self.say("spreading to", peer.address[1])
            peer.rpc_gossip(block.data)
        
        if self.best_block is None or block.pos > self.best_block.pos:
            self.best_block = block
            
            cbs = self.best_block_callbacks
            self.best_block_callbacks = []
            for cb in cbs:
                cb()
    
    def add_contact(self, address, remote_id=None):
        if remote_id is None:
            RemoteNode(self, address, None).rpc_ping() # response will contain id and add_contact will be called
            return
        if remote_id == self.id:
            return
        if (address, remote_id) in self.contacts:
            return self.contacts[(address, remote_id)]
        rn = RemoteNode(self, address, remote_id)
        self.contacts[(address, remote_id)] = rn
        insort(self.peers, rn, key=self.distance_to_node)
        line((self.distance_to_node(rn)/(2.**128)*255, 0, self.distance_to_node(rn)/(2.**128)*255), get_coords(self.id), get_coords(remote_id))
        @defer.inlineCallbacks
        def f(his_hash):
            if his_hash is None:
                return
            if his_hash in self.blocks:
                return
            block = Block((yield rn.rpc_get_block(his_hash)))
            if block is None: return # shouldn't happen, ever ...
            self.received_block(block, rn)
        rn.rpc_get_best_block_hash().addCallback(f)
        return rn
    
    @defer.inlineCallbacks
    def ask_random_contact_for_peers(self):
        if not self.peers:
            return
        c = random.choice(self.peers[:5]) # closest
        for address, id in (yield c.rpc_get_close_nodes(self.id, 2)):
            address = tuple(address) # list -> tuple
            self.add_contact(address, id)
    
    @defer.inlineCallbacks
    def get_time_offset(self, timeout=DEFAULT_TIMEOUT):
        nodes = random.sample(self.peers, min(6, len(self.peers)))
        calls = [node.rpc_get_time(timeout=timeout).addCallback(lambda other_time: (time.time(), other_time)) for node in nodes]
        begin = time.time()
        results = [0]
        for call in calls:
            try:
                ts, other_time = yield call
            except:
                continue
            results.append((begin+ts)/2 - other_time)
        print results
        defer.returnValue(median(results))
    
    # network
    
    @defer.inlineCallbacks
    def datagramReceived(self, datagram, addr):
        #if random.randrange(100) == 0:
        #    return # randomly drop packets
        #print datagram, addr
        
        remote_id, is_answer, contents = json.loads(datagram)
        rn = self.add_contact(addr, remote_id)
        if is_answer:
            tag, is_error, response = contents
            try:
                d, t = self.queries.pop(tag)
            except KeyError:
                return
            
            t.cancel()
            
            #print self.port, tag, repr(response)
            if tag in tags:
                print "AHHHHHHHHHHHHH"
            tags.add(tag)
            if is_error:
                d.errback(RemoteError(response))
            else:
                d.callback(response)
        else: # question
            tag, method_name, args = contents
            
            method = getattr(self, "rpc_" + method_name)
            
            try:
                v = yield method((addr, remote_id, rn), *args)
            except Exception, e:
                is_error = True
                response = str(e)
            else:
                is_error = False
                response = v
            self.transport.write(json.dumps((self.id, True, (tag, is_error, response))), addr)
    
    # RPCs
    
    def rpc_ping(self, _):
        return defer.succeed("pong")
    
    def rpc_get_contacts(self, _):
        return defer.succeed([(c.address, c.id) for c in self.peers])
    
    def rpc_get_my_address(self, (address, id, node)):
        return defer.succeed(address)
    
    def rpc_get_close_nodes(self, _, dest, n):
        return defer.succeed([(close_peer.address, close_peer.id) for close_peer in sorted(self.peers, key=lambda peer: peer.distance_to_id(dest))[:n]])
    
    def rpc_get_best_block_hash(self, _):
        if self.best_block is None:
            return defer.succeed(None)
        return defer.succeed(self.best_block.hash)
    
    def rpc_gossip(self, (address, id, node), x):
        line((255-self.distance_to_id(id)/(2.**128)*255, 255, 255-self.distance_to_id(id)/(2.**128)*255), get_coords(self.id), get_coords(id))
        reactor.callLater(.1, line, (255-self.distance_to_id(id)/(2.**128)*255, 0, 255-self.distance_to_id(id)/(2.**128)*255), get_coords(self.id), get_coords(id))
        
        self.received_block(Block(x), node)
        
        return defer.succeed(None)
    
    def rpc_get_block(self, _, hash):
        if hash in self.blocks:
            return defer.succeed(self.blocks[hash].data)
        else:
            return defer.succeed(None)
    
    def rpc_get_time(self, _):
        return defer.succeed(time.time())

def median(x):
    # don't really need a complex algorithm here
    y = sorted(x)
    left = (len(y) - 1)//2
    right = len(y)//2
    return (y[left] + y[right])/2

def parse(x):
    ip, port = x.split(':')
    return ip, int(port)

if 0:
    last = None
    for i in xrange(5):
        port = random.randrange(49152, 65536)
        reactor.listenUDP(port, Node(port, [] if last is None else [("127.0.0.1", last)]))
        print port
        last = port


def add_node(knowns=[]):
    while True:
        port = random.randrange(49152, 65536)
        try:
            reactor.listenUDP(port, Node(port, [("127.0.0.1", x) for x in knowns]))
        except error.CannotListenError:
            pass
        else:
            return port

if 0:
    pool = []
    task.LoopingCall(lambda: pool.append(add_node(random.sample(pool, 1) if pool else []))).start(13)

pool = []
for i in xrange(3):
    reactor.callLater(10*i, lambda: pool.append(add_node(random.sample(pool, 1) if pool else [])))



print "---"

#port = random.randrange(49152, 65536)
#reactor.listenUDP(port, Node(port, map(parse, sys.argv[1:])))
#print port

#@defer.inlineCallbacks
#def x():
#    print (yield threads.deferToThread(do_work, "hello", 2**20))
#x()

def print_line(x):
    print x
#task.LoopingCall(print_line, "").start(.25)

reactor.run()
