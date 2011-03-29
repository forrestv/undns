#!/usr/bin/python

import os
import sys
import random
import hashlib
import optparse
import subprocess
import json
import itertools

import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server, twisted.names.error, twisted.names.authority
del twisted
from twisted import names
from twisted.internet import reactor, defer, protocol, threads, task, error
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
    help="run an authoritative dns server on PORT; you likely don't want this - this is for _the_ public nameserver",
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

def median(x):
    # don't really need a complex algorithm here
    y = sorted(x)
    left = (len(y) - 1)//2
    right = len(y)//2
    return (y[left] + y[right])/2

def do_work(x, difficulty, stop_flag):
    d = "[%s, " % json.dumps(x)
    h = hashlib.sha256(d)
    for i in itertools.count(random.randrange(2**63)):
        if stop_flag[0]:
            return None
        d2 = "%i]" % i
        h2 = h.copy()
        h2.update(d2)
        if int(h2.hexdigest(), 16) % difficulty == 0:
            return d + d2

GENESIS_DIFFICULTY = 400000

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
            if isinstance(result, failure.Failure):
                return result
            if stop_flag[0]:
                return
            d.callback(cls(result))
        t.addBoth(f)
        return d
    def __init__(self, data):
        self.data = data
        self.hash = int(hashlib.sha256(data).hexdigest(), 16)
        (self.previous_hash, self.pos, self.message, self.difficulty), self.nonce = json.loads(data)

