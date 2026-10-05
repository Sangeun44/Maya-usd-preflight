#!/bin/sh
# Show a file as a notice on the workflow run. usage: notice.sh <title> <file>
printf '::notice title=%s::%s%%0A' "$1" "$1"
tail -c 6000 "$2" | tr -c '[:print:]\n' '?' | sed -e 's/%/%25/g' | sed -e ':a' -e 'N' -e '$!ba' -e 's/\n/%0A/g'
echo
