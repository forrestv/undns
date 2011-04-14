from __future__ import division

import hashlib

from Crypto.PublicKey import RSA

# hash

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

# encoding

default_alphabet = ''.join(chr(i) for i in xrange(256))

def natural_to_string(n, alphabet=default_alphabet, min_width=1):
    res = []
    while n:
        n, x = divmod(n, len(alphabet))
        res.append(alphabet[x])
    res.reverse()
    return ''.join(res).rjust(min_width, '\x00')

def string_to_natural(s, alphabet=default_alphabet):
    if not s or (s != alphabet[0] and s.startswith(alphabet[0])):
        raise ValueError()
    return sum(alphabet.index(char) * len(alphabet)**i for i, char in enumerate(reversed(s)))

# key storage

def key_to_tuple(key):
    k = key.key
    if key.has_private():
        return (k.n, k.e, k.d, k.p, k.q, k.u)
    else:
        return (k.n, k.e)

def tuple_to_key(t):
    return RSA.construct(map(long, t))

def key_to_string(k):
    # for hashing
    return " ".join(map(str, key_to_tuple(k)))

# hashing

def intdigest(h):
    return int(h.hexdigest(), 16)

def strdigest(h, alphabet):
    return natural_to_string(intdigest(h), alphabet)

# names

dns_alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
c1 = 2201097281
c2 = 1865308177

def key_to_name_hash(k):
    assert not k.has_private()
    nh = ripemd160(key_to_string(k)).digest()
    assert len(nh) == 160//8
    return nh

def key_to_name(k):
    assert not k.has_private()
    x = intdigest(ripemd160(key_to_string(k)))
    n = natural_to_string(x * c1 + c2, dns_alphabet)
    return n

def name_to_name_hash(n):
    y = string_to_natural(n, dns_alphabet)
    x, q = divmod(y, c1)
    if q != c2:
        raise ValueError("not a valid name")
    if x < 2**120 or x >= 2**160:
        raise ValueError("not a valid name")
    return natural_to_string(x, min_width=160//8)

def name_hash_to_name(nh):
    assert len(nh) == 160//8
    x = string_to_natural(nh)
    return natural_to_string(x * c1 + c2, dns_alphabet)

# math

def median(x):
    # don't really need a complex algorithm here
    y = sorted(x)
    left = (len(y) - 1)//2
    right = len(y)//2
    return (y[left] + y[right])/2

if __name__ == "__main__":
    import random
    for i in xrange(1000):
        n = random.randrange(2**100)
        assert n == string_to_natural(natural_to_string(n))
