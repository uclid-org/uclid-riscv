#!/usr/bin/env bash
set -ux

python3 gen_riscv_test_ucl.py

for F in autogen-riscv-tests/* ; do
    uclid common.ucl cpu.ucl "$F" # | grep FAIL
done
