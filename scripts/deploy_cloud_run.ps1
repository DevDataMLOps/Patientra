param(
    [Parameter(Mandatory)][ValidatePattern('^[a-z][a-z0-9-]{4,61}[a-z0-9]$')][string]$Project,
    [Parameter(Mandatory)][string]$ApprovedBundle,
    [string]$PythonCommand = 'python',
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]$')][string]$Region = 'us-east1',
    [ValidatePattern('^[a-z][a-z0-9-]{0,19}[a-z0-9]$')][string]$Service = 'patientra-api'
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$bundlePath = (Resolve-Path -LiteralPath $ApprovedBundle).Path
$bundleHash = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ((Get-Item -LiteralPath $bundlePath).Length -gt 65536) { throw 'Aggregate bundle exceeds Secret Manager size limit.' }
& $PythonCommand -c 'import sys; from pathlib import Path; from patientra.api.bundle import read_bundle; read_bundle(Path(sys.argv[1]), sys.argv[2])' $bundlePath $bundleHash
if ($LASTEXITCODE -ne 0) { throw 'Approved aggregate bundle validation failed.' }

function Invoke-Cloud {
    param([string[]]$CloudArguments)
    $result = & gcloud @CloudArguments
    if ($LASTEXITCODE -ne 0) { throw "Cloud operation failed: $($CloudArguments[0]) $($CloudArguments[1])" }
    return $result
}

Push-Location -LiteralPath $repository
$tokenPath = $null
try {
    $billing = Invoke-Cloud @('billing', 'projects', 'describe', $Project, '--format=value(billingEnabled)', '--quiet')
    if (($billing -join '').Trim().ToLowerInvariant() -ne 'true') {
        throw 'Billing must be enabled before deployment. No cloud resources have been changed.'
    }
    $uploads = @(Invoke-Cloud @('meta', 'list-files-for-upload'))
    $unexpected = @($uploads | Where-Object { $_ -notmatch '^(src[\\/].*\.py|Dockerfile|\.dockerignore|\.gcloudignore|pyproject\.toml|README\.md)$' })
    if ($unexpected.Count -gt 0) { throw 'Unexpected file in source-upload context; refusing deployment.' }
    $null = Invoke-Cloud @('services', 'enable', 'run.googleapis.com', 'cloudbuild.googleapis.com',
        'artifactregistry.googleapis.com', 'secretmanager.googleapis.com', 'iam.googleapis.com', "--project=$Project", '--quiet')
    $existingService = @(Invoke-Cloud @('run', 'services', 'list', "--project=$Project", "--region=$Region", "--filter=metadata.name=$Service", '--format=value(metadata.name)'))
    if ($existingService.Count -gt 0) { throw 'Service already exists; choose a new name or an explicitly reviewed revision update.' }
    $runtimeName, $buildName = "$Service-runtime", "$Service-build"
    $runtimeAccount = "$runtimeName@$Project.iam.gserviceaccount.com"
    $buildAccount = "$buildName@$Project.iam.gserviceaccount.com"
    foreach ($name in @($runtimeName, $buildName)) {
        $existing = @(Invoke-Cloud @('iam', 'service-accounts', 'list', "--project=$Project", "--filter=email:$name@", '--format=value(email)'))
        if ($existing.Count -eq 0) {
            $null = Invoke-Cloud @('iam', 'service-accounts', 'create', $name, "--project=$Project", '--quiet')
        }
    }
    $null = Invoke-Cloud @('projects', 'add-iam-policy-binding', $Project,
        "--member=serviceAccount:$buildAccount", '--role=roles/run.builder', '--condition=None', '--quiet')
    $tokenSecret, $bundleSecret = "$Service-token", "$Service-release"
    foreach ($name in @($tokenSecret, $bundleSecret)) {
        $existing = @(Invoke-Cloud @('secrets', 'list', "--project=$Project", "--filter=name:$name", '--format=value(name)'))
        if ($existing.Count -gt 0) { throw 'Deployment secret already exists; choose a new service name or an explicitly reviewed update.' }
    }
    $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 48
    $random.GetBytes($bytes)
    $random.Dispose()
    $apiToken = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $workDirectory = Join-Path $repository 'work'
    $null = New-Item -ItemType Directory -Path $workDirectory -Force
    $tokenPath = Join-Path $workDirectory ('cloud-api-token-' + [guid]::NewGuid().ToString('N') + '.tmp')
    [System.IO.File]::WriteAllText($tokenPath, $apiToken, [System.Text.UTF8Encoding]::new($false))
    $null = Invoke-Cloud @('secrets', 'create', $tokenSecret, '--replication-policy=automatic',
        "--data-file=$tokenPath", "--project=$Project", '--quiet')
    $null = Invoke-Cloud @('secrets', 'create', $bundleSecret, '--replication-policy=automatic',
        "--data-file=$bundlePath", "--project=$Project", '--quiet')
    foreach ($name in @($tokenSecret, $bundleSecret)) {
        $null = Invoke-Cloud @('secrets', 'add-iam-policy-binding', $name,
            "--member=serviceAccount:$runtimeAccount", '--role=roles/secretmanager.secretAccessor',
            '--condition=None', "--project=$Project", '--quiet')
    }
    $null = Invoke-Cloud @('run', 'deploy', $Service, '--source=.', "--project=$Project", "--region=$Region",
        "--service-account=$runtimeAccount", "--build-service-account=projects/$Project/serviceAccounts/$buildAccount",
        '--allow-unauthenticated', '--ingress=all', '--min-instances=0', '--max-instances=1',
        '--concurrency=10', '--memory=512Mi', '--cpu=1', '--timeout=30',
        "--set-env-vars=PATIENTRA_API_RELEASE_BUNDLE=/secrets/approved-release.json,PATIENTRA_API_BUNDLE_SHA256=$bundleHash",
        "--set-secrets=PATIENTRA_API_TOKEN=${tokenSecret}:1,/secrets/approved-release.json=${bundleSecret}:1", '--quiet')
    $url = (Invoke-Cloud @('run', 'services', 'describe', $Service, "--project=$Project", "--region=$Region", '--format=value(status.url)') -join '').Trim()
    if ($url -notmatch '^https://[a-z0-9-]+\.[a-z0-9.-]*run\.app$') { throw 'Unexpected public HTTPS endpoint.' }
    $headers = @{Authorization = "Bearer $apiToken"}
    $null = Invoke-RestMethod -Uri "$url/ready" -Headers $headers
    $overall = Invoke-RestMethod -Uri "$url/api/v1/overall" -Headers $headers
    $quality = Invoke-RestMethod -Uri "$url/api/v1/data-quality" -Headers $headers
    $status = Invoke-RestMethod -Uri "$url/api/v1/pipeline-status" -Headers $headers
    try {
        $null = Invoke-WebRequest -Uri "$url/api/v1/overall"
        throw 'Public API unexpectedly accepted an unauthenticated request.'
    } catch {
        if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 401) { throw }
    }
    [pscustomobject]@{url=$url;release_status=$status.release_status;current_freshness=$status.current_freshness;
        eligible_admissions=$overall.eligible_admissions;readmitted_admissions=$overall.readmitted_admissions;
        readmission_rate_pct=$overall.readmission_rate_pct;unresolved_identity_reviews=$quality.unresolved_identity_reviews;
        unauthenticated_http_status=401} | ConvertTo-Json
} finally {
    if ($tokenPath -and (Test-Path -LiteralPath $tokenPath)) { Remove-Item -LiteralPath $tokenPath }
    $apiToken = $null
    Pop-Location
}
