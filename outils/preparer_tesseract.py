"""Liste les DLL dont tesseract.exe a réellement besoin (dépendances récursives), et copie
le strict nécessaire dans un dossier."""
import os, sys, shutil, pefile
src, dst = sys.argv[1], sys.argv[2]
local = {f.lower(): f for f in os.listdir(src) if f.lower().endswith(".dll")}
need, todo = set(), ["tesseract.exe"]
while todo:
    f = todo.pop()
    pe = pefile.PE(os.path.join(src, local.get(f.lower(), f)), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                           pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
        for e in getattr(pe, attr, []):
            n = e.dll.decode().lower()
            if n in local and n not in need:
                need.add(n); todo.append(n)
shutil.rmtree(dst, ignore_errors=True)
os.makedirs(os.path.join(dst, "tessdata"))
shutil.copy2(os.path.join(src, "tesseract.exe"), dst)
for n in sorted(need):
    shutil.copy2(os.path.join(src, local[n]), dst)
shutil.copy2(os.path.join(src, "tessdata", "eng.traineddata"), os.path.join(dst, "tessdata"))
size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(dst) for f in fs)
print(f"{len(need)} DLL nécessaires sur {len(local)} -> {size / 1e6:.1f} Mo")
print(", ".join(sorted(need)))
