#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: gen-deploy-key.sh [--dir ./keys] [--name id_ed25519] [--force]
EOF
}

key_dir="./keys"
key_name="id_ed25519"
force=0

while (($#)); do
  case "$1" in
    --dir)
      if (($# < 2)); then
        echo "error: --dir requires a path" >&2
        exit 2
      fi
      key_dir="$2"
      shift 2
      ;;
    --name)
      if (($# < 2)); then
        echo "error: --name requires a filename" >&2
        exit 2
      fi
      key_name="$2"
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

key_path="$key_dir/$key_name"
pub_path="$key_path.pub"

if [[ -e "$key_path" || -e "$pub_path" ]] && ((force == 0)); then
  echo "error: key already exists at $key_path; pass --force to overwrite" >&2
  exit 1
fi

mkdir -p "$key_dir"
chmod 700 "$key_dir"
rm -f "$key_path" "$pub_path"
ssh-keygen -t ed25519 -N "" -C "cus-deploy" -f "$key_path"
chmod 600 "$key_path"

public_key="$(cat "$pub_path")"
restricted_line="command=\"rrsync -ro ~/.claude\",restrict $public_key"
fallback_line="$public_key"

cat <<EOF
Private key: $key_path
Public key:  $pub_path

Public key:
$public_key

Recommended restricted authorized_keys line for each remote:
$restricted_line

rrsync ships with rsync docs; the path varies by distro, for example
/usr/share/doc/rsync/scripts/rrsync, or it may be available as rrsync in PATH.
This confines the key to read-only rsync under ~/.claude.

Less safe unrestricted fallback authorized_keys line:
$fallback_line

Install on a remote:
printf '%s\n' '$restricted_line' | ssh user@host 'umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; cat >> ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys'

In config/machines.toml, set ssh_key = "/keys/$key_name" for the in-container path.
EOF
