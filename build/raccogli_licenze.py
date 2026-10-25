"""Copia i testi di licenza delle librerie redistribuite nel pacchetto (cartella licenze/)."""
import shutil
import sys
from importlib.metadata import distributions
from pathlib import Path

venv, out = Path(sys.argv[1]), Path(sys.argv[2])
SKIP = {"pyinstaller", "pyinstaller-hooks-contrib", "pytest", "pluggy", "iniconfig", "pygments", "colorama",
        "altgraph", "pefile", "pywin32-ctypes", "setuptools", "packaging"}
site = venv / "Lib" / "site-packages"
index = ["Librerie di terze parti incluse nel pacchetto e relative licenze", ""]
for dist in sorted(distributions(path=[str(site)]), key=lambda d: d.metadata["Name"].lower()):
    name = dist.metadata["Name"]
    if name.lower() in SKIP:
        continue
    lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
    index.append(f"- {name} {dist.version}: {lic.splitlines()[0] if lic else 'vedi file'}")
    for f in dist.files or []:
        if any(k in f.name.upper() for k in ("LICENSE", "LICENCE", "COPYING", "NOTICE")):
            src = Path(dist.locate_file(f))
            if src.is_file():
                shutil.copyfile(src, out / f"{name}-{f.name}")
index += ["", "Python: Python Software Foundation License (https://docs.python.org/3/license.html).",
          "Modelli OCR PP-OCR (PaddleOCR, distribuiti con RapidOCR): Apache-2.0."]
(out / "ELENCO.txt").write_text("\n".join(index), encoding="utf-8")
print(f"{len(index)} voci di licenza")
