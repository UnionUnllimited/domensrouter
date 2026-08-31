#!/usr/bin/env python3
"""
Проверка маршрутизации с компьютера за роутером.

    python tools/check-routing.py            все группы
    python tools/check-routing.py ru         только российские
    python tools/check-routing.py block      только заблокированные
    python tools/check-routing.py -v         показывать адреса и время

Смысл: увидеть глазами, что схема «всё напрямую, кроме списка» работает.
Российские сайты должны открываться, заблокированные — тоже, но через
туннель. Если не открывается что-то из первой группы — список забрал
лишнее. Если из второй — списка не хватает.

Важно: скрипт намеренно игнорирует HTTP_PROXY и HTTPS_PROXY. На машине
может стоять свой VPN-клиент (например, на 127.0.0.1:10809), и запросы
через него проверяли бы его, а не роутер.
"""
import sys, ssl, json, time, socket, urllib.request, urllib.error, concurrent.futures

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VERBOSE = "-v" in sys.argv
ONLY = next((a for a in sys.argv[1:] if not a.startswith("-")), None)

GROUPS = {
    "ru": ("Российские — должны идти напрямую", [
        "gosuslugi.ru", "nalog.ru", "mos.ru", "rzd.ru", "sberbank.ru", "tbank.ru",
        "vk.com", "ok.ru", "mail.ru", "yandex.ru", "dzen.ru", "ozon.ru",
        "wildberries.ru", "avito.ru", "2gis.ru", "hh.ru", "kinopoisk.ru",
        "rutube.ru", "gismeteo.ru", "mts.ru",
    ]),
    "heavy": ("Тяжёлые незаблокированные — тоже напрямую", [
        "steampowered.com", "steamcommunity.com", "hoyoverse.com", "yuanshen.com",
        "xiaomi.com", "huawei.com", "samsung.com", "apple.com", "aliexpress.com",
        "npmjs.com", "rubygems.org", "almalinux.org", "blender.org", "twitch.tv",
    ]),
    "block": ("Заблокированные — должны идти через туннель", [
        "youtube.com", "googlevideo.com", "instagram.com", "facebook.com",
        "x.com", "discord.com", "telegram.org", "linkedin.com", "medium.com",
        "rutracker.org", "4pda.to", "notepad-plus-plus.org", "patreon.com",
        "openai.com", "spotify.com",
    ]),
    "infra": ("Своя инфраструктура — обязана быть напрямую", [
        "api1.titanvps.su", "vbotrouters.titanvps.click",
        "sub-routers.pandora361.online", "remna-vpn.pandora361.online",
    ]),
}

# Прокси окружения игнорируем: проверяем роутер, а не локальный клиент.
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                     urllib.request.HTTPSHandler(context=ctx))


def check(host):
    t0 = time.time()
    try:
        ip = socket.gethostbyname(host)
    except Exception:
        return host, None, None, "нет DNS", 0.0
    req = urllib.request.Request("https://%s/" % host, method="GET",
                                 headers={"User-Agent": "Mozilla/5.0"})
    # Две попытки: одиночный обрыв соединения — не диагноз.
    last = None
    for _ in range(2):
        try:
            with opener.open(req, timeout=12) as r:
                return host, ip, r.status, None, time.time() - t0
        except urllib.error.HTTPError as e:
            return host, ip, e.code, None, time.time() - t0
        except Exception as e:
            last = type(e).__name__
    return host, ip, None, last, time.time() - t0


def egress():
    for url in ("https://ipinfo.io/json", "https://api.myip.com"):
        try:
            with opener.open(urllib.request.Request(
                    url, headers={"User-Agent": "curl/8"}), timeout=12) as r:
                j = json.load(r)
            return j.get("ip"), j.get("country") or j.get("cc"), j.get("org", "")
        except Exception:
            continue
    return None, None, ""


ip, cc, org = egress()
print("внешний адрес: %s  страна: %s  %s" % (ip or "не определился", cc or "?", org))
print("если страна не RU — значит наружу идёт весь трафик, а не только список\n")

total_ok = total_bad = 0
for key, (title, hosts) in GROUPS.items():
    if ONLY and ONLY != key:
        continue
    print("== %s ==" % title)
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        for host, addr, code, err, dt in ex.map(check, hosts):
            ok = code is not None and code < 500
            total_ok += ok
            total_bad += not ok
            mark = "  ok  " if ok else "ПРОВАЛ"
            tail = ""
            if VERBOSE:
                tail = "  %-15s %4.1fс" % (addr or "-", dt)
            print("  %s %-32s %s%s" % (mark, host, code if ok else err, tail))
    print()

print("итог: открылось %d, не открылось %d" % (total_ok, total_bad))
if total_bad:
    print("\nЧто это значит:")
    print("  провал в группе «Российские» или «Своя инфраструктура»")
    print("     -> proxy-список забрал лишнее, домен уехал в туннель")
    print("  провал в группе «Заблокированные»")
    print("     -> домена нет в proxy-списке, он пошёл напрямую в блокировку")
    print("  провал в группе «Тяжёлые»")
    print("     -> проверьте вручную: часть CDN на корне не отвечает и это норма")
sys.exit(1 if total_bad else 0)
