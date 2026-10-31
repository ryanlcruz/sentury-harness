# Instala o Sentury num passo, no Windows, e termina no doctor.
#
#   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1 -SemNavegador -SemInterface
#
# Refazer e seguro: o venv e reaproveitado, e o que ja esta instalado nao muda.
param(
    [switch]$SemNavegador,
    [switch]$SemInterface
)

$ErrorActionPreference = "Stop"
$raiz = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Set-Location $raiz
# O acento em "Area de Trabalho" derruba o pytest-xdist sem isto.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Rodar([string]$exe, [string[]]$argumentos) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { throw "falhou: $exe $($argumentos -join ' ')" }
}

# O ambiente so e valido no 3.13 (o pandas fixado nao sobe no 3.14).
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Precisa do Python 3.13: winget install --id Python.Python.3.13 -e --scope user"
}
& py -3.13 -c "import sys" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Precisa do Python 3.13: winget install --id Python.Python.3.13 -e --scope user"
}

$python = Join-Path $raiz ".venv\Scripts\python.exe"
Write-Host "== venv (.venv, Python 3.13)"
if (-not (Test-Path $python)) { Rodar "py" @("-3.13", "-m", "venv", ".venv") }
# venv criado por outra ferramenta (uv, por exemplo) pode vir sem pip.
& $python -m pip --version *> $null
if ($LASTEXITCODE -ne 0) { Rodar $python @("-m", "ensurepip", "--upgrade") }
Rodar $python @("-m", "pip", "install", "--quiet", "--upgrade", "pip")

Write-Host "== dependencias"
Rodar $python @("-m", "pip", "install", "--quiet", "-e", "./sentury/plugins/robinbandit[yaml,providers,auth]")
Rodar $python @("-m", "pip", "install", "--quiet", "-e", ".[dev]")

if (-not $SemNavegador) {
    Write-Host "== navegador (Playwright)"
    Rodar $python @("-m", "pip", "install", "--quiet", "-e", ".[extras]")
    # O Chrome ou o Edge da maquina abrem pelo Playwright; o Chromium so vem sem eles.
    $instalado = & $python -c "from sentury.tools.navegador_local import navegador_instalado as n; print(n())"
    if ($instalado) {
        Write-Host "   usa o $instalado instalado; o Chromium do Playwright nao e baixado"
    } else {
        Rodar $python @("-m", "playwright", "install", "chromium")
    }
}

if (-not $SemInterface) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "== interface"
        Push-Location (Join-Path $raiz "sentury\client")
        try {
            Rodar "npm" @("ci", "--no-audit", "--no-fund")
            Rodar "npm" @("run", "build")
        } finally { Pop-Location }
    } else {
        Write-Host "== interface: npm nao encontrado, pulando (a API sobe sem ela)"
    }
}

Write-Host "== doctor"
& $python -m sentury.doctor
exit $LASTEXITCODE
