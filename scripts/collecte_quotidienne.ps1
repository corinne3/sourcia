<#
.SYNOPSIS
    Collecte quotidienne SourcIA : sites prioritaires, puis suivi des liens.

.DESCRIPTION
    1. sourcia collect-sites   (sites actifs de config/sites.yaml : PDF, articles, rapport par site)
    2. sourcia check-links     (liens du catalogue : déplacés, morts, injoignables)

    Journal du jour : data\journal\collecte-AAAA-MM-JJ.log (les lancements du même jour s'ajoutent).
    Rapports JSON   : data\collecte\ et data\liens\ (historique + dernier.json).
    Code de sortie  : 0 si tout va bien ; 1 si un site est en échec ou si une étape a planté ;
                      2 si le projet n'est pas installé ; 3 si une collecte est déjà en cours.

    Le suivi des liens est lancé même si un site est en échec : les deux étapes sont indépendantes.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collecte_quotidienne.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collecte_quotidienne.ps1 -Site arvalis -MaxPages 20
#>
param(
    [string[]]$Site = @(),        # seulement ces sites (par défaut : tous les sites actifs)
    [int]$MaxPages = 0,           # pages visitées au plus par site (par défaut : la configuration)
    [string]$Config = ""          # fichier de configuration (par défaut : config\local.yaml)
)

$ErrorActionPreference = "Stop"
$Racine = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Racine ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "Python du projet introuvable : $Python (créer le .venv et installer le projet, voir le README)"
    exit 2
}

$Dossier = Join-Path $Racine "data\journal"
New-Item -ItemType Directory -Force $Dossier | Out-Null
$Journal = Join-Path $Dossier ("collecte-{0:yyyy-MM-dd}.log" -f (Get-Date))
$Verrou = Join-Path $Dossier "collecte.en-cours"

function Write-Journal([string]$Texte) {
    Write-Host $Texte
    Add-Content -Path $Journal -Value $Texte -Encoding UTF8
}

# une seule collecte à la fois (tâche planifiée + lancement à la main) ; un verrou de plus de 6 h est périmé
if ((Test-Path $Verrou) -and ((Get-Date) - (Get-Item $Verrou).LastWriteTime).TotalHours -lt 6) {
    Write-Journal ("{0:HH:mm} Collecte déjà en cours (verrou {1}) : rien n'est lancé." -f (Get-Date), $Verrou)
    exit 3
}
Set-Content -Path $Verrou -Value $PID

function Invoke-Sourcia([string]$Titre, [string[]]$Arguments) {
    Write-Journal ("`n===== {0:yyyy-MM-dd HH:mm} · {1} =====" -f (Get-Date), $Titre)
    $Sortie = [System.IO.Path]::GetTempFileName()
    $Erreurs = [System.IO.Path]::GetTempFileName()
    try {
        $Base = @("-W", "ignore", "-m", "sourcia.cli")
        if ($Config) { $Base += @("-c", $Config) }
        $Liste = ($Base + $Arguments) | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
        $p = Start-Process -FilePath $Python -ArgumentList $Liste -WorkingDirectory $Racine `
            -NoNewWindow -Wait -PassThru -RedirectStandardOutput $Sortie -RedirectStandardError $Erreurs
        foreach ($f in @($Sortie, $Erreurs)) {
            foreach ($ligne in (Get-Content -Path $f -Encoding UTF8)) {
                if ($ligne.Trim()) { Write-Journal $ligne }
            }
        }
        Write-Journal ("-> code de sortie {0}" -f $p.ExitCode)
        return $p.ExitCode
    }
    finally {
        Remove-Item -Force $Sortie, $Erreurs -ErrorAction SilentlyContinue
    }
}

$env:PYTHONIOENCODING = "utf-8"
try {
    $Collecte = @("collect-sites")
    foreach ($s in $Site) { $Collecte += @("--site", $s) }
    if ($MaxPages -gt 0) { $Collecte += @("--max-pages", "$MaxPages") }
    $CodeCollecte = Invoke-Sourcia "Collecte des sites" $Collecte

    $Liens = @("check-links")
    foreach ($s in $Site) { $Liens += @("--source", $s) }
    $CodeLiens = Invoke-Sourcia "Suivi des liens" $Liens
}
finally {
    Remove-Item -Force $Verrou -ErrorAction SilentlyContinue
}

if ($CodeCollecte -ne 0 -or $CodeLiens -ne 0) {
    Write-Journal "`nRésultat : À VÉRIFIER (un site en échec ou une étape a planté). Journal : $Journal"
    exit 1
}
Write-Journal "`nRésultat : OK. Journal : $Journal"
exit 0
