#!/bin/sh
# ═══════════════════════════════════════════════════════════════════
#  Проверка доменных списков на роутере.
#
#  Для каждого домена: резолв через локальный DNS, определение
#  фактического маршрута по наборам nftables и, по желанию, HTTP-ответ.
#
#      sh router-check.sh                    chnlist, DNS и маршрут
#      sh router-check.sh gfwlist            другой список
#      sh router-check.sh chnlist --http     плюс HTTP (медленно)
#      sh router-check.sh chnlist --http 80  только первые 80 доменов
#
#  Колонка МАРШРУТ показывает, что решит ядро:
#      DIRECT   адрес в psw_chn      — мимо туннеля
#      TUNNEL   адрес в psw_gfw      — через туннель
#      BLACK    адрес в psw_black    — через туннель, ручной список
#      DEFAULT  ни в одном наборе    — по режиму по умолчанию
#
#  Для chnlist ожидается DIRECT, для gfwlist — TUNNEL. Всё остальное
#  помечается как РАСХОЖДЕНИЕ и попадает в итог.
# ═══════════════════════════════════════════════════════════════════

RULES=/usr/share/passwall/rules

# Первый аргумент — имя списка, только если это не флаг и не число.
LIST=chnlist
case "${1:-}" in
    "" | -* )   ;;
    *[!0-9]* )  LIST="$1"; shift ;;
esac

DO_HTTP=0
LIMIT=0
JOBS=16
for a in "$@"; do
    case "$a" in
        --http) DO_HTTP=1 ;;
        [0-9]*) LIMIT="$a" ;;
    esac
done

case "$LIST" in
    */*) FILE="$LIST" ;;
    *)   FILE="$RULES/$LIST" ;;
esac
[ -s "$FILE" ] || { echo "нет файла или он пуст: $FILE"; exit 1; }

case "$(basename "$FILE")" in
    chnlist)  EXPECT=DIRECT ;;
    gfwlist)  EXPECT=TUNNEL ;;
    *)        EXPECT=ANY ;;
esac

command -v nft >/dev/null 2>&1 || { echo "нет nft — роутер на iptables, скрипт не подойдёт"; exit 1; }

TMP=/tmp/router-check.$$
trap 'rm -f "$TMP" "$TMP".*' EXIT INT TERM

TOTAL=$(wc -l < "$FILE" | tr -d ' ')
[ "$LIMIT" -gt 0 ] 2>/dev/null && head -n "$LIMIT" "$FILE" > "$TMP".in || cp "$FILE" "$TMP".in
N=$(wc -l < "$TMP".in | tr -d ' ')

echo "список:   $FILE  ($N из $TOTAL)"
echo "ожидаем:  $EXPECT"
[ "$DO_HTTP" = 1 ] && echo "режим:    DNS + маршрут + HTTP" || echo "режим:    DNS + маршрут"
echo

resolve() {
    nslookup "$1" 127.0.0.1 2>/dev/null |
        awk '/^Address/ && $NF ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ {a=$NF} END{print a}'
}

route_of() {
    nft get element inet passwall psw_black "{ $1 }" >/dev/null 2>&1 && { echo BLACK;   return; }
    nft get element inet passwall psw_gfw   "{ $1 }" >/dev/null 2>&1 && { echo TUNNEL;  return; }
    nft get element inet passwall psw_chn   "{ $1 }" >/dev/null 2>&1 && { echo DIRECT;  return; }
    echo DEFAULT
}

one() {
    d="$1"
    ip=$(resolve "$d")
    if [ -z "$ip" ]; then
        printf '%s\t%s\t%s\t%s\n' "$d" "-" "NODNS" "-" >> "$TMP"
        return
    fi
    r=$(route_of "$ip")
    c="-"
    [ "$DO_HTTP" = 1 ] && c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "https://$d/" 2>/dev/null)
    [ -z "$c" ] && c="000"
    printf '%s\t%s\t%s\t%s\n' "$d" "$ip" "$r" "$c" >> "$TMP"
}

: > "$TMP"
i=0
while IFS= read -r d; do
    [ -n "$d" ] || continue
    one "$d" &
    i=$((i + 1))
    [ $((i % JOBS)) -eq 0 ] && wait
done < "$TMP".in
wait

# кириллица в printf меряется байтами, поэтому у заголовка ширина больше
printf '%-45s %-21s %-15s %s\n' ДОМЕН АДРЕС МАРШРУТ HTTP
sort "$TMP" | while IFS="$(printf '\t')" read -r d ip r c; do
    mark=""
    [ "$EXPECT" != ANY ] && [ "$r" != "$EXPECT" ] && [ "$r" != NODNS ] && mark=" <= РАСХОЖДЕНИЕ"
    printf '%-40s %-16s %-8s %s%s\n' "$d" "$ip" "$r" "$c" "$mark"
done

echo
echo "── итог ──"
echo "всего проверено:  $(wc -l < "$TMP" | tr -d ' ')"
echo "без DNS:          $(awk -F'\t' '$3=="NODNS"' "$TMP" | wc -l | tr -d ' ')"
echo "DIRECT:           $(awk -F'\t' '$3=="DIRECT"' "$TMP" | wc -l | tr -d ' ')"
echo "TUNNEL:           $(awk -F'\t' '$3=="TUNNEL"' "$TMP" | wc -l | tr -d ' ')"
echo "BLACK:            $(awk -F'\t' '$3=="BLACK"' "$TMP" | wc -l | tr -d ' ')"
echo "DEFAULT:          $(awk -F'\t' '$3=="DEFAULT"' "$TMP" | wc -l | tr -d ' ')"
if [ "$EXPECT" != ANY ]; then
    echo "расхождений:      $(awk -F'\t' -v e="$EXPECT" '$3!=e && $3!="NODNS"' "$TMP" | wc -l | tr -d ' ')"
fi
if [ "$DO_HTTP" = 1 ]; then
    echo "ответили HTTP:    $(awk -F'\t' '$4 ~ /^[1-5][0-9][0-9]$/ && $4!="000"' "$TMP" | wc -l | tr -d ' ')"
    echo "молчат:           $(awk -F'\t' '$4=="000"' "$TMP" | wc -l | tr -d ' ')"
fi
echo
echo "Молчащий домен — не обязательно ошибка: CDN-апексы вроде yastatic.net"
echo "и mycdn.me веб на корне не отдают, у них живут только поддомены."
