#!/usr/bin/env bash
set -ux

for F in uclid-sanity-tests/* ; do
    uclid common.ucl cpu.ucl "$F" # | grep FAIL
done
