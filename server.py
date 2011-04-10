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
import time

from Crypto import Random
rng = Random.new().read

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
    help="run a TCP+UDP authoritative dns server on PORT; you likely don't want this - this is for _the_ public nameserver",
    type=int, action="append", default=[], dest="authoritative_dns_ports")
parser.add_argument("-r", "--recursive-dns", metavar="PORT",
    help="run a TCP+UDP recursive dns server on PORT; you likely do want this - this is for clients",
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

def sleep(t):
    d = defer.Deferred()
    reactor.callLater(t, d.callback, None)
    return d


class DomainKeyDictWrapper(db.ValueDictWrapper):
    def _encode(self, addr, domain_record):
        assert addr == domain_key.get_address()
        return domain_key.to_binary()
    def _decode(self, addr, binary):
        domain_key = packet.PrivateKey.from_binary(binary)
        assert addr == domain_key.get_address()
        return domain_key

class JSONWrapper(db.ValueDictWrapper):
    def _encode(self, addr, content):
        return json.dumps(content)
    def _decode(self, addr, binary):
        return json.loads(data)

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
        self.domains = DomainKeyDictWrapper(db.safe_open_db(db_prefix + '.domains'))
        self.entries = JSONWrapper(db.safe_open_db(db_prefix + '.entries'))
        self.clock_deltas = {} # contact -> (time, offset)
        self.clock_offset = 0
    
    def joinNetwork(self, *args, **kwargs):
        node.Node.joinNetwork(self, *args, **kwargs)
        self._joinDeferred.addCallback(lambda _: reactor.callLater(0, self.joined))
    
    def joined(self):
        self.time_task()
        self.push_task()
    
    def get_my_time(self):
        return time.time() - self.clock_offset
    
    @defer.inlineCallbacks
    def time_task(self):
        while True:
            t_send = time.time()
            requests = [(peer, peer.get_time().addCallback(lambda res: (time.time(), res))) for peer in self.peers]
            results = []
            self.clock_deltas[None] = (t_send, t_send)
            for peer, request in requests:
                try:
                    t_recv, response = yield request
                    t = .5 * (t_send + t_recv)
                    self.clock_deltas[(peer.id, peer.address)] = (t, float(response))
                except:
                    traceback.print_exc()
                    continue
            
            print self.clock_deltas
            self.clock_offset = median(mine - theirs for mine, theirs in self.clock_deltas.itervalues())
            print self.clock_offset
            
            yield sleep(random.expovariate(1/10))
    
    @defer.inlineCallbacks
    def push_task(self):
        while True:
            for addr, (zone_file, ttl) in self.entries.iteritems():
                self.push_addr(addr, zone_file, ttl)
            yield sleep(random.expovariate(1/6))
    
    def push_addr(self, addr, zone_file, ttl):
        print "publishing", addr, (zone_file, ttl)
        try:
            key = self.domains[addr]
        except:
            print "MISSING KEY FOR", addr
            return
        t = self.get_my_time()
        record = packet.DomainRecord(zone_file, int(t - 5), int(math.ceil(t + ttl + 5)))
        pkt = key.encode(record)
        n.iterativeStore(packet.get_address_hash(), pkt.to_binary())
    
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        print "store", (self, key, value, originalPublisherID, age, kwargs)
        
        pkt = packet.Packet.from_binary(value)
        if packet.get_address_hash() != key:
            raise ValueError("invalid address hash")
        record = packet.get_record()
        if not record.get_start_time() < self.get_my_time() < record.get_end_time():
            raise ValueError("invalid time range")
        if not packet.verify_signature():
            raise ValueError("invalid signature")
        
        return node.Node.store(self, key, value, originalPublisherID, age, **kwargs)
    
    @node.rpcmethod
    def get_time(self):
        return time.time()

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
    
    def rpc_list_domains(self):
        return n.domains.keys()
    
    def rpc_register(self):
        domain_key = packet.PrivateKey.generate(rng)
        addr = domain_key.get_address()
        n.domains[addr] = domain_key
        return addr
    
    def rpc_update(self, addr, contents, ttl):
        if addr not in n.domains:
            return "don't have key"
        n.entries[addr] = (contents, ttl)
        n.push_addr(addr, contents, ttl)
    
    def rpc_get(self, addr):
        return n.entries[addr]
    
    def rpc_drop(self, addr):
        del n.domains[addr]
        if addr in n.entries:
            del n.entries[addr]

rpc_factory = protocol.ServerFactory()
rpc_factory.protocol = RPCProtocol
for port in args.rpc_ports:
    reactor.listenTCP(port, rpc_factory)

# global

reactor.run()
