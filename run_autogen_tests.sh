#!/usr/bin/env bash
# set -ux
set -u

python3 gen_riscv_test_ucl.py


for D in autogen-riscv-tests/* ; do
    mkdir -p results/$(basename $D)
    for F in $D/*; do
        date
        echo "Starting $F"
        timeout --signal=KILL 5m uclid common.ucl cpu.ucl "$F" | tee results/$(basename $D)/$(basename "$F" | cut -d. -f1) # | grep FAIL
    done
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
