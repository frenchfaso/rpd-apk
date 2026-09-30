#!/bin/sh
# Retry only a transient HTTP503 from standard abuild fetch; keep all checks.
set -eu
test "$#" -eq 1
review=$1
test -d "$review"
attempt=1
while :; do
    log="$review/fetch-attempt-$attempt.log"
    status=0
    if abuild fetch > "$log" 2>&1; then
        cat "$log"
        printf '%s\t0\n' "$attempt" >> "$review/fetch-attempts.tsv"
        exit 0
    else
        status=$?
    fi
    cat "$log"
    printf '%s\t%s\n' "$attempt" "$status" >> "$review/fetch-attempts.tsv"
    # Hash failures and every non-503 failure remain immediately fatal.
    if grep -Eiq '(: FAILED|failed the .*sum check|abuild checksum)' "$log" \
        || ! grep -Eq '^curl: \(22\) The requested URL returned error: 503$' "$log" \
        || { grep '^curl:' "$log" | grep -qEv '^curl: \(22\) The requested URL returned error: 503$'; } \
        || [ "$attempt" -ge 3 ]; then
        exit "$status"
    fi
    printf '%s\n' 'Transient HTTP503: retrying standard abuild fetch in 5 seconds; cached inputs retained.'
    sleep 5
    attempt=$((attempt + 1))
done
