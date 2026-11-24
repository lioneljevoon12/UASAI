"""
Alokasi uang anak kos: VERSI DINAMIS (Forward Chaining + Fuzzy Sugeno)
Python 3, tanpa library tambahan.

"Dinamis" di sini berarti:
  - biaya primer harian (B), batas himpunan fuzzy, dan 9 aturan dibaca dari file
    aturan.json, jadi bisa diganti dari hasil survei TANPA mengubah kode;
  - input diketik langsung (mode interaktif);
  - config divalidasi otomatis (total aturan harus 100, himpunan harus valid).

Pemakaian:
    python alokasi_dinamis.py                       # mode interaktif
    python alokasi_dinamis.py --saldo 500000 --hari 8 --metode keduanya
    python alokasi_dinamis.py --config aturan.json  # pakai file config lain
    python alokasi_dinamis.py --tes                 # jalankan tes
    python alokasi_dinamis.py --tulis-config aturan.json   # buat template config

Semua angka bawaan adalah CONTOH sampai ada data survei.
"""
import argparse
import copy
import json
import sys
from itertools import product
from pathlib import Path

# === INTI (bagian ini juga dipakai di notebook Jupyter) =====================
INF = float("inf")

# (kategori jatah, kategori sisa hari) -> (Primer, Sekunder, Tersier), total 100
_TABEL = {
    ("sedikit", "dekat"): (80, 15, 5),
    ("sedikit", "sedang"): (85, 12, 3),
    ("sedikit", "jauh"): (90, 10, 0),
    ("sedang", "dekat"): (60, 25, 15),
    ("sedang", "sedang"): (65, 23, 12),
    ("sedang", "jauh"): (70, 22, 8),
    ("banyak", "dekat"): (45, 30, 25),
    ("banyak", "sedang"): (50, 30, 20),
    ("banyak", "jauh"): (55, 28, 17),
}

DEFAULT_CONFIG = {
    "_catatan": "Semua angka adalah CONTOH. Ganti dengan hasil survei/jurnal.",
    "B": 30000,  # biaya primer harian (makan + transport), Rp
    "kategori": ["primer", "sekunder", "tersier"],
    # Himpunan trapesium [a, b, c, d]; null = tak terhingga (bahu kiri/kanan)
    "input": {
        "jatah": {  # r = jatah per hari / B
            "sedikit": [None, None, 1, 1.5],
            "sedang": [1, 1.5, 2, 2.5],
            "banyak": [2, 2.5, None, None],
        },
        "hari": {  # sisa hari sampai gajian
            "dekat": [None, None, 5, 10],
            "sedang": [5, 10, 15, 20],
            "jauh": [15, 20, None, None],
        },
    },
    "aturan": [
        {"jika": {"jatah": j, "hari": h}, "maka": list(z)} for (j, h), z in _TABEL.items()
    ],
}

PESAN_PERINGATAN = "Dana tidak cukup untuk kebutuhan primer"
VARIABEL = ("jatah", "hari")


def muat_config(path=None):
    """path=None -> config bawaan. Selain itu baca JSON lalu validasi."""
    if path is None:
        return copy.deepcopy(DEFAULT_CONFIG)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _params(lst):
    a, b, c, d = lst
    a = -INF if a is None else float(a)
    b = -INF if b is None else float(b)
    c = INF if c is None else float(c)
    d = INF if d is None else float(d)
    if not (a <= b <= c <= d):
        raise ValueError("Titik trapesium harus a<=b<=c<=d: %s" % (lst,))
    return a, b, c, d


def validasi(cfg):
    """Raise ValueError jika config salah; return daftar peringatan (boleh kosong)."""
    peringatan = []
    n = len(cfg["kategori"])
    if cfg["B"] <= 0:
        raise ValueError("B harus > 0")
    for var in VARIABEL:
        if var not in cfg["input"] or not cfg["input"][var]:
            raise ValueError("Variabel input '%s' belum didefinisikan" % var)
        for nama, p in cfg["input"][var].items():
            if len(p) != 4:
                raise ValueError("Himpunan %s.%s harus punya 4 titik" % (var, nama))
            _params(p)
    for i, a in enumerate(cfg["aturan"], 1):
        if len(a["maka"]) != n:
            raise ValueError("Aturan R%d: jumlah konsekuen harus %d" % (i, n))
        if abs(sum(a["maka"]) - 100) > 1e-9:
            raise ValueError("Aturan R%d: total %s, harus 100" % (i, sum(a["maka"])))
        for var, s in a["jika"].items():
            if s not in cfg["input"].get(var, {}):
                raise ValueError("Aturan R%d: himpunan '%s' tidak ada di '%s'" % (i, s, var))
    ada = {tuple(a["jika"].get(v) for v in VARIABEL) for a in cfg["aturan"]}
    for kombinasi in product(*(cfg["input"][v] for v in VARIABEL)):
        if kombinasi not in ada:
            peringatan.append("Kombinasi %s belum punya aturan" % (kombinasi,))
    return peringatan


