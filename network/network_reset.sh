#!/usr/bin/env bash
# ==============================================================================
# Network Impairment Reset Script
# Removes any tc/netem qdisc rules applied by network_setup.sh and restores
# normal traffic flow on the specified interface.
# ==============================================================================

set -euo pipefail

INTERFACE=""

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Options:
  -i, --interface <iface>   Target network interface to reset. If omitted, the script
                            will attempt to auto-detect the default route interface.
  -h, --help                Show this help message.

Example:
  sudo $0 -i eth0
EOF
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--interface)
            INTERFACE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            ;;
    esac
done

# Ensure running as root
if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] This script must be run as root (or via sudo)."
    exit 1
fi

# Auto-detect interface if not supplied
if [[ -z "$INTERFACE" ]]; then
    INTERFACE=$(ip route show default 2>/dev/null | awk '/default/ {print $5}' | head -n1 || true)
    if [[ -z "$INTERFACE" ]]; then
        INTERFACE=$(ip link show up 2>/dev/null | awk -F: '$2 !~ /lo/ {gsub(/ /, "", $2); print $2; exit}')
    fi
fi

if [[ -z "$INTERFACE" ]]; then
    echo "[ERROR] Could not determine an active network interface. Provide one with -i <iface>."
    exit 1
fi

# Verify interface exists
if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
    echo "[ERROR] Interface '$INTERFACE' does not exist."
    exit 1
fi

# Delete any root qdisc (including netem) on the interface
echo "[INFO] Removing any traffic control rules on $INTERFACE"
if tc qdisc show dev "$INTERFACE" | grep -q "qdisc"; then
    tc qdisc del dev "$INTERFACE" root || true
    echo "[SUCCESS] Traffic control rules cleared on $INTERFACE."
else
    echo "[INFO] No qdisc rules were present on $INTERFACE."
fi

echo "[VERIFICATION] Current qdisc configuration on $INTERFACE:"
tc qdisc show dev "$INTERFACE"
