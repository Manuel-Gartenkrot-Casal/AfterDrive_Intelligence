# opencode-server.ps1 — Levanta el server remoto de opencode para acceso local/en red.
#
# Dos modos:
#   - Modo <<web>> (default): sirve la WEB UI en el navegador del celular,
#     http://<ip>:<puerto>. Igual que el TUI: le escribís al agente y hace.
#   - Modo <<serve>>: server headless; desde el celular te conectás con
#     `opencode attach http://<ip>/<puerto>` (necesita un cliente opencode o termux).
#
# Uso:
#   .\opencode-server.ps1                                  # modo web, puerto 4096
#   .\opencode-server.ps1 -Mode web -Port 4096
#   $env:OPENCODE_SERVER_PASSWORD="..." ; .\opencode-server.ps1   # password propio
#
# Desde el CELULAR (misma red Wi-Fi):
#   - Modo web:  navegador ->  http://192.168.0.12:4096   (user: opencode / pass: la de arriba)
#
# Si no conecta: abrir el puerto en firewall una vez (consola admin):
#   netsh advfirewall firewall add rule name=opencode dir=in action=allow protocol=TCP localport=4096

param(
    [ValidateSet("web", "serve")]
    [string]$Mode = "web",
    [int]$Port = 4096,
    [string]$Hostname = "0.0.0.0",
    [string]$Username = "opencode"
)

$ErrorActionPreference = "Stop"

if (-not $env:OPENCODE_SERVER_PASSWORD) {
    $env:OPENCODE_SERVER_PASSWORD = -join ((48..122) | Get-Random -Count 12 | ForEach-Object { [char]$_ })
}

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  opencode server remoto ($Mode)" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  URL (local):   http://localhost:$Port"
Write-Host "  Hostname:      $Hostname"
Write-Host "  Username:      $Username"
Write-Host "  Password:      $env:OPENCODE_SERVER_PASSWORD"
Write-Host "--------------------------------------------------------------" -ForegroundColor Cyan
Write-Host "  Desde el CELULAR (misma red Wi-Fi):"
if ($Mode -eq "web") {
    Write-Host "  Navegador ->   http://192.168.0.12:$Port"
    Write-Host "  (user: $Username / pass: la de arriba)"
} else {
    Write-Host "  opencode attach http://192.168.0.12:$Port -u $Username -p <pass>"
}
Write-Host ""
Write-Host "  Si no anda, abrir el puerto en firewall (admin):"
Write-Host "  netsh advfirewall firewall add rule name=opencode dir=in action=allow protocol=TCP localport=$Port"
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host ""

opencode $Mode --hostname $Hostname --port $Port