def trapezoid(x, a, b, c, d):
    if b <= x <= c:
        return 1.0
    if x < b:
        return 0.0 if x <= a else (x - a) / (b - a)
    return 0.0 if x >= d else (d - x) / (d - c)


def nilai_input(cfg, saldo, sisa_hari):
    jatah = saldo / max(sisa_hari, 1)  # max(...,1): hindari bagi nol di hari gajian
    return jatah, {"jatah": jatah / cfg["B"], "hari": float(sisa_hari)}


def derajat(cfg, crisp):
    return {
        var: {nama: trapezoid(crisp[var], *_params(p)) for nama, p in cfg["input"][var].items()}
        for var in crisp
    }


def _peringatan(cfg, jatah):
    return PESAN_PERINGATAN if jatah < cfg["B"] else None


def sugeno(cfg, saldo, sisa_hari):
    jatah, crisp = nilai_input(cfg, saldo, sisa_hari)
    mu = derajat(cfg, crisp)
    n = len(cfg["kategori"])
    pembilang, penyebut, aktif = [0.0] * n, 0.0, []
    for i, a in enumerate(cfg["aturan"], 1):
        alpha = min(mu[v][s] for v, s in a["jika"].items())  # AND = min
        if alpha > 0:
            aktif.append({"aturan": "R%d" % i, "jika": a["jika"], "alpha": alpha, "z": a["maka"]})
            penyebut += alpha
            for k in range(n):
                pembilang[k] += alpha * a["maka"][k]
    if penyebut == 0:
        raise ValueError("Tidak ada aturan aktif: cek himpunan dan aturan di config")
    return {
        "jatah": jatah, "r": crisp["jatah"], "derajat": mu, "aktif": aktif,
        "sum_alpha": penyebut, "persen": [p / penyebut for p in pembilang],
        "peringatan": _peringatan(cfg, jatah),
    }


def forward_chaining(cfg, saldo, sisa_hari):
    """Klasifikasi tegas (himpunan dengan derajat tertinggi; seri -> yang pertama
    di config) -> fakta -> aturan IF-THEN dipicu berulang sampai tidak ada fakta baru."""
    jatah, crisp = nilai_input(cfg, saldo, sisa_hari)
    mu = derajat(cfg, crisp)
    fakta = set()
    for var, himpunan in mu.items():
        if max(himpunan.values()) == 0:
            raise ValueError("Nilai %s di luar semua himpunan" % var)
        fakta.add("%s=%s" % (var, max(himpunan, key=himpunan.get)))
    jejak, hasil, berubah = [], None, True
    while berubah:
        berubah = False
        for i, a in enumerate(cfg["aturan"], 1):
            syarat = {"%s=%s" % (v, s) for v, s in a["jika"].items()}
            kesimpulan = "alokasi=" + "/".join(str(x) for x in a["maka"])
            if syarat <= fakta and kesimpulan not in fakta:
                fakta.add(kesimpulan)
                jejak.append("R%d: IF %s THEN %s" % (i, " AND ".join(sorted(syarat)), kesimpulan))
                if hasil is None:
                    hasil = a["maka"]
                berubah = True
    if hasil is None:
        raise ValueError("Tidak ada aturan yang cocok dengan fakta: %s" % sorted(fakta))
    return {
        "jatah": jatah, "r": crisp["jatah"], "fakta": sorted(fakta), "jejak": jejak,
        "persen": [float(x) for x in hasil], "peringatan": _peringatan(cfg, jatah),
    }


def rp(x):
    return "Rp" + "{:,.0f}".format(x).replace(",", ".")


def p1(persen):
    """Bulatkan 1 desimal, .x5 ke atas (sama dengan hitungan manual)."""
    return [round(x + 1e-9, 1) for x in persen]


# === AKHIR INTI =============================================================


def parse_rupiah(teks):
    """'500000', '500.000', '500rb', '500k', '1,5jt' -> float"""
    t = teks.strip().lower().replace("rp", "").replace(" ", "")
    faktor = 1
    for akhiran, f in (("jt", 1_000_000), ("rb", 1000), ("k", 1000)):
        if t.endswith(akhiran):
            t, faktor = t[: -len(akhiran)], f
            break
    t = t.replace(",", ".") if faktor == 1_000_000 else t.replace(".", "").replace(",", "")
    return float(t) * faktor


