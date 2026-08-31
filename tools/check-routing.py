#!/usr/bin/env python3
"""
Проверка маршрутизации через роутер, минуя VPN на самом компьютере.

    python check-routing.py                     все группы
    python check-routing.py ru                  только российские
    python check-routing.py --list              показать интерфейсы и выйти
    python check-routing.py --src 192.168.1.5   задать адрес вручную
    python check-routing.py -v                  адреса и время

На машине обычно поднят свой VPN-клиент, и он забирает маршрут по
умолчанию. Тогда проверка уходит через него и говорит о клиенте, а не о
роутере. Поэтому здесь два обхода:

  * сокеты привязываются к адресу Wi-Fi (source address), и трафик идёт
    тем интерфейсом, что смотрит в роутер;
  * DNS спрашивается напрямую у шлюза, то есть у самого роутера. Это
    важно: именно его ответы наполняют наборы nftables, а системный
    резолвер через VPN дал бы совсем другую картину.

Группы и смысл провалов:
  Российские, Своя инфраструктура — proxy-список забрал лишнее
  Заблокированные                 — домена нет в списке, ушёл в блок
  Тяжёлые                         — смотреть руками, апексы CDN молчат
"""
import sys, os, re, ssl, json, time, socket, struct, random, subprocess
import http.client, urllib.request, urllib.error, concurrent.futures

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ARGS = sys.argv[1:]
VERBOSE = "-v" in ARGS
LIST_ONLY = "--list" in ARGS
SRC = ARGS[ARGS.index("--src") + 1] if "--src" in ARGS else None

GROUPS = {
    "ru": ("Российские — должны идти напрямую", [
        "gosuslugi.ru", "nalog.ru", "mos.ru", "rzd.ru", "sberbank.ru", "tbank.ru",
        "vk.com", "ok.ru", "mail.ru", "yandex.ru", "dzen.ru", "ozon.ru",
        "wildberries.ru", "avito.ru", "2gis.ru", "hh.ru", "kinopoisk.ru",
        "rutube.ru", "gismeteo.ru", "mts.ru",
    ]),
    "heavy": ("Тяжёлые незаблокированные — тоже напрямую", [
        "steampowered.com", "steamcommunity.com", "hoyoverse.com", "yuanshen.com",
        "xiaomi.com", "samsung.com", "apple.com", "aliexpress.com",
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
        "sub-routers.pandora361.online",
    ]),
}
ONLY = next((a for a in ARGS if a in GROUPS), None)


# ── интерфейсы ───────────────────────────────────────────────────
def interfaces():
    """[(имя, ip, шлюз)] — разбором ipconfig на Windows, ip route на прочих."""
    out = []
    if os.name == "nt":
        try:
            raw = subprocess.run(["ipconfig"], capture_output=True, timeout=15).stdout
        except Exception:
            return out
        txt = None
        for enc in ("cp866", "cp1251", "utf-8"):
            try:
                txt = raw.decode(enc)
                break
            except Exception:
                continue
        if txt is None:
            return out
        name, ip, gw = None, None, None
        for line in txt.splitlines():
            if line.strip() and not line.startswith(" "):
                if name and ip:
                    out.append((name, ip, gw))
                name, ip, gw = line.strip().rstrip(":"), None, None
            m = re.search(r"IPv4.*?:\s*([0-9.]+)", line)
            if m and ip is None:
                ip = m.group(1)
            m = re.search(r"(?:Default Gateway|Основной шлюз).*?:\s*([0-9.]+)", line)
            if m and gw is None:
                gw = m.group(1)
        if name and ip:
            out.append((name, ip, gw))
    else:
        try:
            txt = subprocess.run(["ip", "-4", "route"], capture_output=True,
                                 text=True, timeout=10).stdout
            for line in txt.splitlines():
                m = re.match(r"default via ([0-9.]+) dev (\S+).*src ([0-9.]+)", line)
                if m:
                    out.append((m.group(2), m.group(3), m.group(1)))
        except Exception:
            pass
    return out


def pick(ifaces):
    """Wi-Fi предпочтительнее: именно он смотрит в тестовый роутер."""
    routed = [i for i in ifaces if i[2]]
    for want in ("wi-fi", "wifi", "wireless", "беспровод", "wlan"):
        for i in routed:
            if want in i[0].lower():
                return i
    return routed[0] if routed else None


ifaces = interfaces()
if LIST_ONLY:
    for n, i, g in ifaces:
        print("  %-46s %-15s шлюз %s" % (n[:46], i, g or "нет"))
    sys.exit(0)

if SRC:
    chosen = next((i for i in ifaces if i[1] == SRC), ("задан вручную", SRC, None))
else:
    chosen = pick(ifaces)
if not chosen:
    print("не нашёл интерфейс со шлюзом. Запустите с --list и укажите --src")
    sys.exit(2)
