@echo off
echo ════════════════════════════════════════
echo   منافع الاقتصادية - تشغيل السيرفر
echo ════════════════════════════════════════
echo.
set PORT=7860
echo   جاري تشغيل السيرفر على Port %PORT%...
echo   افتح المتصفح على: http://localhost:%PORT%
echo   اضغط Ctrl+C لإيقاف السيرفر
echo.
python app.py
pause
