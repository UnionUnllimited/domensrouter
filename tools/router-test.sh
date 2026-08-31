#!/bin/sh
# ═══════════════════════════════════════════════════════════════════
#  Titan Router — проверка маршрутизации с самого роутера
#
#      sh router-test.sh          обе группы
#      sh router-test.sh ru       только российские
#      sh router-test.sh out      только зарубежные
#
#  Для каждого домена: адрес от локального DNS, решение ядра по наборам
#  nftables и ответ сервера. Колонка ROUTE показывает не то, что написано
#  в списках, а то, что реально сработает — наборы опрашиваются в том же
#  порядке, в каком стоят правила.
#
#  Запускать на роутере. На VPS смысла нет: там нет ни PassWall, ни
#  таблицы inet passwall, и мерить нечего.
# ═══════════════════════════════════════════════════════════════════

set -u

RU="yandex.ru vk.com ok.ru mail.ru dzen.ru gosuslugi.ru sberbank.ru tbank.ru
    alfabank.ru ozon.ru wildberries.ru avito.ru hh.ru 2gis.ru rutube.ru
    kinopoisk.ru mts.ru rzd.ru dns-shop.ru gismeteo.ru"

OUT="google.com youtube.com instagram.com facebook.com x.com discord.com
     telegram.org github.com openai.com chatgpt.com wikipedia.org reddit.com
     netflix.com spotify.com twitch.tv tiktok.com linkedin.com whatsapp.com
     cloudflare.com steamcommunity.com"

WANT_RU=direct
WANT_OUT=TUNNEL
ONLY="${1:-all}"

command -v nft >/dev/null 2>&1 || { echo "нет nft — это не роутер"; exit 1; }
nft list table inet passwall >/dev/null 2>&1 || {
    echo "нет таблицы inet passwall — PassWall не запущен"; exit 1; }

resolve() {
    nslookup "$1" 127.0.0.1 2>/dev/null |
        awk '/^Address/ && $NF ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ {a=$NF} END{print a}'
}

# psw_chn ведёт туда, куда указывает chn_list: direct, proxy или 0.
# Считать его всегда прямым нельзя — при chn_list=proxy это туннель.
CHN=$(uci -q get passwall.@global[0].chn_list)
case "$CHN" in
    direct) CHN_GOES=direct ;;
    proxy)  CHN_GOES=TUNNEL ;;
    *)      CHN_GOES=skip ;;
esac
MODE=$(uci -q get passwall.@global[0].tcp_proxy_mode)

# Порядок как в nftables.sh: white -> black -> gfw -> chn -> замыкающее.
#
# У каждого набора есть парный *_static: обычный наполняется dnsmasq по
# мере запросов, статический — из файла правил при старте службы. Правила
# ставятся через nft_rule_dual, то есть на оба сразу. Опрашивать нужно
# тоже оба, иначе адрес из файла выглядит как «нигде не найден»: сетей в
# psw_chn_static было 11 731, а в psw_chn всего четыре.
in_set() {
    nft get element inet passwall "$1" "{ $2 }" >/dev/null 2>&1 && return 0
    nft get element inet passwall "${1}_static" "{ $2 }" >/dev/null 2>&1
}

route_of() {
    in_set psw_white "$1" && { echo direct; return; }
    in_set psw_black "$1" && { echo TUNNEL; return; }
    nft get element inet passwall psw_gfw "{ $1 }" >/dev/null 2>&1 && { echo TUNNEL; return; }
    if [ "$CHN_GOES" != skip ]; then
        in_set psw_chn "$1" && { echo "$CHN_GOES"; return; }
    fi
    # Ни в одном наборе: решает tcp_proxy_mode.
    if [ "$MODE" = "disable" ]; then
        echo direct
    else
        echo TUNNEL
    fi
}

run_group() {
    title="$1"; want="$2"; shift 2
    echo "== $title (ожидаем $want) =="
    printf '%-20s %-16s %-8s %s\n' DOMAIN ADDRESS ROUTE HTTP
    bad=0
    for d in $@; do
        ip=$(resolve "$d")
        if [ -z "$ip" ]; then
            printf '%-20s %-16s %-8s %s\n' "$d" "нет DNS" "-" "-"
            bad=$((bad + 1))
            continue
        fi
        r=$(route_of "$ip")
        c=$(curl -s --max-time 10 -o /dev/null -w '%{http_code} %{time_total}s' \
            "https://$d/" 2>/dev/null)
        [ -z "$c" ] && c="нет ответа"
        mark=""
        if [ "$r" != "$want" ]; then
            mark="  <= не туда"
            bad=$((bad + 1))
        fi
        printf '%-20s %-16s %-8s %s%s\n' "$d" "$ip" "$r" "$c" "$mark"
    done
    echo "расхождений: $bad"
    echo
}

echo "режим: tcp_proxy_mode=$(uci -q get passwall.@global[0].tcp_proxy_mode) \
chn_list=$(uci -q get passwall.@global[0].chn_list) \
gfw=$(uci -q get passwall.@global[0].use_gfw_list) \
proxy_list=$(uci -q get passwall.@global[0].use_proxy_list) \
direct_list=$(uci -q get passwall.@global[0].use_direct_list)"
echo

[ "$ONLY" = "all" ] || [ "$ONLY" = "ru" ]  && run_group "Российские"  "$WANT_RU"  $RU
[ "$ONLY" = "all" ] || [ "$ONLY" = "out" ] && run_group "Зарубежные"  "$WANT_OUT" $OUT

echo "ROUTE — решение ядра, а не запись в списке."
echo "Российский домен с TUNNEL: список забрал лишнее."
echo "Зарубежный с direct: домена нет в proxy-списке."
exit 0
