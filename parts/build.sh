#!/bin/sh
# Сборка плоских списков из категорийных частей.
#
#   parts/domains/*.lst  ->  test.lst
#   parts/ip/*.lst       ->  testip.lst
#
# Результат байт-в-байт совпадает с тем, что лежит в корне репозитория.
# Порядок сортировки повторяет исходный: домены — байтовый (LC_ALL=C),
# сети — числовой по адресу сети.
#
# Запуск из корня репозитория:  sh parts/build.sh

set -e
cd "$(dirname "$0")/.."

cat parts/domains/*.lst | LC_ALL=C sort -u > test.lst
cat parts/ip/*.lst | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n -u > testip.lst

echo "test.lst:   $(wc -l < test.lst) строк"
echo "testip.lst: $(wc -l < testip.lst) строк"
