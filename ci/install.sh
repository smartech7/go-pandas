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

function edit_init()
{
    if [ -n "$LOCALE_OVERRIDE" ]; then
        echo "Adding locale to the first line of pandas/__init__.py"
        rm -f pandas/__init__.pyc
        sedc="3iimport locale\nlocale.setlocale(locale.LC_ALL, '$LOCALE_OVERRIDE')\n"
        sed -i "$sedc" pandas/__init__.py
        echo "head -4 pandas/__init__.py"
        head -4 pandas/__init__.py
        echo
    fi
}

edit_init

# Install Dependencies
# as of pip 1.4rc2, wheel files are still being broken regularly, this is a
# known good commit. should revert to pypi when a final release is out
pip_commit=42102e9deaea99db08b681d06906c2945f6f95e2
pip install -I git+https://github.com/pypa/pip@$pip_commit#egg=pip

python_major_version="${TRAVIS_PYTHON_VERSION:0:1}"
[ "$python_major_version" == "2" ] && python_major_version=""

pip install -I -U setuptools
pip install wheel

# comment this line to disable the fetching of wheel files
base_url=http://cache27diy-cpycloud.rhcloud.com
wheel_box=${TRAVIS_PYTHON_VERSION}${JOB_TAG}
PIP_ARGS+=" -I --use-wheel --find-links=$base_url/$wheel_box/"

# Force virtualenv to accpet system_site_packages
rm -f $VIRTUAL_ENV/lib/python$TRAVIS_PYTHON_VERSION/no-global-site-packages.txt


if [ -n "$LOCALE_OVERRIDE" ]; then
    # make sure the locale is available
    # probably useless, since you would need to relogin
    time sudo locale-gen "$LOCALE_OVERRIDE"
fi

# show-skipped is working at this particular commit
show_skipped_commit=fa4ff84e53c09247753a155b428c1bf2c69cb6c3
time pip install git+git://github.com/cpcloud/nose-show-skipped.git@$show_skipped_commit
time pip install $PIP_ARGS -r ci/requirements-${wheel_box}.txt

# we need these for numpy
time sudo apt-get $APT_ARGS install libatlas-base-dev gfortran


# Need to enable for locale testing. The location of the locale file(s) is
# distro specific. For example, on Arch Linux all of the locales are in a
# commented file--/etc/locale.gen--that must be commented in to be used
# whereas Ubuntu looks in /var/lib/locales/supported.d/* and generates locales
# based on what's in the files in that folder
time echo 'it_CH.UTF-8 UTF-8' | sudo tee -a /var/lib/locales/supported.d/it
time sudo locale-gen


# install gui for clipboard testing
if [ -n "$CLIPBOARD_GUI" ]; then
    echo "Using CLIPBOARD_GUI: $CLIPBOARD_GUI"
    [ -n "$python_major_version" ] && py="py"
    python_cb_gui_pkg=python${python_major_version}-${py}${CLIPBOARD_GUI}
    time sudo apt-get $APT_ARGS install $python_cb_gui_pkg
fi


# install a clipboard if $CLIPBOARD is not empty
if [ -n "$CLIPBOARD" ]; then
    echo "Using clipboard: $CLIPBOARD"
    time sudo apt-get $APT_ARGS install $CLIPBOARD
fi


# Optional Deps
if [ -n "$FULL_DEPS" ]; then
    echo "Installing FULL_DEPS"

    # need libhdf5 for PyTables
    time sudo apt-get $APT_ARGS install libhdf5-serial-dev
fi


# build and install pandas
time python setup.py build_ext install

true
