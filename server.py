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
import math

from twisted.names import common, client, dns, server, error, authority
from twisted.internet import reactor, defer, protocol, threads, task, error
from twisted.python import failure
from twisted.protocols import basic
from entangled.kademlia import node, datastore

import packet
import util
import db

# DHT

def sleep(t):
    d = defer.Deferred()
    reactor.callLater(t, d.callback, None)
    return d

class DomainKeyDictWrapper(db.ValueDictWrapper):
    def _encode(self, name_hash, domain_key):
        assert name_hash == domain_key.get_name_hash()
        return domain_key.to_binary()
    def _decode(self, name_hash, binary):
        domain_key = packet.DomainKey.from_binary(binary)
        assert name_hash == domain_key.get_name_hash()
        return domain_key

class OldDictDataStore(datastore.DictDataStore):
    def __init__(self, inner):
        self._dict = inner

class UnDNSNode(node.Node):
    @property
    def peers(self):
        res = []
        for bucket in self._routingTable._buckets:
            for contact in bucket._contacts:
                res.append(contact)
        return res
    
    def __init__(self, config_db, rng, udpPort=None):
        self.config = db.PickleValueWrapper(db.SQLiteDict(config_db, 'config'))
        self.domains = db.CachingDictWrapper(DomainKeyDictWrapper(db.SQLiteDict(config_db, 'domains')))
        self.entries = db.CachingDictWrapper(db.PickleValueWrapper(db.SQLiteDict(config_db, 'entries')))
        
        self.rng = rng
        
        self.config['auth'] = rng(64)
        if udpPort is None:
            if 'port' in self.config:
                udpPort = self.config['port']
            else:
                udpPort = random.randrange(49152, 65536)
        self.config['port'] = udpPort
        
        self.clock_offset = 0
        node.Node.__init__(self, udpPort=udpPort, dataStore=OldDictDataStore(db.PickleValueWrapper(db.SQLiteDict(config_db, 'node'))))
    
    def joinNetwork(self, *args, **kwargs):
        node.Node.joinNetwork(self, *args, **kwargs)
        self._joinDeferred.addCallback(self.joined)
    
    def joined(self):
        self.time_task()
        self.push_task()
    
    def get_my_time(self):
        return time.time() - self.clock_offset
    
    @defer.inlineCallbacks
    def time_task(self):
        while True:
            t_send = time.time()
            clock_deltas = {None: (t_send, t_send)}
            for peer, request in [(peer, peer.get_time().addCallback(lambda res: (time.time(), res))) for peer in self.peers]:
                try:
                    t_recv, response = yield request
                    t = .5 * (t_send + t_recv)
                    clock_deltas[(peer.id, peer.address, peer.port)] = (t, float(response))
                except:
                    traceback.print_exc()
                    continue
            
            self.clock_offset = util.median(mine - theirs for mine, theirs in clock_deltas.itervalues())
            
            yield sleep(random.expovariate(1/100))
    
    @defer.inlineCallbacks
    def push_task(self):
        while True:
            for name_hash, (zone_file, ttl) in self.entries.iteritems():
                self.push(name_hash, zone_file, ttl)
            yield sleep(random.expovariate(1/60))
    
    def push(self, name_hash, zone_file, ttl):
        print "publishing", util.name_hash_to_name(name_hash)
        try:
            key = self.domains[name_hash]
        except KeyError:
            print "MISSING KEY FOR", util.name_hash_to_name(name_hash)
            return
        t = self.get_my_time()
        record = packet.DomainRecord(zone_file, int(math.ceil(t + ttl + 5)))
        pkt = key.encode(record, self.rng)
        assert pkt.get_name_hash() == name_hash
        return self.iterativeStore(name_hash, pkt.to_binary())
    
    @node.rpcmethod
    def store(self, key, value, originalPublisherID=None, age=0, **kwargs):
        print "store", str((util.name_hash_to_name(key), value, originalPublisherID, age, kwargs))
        # XXX maybe prefer current
        
        pkt = packet.DomainPacket.from_binary(value)
        if pkt.get_name_hash() != key:
            raise ValueError("invalid name hash")
        record = pkt.get_record()
        if not self.get_my_time() < record.get_end_time():
            raise ValueError("invalid time range")
        if not pkt.verify_signature():
            raise ValueError("invalid signature")
        record.get_zone(pkt.get_name())
        
        return node.Node.store(self, key, value, originalPublisherID, age, **kwargs)
    
    @node.rpcmethod
    def get_time(self):
        return time.time()
    
    def _republishData(self, *args):
        return defer.succeed(None)

# DNS

class UnDNSResolver(common.ResolverBase):
    def __init__(self, dht):
        common.ResolverBase.__init__(self)
        self.dht = dht
    
    @defer.inlineCallbacks
    def _lookup(self, name, cls, type, timeout):
        segs = name.split('.')
        
        print name, segs
        
        for i in reversed(xrange(len(segs))):
            seg = segs[i]
            try:
                nh = util.name_to_name_hash(seg)
            except ValueError:
                continue
            name2 = '.'.join(segs[i:])
            break
        else:
            raise dns.DomainError(name)
        
        print (nh, name2)
        
        result = yield self.dht.iterativeFindValue(nh)
        
        if isinstance(result, list):
            print result
            print 5
            raise dns.AuthoritativeDomainError(name)
        
        assert isinstance(result, dict), result
        print result
        pkt = packet.DomainPacket.from_binary(result[nh])
        
        if pkt.get_name_hash() != nh:
            print 6
            raise dns.AuthoritativeDomainError(name)
        record = pkt.get_record()
        if not self.dht.get_my_time() < record.get_end_time():
            print 7
            raise dns.AuthoritativeDomainError(name)
        if not pkt.verify_signature():
            print 8
            raise dns.AuthoritativeDomainError(name)
        
        zone = record.get_zone(name2)
        
        defer.returnValue((yield zone._lookup(name, cls, type, timeout)))

# RPC

class RPCProtocol(basic.LineOnlyReceiver):
    def lineReceived(self, line):
        method, args = json.loads(line)
        try:
            res = json.dumps(getattr(self, "rpc_" + method)(*args))
        except Exception, e:
            traceback.print_exc()
            res = json.dumps(str(e))
        self.sendLine(res)
    
    def rpc_list_domains(self):
        return map(util.name_hash_to_name, self.factory.node.domains.keys())
    
    def rpc_register(self):
        domain_key = packet.DomainKey.generate(self.factory.rng)
        self.factory.node.domains[domain_key.get_name_hash()] = domain_key
        return domain_key.get_name()
    
    def rpc_update(self, name, contents, ttl):
        ttl = float(ttl)
        name_hash = util.name_to_name_hash(name)
        if name_hash not in self.factory.node.domains:
            return "don't have key"
        self.factory.node.entries[name_hash] = (contents, ttl)
        self.factory.node.push(name_hash, contents, ttl)
    
    def rpc_get(self, name):
        name_hash = util.name_to_name_hash(name)
        return self.factory.node.entries[name_hash]
    
    def rpc_disable(self, name):
        name_hash = util.name_to_name_hash(name)
        del self.factory.node.entries[name_hash]
    
    def rpc_drop(self, name):
        name_hash = util.name_to_name_hash(name)
        if name_hash in self.factory.node.entries:
            raise ValueError("disable domain first") # XXX
        del self.factory.node.domains[name_hash]
