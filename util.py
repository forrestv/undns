import hashlib

from Crypto.PublicKey import RSA

# encoding

default_alphabet = ''.join(chr(i) for i in xrange(256))

def natural_to_string(n, alphabet=default_alphabet):
    if n < 0:
        raise ValueError()
    a, b = divmod(n, len(alphabet))
    return (natural_to_string(a, alphabet) if a else "") + alphabet[b]

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

def key_to_name(k):
    assert not k.has_private()
    return natural_to_string(intdigest(hashlib.sha256(key_to_string(k))), dns_alphabet)

if __name__ == "__main__":
    import random
    for i in xrange(1000):
        n = random.randrange(2**100)
        assert n == string_to_natural(natural_to_string(n))
