#!/usr/bin/python

from __future__ import division

import os
import sys
import random
import hashlib
import argparse
import subprocess
import traceback
import json
import itertools
import sqlite3
import time
import bsddb

import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server, twisted.names.error, twisted.names.authority
del twisted
from twisted import names
from twisted.internet import reactor, defer, protocol, threads, task, error
from twisted.python import failure
from twisted.protocols import basic
from entangled.kademlia import node, datastore

import packet
import util
import db

try:
    __version__ = subprocess.Popen(["svnversion", os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except IOError:
    __version__ = "unknown"

name = "UnDNS server (version %s)" % (__version__,)

parser = argparse.ArgumentParser(description=name)
parser.add_argument('--version', action='version', version=__version__)
parser.add_argument("-a", "--authoritative-dns", metavar="PORT",
    help="run an authoritative dns server on PORT; you likely don't want this - this is for _the_ public nameserver",
    type=int, action="append", default=[], dest="authoritative_dns_ports")
parser.add_argument("-r", "--recursive-dns", metavar="PORT",
    help="run a recursive dns server on PORT; you likely do want this - this is for clients",
    type=int, action="append", default=[], dest="recursive_dns_ports")
parser.add_argument("-d", "--dht-port", metavar="PORT",
    help="use UDP port PORT to connect to other DHT nodes and listen for connections (if not specified a random high port is chosen)",
    type=int, action="store", default=random.randrange(49152, 65536), dest="dht_port")
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

print name

port = args.dht_port
print "PORT:", port

db_prefix = args.config

def parse(x):
    if ':' not in x:
        return ('127.0.0.1', int(x))
    ip, port = x.split(':')
    return ip, int(port)
knownNodes = map(parse, args.dht_nodes)

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
    h = util.hash_difficulty(d)
    count = 0
    for i in itertools.count(random.randrange(2**63)):
        count += 1
        if count > 1000:
            return None
        if stop_flag[0]:
            return None
        d2 = "%i]" % i
        h2 = h.copy()
        h2.update(d2)
        if int(h2.hexdigest(), 16) % difficulty == 0:
            return d + d2

def sleep(t):
    d = defer.Deferred()
    reactor.callLater(t, d.callback, None)
    return d

GENESIS_DIFFICULTY = 100
LOOKBEHIND = 20

class Block(object):
    @classmethod
    def generate(cls, previous_hash, pos, timestamp, total_difficulty, message, difficulty):
        contents = (previous_hash, pos, timestamp, total_difficulty, message, difficulty)
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
            if result is None:
                return
            d.callback(cls(result))
        t.addBoth(f)
        return d
    def __init__(self, data):
        self.data = data
        self.hash_difficulty = int(util.hash_difficulty(data).hexdigest(), 16)
        self.hash_id = hashlib.sha1(self.data).hexdigest()
        (self.previous_hash, self.pos, self.timestamp, self.total_difficulty, self.message, self.difficulty), self.nonce = json.loads(data)
        if isinstance(self.previous_hash, unicode):
            self.previous_hash = str(self.previous_hash)

class BlockDictWrapper(object):
    # int -> Block : str -> str
    def __init__(self, inner):
        self._inner = inner
    def __len__(self):
        return len(self._inner)
    def __getitem__(self, key):
        block = Block(self._inner[key])
        if block.hash_id != key:
            print "warning: invalid block in db!"
            self._inner[key]
            raise KeyError()
        return block
    def __setitem__(self, key, value):
        if value.hash_id != key:
            raise ValueError("invalid block insertion")
        self._inner[key] = value.data
    def __contains__(self, key):
        return key in self._inner
    def __iter__(self):
        return iter(self._inner)

class UnDNSNode(node.Node):
    @property
    def peers(self):
        res = []
        for bucket in self._routingTable._buckets:
            for contact in bucket._contacts:
                res.append(contact)
        return res
    
    def __init__(self, *args, **kwargs):
        node.Node.__init__(self, *args, **kwargs)
        
        blocks_db = bsddb.hashopen(db_prefix + '.blocks2')
        task.LoopingCall(blocks_db.sync).start(5)
        self.blocks = db.CachingDictWrapper(BlockDictWrapper(blocks_db))
        
        verified_db = bsddb.hashopen(db_prefix + '.verified')
        task.LoopingCall(verified_db.sync).start(5)
        self.verified = db.CachingSetWrapper(db.SetDictWrapper(verified_db))
        
        self.referrers = {} # hash -> list of hashes
        self.requests_in_progress = set()
        
        #self.best_block = max(
        #    itertools.chain(
        #        [None],
        #        (self.blocks[block_hash] for block_hash in self.blocks if block_hash in self.verified),
        #    ),
        #    key=lambda block: 0 if block is None else block.total_difficulty,
        #)
        self.best_block = None
        self.best_block_callbacks = []
    
    def joinNetwork(self, *args, **kwargs):
        node.Node.joinNetwork(self, *args, **kwargs)
        self._joinDeferred.addCallback(lambda _: reactor.callLater(0, self.joined))
    
    def joined(self):
        self.push_task()
        self.try_to_do_something()
    
    @defer.inlineCallbacks
    def push_task(self):
        while True:
            def x(resp):
                print resp
            for peer in self.peers:
                peer.ping().addCallback(x)
            #for packet in packets:
            #    print "publishing", packet.get_address()
            #    n.iterativeStore(packet.get_address_hash(), packet.to_binary())
            yield sleep(random.expovariate(1/6))
    
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        print "store", (self, key, value, originalPublisherID, age, kwargs)
        
        packet.Packet.from_binary(value, address_hash=key) # will throw an exception if not valid
        
        return node.Node.store(self, key, value, originalPublisherID, age, **kwargs)
    
    @node.rpcmethod
    def handle_new_block(self, block_data, _rpcNodeID, _rpcNodeContact):
        try:
            self.received_block(Block(block_data), _rpcNodeContact)
        except:
            traceback.print_exc()
    
    @node.rpcmethod
    def handle_new_request(self, request_data):
        request = Request(request_data)
        if request.hash_id in self.requests:
            return
        
        # check
        
        self.requests[request.hash_id] = request
    
    def check_request(self, request):
        if request.hash_difficulty % request.difficulty != 0:
            return False
    
    @node.rpcmethod
    def get_block(self, block_hash):
        block_data = None
        if block_hash in self.blocks:
            block = self.blocks[block_hash]
            assert block.hash_id == block_hash
            block_data = block.data
        return block_data
    
    @node.rpcmethod
    def get_blocks(self, block_hash, n):
        result = []
        while True:
            if block_hash in self.requests_in_progress:
                break
            try:
                block = self.blocks[block_hash]
            except KeyError:
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
        return None if self.best_block is None else self.best_block.hash_id
    
    @node.rpcmethod
    def get_time(self):
        return time.time()
    
    def say(self, *x):
        print " " * (self.port%120), self.port, ' '.join(map(str,x))
    
    @defer.inlineCallbacks
    def try_to_do_something(self):
        while True:
            previous_block = self.best_block
            if previous_block is None:
                previous_hash = None
                pos = 0
                timestamp = int(time.time())
                message = {self.port: 1} # XXX insert self.requests
                difficulty = GENESIS_DIFFICULTY
                total_difficulty = 0 + difficulty
            else:
                previous_hash = previous_block.hash_id
                pos = previous_block.pos + 1
                timestamp = max(previous_block.timestamp, int(time.time()))
                message = dict((int(k), int(v)) for k, v in previous_block.message.iteritems()) # XXX insert self.requests
                message[self.port] = message.get(self.port, 0) + 1
            
                if pos < 25:
                    difficulty = GENESIS_DIFFICULTY
                else:
                    cur = previous_block
                    for i in xrange(LOOKBEHIND):
                        if cur.previous_hash is None:
                            break
                        cur = self.blocks[cur.previous_hash]
                    
                    # want each block to take 10 seconds
                    difficulty_sum = previous_block.total_difficulty - cur.total_difficulty
                    dt = previous_block.timestamp - cur.timestamp
                    if dt == 0:
                        dt = 1
                    difficulty = difficulty_sum * 10 // dt
                
                total_difficulty = previous_block.total_difficulty + difficulty
            
            d = Block.generate(previous_hash, pos, timestamp, total_difficulty, message, difficulty)
            def abort(d=d):
                if not d.called:
                    d.cancel()
            self.best_block_callbacks.append(abort)
            reactor.callLater(5, abort) # update timestamp
            
            try:
                result = yield d
            except defer.CancelledError:
                self.say("cancelled")
                continue # we aborted because of a new longest chain
            if result is None:
                continue
            
            self.say("generated", result.pos, result.message, result.difficulty, self.received_block(result))
    
    def received_block(self, block, from_node=None, depth=0):
      try:
        print block.data
        if block.hash_id in self.verified:
            return "already verified"
        
        if block.hash_difficulty % block.difficulty != 0:
            return "invalid nonce"
        
        if block.timestamp > time.time() + 60 * 10:
            return "block is from the future!"
        
        # this needs to change ... it should compare against all blocks, not the best verified block
        #if self.best_block is not None and block.pos < self.best_block.pos - 16:
        #    return "you lose"
        
        if block.pos == 0:
            if block.previous_hash is not None:
                return "genesis block can't refer to previous..."
            
            if block.difficulty != GENESIS_DIFFICULTY:
                return "genesis difficulty"
            
            if block.total_difficulty != block.difficulty:
                return "genesis total_difficulty"
            
            self.blocks[block.hash_id] = block
            self.referrers.setdefault(block.previous_hash, set()).add(block.hash_id)
            self.say("g_received", block.pos, block.message)
            self.verified_block(block, from_node, depth=depth + 1)
        elif block.previous_hash not in self.verified:
            self.blocks[block.hash_id] = block
            self.referrers.setdefault(block.previous_hash, set()).add(block.hash_id)
            self.say("h_received", block.pos, block.message)
            
            b = block
            while True:
                print 1
                assert b.previous_hash is not None, b.__dict__
                if b.previous_hash not in self.blocks:
                    print .5
                    if from_node is None:
                        if not self.peers:
                            print 2
                            return
                        from_node = random.choice(self.peers)
                    def got_block(datas):
                        print datas
                        self.requests_in_progress.remove(b.previous_hash)
                        for data in reversed(datas):
                            block2 = Block(data)
                            try:
                                self.received_block(block2, from_node)
                            except:
                                traceback.print_exc()
                    def got_error(fail):
                        print fail
                        self.requests_in_progress.remove(b.previous_hash)
                    if b.previous_hash in self.requests_in_progress:
                        print 3
                        print "not requesting!", block.pos
                        return "waiting on other request ..."
                    print 4
                    print "requesting", b.previous_hash
                    self.requests_in_progress.add(b.previous_hash)
                    from_node.get_blocks(b.previous_hash, 20).addCallbacks(got_block, got_error)
                    return "waiting on block.."
                b = self.blocks[b.previous_hash]
        else:
            previous_block = self.blocks[block.previous_hash]
            
            if block.pos != previous_block.pos + 1:
                return "pos needs to advance by 1"
            
            if block.timestamp < previous_block.timestamp:
                return "timestamp must not decrease"
            
            if block.total_difficulty != previous_block.total_difficulty + block.difficulty:
                return "genesis total_difficulty"
            
            if block.pos < 25:
                difficulty = GENESIS_DIFFICULTY
            else:
                difficulty_sum = 0
                cur = previous_block
                for i in xrange(LOOKBEHIND):
                    if cur.previous_hash is None:
                        break
                    difficulty_sum += cur.difficulty
                    cur = self.blocks[cur.previous_hash]
                
                # want each block to take 10 seconds
                difficulty = difficulty_sum * 10 // (previous_block.timestamp - cur.timestamp)
            
            if block.difficulty != difficulty:
                return "difficulty must follow pattern (%i != %i)" % (block.difficulty, difficulty)
            
            self.blocks[block.hash_id] = block
            self.referrers.setdefault(block.previous_hash, set()).add(block.hash_id)
            self.say("i_received", block.pos, block.difficulty, block.timestamp, block.message)
            self.verified_block(block, depth=depth + 1)
      except:
        traceback.print_exc()
    
    def verified_block(self, block, from_node=None, depth=0):
        assert block.previous_hash is None or block.previous_hash in self.verified
        assert block.hash_id in self.blocks
        
        self.verified.add(block.hash_id)
        self.say("verified", block.pos, block.message)
        
        for referring_block_hash_id in self.referrers.pop(block.hash_id, set()):
            referring_block = self.blocks[referring_block_hash_id]
            # no from_node here because we might send the newly released block back
            if depth > 100:
                reactor.callLater(0, self.received_block, referring_block)
            else:
                self.received_block(referring_block, depth=depth+1)
        
        for peer in self.peers:
            if peer == from_node:
                continue
            self.say("spreading to", peer.port)
            peer.handle_new_block(block.data).addErrback(lambda fail: None)
        
        if self.best_block is None or block.total_difficulty > self.best_block.total_difficulty:
            self.say("new best", block.pos, block.message)
            self.best_block = block
            
            cbs = self.best_block_callbacks
            self.best_block_callbacks = []
            for cb in cbs:
                cb()
    
    def __del__(self):
        print "DELETED"

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
for port in args.authoritative_dns_ports:
    reactor.listenTCP(port, authoritative_dns)
    reactor.listenUDP(port, names.dns.DNSDatagramProtocol(authoritative_dns))

recursive_dns = names.server.DNSServerFactory(authorities=[resolver], clients=[names.client.createResolver()])
for port in args.recursive_dns_ports:
    reactor.listenTCP(port, recursive_dns)
    reactor.listenUDP(port, names.dns.DNSDatagramProtocol(recursive_dns))

# RPC

class RPCProtocol(basic.LineOnlyReceiver):
    def lineReceived(self, line):
        method, args = json.loads(line)
        try:
            res = json.dumps(getattr(self, "rpc_" + method)(*args))
        except Exception, e:
            res = json.dumps(str(e))
        self.sendLine(res)
    
    def rpc_help(self):
        return "hi!"
    
    def rpc_get_graph(self):
        self = n
        res = []
        if self.best_block is not None:
            cur = self.best_block
            while True:
                res.append((cur.timestamp, cur.difficulty))
                if cur.previous_hash is None:
                    break
                cur = self.blocks[cur.previous_hash]
        return "{" + ', '.join("{%i, %i}" % x for x in res[::-1]) + "}"
    
    def rpc_register(self, name, contents, ttl):
        # update time and expiry time are different
        a
    
    def rpc_update(self, name, contents, ttl):
        a
    
    def rpc_transfer(self, name, dest):
        # change key, contents remain
        a
    
    def rpc_drop(self, name):
        a

rpc_factory = protocol.ServerFactory()
rpc_factory.protocol = RPCProtocol
for port in args.rpc_ports:
    reactor.listenTCP(port, rpc_factory)

# global

reactor.run()
