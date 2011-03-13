#!/bin/bash

python tool.py generate > $1.key

echo key:
cat $1.key
echo

python tool.py info $1.key > $1.url

echo url:
cat $1.url
echo

python tool.py encode $1.key $1.zone > $1.packet

echo packet:
cat $1.packet
echo

echo decode:
python tool.py decode $1.packet
