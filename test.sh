#!/bin/bash

./tool.py generate > $1.key

echo key:
./tool.py view $1.key
echo


echo url:
./tool.py info $1.key
echo

./tool.py encode $1.key $1.zone > $1.packet

echo packet:
./tool.py view $1.packet
echo

echo decode:
./tool.py decode $1.packet
