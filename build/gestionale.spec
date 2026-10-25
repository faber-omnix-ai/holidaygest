# -*- mode: python ; coding: utf-8 -*-
# Build riproducibile: vedi docs/BUILD.md. Produce dist/AvviaGestionale/ (cartella autosufficiente).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = SPECPATH + "/.."
datas = [
    (ROOT + "/app/static", "app/static"),
    (ROOT + "/app/data", "app/data"),
    (ROOT + "/app/schema.sql", "app"),
]
datas += collect_data_files("rapidocr")          # modelli PP-OCR ONNX e configurazioni (Apache-2.0)
datas += collect_data_files("tzdata")            # fuso Europe/Rome senza database di sistema
datas += collect_data_files("reportlab")
hidden = collect_submodules("rapidocr") + collect_submodules("tzdata") + ["app.api"]

a = Analysis(
    [ROOT + "/AvviaGestionale.py"],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hidden,
    excludes=["pytest", "IPython", "matplotlib", "torch", "paddle", "openvino", "tensorflow", "pandas",
              "scipy", "fitz", "pymupdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AvviaGestionale", console=False,
          icon=ROOT + "/build/icona.ico", version=ROOT + "/build/versione.txt", upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="AvviaGestionale", upx=False)
