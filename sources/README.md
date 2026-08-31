# sources/ — откуда тянуть списки

Смысл каталога простой: **не поддерживать руками то, что за нас уже ведут**.
Здесь перечислены живые внешние источники и лежат только те домены, которых
нет ни в одном из них.

Проверка на 2026-08-31: из наших 1159 direct-доменов внешние источники
покрывают 823, наших остаётся 336. Из 47 proxy-доменов покрыто 30, наших 17.
То есть руками поддерживается 353 записи вместо 1206.

## Что обновляется, а что нет

Даты последнего изменения на 2026-08-31:

| Источник | Обновлён | Звёзд |
|---|---|---:|
| `1andrevich/Re-filter-lists` | **сегодня** | 1304 |
| `v2fly/domain-list-community` | **сегодня** | 9421 |
| `haritos90/allow-domains` | 5 дней назад | 2 |
| `itdoginfo/allow-domains` | 7 дней назад | 1712 |
| `runetfreedom/russia-blocked-geosite` | 3 недели назад | 564 |
| `dartraiden/no-russia-hosts` | 3 недели назад | 362 |

Основными брать первые два. `itdoginfo` заметно отстаёт, хотя и самый
известный; `haritos90` свежее, но это личный репозиторий с двумя звёздами —
как единственный источник его брать не стоит.

## В туннель — домены

```
https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/domains_all.lst
https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/community.lst
https://raw.githubusercontent.com/haritos90/allow-domains/main/Russia/russia-all.lst
https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/inside-raw.lst
```

`domains_all.lst` — 78 740 доменов, основной. `russia-all.lst` — 1563,
`inside-raw.lst` — 1183, оба как дополнение.

## В туннель — сети

```
https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/ipsum.lst
https://raw.githubusercontent.com/1andrevich/Re-filter-lists/main/discord_ips.lst
https://raw.githubusercontent.com/haritos90/allow-domains/main/Subnets/IPv4/03-meta.lst
https://raw.githubusercontent.com/haritos90/allow-domains/main/Subnets/IPv4/04-telegram.lst
https://raw.githubusercontent.com/haritos90/allow-domains/main/Subnets/IPv4/05-twitter.lst
```

Сетей YouTube не существует ни у кого и не может существовать: его кэши GGC
стоят внутри сетей российских провайдеров. YouTube держится только на
доменных правилах.

## Мимо туннеля — домены

```
https://raw.githubusercontent.com/v2fly/domain-list-community/master/data/category-ru
https://raw.githubusercontent.com/haritos90/allow-domains/main/Russia/russia-outside.lst
https://raw.githubusercontent.com/itdoginfo/allow-domains/main/Russia/outside-raw.lst
```

`category-ru` **нельзя скачать одним файлом** — внутри 79 вложенных
`include:`, их надо разворачивать рекурсивно. В развёрнутом виде это 1788
российских доменов, из них 796 у нас отсутствуют. Логика разворачивания
лежит в `build_domains_list.py`.

Списки `outside` у haritos и itdog — это ресурсы, которые режут иностранные
адреса: госуслуги, налоговая, банки, РЖД. Им прямой маршрут обязателен.

## Мимо туннеля — сети

Внешнего источника нет, держим свой `testip.lst` — полное российское
IP-пространство, 8662 сети. Альтернатива: `direct_ip` у PassWall понимает
синтаксис `geoip:ru` и вытянет диапазон сам из `geoip.dat` (`nftables.sh:1018`).

## Наши файлы

| Файл | Записей | Что это |
|---|---:|---|
| `only-ours-direct.lst` | 336 | Мимо туннеля, нет ни в одном источнике |
| `only-ours-proxy.lst` | 17 | В туннель, нет ни в одном источнике |

В `only-ours-direct.lst` в основном то, что мы разгружали с ноды: прошивки
телефонов, репозитории пакетов, драйверы, дистрибутивы, десктопный софт,
китайские сервисы, игровые издатели. Такого не ведёт никто — чужие списки
занимаются блокировками, а не разгрузкой.

В `only-ours-proxy.lst` — своя инфраструктура и заблокированные ресурсы на
российском хостинге, которые перехватываются `testip.lst` по адресу.

## Сборка

```
proxy-domains = (Re-filter + haritos + itdog + only-ours-proxy) − direct-domains
proxy-ip      = Re-filter ipsum + discord_ips + подсети haritos
direct-domains= (category-ru + outside-списки + only-ours-direct)
direct-ip     = testip.lst либо geoip:ru
```

Вычитание direct из proxy обязательно и делается **при сборке**, а не на
роутере. Чужие списки местами захватывают лишнее: при сверке нашлось девять
пересечений, среди них `archlinux.org`, `windowsupdate.com`, `music.apple.com`
и `connectivitycheck.gstatic.com`. Ещё один случай — `2gis.com.cy` числится
заблокированным у Re-filter, хотя лежит в `category-ru` у v2fly.
