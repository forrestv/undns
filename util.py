import itertools

from Crypto.PublicKey import RSA

# hash functions

from hashlib import sha256, sha512

def get(name):
    from hashlib import new
    try:
        parent = new(name)
    except:
        raise ValueError("openssl does not have hash algorithm")
    def construct(string=''):
        h = parent.copy()
        if string:
            h.update(string)
        return h
    return construct

try:
    ripemd160 = get("ripemd160")
except ValueError:
    from Crypto.Hash import RIPEMD160 as ripemd160

try:
    whirlpool = get('whrlpool')
except ValueError:
    from whirlpool import Whirlpool as whirlpool

assert sha256("hello world").hexdigest() == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
assert ripemd160("hello world").hexdigest() == "98c615784ccb5fe5936fbc0cbe9dfdb408d92f0f"
assert whirlpool("hello world").hexdigest() == "8d8309ca6af848095bcabaf9a53b1b6ce7f594c1434fd6e5177e7e5c20e76cd30936d8606e7f36acbef8978fea008e6400a975d51abe6ba4923178c7cf90c802"

# encoding

default_alphabet = ''.join(chr(i) for i in xrange(256))

def natural_to_string(n, alphabet=default_alphabet, min_width=1):
    if n < 0:
        raise ValueError()
    res = []
    while n:
        n, f = divmod(n, len(alphabet))
        res.append(alphabet[f])
    return ''.join(res[::-1]).rjust(min_width, alphabet[0])

def string_to_natural(s, alphabet=default_alphabet):
    return sum(alphabet.index(char) * len(alphabet)**i for i, char in enumerate(reversed(s)))

# key storage

def key_to_tuple(k):
    if k.has_private():
        k = k.key
        return (k.n, k.e, k.d, k.p, k.q, k.u)
    else:
        k = k.key
        return (k.n, k.e)

def tuple_to_key(t):
    return RSA.construct(map(long, t))

def key_to_string(k):
    # for hashing
    return " ".join(map(str, key_to_tuple(k)))

# hashing

def mix_naturals(a, b):
    acc = 0
    for pos in itertools.count():
        if a < 2**pos:
            break
        if a & 2**pos:
            acc |= 2**(2*pos)
    for pos in itertools.count():
        if b < 2**pos:
            break
        if b & 2**pos:
            acc |= 2**(2*pos+1)
    return acc

def mix_strings(a, b):
    return natural_to_string(mix_naturals(string_to_natural(a), string_to_natural(b)), min_width=len(a) + len(b))

def hash_address(x):
    # for addresses
    # limited based on seen length
    # if this is broken, people can gain control over randomly-generated addresses by providing a forged public key with the appropriate hash (along with node IDs)
    # generating a valid public key, should be difficult, even so
    return sha256(x).digest()

def hash_pow(x):
    # for block difficulty checking
    # not limited
    # if this is broken, people have an advantage in generating blocks, possibly compromising the network
    # merging the bits of two hash algorithms prevents breaking of one algorithm from resulting in more than a 2x speed gain
    return mix_strings(sha256(x).digest(), whirlpool(x).digest()[:256//8])

def hash_block(x):
    # for block references
    # limited by storage space for chain
    # if this is broken, people can change the history of the block chain
    return ripemd160(x).digest() + sha256(x).digest()

# also need for block reference

def hash_sign(x):
    # for signing
    # if this is broken, people can forge DHT node IDs and gain control over randomly-generated addresses by generating messages that fit a past signature
    return whirlpool(x).digest() + sha512(x).digest()

dns_alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'

def key_to_name(k):
    assert not k.has_private()
    hash = int(sha256(key_to_string(k)).hexdigest(), 16)
    return natural_to_string(hash, dns_alphabet)

def key_to_address(k):
    return key_to_name(k) + ".undns.forre.st"