class UnDNSNode(node.Node):
    def __init__(self, *args, **kwargs):
        node.Node.__init__(self, *args, **kwargs)
        
        print 1
        
        self.blocks = {} # hash -> data
        self.verified = set() # hashes of blocks that can be tracked to a genesis block
        self.referrers = {} # hash -> list of hashes
        self.best_block = None
        self.best_block_callbacks = []
    
    def joinNetwork(self, *args, **kwargs):
        node.Node.joinNetwork(self, *args, **kwargs)
        
        def store(*args):
            print "store"
            for packet in packets:
                print "publishing", packet.get_address()
                n.iterativeStore(packet.get_address_hash(), packet.to_binary())
            reactor.callLater(13.23324141, store)
        self._joinDeferred.addCallback(store)
        print "aaa"
        def start(*args):
            self.try_to_do_something()
        self._joinDeferred.addCallback(start)
    
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        print "store", (self, key, value, originalPublisherID, age, kwargs)
        
        packet.Packet.from_binary(value, address_hash=key) # will throw an exception if not valid
        
        return node.Node.store(self, key, value, originalPublisherID, age, **kwargs)
    
    @node.rpcmethod
    def handle_new_block(self, block, **kwargs):
        self.received_block(Block(block_data), node)
    
    @node.rpcmethod
    def get_block(self, block_hash):
        block_data = None
        if block_hash in self.blocks:
            block = self.blocks[block_hash]
            assert block.hash == block_hash
            block_data = block.data
        return block_data
    
    @node.rpcmethod
    def rpc_get_blocks(self, block_hash, n):
        result = []
        while True:
            try:
                block = self.blocks[block_hash]
            except KeyError:
                break
            if block is None:
                break
            result.append(block.data)
            if len(result) >= n:
                break
            block_hash = block.previous_hash
            if block_hash is None:
                break
        return result
    
    @node.rpcmethod
    def get_best_block_hash(self):
        best_block_hash = None
        if self.best_block is not None:
            best_block_hash = self.best_block.hash
        return defer.succeed(best_block_hash)
    
    @node.rpcmethod
    def get_time(self):
        return time.time()
    
    def say(self, *x):
        print " " * (self.port%120), self.port, ' '.join(map(str,x))
    
    @defer.inlineCallbacks
    def try_to_do_something(self):
        while True:
            print "hello"
            previous_block = self.best_block
            if previous_block is None:
                previous_hash = None
                pos = 0
                message = {self.port: 1}
                difficulty = GENESIS_DIFFICULTY
            else:
                previous_hash = previous_block.hash
                pos = previous_block.pos + 1
                message = dict((int(k), int(v)) for k, v in previous_block.message.iteritems())
                message[self.port] = message.get(self.port, 0) + 1
                difficulty = previous_block.difficulty + 1 # (previous_block.difficulty + 999) // 1000
            print 1
            d = Block.generate(previous_hash, pos, message, difficulty)
            def abort(d=d):
                if not d.called:
                    d.cancel()
            self.best_block_callbacks.append(abort)
            print 2
            try:
                result = yield d
            except defer.CancelledError:
                self.say("cancelled")
                continue # we aborted because of a new longest chain
            
            self.say("generated", result.pos, result.message, self.received_block(result, self))
            
            
            
            #d2 = defer.Deferred()
            #reactor.callLater(random.expovariate(1/3), d2.callback, "pineapple")
            #yield d2
            #del d2
    
    def received_block(self, block, from_node=None, depth=0):
        if block.hash in self.verified:
            return "already verified"
        
        if block.hash % block.difficulty != 0:
            return "invalid nonce"
        
        # this needs to change ... it should compare against all blocks, not the best verified block
        #if self.best_block is not None and block.pos < self.best_block.pos - 16:
        #    return "you lose"
        
        if block.pos == 0:
            if block.previous_hash is not None:
                return "genesis block can't refer to previous..."
            
            if block.difficulty != GENESIS_DIFFICULTY:
                return "genesis difficulty"
            
            self.blocks[block.hash] = block
            self.referrers.setdefault(block.previous_hash, set()).add(block)
            self.say("g_received", block.pos, block.message)
            self.verified_block(block, from_node, depth=depth + 1)
        elif block.previous_hash not in self.verified:
            self.blocks[block.hash] = block
            self.referrers.setdefault(block.previous_hash, set()).add(block)
            self.say("h_received", block.pos, block.message)
            
            b = block
            while True:
                assert b.previous_hash is not None
                if b.previous_hash not in self.blocks:
                    if from_node is None:
                        if not self.peers:
                            return
                        from_node = random.choice(self.peers)
                    def got_block(datas):
                        print datas
                        self.blocks.pop(b.previous_hash)
                        for data in reversed(datas):
                            block2 = Block(data)
                            self.received_block(block2)
                    def got_error(fail):
                        self.blocks.pop(b.previous_hash)
                        print fail
                    self.blocks[b.previous_hash] = None
                    print "requesting block before", b.pos
                    from_node.rpc_get_blocks(b.previous_hash, 20, timeout=5).addCallbacks(got_block, got_error)
                    return "waiting on block.."
                b = self.blocks[b.previous_hash]
                if b is None:
                    return # in progress
        else:
            previous_block = self.blocks[block.previous_hash]
            
            if block.pos != previous_block.pos + 1:
                return "pos needs to advance by 1"
            
            if block.difficulty != previous_block.difficulty + 1: #(previous_block.difficulty + 999) // 1000:
                return "difficulty must follow pattern"
            
            self.blocks[block.hash] = block
            self.referrers.setdefault(block.previous_hash, set()).add(block)
            self.say("i_received", block.pos, block.message)
            self.verified_block(block, depth=depth + 1)
    
    def verified_block(self, block, from_node=None, depth=0):
        assert block.hash in self.blocks
        
        self.verified.add(block.hash)
        self.say("verified", block.pos, block.message)
        
        for referring_block in self.referrers.pop(block.hash, set()):
            if depth > 100:
                reactor.callLater(0, self.received_block, referring_block) # no from_node here because we might send the newly released block back
            else:
                self.received_block(referring_block, depth=depth+1)
        
        for peer in self.peers:
            if peer == from_node:
                continue
            self.say("spreading to", peer.address[1])
            peer.rpc_gossip(block.data).addErrback(lambda fail: None)
        
        if self.best_block is None or block.pos > self.best_block.pos:
            self.say("new best", block.pos, block.message)
            self.best_block = block
            
            cbs = self.best_block_callbacks
            self.best_block_callbacks = []
            for cb in cbs:
                cb()

n = UnDNSNode(udpPort=port, dataStore=dataStore)
n.joinNetwork(knownNodes)

print "ID:", n.id.encode('hex')

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
        
        name_hash = hashlib.sha256(name_alone).digest()
        
        #print name, names.dns.QUERY_CLASSES[cls], names.dns.QUERY_TYPES[type], timeout
        
        def callback(result):
            if isinstance(result, list):
                print result
                return defer.fail(failure.Failure(names.dns.AuthoritativeDomainError(name)))
            
            assert isinstance(result, dict), result
            packet = packet.Packet.from_binary(result[name_hash])
            
            if packet.get_address() != name_alone:
                return defer.fail(failure.Failure(names.dns.AuthoritativeDomainError(name)))
            
            return packet.get_zone()._lookup(name, cls, type, timeout)
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
