#!/bin/bash

if [ "${TRAVIS_OS_NAME}" != "linux" ]; then
   echo "not doing build_docs on non-linux"
   exit 0
fi

cd "$TRAVIS_BUILD_DIR"
echo "inside $0"

git show --pretty="format:" --name-only HEAD~5.. --first-parent | grep -P "rst|txt|doc"

# if [ "$?" != "0" ]; then
#     echo "Skipping doc build, none were modified"
#     # nope, skip docs build
#     exit 0
# fi


if [ "$DOC" ]; then

    echo "Will build docs"

    source activate pandas

    mv "$TRAVIS_BUILD_DIR"/doc /tmp
    mv "$TRAVIS_BUILD_DIR/LICENSE" /tmp  # included in the docs.
    cd /tmp/doc

    echo ###############################
    echo # Log file for the doc build  #
    echo ###############################

    echo ./make.py
    ./make.py

    echo ########################
    echo # Create and send docs #
    echo ########################

    cd /tmp/doc/build/html
    git config --global user.email "pandas-docs-bot@localhost.foo"
    git config --global user.name "pandas-docs-bot"

    # create the repo
    git init

    touch README
    git add README
    git commit -m "Initial commit" --allow-empty
    git branch gh-pages
    git checkout gh-pages
    touch .nojekyll
    git add --all .
    git commit -m "Version" --allow-empty

    git remote remove origin
    git remote add origin "https://${PANDAS_GH_TOKEN}@github.com/pandas-dev/pandas-docs-travis.git"
    git fetch origin
    git remote -v

    git push origin gh-pages -f

    echo "Running doctests"
    cd "$TRAVIS_BUILD_DIR"
    pytest --doctest-modules \
           pandas/core/reshape/concat.py \
           pandas/core/reshape/pivot.py \
           pandas/core/reshape/reshape.py \
           pandas/core/reshape/tile.py

fi

exit 0
