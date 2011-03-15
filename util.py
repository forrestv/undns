import hashlib

from Crypto.PublicKey import RSA

alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'

def natural_to_string(n, alphabet):
    if n < 0:
        raise ValueError()
    a, b = divmod(n, len(alphabet))
    return (natural_to_string(a, alphabet) if a else "") + alphabet[b]

def string_to_natural(s, alphabet):
    if not s or (s != alphabet[0] and s.startswith(alphabet[0])):
        raise ValueError()
    return sum(alphabet.index(char) * len(alphabet)**i for i, char in enumerate(reversed(s)))

def key_to_name(k):
    hash = int(hashlib.sha1(k.exportKey()).hexdigest(), 16)
    return natural_to_string(hash, alphabet)

def key_to_address(k):
    return key_to_name(k) + ".undns.forre.st"


def key_to_tuple(k):
    if k.has_private():
        k = k.key
        return (k.n, k.e, k.d, k.p, k.q, k.u)
    else:
        k = k.key
        return (k.n, k.e)

def tuple_to_key(t):
    return RSA.construct(map(long, t))

