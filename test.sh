#!/bin/bash

python tool.py generate > .key

echo key:
cat .key
echo

python tool.py info .key > .url

echo url:
cat .url
echo

python tool.py encode .key <(echo -n 42.42.13.37) > .packet

echo packet:
cat .packet
echo

echo decode:
python tool.py decode .packet $(cat .url)
