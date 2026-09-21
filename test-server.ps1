param($Port=4096, $Mode="web", $Hostname="0.0.0.0")

pushd "C:\Users\Manuel\Desktop\Productividad\AfterDrive_Intelligence"
& "C:\Users\Manuel\AppData\Roaming\npm\node_modules\opencode-ai\bin\opencode.exe" $Mode --port $Port --hostname $Hostname --print-logs > server.log 2>&1
popd