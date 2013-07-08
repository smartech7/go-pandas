#!/bin/bash

# There are 2 distinct pieces that get zipped and cached
# - The venv site-packages dir including the installed dependencies
# - The pandas build artifacts, using the build cache support via
#   scripts/use_build_cache.py
#
# if the user opted in to use the cache and we're on a whitelisted fork
# - if the server doesn't hold a cached version of venv/pandas build,
#   do things the slow way, and put the results on the cache server
#   for the next time.
# -  if the cache files are available, instal some necessaries via apt
#    (no compiling needed), then directly goto script and collect 200$.
#

echo "inside $0"

# Install Dependencies
# as of pip 1.4rc2, wheel files are still being broken regularly, this is a known good
# commit. should revert to pypi when a final release is out
pip install -I git+https://github.com/pypa/pip@42102e9deaea99db08b681d06906c2945f6f95e2#egg=pip
pv="${TRAVIS_PYTHON_VERSION:0:1}"
[ "$pv" == "2" ] && pv=""
[ "$pv" == "2" ] && DISTRIBUTE_VERSION="==0.6.35"

pip install -I distribute${DISTRIBUTE_VERSION}
pip install wheel

# comment this line to disable the fetching of wheel files
PIP_ARGS+=" -I --use-wheel --find-links=http://cache27diy-cpycloud.rhcloud.com/${TRAVIS_PYTHON_VERSION}${JOB_TAG}/"

# Force virtualenv to accpet system_site_packages
rm -f $VIRTUAL_ENV/lib/python$TRAVIS_PYTHON_VERSION/no-global-site-packages.txt


if [ -n "$LOCALE_OVERRIDE" ]; then
    # make sure the locale is available
    # probably useless, since you would need to relogin
    sudo locale-gen "$LOCALE_OVERRIDE"
fi

time pip install $PIP_ARGS -r ci/requirements-${TRAVIS_PYTHON_VERSION}${JOB_TAG}.txt

# Optional Deps
if [ x"$FULL_DEPS" == x"true" ]; then
    echo "Installing FULL_DEPS"
   # for pytables gets the lib as well
    time sudo apt-get $APT_ARGS install libhdf5-serial-dev
    time sudo apt-get $APT_ARGS install python${pv}-bs4
    time sudo apt-get $APT_ARGS install python${pv}-scipy

    time sudo apt-get $APT_ARGS remove python${pv}-lxml

    # fool statsmodels into thinking pandas was already installed
    # so it won't refuse to install itself.

    SITE_PKG_DIR=$VIRTUAL_ENV/lib/python$TRAVIS_PYTHON_VERSION/site-packages
    echo "Using SITE_PKG_DIR: $SITE_PKG_DIR"

    mkdir  $SITE_PKG_DIR/pandas
    touch $SITE_PKG_DIR/pandas/__init__.py
    echo "version='0.10.0-phony'" >  $SITE_PKG_DIR/pandas/version.py
    time pip install $PIP_ARGS git+git://github.com/statsmodels/statsmodels@c9062e43b8a5f7385537ca95#egg=statsmodels

    rm -Rf $SITE_PKG_DIR/pandas # scrub phoney pandas
fi

# build pandas
time python setup.py build_ext install

true
