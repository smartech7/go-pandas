#!/bin/bash -e

echo "[script multi]"

if [ -n "$LOCALE_OVERRIDE" ]; then
    export LC_ALL="$LOCALE_OVERRIDE";
    export LANG="$LOCALE_OVERRIDE";
    echo "Setting LC_ALL to $LOCALE_OVERRIDE"

    pycmd='import pandas; print("pandas detected console encoding: %s" % pandas.get_option("display.encoding"))'
    python -c "$pycmd"
fi

# Enforce absent network during testing by faking a proxy
if echo "$TEST_ARGS" | grep -e --skip-network -q; then
    export http_proxy=http://1.2.3.4 https_proxy=http://1.2.3.4;
fi

# Workaround for pytest-xdist flaky collection order
# https://github.com/pytest-dev/pytest/issues/920
# https://github.com/pytest-dev/pytest/issues/1075
export PYTHONHASHSEED=$(python -c 'import random; print(random.randint(1, 4294967295))')
echo PYTHONHASHSEED=$PYTHONHASHSEED

if [ "$DOC" ]; then
    echo "We are not running pytest as this is a doc-build"

elif [ "$COVERAGE" ]; then
    echo pytest -s -n 2 -m "not single" --durations=10 --cov=pandas --cov-report xml:/tmp/cov-multiple.xml --junitxml=test-data-multiple.xml --strict $TEST_ARGS pandas
    pytest      -s -n 2 -m "not single" --durations=10 --cov=pandas --cov-report xml:/tmp/cov-multiple.xml --junitxml=test-data-multiple.xml --strict $TEST_ARGS pandas

elif [ "$SLOW" ]; then
    TEST_ARGS="--only-slow --skip-network"
    # The `-m " and slow"` is redundant here, as `--only-slow` is already used (via $TEST_ARGS). But is needed, because with
    # `--only-slow` fast tests are skipped, but each of them is printed in the log (which can be avoided with `-q`),
    # and also added to `test-data-multiple.xml`, and then printed in the log in the call to `ci/print_skipped.py`.
    # Printing them to the log makes the log exceed the maximum size allowed by Travis and makes the build fail.
    echo pytest -n 2 -m "not single and slow" --durations=10 --junitxml=test-data-multiple.xml --strict $TEST_ARGS pandas
    pytest      -n 2 -m "not single and slow" --durations=10 --junitxml=test-data-multiple.xml --strict $TEST_ARGS pandas

else
    echo pytest -n 2 -m "not single" --durations=10 --junitxml=test-data-multiple.xml --strict $TEST_ARGS pandas
    pytest      -n 2 -m "not single" --durations=10 --junitxml=test-data-multiple.xml --strict $TEST_ARGS pandas # TODO: doctest

fi

RET="$?"

exit "$RET"
