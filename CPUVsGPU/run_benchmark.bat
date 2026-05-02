@echo off
:: run_benchmark.bat — Lance run_benchmark.ps1 en contournant la restriction de signature
:: Usage : run_benchmark.bat [quick]

echo.
echo  Lancement du benchmark CPUVsGPU...
echo.

if "%1"=="quick" (
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_benchmark.ps1" -Quick
) else (
    powershell.exe -ExecutionPolicy Bypass -File "%~dp0run_benchmark.ps1"
)

echo.
pause
