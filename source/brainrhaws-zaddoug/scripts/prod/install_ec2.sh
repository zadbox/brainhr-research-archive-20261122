#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root on Ubuntu/Debian."
  exit 1
fi

apt-get update
apt-get install -y ca-certificates curl gnupg jq lsb-release ruby unzip

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

architecture="$(dpkg --print-architecture)"
ubuntu_codename="$(
  . /etc/os-release
  echo "$VERSION_CODENAME"
)"

cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=${architecture} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${ubuntu_codename} stable
EOF

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o "$tmp_dir/awscliv2.zip"
unzip -q "$tmp_dir/awscliv2.zip" -d "$tmp_dir"
"$tmp_dir/aws/install" --update

install -d -o root -g root -m 0750 /srv/brainrh/logs /srv/brainrh/recordings

echo "EC2 runtime prerequisites installed. Local PostgreSQL was not provisioned; production uses RDS."
