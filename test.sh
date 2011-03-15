#!/bin/bash

time python tool.py generate > $1.key

echo key:
time python tool.py view $1.key
echo


echo url:
time python tool.py info $1.key
echo

time python tool.py encode $1.key $1.zone > $1.packet

echo packet:
time python tool.py view $1.packet
echo

echo decode:
time python tool.py decode $1.packet
