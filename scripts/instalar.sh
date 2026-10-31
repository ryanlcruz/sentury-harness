#!/usr/bin/env bash
# Instala o Sentury num passo, em Linux ou Mac, e termina no doctor.
#
#   bash scripts/instalar.sh            # tudo
#   bash scripts/instalar.sh --sem-navegador --sem-interface
#
# Refazer e seguro: o venv e reaproveitado, e o que ja esta instalado nao muda.
set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$raiz"

navegador=1
interface=1
for arg in "$@"; do
  case "$arg" in
    --sem-navegador) navegador=0 ;;
    --sem-interface) interface=0 ;;
    *) echo "opcao desconhecida: $arg" >&2; exit 2 ;;
  esac
done

# O ambiente so e valido no 3.13 (o pandas fixado nao sobe no 3.14).
python=""
for candidato in python3.13 python3; do
  if command -v "$candidato" >/dev/null 2>&1 && "$candidato" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 13))'; then
    python="$candidato"; break
  fi
done
if [ -z "$python" ]; then
  echo "Precisa do Python 3.13. Instale e rode de novo." >&2
  exit 1
fi

echo "== venv (.venv, $("$python" --version))"
[ -d .venv ] || "$python" -m venv .venv
# venv criado por outra ferramenta (uv, por exemplo) pode vir sem pip.
.venv/bin/python -m pip --version >/dev/null 2>&1 || .venv/bin/python -m ensurepip --upgrade >/dev/null
.venv/bin/python -m pip install --quiet --upgrade pip

echo "== dependencias"
.venv/bin/python -m pip install --quiet -e "./sentury/plugins/robinbandit[yaml,providers,auth]"
.venv/bin/python -m pip install --quiet -e ".[dev]"

if [ "$navegador" = 1 ]; then
  echo "== navegador (Playwright)"
  .venv/bin/python -m pip install --quiet -e ".[extras]"
  # O Chrome ou o Edge da máquina abrem pelo Playwright; o Chromium só vem sem eles.
  instalado=$(.venv/bin/python -c "from sentury.tools.navegador_local import navegador_instalado as n; print(n())")
  if [ -n "$instalado" ]; then
    echo "   usa o $instalado instalado; o Chromium do Playwright não é baixado"
  else
    .venv/bin/python -m playwright install chromium
  fi
fi

if [ "$interface" = 1 ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "== interface"
    (cd sentury/client && npm ci --no-audit --no-fund && npm run build)
  else
    echo "== interface: npm nao encontrado, pulando (a API sobe sem ela)"
  fi
fi

echo "== doctor"
.venv/bin/python -m sentury.doctor
