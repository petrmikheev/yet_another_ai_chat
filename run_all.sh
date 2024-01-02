#!/bin/bash

./run_llama.sh &
./run_chroma.sh &

sleep 2

python3 server.py
