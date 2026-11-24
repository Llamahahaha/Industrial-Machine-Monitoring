#!/usr/bin/env bash
# ==============================================================================
# Industrial Machine Monitoring Network — Network Impairment Setup
# Author: E (Arch Linux Host)
#
# Uses Linux tc (Traffic Control) and netem (Network Emulation)
# Simulates controlled network conditions:
#   - Latency (delay in ms)
#   - Jitter (variation in ms)
#   - Packet loss (percentage %)
#   - Combined latency, jitter and loss
#
# NOTE: Requires root privileges (sudo). Always review before applying.
# ==============================================================================

set -euo pipefail

# Default parameters
INTERFACE=""
DELAY_MS=0
JITTER_MS=0
LOSS_PCT=0
CORRELATION_PCT=""

# Help / Usage message
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Options:
  -i, --interface <iface>   Target network interface (e.g. wlan0, eth0).
                            If omitted, auto-detects active default route interface.
  -d, --delay <ms>          Added round-trip latency in milliseconds (e.g. 100).
  -j, --jitter <ms>         Jitter in milliseconds (e.g. 10). Requires --delay.
  -l, --loss <percent>      Packet loss percentage (e.g. 5 for 5% loss).
  -c, --correlation <pct>   Correlation percentage for loss or jitter (e.g. 25).
  -h, --help                Show this help message.

Examples:
  # Add 100ms latency to auto-detected interface:
  sudo $0 -d 100

  # Add 100ms latency with 15ms jitter:
  sudo $0 -d 100 -j 15

  # Add 5% packet loss:
  sudo $0 -l 5

  # Combined 150ms delay, 20ms jitter, and 3% packet loss on wlan0:
  sudo $0 -i wlan0 -d 150 -j 20 -l 3
EOF
    exit 1
}

# Parse command line flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        -i|--interface)
            INTERFACE="$2"
            shift 2
            ;;
        -d|--delay)
            DELAY_MS="$2"
            shift 2
            ;;
        -j|--jitter)
            JITTER_MS="$2"
            shift 2
            ;;
        -l|--loss)
            LOSS_PCT="$2"
            shift 2
            ;;
        -c|--correlation)
            CORRELATION_PCT="$2"
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

# Ensure running with root privileges
if [[ $EUID -ne 0 ]]; then
   echo "[ERROR] This script modifies kernel traffic control rules and must be run as root (or via sudo)."
   exit 1
fi

# Detect default interface if not specified
if [[ -z "$INTERFACE" ]]; then
    INTERFACE=$(ip route show default 2>/dev/null | awk '/default/ {print $5}' | head -n1 || true)
    if [[ -z "$INTERFACE" ]]; then
        # Fallback to first non-loopback UP interface
        INTERFACE=$(ip link show up 2>/dev/null | awk -F: '$2 !~ /lo/ {gsub(/ /, "", $2); print $2; exit}')
    fi
fi

if [[ -z "$INTERFACE" ]]; then
    echo "[ERROR] Could not automatically identify an active network interface. Please specify one with -i <interface>."
    exit 1
fi

# Validate interface exists
if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
    echo "[ERROR] Interface '$INTERFACE' does not exist."
    exit 1
fi

# Validate parameter combinations
if [[ "$JITTER_MS" -gt 0 ]] && [[ "$DELAY_MS" -le 0 ]]; then
    echo "[ERROR] Jitter (--jitter) requires delay (--delay) to be greater than 0."
    exit 1
fi

if [[ "$DELAY_MS" -le 0 ]] && [[ "$LOSS_PCT" -le 0 ]]; then
    echo "[ERROR] You must specify at least one impairment (--delay > 0 or --loss > 0)."
    usage
fi

# Construct netem command string
NETEM_CMD="netem"

if [[ "$DELAY_MS" -gt 0 ]]; then
    NETEM_CMD="$NETEM_CMD delay ${DELAY_MS}ms"
    if [[ "$JITTER_MS" -gt 0 ]]; then
        NETEM_CMD="$NETEM_CMD ${JITTER_MS}ms"
        if [[ -n "$CORRELATION_PCT" ]]; then
            NETEM_CMD="$NETEM_CMD ${CORRELATION_PCT}%"
        fi
    fi
fi

if [[ "$LOSS_PCT" -gt 0 ]]; then
    NETEM_CMD="$NETEM_CMD loss ${LOSS_PCT}%"
    if [[ -n "$CORRELATION_PCT" ]] && [[ "$JITTER_MS" -le 0 ]]; then
        NETEM_CMD="$NETEM_CMD ${CORRELATION_PCT}%"
    fi
fi

echo "=========================================================="
echo "Applying Network Impairment via Linux tc/netem"
echo "=========================================================="
echo "Target Interface : $INTERFACE"
echo "Delay / Jitter   : ${DELAY_MS}ms / ${JITTER_MS}ms"
echo "Packet Loss      : ${LOSS_PCT}%"
echo "Netem Parameters : $NETEM_CMD"
echo "=========================================================="

# Check if a root qdisc already exists on this interface
CURRENT_QDISC=$(tc qdisc show dev "$INTERFACE" | grep -E "netem" || true)

if [[ -n "$CURRENT_QDISC" ]]; then
    echo "[INFO] Existing netem configuration found. Updating with 'tc qdisc change'..."
    tc qdisc change dev "$INTERFACE" root $NETEM_CMD
else
    echo "[INFO] Adding new netem configuration with 'tc qdisc add'..."
    # Attempt add; if non-netem root exists, replace it
    if ! tc qdisc add dev "$INTERFACE" root $NETEM_CMD 2>/dev/null; then
        echo "[INFO] Replacing root qdisc..."
        tc qdisc replace dev "$INTERFACE" root $NETEM_CMD
    fi
fi

echo ""
echo "[VERIFICATION] Current qdisc rules on $INTERFACE:"
tc qdisc show dev "$INTERFACE"
echo ""
echo "[SUCCESS] Network impairment active on $INTERFACE."
echo "To reset to normal network conditions, run: sudo $(dirname "$0")/network_reset.sh -i $INTERFACE"
