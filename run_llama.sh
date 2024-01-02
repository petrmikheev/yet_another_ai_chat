#!/bin/bash

cd $HOME/llama.cpp

MODEL1=models/openchat/openchat_3.5.Q4_K_M.gguf
CTX1=8192

MODEL2=models/mythomax/mythomax-l2-13b.Q4_K_M.gguf
CTX2=4096

PID2=$$

( ./server -c $CTX1 --embedding -ngl 100 -m $MODEL1 --host '0.0.0.0' --port 8080 > model1.log 2>&1 || echo First instance stopped ; pkill -P $PID2 ) &

PID1=$!

( ./server -c $CTX2 -ngl 100 -m $MODEL2 --host '0.0.0.0' --port 8081 > model2.log 2>&1 || echo Second instance stopped ; pkill -P $PID1 )
