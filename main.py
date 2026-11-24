from src.models import Item
from src.manager import LostAndFoundManager

def print_item(item: Item):
    badge = "🔴 HILANG" if item.report_type == "LOST" else "🟢 DITEMUKAN"
    print(f"[{item.item_id}] {badge} | {item.title} ({item.category})")
    print(f"    Lokasi : {item.location} | Waktu: {item.created_at}")
    print(f"    Detail : {item.description}")
    print(f"    Kontak : {item.contact} | Status: {item.status}\n")

def main():
    manager = LostAndFoundManager()

    while True:
        print("=== SISTEM LOST & FOUND ===")
        print("1. Lapor Barang Hilang (LOST)")
        print("2. Lapor Barang Temuan (FOUND)")
        print("3. Lihat Semua Laporan Aktif")
        print("4. Cari Barang (Keyword)")
        print("5. Tandai Selesai / Dikembalikan (RESOLVED)")
        print("0. Keluar")

        choice = input("\nPilih menu (0-5): ").strip()

        if choice in ("1", "2"):
            r_type = "LOST" if choice == "1" else "FOUND"
            print(f"\n--- Form Laporan {r_type} ---")
            title = input("Nama Barang (cth: Tumbler Corkcicle Hitam): ").strip()
            category = input("Kategori (Elektronik/Dokumen/Kunci/Aksesoris/Lainnya): ").strip()
            location = input("Lokasi Kejadian: ").strip()
            desc = input("Ciri-ciri Spesifik: ").strip()
            contact = input("Kontak (WA/ID Line): ").strip()

            new_item = Item(title, category, r_type, location, desc, contact)
            matches = manager.add_report(new_item)
            print(f"\n✅ Laporan berhasil disimpan dengan ID: {new_item.item_id}")

            if matches:
                print("\n⚠️ DITEMUKAN KECOCOKAN POTENSIAL DI DATABASE:")
                for m in matches:
                    print_item(m)

        elif choice == "3":
            print("\n--- Daftar Laporan Aktif ---")
            active = [i for i in manager.items if i.status == "OPEN"]
            if not active:
                print("Belum ada laporan aktif.\n")
            for item in active:
                print_item(item)

        elif choice == "4":
            kw = input("\nMasukkan kata kunci (nama/lokasi/ciri): ").strip()
            results = manager.search_items(keyword=kw)
            print(f"\nDitemukan {len(results)} hasil:")
            for item in results:
                print_item(item)

        elif choice == "5":
            item_id = input("\nMasukkan ID Barang yang sudah selesai: ").strip()
            if manager.mark_resolved(item_id):
                print("✅ Status barang diperbarui menjadi RESOLVED.\n")
            else:
                print("❌ ID tidak ditemukan atau sudah berstatus RESOLVED.\n")

        elif choice == "0":
            print("Keluar dari program.")
            break
        else:
            print("Pilihan tidak valid.\n")

if __name__ == "__main__":
    main()
