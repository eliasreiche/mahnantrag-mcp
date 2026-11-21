#!/bin/sh
# Startet den MCP-Server. Fehlt uv, wird es einmalig ohne Adminrechte in einen
# Nutzerordner geladen: fest gepinnte Version aus den offiziellen GitHub-Releases von
# astral-sh/uv, geprüft gegen die hier eingetragenen SHA-256-Werte. Kein Installer-Skript,
# kein Eingriff in PATH oder Shell-Profile.
# stdout gehört dem MCP-Protokoll: alle Meldungen gehen nach stderr.
set -eu

UV_VERSION="0.12.8"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
UV_HOME="${MAHNANTRAG_UV_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/mahnantrag-mcp/uv}"

log() { printf 'mahnantrag-start: %s\n' "$*" >&2; }

finde_uv() {
  # Claude Desktop startet mit knappem PATH, deshalb die üblichen Orte selbst ansehen.
  for k in "$UV_HOME/uv" "$(command -v uv 2>/dev/null || true)" \
           "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [ -n "$k" ] && [ -x "$k" ]; then printf '%s' "$k"; return 0; fi
  done
  return 1
}

sha256_von() {
  case "$UV_ZIEL" in
    aarch64-apple-darwin)      echo 8ce083658dbff20143607ca7af8e0c1d64b6fd7bf03a5cdcb62bf3d47d991b5f ;;
    x86_64-apple-darwin)       echo bfcd4407de99e0a2c1904df0902fa1795653d4edd145358e6561527e746a4f16 ;;
    x86_64-unknown-linux-gnu)  echo 2e2b37e9811e17675a9e70bed5e1a58fc8c0388be63d751d72cc735188c149ff ;;
    aarch64-unknown-linux-gnu) echo ba8661f4fd207c8e94814191598e619b355ac10d5014e851e21eb800f9ef2b00 ;;
    *) return 1 ;;
  esac
}

installiere_uv() {
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)                UV_ZIEL=aarch64-apple-darwin ;;
    Darwin-x86_64)               UV_ZIEL=x86_64-apple-darwin ;;
    Linux-x86_64)                UV_ZIEL=x86_64-unknown-linux-gnu ;;
    Linux-aarch64|Linux-arm64)   UV_ZIEL=aarch64-unknown-linux-gnu ;;
    *) log "Plattform $(uname -s)-$(uname -m) nicht unterstützt; bitte uv manuell installieren: https://docs.astral.sh/uv/"; exit 1 ;;
  esac
  command -v curl >/dev/null 2>&1 || { log "curl fehlt; bitte uv manuell installieren: https://docs.astral.sh/uv/"; exit 1; }
  log "uv nicht gefunden, lade uv $UV_VERSION ($UV_ZIEL) nach $UV_HOME (einmalig, ohne Adminrechte)"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  archiv="$tmp/uv.tar.gz"
  curl --proto '=https' --tlsv1.2 -fLsS -o "$archiv" \
    "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$UV_ZIEL.tar.gz" \
    || { log "Download fehlgeschlagen (Netz oder Proxy?)"; exit 1; }
  if command -v shasum >/dev/null 2>&1; then ist="$(shasum -a 256 "$archiv" | cut -d' ' -f1)"
  else ist="$(sha256sum "$archiv" | cut -d' ' -f1)"; fi
  if [ "$ist" != "$(sha256_von)" ]; then
    log "Prüfsumme stimmt nicht (erwartet $(sha256_von), erhalten $ist). Abbruch, nichts installiert."
    exit 1
  fi
  tar -xzf "$archiv" -C "$tmp"
  mkdir -p "$UV_HOME"
  cp "$tmp/uv-$UV_ZIEL/uv" "$UV_HOME/uv.neu" && chmod 755 "$UV_HOME/uv.neu" && mv "$UV_HOME/uv.neu" "$UV_HOME/uv"
  rm -rf "$tmp"; trap - EXIT
  log "uv $UV_VERSION installiert; erster Start lädt Python und Abhängigkeiten (ca. 1 Minute)"
}

if ! UV="$(finde_uv)"; then
  installiere_uv
  UV="$UV_HOME/uv"
fi

exec "$UV" run --quiet --frozen --directory "$PLUGIN_ROOT" mahnantrag-mcp
