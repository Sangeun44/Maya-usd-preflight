#!/bin/sh
# Install Autodesk's Maya USD build into a Maya container that lacks it.
# usage: install_mayausd.sh <url of MayaUSD_..._Linux.run>
set -e
url="$1"
work=/tmp/mayausd
mkdir -p "$work"

echo "downloading $url"
if command -v curl > /dev/null; then
    curl -fsSL --max-time 240 -o "$work/installer.run" "$url"
else
    mayapy -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" "$url" "$work/installer.run"
fi
ls -l "$work/installer.run"
echo "--- start of the installer"
head -c 3000 "$work/installer.run" | tr -c '[:print:]\n' '?' | head -n 60
echo "--- tools"
head -n 2 /etc/os-release
for tool in rpm rpm2cpio cpio dnf yum apt-get bash file; do command -v "$tool" || echo "no $tool"; done

# The installer is a self-extracting archive wrapping an rpm. Unpack it
# without running it, then unpack the rpm into /.
sh "$work/installer.run" --noexec --target "$work/unpacked" < /dev/null
ls -l "$work/unpacked"
rpm_file=$(find "$work/unpacked" -name "*.rpm" | head -n 1)
echo "rpm: $rpm_file"
if command -v rpm > /dev/null; then
    rpm -ivh --nodeps "$rpm_file"
else
    command -v rpm2cpio > /dev/null || (apt-get update -q && apt-get install -y -q rpm2cpio cpio)
    (cd / && rpm2cpio "$rpm_file" | cpio -idm --quiet)
fi

module=$(find /usr/autodesk -name "mayaUSD.mod" | head -n 1)
echo "module file: $module"
test -n "$module"
echo "MAYA_MODULE_PATH=$(dirname "$module")" >> "$GITHUB_ENV"
