@echo off
rem Simulated Unity executable for dry runs
echo [unity_stub] Starting simulated run...
rem Sleep briefly to mimic activity
ping -n 2 127.0.0.1 >NUL
echo [unity_stub] Completed run.
exit /b 0
