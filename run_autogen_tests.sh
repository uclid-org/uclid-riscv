#!/usr/bin/env bash
set -ux

python3 gen_riscv_test_ucl.py

mkdir -p results/

for F in autogen-riscv-tests/* ; do
    uclid common.ucl cpu.ucl "$F" > results/$(basename "$F" | cut -d. -f1) # | grep FAIL
done

# https://stackoverflow.com/questions/356100/
#FAIL=0
#for job in `jobs -p` do
#    echo "$job"
#    wait "$job" || let "FAIL+=1"
#done
#echo "$FAIL"
#
#if [ "$FAIL" -ne 0 ]; then
#    echo "$FAIL jobs failed."
#fi
