#!/bin/bash
# Only run on even ISO week numbers — gives a bi-weekly cadence when called every Monday.
WEEK=$(date +%V)
if [ $((10#$WEEK % 2)) -eq 0 ]; then
  exec python3 "/Users/maxalderman/AI Agents - Max/trendtrack-intelligence/post_digest.py" "$@"
fi
