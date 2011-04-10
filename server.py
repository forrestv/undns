#!/usr/bin/python

from __future__ import division

import os
import sys
import random
import hashlib
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


# DHT


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
    
    def __init__(self, rng, db_prefix, udpPort):
        self.rng = rng
        dbFilename = '/tmp/undns%i.db' % (udpPort,)
        if os.path.isfile(dbFilename):
            os.remove(dbFilename)
        dataStore = datastore.SQLiteDataStore(dbFile=dbFilename)
        node.Node.__init__(self, udpPort=udpPort, dataStore=dataStore)
        self.domains = db.CachingDictWrapper(DomainKeyDictWrapper(db.safe_open_db(db_prefix + '.domains')))
        self.entries = db.CachingDictWrapper(JSONWrapper(db.safe_open_db(db_prefix + '.entries')))
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
                    self.clock_deltas[(peer.id, peer.address, peer.port)] = (t, float(response))
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
        pkt = key.encode(record, self.rng)
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
    
    @defer.inlineCallbacks
    def get_zone(self, address):
        a

class UnDNS(object):
    def __init__(self, dht_port): pass


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
            print result.keys()
            packet = packet.Packet.from_binary(result[name_hash])
            
            if packet.get_address() != name_alone:
                return defer.fail(failure.Failure(names.dns.AuthoritativeDomainError(name)))
            
            return packet.get_zone()._lookup(name, cls, type, timeout)
        return self.dht.iterativeFindValue(name_hash).addCallback(callback)

# RPC

class RPCProtocol(basic.LineOnlyReceiver):
    def __init__(self, node, rng):
        self.node = node
        self.rng = rng
    
    def lineReceived(self, line):
        method, args = json.loads(line)
        try:
            res = json.dumps(getattr(self, "rpc_" + method)(*args))
        except Exception, e:
            traceback.print_exc()
            res = json.dumps(str(e))
        self.sendLine(res)
    
    def rpc_list_domains(self):
        return self.node.domains.keys()
    
    def rpc_register(self):
        domain_key = packet.DomainKey.generate(self.rng)
        addr = domain_key.get_address()
        self.node.domains[addr] = domain_key
        return addr
    
    def rpc_update(self, addr, contents, ttl):
        if addr not in self.node.domains:
            return "don't have key"
        self.node.entries[addr] = (contents, ttl)
        self.node.push_addr(addr, contents, ttl)
    
    def rpc_get(self, addr):
        return self.node.entries[addr]
    
    def rpc_drop(self, addr):
        del self.node.domains[addr]
        if addr in self.node.entries:
            del self.node.entries[addr]
