#!/bin/bash
# Put the site on a machine made by provision.sh: copy the trained models and the language
# service key over SSH, build the container there from the public repository, and serve it
# over HTTPS at https://<address>.sslip.io (a free name that points at the address).
#
#   deploy/aws/setup.sh 203.0.113.10
#
# The key in .env is copied to the machine only; it is never put in the image or the repository.
set -euo pipefail
IP=$1
KEY=~/.ssh/flowcast-aws
HOST=ubuntu@$IP
NAME=$(echo $IP | tr . -).sslip.io
SSH=(ssh -i $KEY -o StrictHostKeyChecking=accept-new $HOST)
cd "$(dirname "$0")/../.."

echo "1. software"
"${SSH[@]}" 'sudo apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq podman git rsync >/dev/null && sudo loginctl enable-linger ubuntu'

echo "2. models and key"
"${SSH[@]}" 'mkdir -p ~/flowcast-data'
rsync -az --info=progress2 -e "ssh -i $KEY" data/models data/models-ceiling data/models-cross data/models-cabinet $HOST:~/flowcast-data/
scp -q -i $KEY .env $HOST:~/flowcast.env
"${SSH[@]}" 'chmod 600 ~/flowcast.env'

echo "3. build"
"${SSH[@]}" 'rm -rf ~/flowcast && git clone -q --depth 1 https://github.com/MrtnOmwenga/flowcast ~/flowcast && cd ~/flowcast && podman build -q -t flowcast .'

echo "4. run"
"${SSH[@]}" bash -s <<REMOTE
set -e
podman rm -f flowcast caddy >/dev/null 2>&1 || true
podman run -d --name flowcast --restart=always --env-file ~/flowcast.env \
  -e FLOWCAST_HARDWARE="AWS t3a.xlarge, AMD EPYC processor" \
  -v ~/flowcast-data:/data:ro,z -p 127.0.0.1:8000:8000 localhost/flowcast
mkdir -p ~/caddy
printf '%s {\n  reverse_proxy 127.0.0.1:8000\n}\n' $NAME > ~/caddy/Caddyfile
sudo podman rm -f caddy >/dev/null 2>&1 || true
sudo podman run -d --name caddy --restart=always --network host \
  -v /home/ubuntu/caddy/Caddyfile:/etc/caddy/Caddyfile:ro,z -v caddy-data:/data docker.io/library/caddy:2
sudo systemctl enable --now podman-restart.service >/dev/null 2>&1 || true
systemctl --user enable --now podman-restart.service >/dev/null 2>&1 || true
REMOTE

echo "5. check"
for i in $(seq 1 60); do curl -fsS https://$NAME/api/health >/dev/null 2>&1 && break; sleep 5; done
curl -fsS https://$NAME/api/health && echo && echo "site: https://$NAME"
