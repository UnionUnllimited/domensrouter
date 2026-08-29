# parts/ — категорийные части списков

В корне репозитория лежат три плоских списка:

| Файл | Механизм PassWall | Смысл |
|---|---|---|
| `test.lst` | `chnlist_url` при `chn_list 'direct'` | домены **мимо туннеля** |
| `testip.lst` | `chnroute_url` | сети **мимо туннеля** |
| `testproxy.lst` | `gfwlist_url` при `gfwlist_update '1'` | домены **через туннель** |

Всё, чего нет ни в одном списке, идёт по режиму по умолчанию.
При совпадении выигрывает proxy: в `iptables.sh` и `nftables.sh` правила
добавляются в порядке `use_proxy_list` → `use_gfw_list` → `chn_list`,
а срабатывает первое подходящее.

Здесь те же самые записи, разложенные по категориям, чтобы их можно было править
и пересобирать по частям. Плоские файлы в корне остаются на месте и являются
результатом сборки.

```sh
sh parts/build.sh
```

даёт все три файла, побайтово совпадающие с текущими. Собрать можно и
своим скриптом — формат частей тот же, что у плоских списков: одна запись в строке,
без комментариев и пустых строк.

Порядок сортировки при сборке: домены — байтовый (`LC_ALL=C sort -u`),
сети — числовой по адресу сети.

## parts/domains — 974 записи

| Файл | Записей | Что внутри |
|---|---:|---|
| `00-tld-zones.lst` | 15 | Целые зоны: `ru`, `su`, `by`, `moscow`, `tatar`, `yandex`, `ru.com`, `ru.net`. **13 из 15 PassWall отбрасывает** — `extract_domain()` в `rule_update.lua` требует точку в строке, поэтому голые TLD до роутера не доезжают. Доходят только `ru.com` и `ru.net`. Домены `*.ru` тянутся напрямую не из-за этих строк, а потому что их адреса попадают в `testip.lst` |
| `01-idn-zones.lst` | 15 | Кириллические зоны и домены в них (`xn--p1ai` = рф, `xn--80asehdb` = онлайн и др.) |
| `10-yandex.lst` | 69 | Яндекс и Yango, включая CDN и рекламные домены |
| `11-vk-mail.lst` | 106 | VK, Mail.ru, Одноклассники, ICQ, My.Games |
| `12-sber.lst` | 7 | Сбер и GigaChat |
| `20-banks-fintech.lst` | 38 | Банки, платёжные шлюзы, биржа, финтех |
| `21-marketplace-retail.lst` | 83 | Маркетплейсы, ритейл, классифайды |
| `22-travel-delivery-taxi.lst` | 22 | Авиа, такси, доставка, отели |
| `23-gov-health-edu.lst` | 24 | Медицина, образование, городские сервисы |
| `24-maps.lst` | 14 | 2ГИС во всех странах присутствия |
| `26-corporate.lst` | 8 | Сайты промышленных корпораций на `.com` (под санкциями, из-за рубежа часто недоступны) |
| `30-telecom.lst` | 6 | Операторы связи |
| `31-hosting-cloud-cdn.lst` | 71 | Хостинги, облака, CDN, конструкторы сайтов |
| `32-security-av.lst` | 84 | Антивирусы и ИБ: Kaspersky, Dr.Web, F6/Group-IB, Positive Technologies |
| `40-state-media.lst` | 111 | RT, Sputnik, Ruptly, ТАСС и прочее госмедиа. **Критично держать напрямую**: за рубежом эти домены блокируются, через туннель не откроются |
| `41-media-streaming.lst` | 36 | Онлайн-кинотеатры, музыка, ТВ, погода |
| `50-games.lst` | 30 | Игры и издатели, живые в РФ |
| `51-steam-valve.lst` | 18 | Steam и остальная Valve |
| `60-saas-martech.lst` | 118 | B2B SaaS, CRM, аналитика, виджеты, трекеры |
| `70-it-content.lst` | 16 | IT-медиа и сообщества, RuStore |
| `80-oss-updates.lst` | 16 | Свободный софт и обновления ОС |
| `90-ip-speed-check.lst` | 60 | Проверка IP, DNS-утечек и скорости. Напрямую, иначе покажут адрес туннеля |
| `99-other.lst` | 7 | Не поддалось классификации |

## parts/ip — 8662 сети

Владельцы определены bulk-whois Team Cymru по анонсирующей AS.

| Файл | Сетей | Что внутри |
|---|---:|---|
| `00-steam-valve.lst` | 11 | Сети Valve (AS32590). **Единственные не-RU в списке.** Добавлены, потому что Steam по IP иначе уходил в туннель |
| `10-ru-operators.lst` | 2545 | Магистральные и домовые операторы: Ростелеком, МТС, МегаФон, Билайн, ТТК, ЭР-Телеком, МГТС и др. |
| `20-ru-hosting-cloud.lst` | 805 | Хостинги и облака: Selectel, Beget, Timeweb, REG.RU, Cloud.ru и др. |
| `30-ru-bigtech.lst` | 189 | Собственные сети Яндекса, VK, Сбера, Касперского, маркетплейсов |
| `40-cdn-antiddos.lst` | 95 | CDN и защита от DDoS: EdgeCenter, Ngenix, DDoS-Guard, Qrator |
| `50-ru-unrouted.lst` | 738 | Выделены России, но сейчас не анонсируются. Оставлены на случай, когда поднимутся |
| `90-ru-other.lst` | 4279 | Прочие российские сети — длинный хвост из региональных провайдеров и корпоративных AS |

## parts/proxy — 111 доменов

Идут **через туннель**. Подключается как `gfwlist_url` (у PassWall это
единственный список прокси, который обновляется по URL; `proxy_host`
правится только локально). Списка прокси-адресов по URL не существует —
`gfwlist` принимает только домены.

| Файл | Записей | Что внутри |
|---|---:|---|
| `00-own-infra.lst` | 3 | Собственные панели: Nezha, Remnawave, titanvps.su |
| `10-dev-github.lst` | 14 | GitHub, Docker Hub, GitLab, Hugging Face, JetBrains, HashiCorp |
| `20-google-youtube.lst` | 10 | YouTube и его CDN |
| `30-meta.lst` | 14 | Instagram, Facebook, WhatsApp, Threads |
| `40-telegram.lst` | 8 | Telegram |
| `50-social.lst` | 19 | X, Discord, LinkedIn, Signal, Reddit, TikTok |
| `60-ai.lst` | 13 | OpenAI, Anthropic, Gemini, Perplexity, Midjourney |
| `70-media.lst` | 17 | Netflix, Spotify, Twitch, SoundCloud, Patreon |
| `80-saas-blocked.lst` | 13 | Notion, Figma, Slack, Zoom, Atlassian, PayPal |

### Чего здесь намеренно нет

`frp.pandora361.online`, `sub-routers.pandora361.online` и
`vbotrouters.titanvps.click` — канал удалённого доступа, подписка на ноды и
зеркало самих списков. Если завернуть их в туннель, то при упавшем туннеле
роутер не сможет ни обновить списки, ни получить ноды, ни быть доступным
снаружи — ровно тогда, когда это нужнее всего. Поэтому в `00-own-infra.lst`
добавлен только конкретный поддомен `remna-vpn.pandora361.online`,
а не вся зона `pandora361.online`.

## Что не кладём в direct

GitHub, YouTube, Instagram, Telegram и прочее заблокированное или замедленное.
Им нужен туннель — попав в `test.lst`, они перестанут открываться.