def config_ke_teks(cfg):
    """JSON yang rapi: satu himpunan/aturan per baris."""
    j = lambda v: json.dumps(v, ensure_ascii=False)
    baris = ["{", '  "_catatan": %s,' % j(cfg.get("_catatan", "")), '  "B": %s,' % j(cfg["B"]),
             '  "kategori": %s,' % j(cfg["kategori"]), '  "input": {']
    var_teks = []
    for var, himp in cfg["input"].items():
        isi = ",\n".join('      %s: %s' % (j(n), j(p)) for n, p in himp.items())
        var_teks.append('    %s: {\n%s\n    }' % (j(var), isi))
    baris.append(",\n".join(var_teks))
    baris.append("  },")
    baris.append('  "aturan": [')
    baris.append(",\n".join("    " + j(a) for a in cfg["aturan"]))
    baris.append("  ]")
    baris.append("}")
    return "\n".join(baris) + "\n"


def cetak_hasil(cfg, saldo, hari, metode):
    B = cfg["B"]
    jatah = saldo / max(hari, 1)
    print("\nSaldo %s | sisa %d hari | B %s" % (rp(saldo), hari, rp(B)))
    print("jatah/hari = %s  (r = %.3f)" % (rp(jatah), jatah / B))
    hasil = None
    if metode in ("fc", "keduanya"):
        f = forward_chaining(cfg, saldo, hari)
        print("\n[Forward Chaining]")
        for j in f["jejak"]:
            print("   " + j)
        print("   " + "  ".join("%s %.1f%%" % (k, v) for k, v in zip(cfg["kategori"], p1(f["persen"]))))
        hasil = f
    if metode in ("sugeno", "keduanya"):
        s = sugeno(cfg, saldo, hari)
        print("\n[Fuzzy Sugeno]")
        for a in s["aktif"]:
            print("   %s %s alpha=%.3f z=%s" % (
                a["aturan"], a["jika"], a["alpha"], a["z"]))
        print("   " + "  ".join("%s %.1f%%" % (k, v) for k, v in zip(cfg["kategori"], p1(s["persen"]))))
        hasil = s
    print("\nRupiah per hari (%s):" % ("Sugeno" if metode != "fc" else "Forward Chaining"))
    for k, v in zip(cfg["kategori"], hasil["persen"]):
        print("   %-9s %s" % (k, rp(jatah * v / 100)))
    if hasil["peringatan"]:
        print("\nPERINGATAN: " + hasil["peringatan"])
    print()


def interaktif(cfg):
    print("=== Alokasi Uang Anak Kos (versi dinamis) ===")
    print("Ketik 'q' kapan saja untuk keluar. Contoh saldo: 500000, 500.000, 500rb, 1,5jt")
    masuk = input("Biaya primer harian B [Enter = %s]: " % rp(cfg["B"])).strip()
    if masuk.lower() == "q":
        return
    if masuk:
        cfg["B"] = parse_rupiah(masuk)
    while True:
        m = input("Metode: [1] Forward Chaining  [2] Fuzzy Sugeno  [3] Keduanya (Enter=3): ").strip().lower()
        if m == "q":
            return
        metode = {"1": "fc", "2": "sugeno", "3": "keduanya", "": "keduanya"}.get(m)
        if metode:
            break
        print("Pilih 1, 2, atau 3.")
    while True:
        try:
            s = input("Saldo tersedia: ").strip()
            if s.lower() == "q":
                return
            saldo = parse_rupiah(s)
            h = input("Sisa hari sampai gajian: ").strip()
            if h.lower() == "q":
                return
            hari = int(h)
            if saldo < 0 or hari < 0:
                raise ValueError("Saldo dan sisa hari tidak boleh negatif")
            cetak_hasil(cfg, saldo, hari, metode)
        except ValueError as e:
            print("Input tidak valid: %s\n" % e)