IFNAME, SRC, GW = chosen
print("интерфейс: %s" % IFNAME)
print("адрес:     %s   шлюз, он же DNS роутера: %s" % (SRC, GW or "не найден"))


# ── DNS напрямую у роутера ───────────────────────────────────────
def dns_a(name, server, src, timeout=4):
    if not server:
        return None
    q = struct.pack(">HHHHHH", random.randint(0, 65535), 0x0100, 1, 0, 0, 0)
    for part in name.split("."):
        q += bytes([len(part)]) + part.encode()
    q += b"\x00" + struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((src, 0))
        s.settimeout(timeout)
        s.sendto(q, (server, 53))
        data, _ = s.recvfrom(2048)
    except Exception:
        return None
    finally:
        s.close()
    try:
        an = struct.unpack(">H", data[6:8])[0]
        i = 12
        while data[i]:
            i += data[i] + 1
        i += 5
        for _ in range(an):
            if data[i] & 0xC0:
                i += 2
            else:
                while data[i]:
                    i += data[i] + 1
                i += 1
            typ, _, _, dl = struct.unpack(">HHIH", data[i:i + 10])
            i += 10
            if typ == 1 and dl == 4:
                return socket.inet_ntoa(data[i:i + 4])
            i += dl
    except Exception:
        return None
    return None


# ── HTTPS: коннект по адресу от роутера, имя в SNI ───────────────
# Принципиальный момент. Если соединяться по имени, urllib и curl
# резолвят его СИСТЕМНЫМ резолвером, а он на этой машине смотрит в
# VPN-адаптер. Тогда адрес в отчёте роутерный, а коннект уходит совсем
# на другой — и проверка врёт. Поэтому соединяемся ровно на тот адрес,
# который дал роутер, а хост передаём в SNI и в заголовке Host.
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def fetch(host, ip, timeout=12):
    s = socket.create_connection((ip, 443), timeout=timeout, source_address=(SRC, 0))
    try:
        with ctx.wrap_socket(s, server_hostname=host) as ss:
            ss.settimeout(timeout)
            req = (
                "GET / HTTP/1.1\r\n"
                "Host: %s\r\n"
                "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
                "Accept: */*\r\n"
                "Connection: close\r\n\r\n" % host
            )
            ss.sendall(req.encode())
            head = ss.recv(256).decode("latin-1", "replace")
        return int(head.split(" ")[1])
    except Exception:
        raise
    finally:
        try:
            s.close()
        except Exception:
            pass


def check(host):
    t0 = time.time()
    ip = dns_a(host, GW, SRC)
    if ip is None:
        return host, None, None, "нет DNS от роутера", 0.0
    last = None
    for _ in range(2):
        try:
            return host, ip, fetch(host, ip), None, time.time() - t0
        except Exception as e:
            last = type(e).__name__
    return host, ip, None, last, time.time() - t0


def egress():
    ip = dns_a("ipinfo.io", GW, SRC)
    if not ip:
        return None, None, ""
    try:
        s = socket.create_connection((ip, 443), timeout=12, source_address=(SRC, 0))
        with ctx.wrap_socket(s, server_hostname="ipinfo.io") as ss:
            ss.sendall(b"GET /json HTTP/1.1\r\nHost: ipinfo.io\r\n"
                       b"User-Agent: curl/8\r\nConnection: close\r\n\r\n")
            buf = b""
            while True:
                c = ss.recv(4096)
                if not c:
                    break
                buf += c
        body = buf.split(b"\r\n\r\n", 1)[1]
        if body[:1] != b"{":
            body = body.split(b"\r\n", 1)[1]
        j = json.loads(body[:body.rfind(b"}") + 1])
        return j.get("ip"), j.get("country"), j.get("org", "")
    except Exception:
        return None, None, ""


eip, cc, org = egress()
print("внешний адрес: %s  страна: %s  %s" % (eip or "не определился", cc or "?", org))
if cc and cc != "RU":
    print("!! страна не RU. Либо схема не применилась и наружу идёт всё,")
    print("!! либо привязка к интерфейсу не сработала и запросы ушли в VPN.")
print()

ok_n = bad_n = 0
for key, (title, hosts) in GROUPS.items():
    if ONLY and ONLY != key:
        continue
    print("== %s ==" % title)
    with concurrent.futures.ThreadPoolExecutor(6) as ex:
        for host, addr, code, err, dt in ex.map(check, hosts):
            good = code is not None and code < 500
            ok_n += good
            bad_n += not good
            tail = "  %-15s %4.1fс" % (addr or "-", dt) if VERBOSE else ""
            print("  %s %-32s %s%s" % ("  ok  " if good else "ПРОВАЛ",
                                       host, code if good else err, tail))
    print()

print("итог: открылось %d, не открылось %d" % (ok_n, bad_n))
sys.exit(1 if bad_n else 0)
