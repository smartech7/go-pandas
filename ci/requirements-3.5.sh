#!/bin/bash

source activate pandas

echo "install 35"

conda install -n pandas -c conda-forge feather-format

# pip install python-dateutil to get latest
conda remove -n pandas python-dateutil --force
pip install python-dateutil