def jalankan_tes():
    import random
    cfg = muat_config()
    assert validasi(cfg) == []

    def dekat(a, b, tol=0.06):
        return all(abs(x - y) <= tol for x, y in zip(a, b))

    s = sugeno(cfg, 500_000, 8)
    assert dekat(s["persen"], (59.1, 25.4, 15.5)) and abs(s["sum_alpha"] - 4 / 3) < 1e-9
    assert p1(s["persen"]) == [59.1, 25.4, 15.5]
    for saldo, hari, harap in [(300_000, 4, (45, 30, 25)), (300_000, 20, (90, 10, 0))]:
        assert dekat(sugeno(cfg, saldo, hari)["persen"], harap)
        assert dekat(forward_chaining(cfg, saldo, hari)["persen"], harap)
    assert sugeno(cfg, 300_000, 20)["peringatan"] and not sugeno(cfg, 300_000, 4)["peringatan"]
    assert dekat(sugeno(cfg, 450_000, 12)["persen"], (75, 17.5, 7.5))
    assert forward_chaining(cfg, 37_000 * 12, 12)["persen"] == [85.0, 12.0, 3.0]
    assert forward_chaining(cfg, 38_000 * 12, 12)["persen"] == [65.0, 23.0, 12.0]
    assert dekat(sugeno(cfg, 37_000 * 12, 12)["persen"], (75.7, 17.1, 7.2))
    assert abs(sum(sugeno(cfg, 100_000, 0)["persen"]) - 100) < 1e-9  # hari gajian

    # config dari file harus setara dengan bawaan
    berkas = Path(__file__).with_name("aturan.json")
    if berkas.exists():
        c2 = muat_config(berkas)
        assert validasi(c2) == []
        for saldo, hari in [(500_000, 8), (300_000, 4), (123_456, 17)]:
            assert dekat(sugeno(c2, saldo, hari)["persen"], sugeno(cfg, saldo, hari)["persen"], 1e-9)

    # dinamis: ubah B dan ubah satu aturan -> hasil ikut berubah
    c3 = muat_config()
    c3["B"] = 40_000
    assert sugeno(c3, 500_000, 8)["persen"] != sugeno(cfg, 500_000, 8)["persen"]
    c4 = muat_config()
    c4["aturan"][6]["maka"] = [40, 30, 30]
    assert dekat(sugeno(c4, 300_000, 4)["persen"], (40, 30, 30))

    # validasi menangkap config yang salah
    def harus_error(ubah):
        c = muat_config()
        ubah(c)
        try:
            validasi(c)
        except ValueError:
            return True
        return False

    assert harus_error(lambda c: c["aturan"][0].update({"maka": [80, 15, 6]}))   # total 101
    assert harus_error(lambda c: c["input"]["jatah"].update({"sedikit": [None, None, 2, 1]}))
    assert harus_error(lambda c: c["aturan"][0].update({"jika": {"jatah": "kaya", "hari": "dekat"}}))
    c5 = muat_config()
    c5["aturan"].pop()
    assert len(validasi(c5)) == 1  # kombinasi banyak-jauh hilang -> peringatan

    # total selalu 100% untuk input acak
    random.seed(1)
    for _ in range(2000):
        saldo, hari = random.randint(10_000, 3_000_000), random.randint(0, 40)
        assert abs(sum(sugeno(cfg, saldo, hari)["persen"]) - 100) < 1e-9
        assert abs(sum(forward_chaining(cfg, saldo, hari)["persen"]) - 100) < 1e-9

    # parser rupiah
    assert parse_rupiah("500.000") == 500000 and parse_rupiah("500rb") == 500000
    assert parse_rupiah("1,5jt") == 1_500_000 and parse_rupiah("Rp 750k") == 750000
    print("Semua tes lulus.")


def main():
    ap = argparse.ArgumentParser(description="Alokasi uang anak kos (dinamis)")
    ap.add_argument("--config", help="file JSON aturan (default: aturan.json di folder skrip, jika ada)")
    ap.add_argument("--saldo", help="mis. 500000, 500rb, 1,5jt")
    ap.add_argument("--hari", type=int)
    ap.add_argument("--B", help="override biaya primer harian")
    ap.add_argument("--metode", choices=["fc", "sugeno", "keduanya"], default="keduanya")
    ap.add_argument("--tes", action="store_true")
    ap.add_argument("--tulis-config", metavar="FILE", help="tulis template config lalu keluar")
    a = ap.parse_args()

    if a.tulis_config:
        Path(a.tulis_config).write_text(config_ke_teks(DEFAULT_CONFIG), encoding="utf-8")
        print("Template config ditulis ke", a.tulis_config)
        return
    if a.tes:
        jalankan_tes()
        return

    default_file = Path(__file__).with_name("aturan.json")
    path = a.config or (default_file if default_file.exists() else None)
    try:
        cfg = muat_config(path)
        info = validasi(cfg)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        sys.exit("Config bermasalah: %s" % e)
    print("Config: %s" % (path or "bawaan (contoh)"))
    for p in info:
        print("  Peringatan config:", p)
    if a.B:
        cfg["B"] = parse_rupiah(a.B)

    if a.saldo is not None and a.hari is not None:
        cetak_hasil(cfg, parse_rupiah(a.saldo), a.hari, a.metode)
    else:
        interaktif(cfg)


if __name__ == "__main__":
    main()
