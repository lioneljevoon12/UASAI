"""
Alokasi uang anak kos: Forward Chaining vs Fuzzy Sugeno
Python 3, tanpa library tambahan.

Jalankan:
    python alokasi_fc_vs_sugeno.py                      # tes + demo perbandingan
    python alokasi_fc_vs_sugeno.py --saldo 500000 --hari 8 --B 30000

Input otomatis:
    jatah = saldo / max(sisa_hari, 1)
    r     = jatah / B           (B = biaya primer harian: makan + transport)

Semua angka aturan di bawah adalah CONTOH sampai ada data survei.
"""
import argparse
import random

B_DEFAULT = 30_000

# ---------------------------------------------------------------------------
# BASIS ATURAN (dipakai bersama oleh Forward Chaining dan Sugeno)
# (kategori jatah, kategori sisa hari) -> (Primer, Sekunder, Tersier), total 100
# ---------------------------------------------------------------------------
RULES = {
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


def hitung_input(saldo, sisa_hari, B=B_DEFAULT):
    jatah = saldo / max(sisa_hari, 1)  # max(...,1): hindari bagi nol di hari gajian
    return jatah, jatah / B


def peringatan(jatah, B=B_DEFAULT):
    if jatah < B:
        return "Dana tidak cukup untuk kebutuhan primer"
    return None


# ---------------------------------------------------------------------------
# FORWARD CHAINING
# Tahap 1: klasifikasi angka -> fakta. Tahap 2: aturan IF-THEN dipicu
# berulang sampai tidak ada fakta baru (inti forward chaining).
# Batas tegas = titik potong antar himpunan Sugeno (r=1,25 ; 2,25 ; 7,5 ; 17,5 hari).
# ---------------------------------------------------------------------------
def klasifikasi(r, sisa_hari):
    fakta = set()
    if r < 1.25:
        fakta.add("jatah=sedikit")
    elif r < 2.25:
        fakta.add("jatah=sedang")
    else:
        fakta.add("jatah=banyak")
    if sisa_hari <= 7.5:
        fakta.add("hari=dekat")
    elif sisa_hari <= 17.5:
        fakta.add("hari=sedang")
    else:
        fakta.add("hari=jauh")
    return fakta


# Aturan IF-THEN dibentuk dari tabel RULES: IF jatah=x AND hari=y THEN alokasi=...
FC_RULES = [
    (
        "R%d" % (i + 1),
        {"jatah=%s" % j, "hari=%s" % h},
        "alokasi=%d/%d/%d" % z,
        z,
    )
    for i, ((j, h), z) in enumerate(RULES.items())
]


def forward_chaining(saldo, sisa_hari, B=B_DEFAULT):
    jatah, r = hitung_input(saldo, sisa_hari, B)
    fakta = klasifikasi(r, sisa_hari)
    jejak, hasil = [], None
    berubah = True
    while berubah:  # ulangi sampai tidak ada aturan baru yang terpicu
        berubah = False
        for nama, kondisi, kesimpulan, z in FC_RULES:
            if kondisi <= fakta and kesimpulan not in fakta:
                fakta.add(kesimpulan)
                jejak.append("%s: IF %s THEN %s" % (nama, " AND ".join(sorted(kondisi)), kesimpulan))
                hasil = z
                berubah = True
    return {
        "jatah": jatah,
        "r": r,
        "persen": tuple(float(x) for x in hasil),
        "jejak": jejak,
        "peringatan": peringatan(jatah, B),
    }


# ---------------------------------------------------------------------------
# FUZZY SUGENO (orde nol): fuzzifikasi -> alpha = min -> rata-rata terbobot
# ---------------------------------------------------------------------------
def mu_jatah(r):
    sedikit = 1.0 if r <= 1 else max(0.0, (1.5 - r) / 0.5)
    if r <= 1 or r >= 2.5:
        sedang = 0.0
    elif r < 1.5:
        sedang = (r - 1) / 0.5
    elif r <= 2:
        sedang = 1.0
    else:
        sedang = (2.5 - r) / 0.5
    banyak = 0.0 if r <= 2 else 1.0 if r >= 2.5 else (r - 2) / 0.5
    return {"sedikit": sedikit, "sedang": sedang, "banyak": banyak}


def mu_hari(h):
    dekat = 1.0 if h <= 5 else max(0.0, (10 - h) / 5)
    if h <= 5 or h >= 20:
        sedang = 0.0
    elif h < 10:
        sedang = (h - 5) / 5
    elif h <= 15:
        sedang = 1.0
    else:
        sedang = (20 - h) / 5
    jauh = 0.0 if h <= 15 else 1.0 if h >= 20 else (h - 15) / 5
    return {"dekat": dekat, "sedang": sedang, "jauh": jauh}


def sugeno(saldo, sisa_hari, B=B_DEFAULT):
    jatah, r = hitung_input(saldo, sisa_hari, B)
    mj, mh = mu_jatah(r), mu_hari(sisa_hari)
    pembilang, penyebut, aktif = [0.0, 0.0, 0.0], 0.0, []
    for (j, h), z in RULES.items():
        alpha = min(mj[j], mh[h])  # operator AND = min
        if alpha > 0:
            aktif.append((j + "-" + h, alpha, z))
            penyebut += alpha
            for i in range(3):
                pembilang[i] += alpha * z[i]
    return {
        "jatah": jatah,
        "r": r,
        "persen": tuple(p / penyebut for p in pembilang),
        "aktif": aktif,
        "sum_alpha": penyebut,
        "peringatan": peringatan(jatah, B),
    }


# ---------------------------------------------------------------------------
# TES (angka sama dengan contoh di PDF dan di chat)
# ---------------------------------------------------------------------------
def dekat(a, b, tol=0.06):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def jalankan_tes():
    # Contoh 1: Rp500rb, 8 hari -> Sugeno 59,1 / 25,4 / 15,5
    s = sugeno(500_000, 8)
    assert dekat(s["persen"], (59.1, 25.4, 15.5)), s["persen"]
    assert abs(s["sum_alpha"] - 4 / 3) < 1e-9

    # Hanya satu aturan aktif -> Sugeno = konsekuen aturan = hasil FC
    for saldo, hari, harap in [(300_000, 4, (45, 30, 25)), (300_000, 20, (90, 10, 0))]:
        assert dekat(sugeno(saldo, hari)["persen"], harap)
        assert dekat(forward_chaining(saldo, hari)["persen"], harap)
    assert sugeno(300_000, 20)["peringatan"] is not None  # jatah 15rb < 30rb
    assert sugeno(300_000, 4)["peringatan"] is None

    # Interpolasi dua aturan: Rp450rb, 12 hari -> 75 / 17,5 / 7,5
    assert dekat(sugeno(450_000, 12)["persen"], (75, 17.5, 7.5))

    # Demo batas: jatah Rp37rb vs Rp38rb (sisa 12 hari)
    f37, f38 = forward_chaining(37_000 * 12, 12), forward_chaining(38_000 * 12, 12)
    assert f37["persen"] == (85, 12, 3) and f38["persen"] == (65, 23, 12)  # FC melompat 20 poin
    s37, s38 = sugeno(37_000 * 12, 12), sugeno(38_000 * 12, 12)
    assert dekat(s37["persen"], (75.7, 17.1, 7.2)) and dekat(s38["persen"], (74.3, 17.9, 7.8))

    # Sisa hari = 0 (hari gajian) tidak boleh error
    assert abs(sum(sugeno(100_000, 0)["persen"]) - 100) < 1e-9

    # Total selalu 100% untuk input acak
    random.seed(1)
    for _ in range(2000):
        saldo, hari = random.randint(10_000, 3_000_000), random.randint(0, 40)
        assert abs(sum(sugeno(saldo, hari)["persen"]) - 100) < 1e-9
        assert abs(sum(forward_chaining(saldo, hari)["persen"]) - 100) < 1e-9
    print("Semua tes lulus.\n")


def p1(persen):
    """Format 1 desimal dengan pembulatan ke atas di .x5 (sama dengan hitungan manual)."""
    return tuple(round(x + 1e-9, 1) for x in persen)


def cetak(saldo, hari, B=B_DEFAULT):
    f, s = forward_chaining(saldo, hari, B), sugeno(saldo, hari, B)
    print("Saldo Rp{:,.0f} | sisa {} hari | B Rp{:,.0f}".format(saldo, hari, B).replace(",", "."))
    print("  jatah/hari = Rp{:,.0f}  (r = {:.3f})".format(f["jatah"], f["r"]).replace(",", "."))
    print("  Forward Chaining  P/S/T = %.1f / %.1f / %.1f" % p1(f["persen"]))
    for j in f["jejak"]:
        print("     " + j)
    print("  Fuzzy Sugeno      P/S/T = %.1f / %.1f / %.1f" % p1(s["persen"]))
    for nama, a, z in s["aktif"]:
        print("     aturan %-14s alpha=%.3f  z=%s" % (nama, a, z))
    p = s["persen"]
    print("  Rupiah/hari (Sugeno): primer Rp{:,.0f} | sekunder Rp{:,.0f} | tersier Rp{:,.0f}".format(
        f["jatah"] * p[0] / 100, f["jatah"] * p[1] / 100, f["jatah"] * p[2] / 100).replace(",", "."))
    if s["peringatan"]:
        print("  PERINGATAN: " + s["peringatan"])
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--saldo", type=float)
    ap.add_argument("--hari", type=int)
    ap.add_argument("--B", type=float, default=B_DEFAULT)
    a = ap.parse_args()
    if a.saldo is not None and a.hari is not None:
        cetak(a.saldo, a.hari, a.B)
    else:
        jalankan_tes()
        print("== Perbandingan Forward Chaining vs Sugeno ==\n")
        for saldo, hari in [(37_000 * 12, 12), (38_000 * 12, 12), (500_000, 8), (300_000, 4), (300_000, 20)]:
            cetak(saldo, hari)