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

alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'

