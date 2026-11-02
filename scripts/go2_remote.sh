#!/usr/bin/env bash
# Run the patrol on the Go2's onboard computer. This script never sends a motion command.
#   go2_remote.sh check   show Python, packages and the robot network interface
#   go2_remote.sh sync    copy the code and set the interface
#   go2_remote.sh fetch   copy logs back to this PC
# Override with GO2_HOST=user@address and GO2_DIR=folder. GO2_HOST=local copies to a local folder.
set -euo pipefail
HOST="${GO2_HOST:-unitree@192.168.123.18}"
DIR="${GO2_DIR:-go2_second_look}"
cd "$(dirname "$0")/.."

remote() { if [ "$HOST" = local ]; then bash -c "$1"; else ssh -o ConnectTimeout=8 "$HOST" "$1"; fi; }
target() { if [ "$HOST" = local ]; then echo "$DIR"; else echo "$HOST:$DIR"; fi; }

case "${1:-}" in
  check)
    remote 'python3 --version; uname -m; ip -4 -o addr show | grep "192.168.123." || echo "no 192.168.123.x interface";
      for m in numpy PIL yaml cv2 cyclonedds unitree_sdk2py; do
        python3 -c "import $m" 2>/dev/null && echo "ok      $m" || echo "MISSING $m"; done;
      command -v tmux || echo "MISSING tmux"; df -h ~ | tail -1'
    ;;
  sync)
    remote "mkdir -p $DIR"
    rsync -az --delete --exclude='__pycache__' --exclude='sim/' --exclude='logs/' --exclude='.venv*' --exclude='.git/' \
      --include='scout/***' --include='configs/***' --include='third_party_sdk/***' --include='scripts/' \
      --include='scripts/run_patrol.py' --include='scripts/check_go2.py' --include='scripts/test_motion.py' --exclude='*' \
      ./ "$(target)/"
    iface=$(remote "ip -4 -o addr show | awk '/192\.168\.123\./{print \$2; exit}'")
    if [ -n "$iface" ]; then
      remote "cd $DIR && sed -i 's/^  interface: .*/  interface: $iface/' configs/mission.yaml"
      echo "interface set to $iface"
    else
      echo "WARNING: no 192.168.123.x interface found, so set robot.interface by hand"
    fi
    echo "Next: ssh in, install anything check lists as missing, then run scripts/check_go2.py."
    ;;
  fetch)
    mkdir -p logs
    rsync -az "$(target)/logs/" logs/
    echo "Logs copied. Run scripts/revlm.py logs/RUN on this PC."
    ;;
  *) sed -n 2,6p "$0"; exit 1 ;;
esac
