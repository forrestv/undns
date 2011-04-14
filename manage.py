import subprocess
import os
import argparse
import random
import sys
import json

from twisted.internet import reactor, protocol, endpoints, defer
from twisted.protocols import basic

try:
    __version__ = subprocess.Popen(["svnversion", os.path.dirname(sys.argv[0])], stdout=subprocess.PIPE).stdout.read().strip()
except IOError:
    __version__ = "unknown"

name = "UnDNS manager (version %s)" % (__version__,)

parser = argparse.ArgumentParser(description=name)
parser.add_argument('--version', action='version', version=__version__)
parser.add_argument("-c", "--connect", metavar="ADDR:PORT",
    help="connect to server running on ADDR:PORT (default: 127.0.0.1:4000)",
    type=str, action="store", default="4000", dest="connect")

#config_default = os.path.join(os.path.expanduser('~'), '.undns')
#parser.add_argument("-c", "--config", metavar="PATH",
#    help="use configuration database at PATH (default: %s)" % (config_default,),
#    action="store", default=config_default, dest="config")

parser.add_argument(metavar="COMMAND",
    help="command to run",
    type=str, action="store", dest="command")
parser.add_argument(metavar="ARGUMENT",
    help="argument to command",
    type=str, action="store", nargs="*", dest="arguments")

args = parser.parse_args()

class RPCClient(basic.LineOnlyReceiver):
    def __init__(self):
        self.deferreds = []
        self.queue = []
    
    def send_queries(self):
        while self.queue:
            self.sendLine(self.queue.pop())
    
    def connectionMade(self):
        self.send_queries()
    
    def query(self, command, arguments):
        self.queue.append(json.dumps([command, arguments]))
        self.send_queries()
        
        df = defer.Deferred()
        self.deferreds.append(df)
        return df
    
    def lineReceived(self, line):
        self.deferreds.pop(0).callback(json.loads(line))

def parse(x):
    if ':' not in x:
        return ('127.0.0.1', int(x))
    ip, port = x.split(':')
    return ip, int(port)

host, port = parse(args.connect)

def got_response(resp):
    print repr(resp)

arguments = [open(a[1:]).read() if a.startswith('@') else a for a in args.arguments]

f = protocol.ClientFactory()
f.protocol = RPCClient
endpoints.TCP4ClientEndpoint(reactor, host, port).connect(f).addCallback(lambda rpcclient: rpcclient.query(args.command, arguments)).addCallback(got_response).addBoth(lambda _: reactor.stop())

reactor.run()
