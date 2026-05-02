@echo off
:: setup.bat — Lance setup.ps1 en contournant la restriction de signature
:: Double-clique sur ce fichier OU lance-le depuis PowerShell

echo.
echo  Lancement du setup CPUVsGPU...
echo.

powershell.exe -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

echo.
pause
