#!/bin/bash
set -e

apt update
apt install -y gcc g++ gfortran libopenblas-dev liblapack-dev pkg-config

wget -O Miniforge3.sh "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh"
bash Miniforge3.sh -b -p "${HOME}/conda"
source "${HOME}/conda/etc/profile.d/conda.sh"
source "${HOME}/conda/etc/profile.d/mamba.sh"
mamba shell init -s bash

mamba env create -f environment.yml python=3.12 -y
mamba activate scipy-dev

pip install -e . --no-build-isolation

pip install coverage