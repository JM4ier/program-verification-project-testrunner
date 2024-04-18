#! /bin/bash

set -euo pipefail

cd "$(dirname "$0")"

NAME='program-verification-project1'
docker build -t $NAME .

cd ..
CMD="docker run --rm -v ./:/workdir/project"

if [ $# -gt 0 ]; then
    $CMD -it $NAME bash 
else
    $CMD $NAME ./testrunner.py
fi
