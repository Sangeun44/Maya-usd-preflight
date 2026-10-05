#!/bin/sh
# Install Autodesk's Maya USD build into a Maya container that lacks it.
# usage: install_mayausd.sh <url of MayaUSD_..._Linux.run>
set -e
url="$1"
work=/tmp/mayausd
mkdir -p "$work"
export DEBIAN_FRONTEND=noninteractive

head -n 2 /etc/os-release
for tool in curl rpm rpm2cpio cpio dnf yum apt-get bash; do command -v "$tool" || echo "no $tool"; done

echo "--- download $url"
if command -v curl > /dev/null; then
    curl -fsSL --max-time 200 -o "$work/installer.run" "$url"
else
    timeout 200 mayapy -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" "$url" "$work/installer.run"
fi
ls -l "$work/installer.run"
head -c 1500 "$work/installer.run" | tr -c '[:print:]\n' '?' | head -n 25

# The installer is a self-extracting archive wrapping an rpm. Unpack it
# without running it, then unpack the rpm into /.
echo "--- unpack"
timeout 90 sh "$work/installer.run" --noexec --target "$work/unpacked" < /dev/null
ls -l "$work/unpacked"
rpm_file=$(find "$work/unpacked" -name "*.rpm" | head -n 1)
echo "--- install $rpm_file"
if command -v rpm > /dev/null; then
    timeout 120 rpm -ivh --nodeps "$rpm_file" < /dev/null
else
    command -v rpm2cpio > /dev/null || (timeout 120 apt-get update -q && timeout 120 apt-get install -y -q rpm2cpio cpio) < /dev/null
    (cd / && rpm2cpio "$rpm_file" | cpio -idm --quiet)
fi

module=$(find /usr/autodesk -name "mayaUSD.mod" | head -n 1)
echo "--- module file: $module"
test -n "$module"
echo "MAYA_MODULE_PATH=$(dirname "$module")" >> "$GITHUB_ENV"
