#!/usr/bin/env python3
"""Genera un QR por póster. Uso: python3 make_qr.py https://tu-dominio.cl 8
Crea qr_p01.png ... qr_p08.png apuntando a https://tu-dominio.cl/#p01 ... (el id del póster viaja en el #)."""
import sys, qrcode
from qrcode.constants import ERROR_CORRECT_M
base = sys.argv[1].rstrip("/"); n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
if not base.startswith("https://"): sys.exit("Usa una URL https:// pública y definitiva.")
for i in range(1, n + 1):
    pid = f"p{i:02d}"
    img = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=20, border=4)
    img.add_data(f"{base}/#{pid}"); img.make(fit=True)
    img.make_image(fill_color="black", back_color="white").save(f"qr_{pid}.png")
    print("ok", pid, f"{base}/#{pid}")
