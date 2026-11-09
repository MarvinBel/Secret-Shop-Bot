@echo off
:: Fabrique dist\SecretShopBot.exe (Python + bibliotheques + Tesseract integres).
:: Prerequis sur TA machine : Python 3.12 et Tesseract installes (pas chez ceux a qui tu l'envoies).
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=python"
set "TESS=C:\Program Files\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" (
    echo Tesseract introuvable dans "%TESS%". Installe-le d'abord.
    pause
    exit /b 1
)

echo [1/3] Installation des outils...
"%PY%" -m pip install -q -r requirements.txt pyinstaller pefile || goto :erreur

echo [2/3] Preparation de Tesseract (strict necessaire)...
"%PY%" outils\preparer_tesseract.py "%TESS%" build\tesseract || goto :erreur

echo [3/3] Fabrication du .exe (1 a 3 minutes)...
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin ^
    --name SecretShopBot --icon icone.ico ^
    --add-data "build\tesseract;tesseract" --add-data "icone.ico;." ^
    e7_shop_bot.py || goto :erreur

echo.
echo Termine : dist\SecretShopBot.exe
pause
exit /b 0

:erreur
echo.
echo Echec de la fabrication (voir les messages ci-dessus).
pause
exit /b 1
