#!/usr/bin/env python3
"""
Проверка списков маршрутизации.

    python parts/check.py            быстрые офлайн-проверки
    python parts/check.py --dns      плюс резолв: обоснована ли каждая
                                     запись в proxy и не мёртв ли домен

Запускать из корня репозитория. Ненулевой код возврата — что-то не так.
"""
import sys, os, glob, ipaddress, bisect

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DNS = "--dns" in sys.argv
errors, warns = [], []


def err(m): errors.append(m)
def warn(m): warns.append(m)


def read(p):
    return [l.rstrip("\n") for l in open(p, encoding="utf-8")]


# == как PassWall разбирает строку домена (rule_update.lua, extract_domain) ==
def extract_domain(s):
    start = last_dot = None
    for i, ch in enumerate(s, 1):
        b = ord(ch)
        if (48 <= b <= 57) or (65 <= b <= 90) or (97 <= b <= 122) or b == 45 or b == 46:
            if start is None:
                start = i
            if b == 46:
                last_dot = i
        else:
            if start is not None:
                if last_dot and last_dot > start:
                    return s[start - 1:i - 1].lstrip(".")
                start = last_dot = None
    if start is not None and last_dot and last_dot > start:
        return s[start - 1:].lstrip(".")
    return None


def load_parts(sub, kind):
    """Читает parts/<sub>/*.lst, ругается на формат, возвращает {запись: файл}."""
    out, seen = {}, {}
    for path in sorted(glob.glob(os.path.join("parts", sub, "*.lst"))):
        name = os.path.basename(path)
        for n, line in enumerate(read(path), 1):
            if line != line.strip():
                err(f"{name}:{n} лишние пробелы: {line!r}")
            e = line.strip()
            if not e:
                err(f"{name}:{n} пустая строка")
                continue
            if e.startswith("#"):
                err(f"{name}:{n} комментарий — сборка склеивает файлы как есть")
                continue
            if kind == "domain":
                if e != e.lower():
                    err(f"{name}:{n} верхний регистр: {e}")
                if not extract_domain(e):
                    warn(f"{name}:{n} PassWall отбросит (нет точки): {e}")
            else:
                try:
                    net = ipaddress.ip_network(e)
                except ValueError as ex:
                    err(f"{name}:{n} не CIDR: {e} ({ex})")
                    continue
                if net.version != 4:
                    err(f"{name}:{n} не IPv4: {e}")
                if net.is_private or net.is_loopback or net.is_multicast:
                    err(f"{name}:{n} служебный диапазон: {e}")
            if e in seen:
                err(f"дубль {e}: {seen[e]} и {name}")
            seen[e] = name
            out[e] = name
    return out


print("== формат частей ==")
dom = load_parts("domains", "domain")
ips = load_parts("ip", "ip")
prx = load_parts("proxy", "domain")
print(f"  parts/domains  {len(dom)}")
print(f"  parts/ip       {len(ips)}")
print(f"  parts/proxy    {len(prx)}")

# == сборка воспроизводит корневые файлы ==
print("== сборка ==")
def check_build(parts, root, keyfn):
    if not os.path.exists(root):
        err(f"нет файла {root}")
        return
    built = sorted(set(parts), key=keyfn)
    actual = [l.strip() for l in read(root) if l.strip()]
    if built != actual:
        only_b = set(built) - set(actual)
        only_a = set(actual) - set(built)
        err(f"{root} расходится со сборкой: только в частях {len(only_b)}, "
            f"только в файле {len(only_a)}")
        for x in list(only_b)[:5]:
            err(f"   только в частях: {x}")
        for x in list(only_a)[:5]:
            err(f"   только в {root}: {x}")
    else:
        print(f"  {root} сходится ({len(actual)})")

bytesort = lambda s: s.encode()
netsort = lambda s: (int(ipaddress.ip_network(s).network_address),
                     ipaddress.ip_network(s).prefixlen)
check_build(dom, "test.lst", bytesort)
check_build(ips, "testip.lst", netsort)
check_build(prx, "testproxy.lst", bytesort)

# == сети: перекрытия ==
print("== сети ==")
nets = sorted((ipaddress.ip_network(x) for x in ips), key=lambda n: int(n.network_address))
ov = 0
for a, b in zip(nets, nets[1:]):
    if int(b.network_address) <= int(a.broadcast_address):
        err(f"перекрываются {a} и {b}")
        ov += 1
        if ov > 10:
            err("   ...дальше не показываю")
            break
if not ov:
    print(f"  перекрытий нет, {len(nets)} сетей / {sum(n.num_addresses for n in nets)} адресов")

# == direct против proxy ==
print("== direct против proxy ==")
both = sorted(set(dom) & set(prx))
for d in both:
    err(f"{d} есть и в direct, и в proxy")
if not both:
    print("  точных пересечений нет")

starts = [int(n.network_address) for n in nets]
def net_of(ip):
    a = int(ipaddress.ip_address(ip))
    i = bisect.bisect_right(starts, a) - 1
    return nets[i] if i >= 0 and a <= int(nets[i].broadcast_address) else None

def parents(d):
    p = d.split(".")
    return [".".join(p[i:]) for i in range(1, len(p))]

if DNS:
    import socket, concurrent.futures
    socket.setdefaulttimeout(4)

    def resolve(d):
        try:
            return d, sorted({r[4][0] for r in socket.getaddrinfo(d, None, socket.AF_INET)})
        except Exception:
            return d, []

    print("== обоснованность proxy (резолв) ==")
    with concurrent.futures.ThreadPoolExecutor(40) as ex:
        res = dict(ex.map(resolve, prx))
    for d in sorted(prx):
        ip_hit = next((net_of(i) for i in res[d] if net_of(i)), None)
        par = [p for p in parents(d) if p in dom]
        if not res[d]:
            warn(f"{d} не резолвится — обоснование не проверить")
        elif ip_hit:
            print(f"  ok  {d} -> {res[d][0]} в {ip_hit}")
        elif par:
            print(f"  ok  {d} <- родитель {par[0]} в direct")
        else:
            warn(f"{d} ничем из direct не перекрывается — запись лишняя, "
                 f"домен и так уйдёт в туннель")

print()
for w in warns:
    print("ПРЕДУПРЕЖДЕНИЕ:", w)
for e in errors:
    print("ОШИБКА:", e)
print(f"\nитог: ошибок {len(errors)}, предупреждений {len(warns)}")
sys.exit(1 if errors else 0)
