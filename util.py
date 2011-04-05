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
    try:
        import mhash
    except ImportError:
        import whirlpool as _whirlpool
        class whirlpool(object):
            def __init__(self, data=""):
                self._data = data
            def update(self, x):
                self._data += x
            def copy(self):
                return whirlpool(self._data)
            def digest(self):
                return _whirlpool.Whirlpool(self._data).digest()
            def hexdigest(self):
                return self.digest().encode('hex')
    else:
        # mhash is broken
        class whirlpool(object):
            def __init__(self, data=""):
                self._data = data
            def update(self, x):
                self._data += x
            def copy(self):
                return whirlpool(self._data)
            def digest(self):
                return mhash.MHASH(mhash.MHASH_WHIRLPOOL, self._data).digest()
            def hexdigest(self):
                return self.digest().encode('hex')

def test_hash(func, inp, out):
    assert func(inp).hexdigest() == out, (func(inp).hexdigest(), out)
    s = func(inp[:len(inp)//2])
    s.update(inp[len(inp)//2:])
    assert s.hexdigest() == out, (s.hexdigest(), out)
test_hash(sha256, "hello world", "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
test_hash(ripemd160, "hello world", "98c615784ccb5fe5936fbc0cbe9dfdb408d92f0f")
test_hash(whirlpool, "hello world", "8d8309ca6af848095bcabaf9a53b1b6ce7f594c1434fd6e5177e7e5c20e76cd30936d8606e7f36acbef8978fea008e6400a975d51abe6ba4923178c7cf90c802")

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

# for addresses
# limited based on seen length
# if this is broken, people can gain control over randomly-generated addresses by providing a forged public key with the appropriate hash (along with node IDs)
# generating a valid public key, should be difficult, even so
hash_address = sha256

def make_hash_class(funcs, interleave):
    class hash_class(object):
        def __init__(self, x=None, _states=None):
            if _states is None:
                self.states = [func() for func in funcs]
            else:
                self.states = [state.copy() for state in _states]
            if x is not None:
                self.update(x)
        def update(self, x):
            for state in self.states:
                state.update(x)
        def copy(self):
            return self.__class__(_states=[state.copy() for state in self.states])
        def digest(self):
            if interleave:
                ds = [state.digest() for state in self.states]
                l = min(len(d) for d in ds)
                return reduce(mix_strings, (d[:l] for d in ds))
            else:
                return ''.join(state.digest() for state in self.states)
        def hexdigest(self):
            return self.digest().encode('hex')
    hash_class.digest_size = len(hash_class().digest())
    return hash_class

# for block difficulty checking
# not limited
# if this is broken, people have an advantage in generating blocks, possibly compromising the network
# interleaving the bits of two hash algorithms prevents breaking of one algorithm from resulting in more than a 2x speed gain
hash_difficulty = make_hash_class([whirlpool, sha256], interleave=True)

# for block references
# limited by storage space for chain
# if this is broken, people can change the history of the block chain
hash_block = make_hash_class([ripemd160, sha256], interleave=False)

# for signing
# if this is broken, people can forge DHT node IDs and gain control over randomly-generated addresses by generating messages that fit a past signature
hash_sign = make_hash_class([whirlpool, ripemd160, sha256], interleave=False)

# names

dns_alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'

def key_to_name(k):
    assert not k.has_private()
    hash = int(sha256(key_to_string(k)).hexdigest(), 16)
    return natural_to_string(hash, dns_alphabet)

def key_to_address(k):
    return key_to_name(k) + ".undns.forre.st"
