# Keep the plugin's bundled engine identical to the working copy.
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$src = Join-Path $Root 'ptforge'
$dst = Join-Path $Root 'packages\dsh-ptforge\engine\ptforge'
if (-not (Test-Path $src)) { throw "missing source package: $src" }
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Get-ChildItem $src -Recurse -File |
    Where-Object { $_.FullName -notmatch '__pycache__' } |
    ForEach-Object {
        $rel = $_.FullName.Substring($src.Length + 1)
        $target = Join-Path $dst $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
        Copy-Item $_.FullName $target -Force
    }
$count = (Get-ChildItem $dst -Recurse -File).Count
$size = (Get-ChildItem $dst -Recurse -File | Measure-Object Length -Sum).Sum
"synced {0} files ({1:N2} MB)" -f $count, ($size / 1MB)
