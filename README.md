# Campus Lost & Found

Aplikasi web laporan barang hilang dan temuan untuk Fasilkom UI.

## Menjalankan aplikasi

Dari folder proyek, jalankan:

```bash
.venv/bin/python -m uvicorn web_app:app --reload
```

Buka <http://127.0.0.1:8000>. Biarkan Terminal tetap berjalan. Jika baru memasang proyek, buat lingkungan dengan `python3 -m venv .venv`, lalu jalankan `.venv/bin/python -m pip install -r requirements.txt` terlebih dahulu.

Jalankan di macOS atau Linux. Server web memakai penguncian file untuk melindungi penyimpanan JSON saat ada permintaan bersamaan.

## Pencocokan foto

Jalankan langkah persiapan ini sekali di folder proyek:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m src.photo_matching
```

Perintah kedua mengunduh [DINOv2 Small](https://huggingface.co/facebook/dinov2-small) ke `.model-cache/`. Setelah itu, server menjalankan pencocokan secara lokal. Foto laporan diproses dan disimpan di `data/report-photos/` tanpa metadata EXIF.

Saat membuat laporan, foto barang bersifat opsional. Pilih JPG, PNG, atau WebP dengan ukuran maksimal 8 MB. Sistem membandingkan laporan aktif hilang dengan laporan aktif temuan dan menampilkan hingga tiga **Kemungkinan cocok** di setiap kartu. Jika salah satu laporan tidak punya foto, sistem menggunakan kategori, judul, ciri, dan lokasi. Jika sebuah foto gagal diproses, pengguna dapat menghapus lampirannya dan tetap mengirim laporan.

Kemiripan foto dapat menunjukkan barang bermodel sama. Periksa ciri barang sebelum mengambilnya.

## Penitipan di satpam dan penutupan laporan

1. Setelah menyerahkan barang, buka kartu laporan dan pilih **Perbarui status → Dititipkan ke satpam**.
2. Isi nama atau lokasi pos, centang konfirmasi, lalu klik **Simpan status**. Lokasi pos tampil di kartu dan di hasil pencocokan. Laporan tetap aktif dan bisa ditemukan lewat filter **Di pos satpam**.
3. Setelah barang diambil pemilik, perbarui status menjadi **Barang sudah dikembalikan**. Laporan hilang juga bisa ditutup dengan alasan **Sudah ditemukan sendiri**. Pembatalan tetap tersedia.

Papan ini terbuka. Siapa pun yang dapat mengaksesnya bisa memperbarui status laporan tanpa PIN atau login.

## Pengujian

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tes memakai penyimpanan sementara sehingga tidak mengubah laporan pengguna. Untuk server uji terpisah, variabel lingkungan `CAMPUS_DATA_FILE` dapat diarahkan ke file JSON sementara.
