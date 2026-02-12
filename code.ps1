param([string]$OutFile = "ALL_CODE.txt")

$skipDirs = @(".git","node_modules","dist","build",".venv",".idea",".vscode","__pycache__","data")
$denyExt  = @(
  ".png",".jpg",".jpeg",".gif",".bmp",".webp",".ico",".svg",
  ".pdf",".zip",".7z",".tar",".gz",".xz",
  ".mp3",".mp4",".mov",".avi",".ogg",".wav",
  ".woff",".woff2",".ttf",".eot",
  ".exe",".dll",".so",".dylib",".bin",".dat",
  ".db",".sqlite",".sqlite3",
  ".pcap",".har",".bak",
  ".log",".logg"
)
$denyNames = @(".env","ALL_CODE.txt")

function Test-BinaryLike([byte[]]$Bytes) {
  if ($Bytes.Length -eq 0) { return $false }
  if ($Bytes -contains 0x00) { return $true }
  $ctrl = 0
  foreach ($b in $Bytes) {
    if ( ($b -lt 0x09) -or ($b -ge 0x0E -and $b -le 0x1F) ) {
      if ($b -ne 0x09 -and $b -ne 0x0A -and $b -ne 0x0D) { $ctrl++ }
    }
  }
  return (($ctrl / [double]$Bytes.Length) -gt 0.30)
}

function Read-TextSmart([string]$Path) {
  $bytes = [System.IO.File]::ReadAllBytes($Path)
  if (Test-BinaryLike $bytes) { return $null }
  if ($bytes.Length -ge 3 -and $bytes[0]-eq 0xEF -and $bytes[1]-eq 0xBB -and $bytes[2]-eq 0xBF) {
    return [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
  }
  if ($bytes.Length -ge 2 -and $bytes[0]-eq 0xFF -and $bytes[1]-eq 0xFE) {
    return [System.Text.Encoding]::Unicode.GetString($bytes)           # UTF-16 LE
  }
  if ($bytes.Length -ge 2 -and $bytes[0]-eq 0xFE -and $bytes[1]-eq 0xFF) {
    return [System.Text.Encoding]::BigEndianUnicode.GetString($bytes)  # UTF-16 BE
  }
  try { return [System.Text.Encoding]::UTF8.GetString($bytes) }
  catch { return [System.Text.Encoding]::GetEncoding(1251).GetString($bytes) }
}

# get only tracked files
$files = git ls-files | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" }

# filter
$files = $files | Where-Object {
  $path = $_.Replace('\','/')
  foreach ($d in $skipDirs) { if ($path -like "$d/*" -or $path -like "*/$d/*") { return $false } }
  $ext = [System.IO.Path]::GetExtension($_).ToLowerInvariant()
  if ($denyExt -contains $ext) { return $false }
  $name = [System.IO.Path]::GetFileName($_)
  if ($denyNames -contains $name) { return $false }
  return $true
}

Remove-Item $OutFile -ErrorAction SilentlyContinue
Set-Content -Path $OutFile -Value "" -Encoding UTF8

foreach ($f in $files) {
  $text = $null
  try { $text = Read-TextSmart -Path $f } catch { $text = $null }
  if ($null -eq $text) { continue }

  Add-Content -Path $OutFile -Encoding UTF8 -Value "===== START: $f =====`r`n"
  Add-Content -Path $OutFile -Encoding UTF8 -Value $text
  Add-Content -Path $OutFile -Encoding UTF8 -Value "`r`n===== END: $f =====`r`n`r`n"
}

Write-Host ("Done -> {0}" -f $OutFile)
