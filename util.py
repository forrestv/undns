import hashlib

from Crypto.PublicKey import RSA
from Crypto import Random

def int_to_string(i, alphabet):
    res = []
    while True:
        res.append(i % len(alphabet))
        i //= len(alphabet)
        if not i:
            break
    return ''.join(alphabet[x] for x in reversed(res))

def string_to_int(s, alphabet):
    acc = 0
    place_value = 1
    for char in s[::-1]:
        acc += place_value * alphabet.index(char)
        place_value *= len(alphabet)
    return acc


def key_to_name(k):
    hash = int(hashlib.sha1(k.exportKey()).hexdigest(), 16)
    return int_to_string(hash, alphabet)

def key_to_address(k):
    return key_to_name(k) + ".undns.forre.st"

alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'

def key_to_tuple(k):
    if k.has_private():
        k = k.key
        return (k.n, k.e, k.d, k.p, k.q, k.u)
    else:
        k = k.key
        return (k.n, k.e)

def tuple_to_key(t):
    return RSA.construct(map(long, t))

