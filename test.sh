export PYTHONPATH=~/repos/pycrypto/build/lib.linux-i686-2.7/

python tool.py generate > .key

echo key:
cat .key

python tool.py info .key > .url

echo url:
cat .url

python tool.py encode .key <(echo -n hello, world) > .packet

echo packet:
cat .packet

echo decode:
python tool.py decode .packet $(cat .url)
