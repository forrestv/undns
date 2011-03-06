import twisted.names.common, twisted.names.client, twisted.names.dns, twisted.names.server
del twisted

from twisted import names
from twisted.internet import reactor, defer
from twisted.python import failure

class Mine(names.common.ResolverBase):
    def _lookup(self, name, cls, type, timeout):
        if not name.endswith('.undns.forre.st'):
            return defer.fail(failure.Failure(names.dns.DomainError(name)))
        name2 = name[:-len('.undns.forre.st')]
        print name2, names.dns.QUERY_CLASSES[cls], names.dns.QUERY_TYPES[type], timeout
        return defer.fail(failure.Failure(names.dns.AuthoritativeDomainError(name)))

f = names.server.DNSServerFactory(authorities=[Mine()], clients=[names.client.createResolver()], verbose=1000)

reactor.listenTCP(53, f)
reactor.listenUDP(53, names.dns.DNSDatagramProtocol(f))

reactor.run()
