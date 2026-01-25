#!/bin/sh

# --- БЛОК 0: ПРОВЕРКА СЕТИ И ПОДГОТОВКА ---
echo ">>> Шаг 0: Проверка сетевого подключения..."
if ! ping -c 1 -W 5 8.8.8.8 > /dev/null 2>&1; then
  echo "ОШИБКА: Нет доступа к интернету. Пожалуйста, проверьте подключение роутера."
  exit 1
fi
echo ">>> Сеть доступна."
echo ""

# --- БЛОК 1: УСТАНОВКА ПАКЕТОВ ---
echo ">>> Шаг 1: Установка PassWall и необходимых зависимостей..."

# 1.1. Добавление GPG ключа
wget -O /tmp/passwall.pub https://master.dl.sourceforge.net/project/openwrt-passwall-build/passwall.pub
opkg-key add /tmp/passwall.pub

# 1.2. Безопасное добавление репозиториев
DISTRIB_RELEASE=$(grep "DISTRIB_RELEASE" /etc/openwrt_release | cut -d "'" -f 2 | cut -d "." -f 1,2)
DISTRIB_ARCH=$(grep "DISTRIB_ARCH" /etc/openwrt_release | cut -d "'" -f 2)
LUCI_FEED_URL="src/gz passwall_luci https://master.dl.sourceforge.net/project/openwrt-passwall-build/releases/packages-${DISTRIB_RELEASE}/${DISTRIB_ARCH}/passwall_luci"
PACKAGES_FEED_URL="src/gz passwall_packages https://master.dl.sourceforge.net/project/openwrt-passwall-build/releases/packages-${DISTRIB_RELEASE}/${DISTRIB_ARCH}/passwall_packages"

if ! grep -q "passwall_luci" /etc/opkg/customfeeds.conf; then
  echo $LUCI_FEED_URL >> /etc/opkg/customfeeds.conf
fi
if ! grep -q "passwall_packages" /etc/opkg/customfeeds.conf; then
  echo $PACKAGES_FEED_URL >> /etc/opkg/customfeeds.conf
fi

# 1.3. Обновление списка пакетов с 3 попытками
echo "Обновление списков пакетов..."
for i in 1 2 3; do
  echo "Попытка $i из 3..."
  rm -f /var/opkg-lists/*
  opkg update
  if [ $? -eq 0 ]; then
    echo "Списки пакетов успешно обновлены."
    break
  fi
  if [ $i -lt 3 ]; then
    echo "Ошибка обновления, ждем 10 секунд перед повторной попыткой..."
    sleep 10
  else
    echo "КРИТИЧЕСКАЯ ОШИБКА: Не удалось обновить списки пакетов после 3 попыток."
    exit 1
  fi
done

# 1.4. Принудительное удаление dnsmasq
echo "Принудительное удаление стандартного dnsmasq..."
opkg remove dnsmasq >/dev/null 2>&1

# 1.5. Установка основных пакетов с 3 попытками
echo "Установка основных пакетов..."
for i in 1 2 3; do
  echo "Попытка установки $i из 3..."
  opkg install luci-app-passwall dnsmasq-full xray-core chinadns-ng ipset ipt2socks iptables-mod-tproxy
  if [ $? -eq 0 ] && opkg list-installed | grep -q "luci-app-passwall"; then
    echo "Основные пакеты успешно установлены."
    break
  fi
  if [ $i -lt 3 ]; then
    echo "Ошибка установки, ждем 10 секунд перед повторной попыткой..."
    sleep 10
  else
    echo "КРИТИЧЕСКАЯ ОШИБКА: Не удалось установить пакеты после 3 попыток."
    exit 1
  fi
done

echo ">>> Установка пакетов завершена."
echo ""

# --- БЛОК 2: УСИЛЕНИЕ БЕЗОПАСНОСТИ ---
echo ">>> Шаг 2: Усиление безопасности системы..."
uci -q delete network.globals.ula_prefix
for iface in lan wan; do
    uci -q set network.${iface}.ipv6='0'
done
if uci -q get network.wan6 >/dev/null; then
    uci set network.wan6.proto='none'
    uci -q delete network.wan6.ifname
fi
uci set dhcp.lan.dhcpv6='disabled'
uci set dhcp.lan.ra='disabled'
uci -q delete firewall.lan.ip6class
uci -q delete firewall.wan.ip6class

uci add firewall redirect >/dev/null
uci set firewall.@redirect[-1].name='Force-DNS-Hijack'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].proto='tcp udp'
uci set firewall.@redirect[-1].src_dport='53'
uci set firewall.@redirect[-1].dest_port='53'
uci set firewall.@redirect[-1].target='DNAT'

uci add firewall rule >/dev/null
uci set firewall.@rule[-1].name='Block-STUN-for-WebRTC'
uci set firewall.@rule[-1].src='lan'
uci set firewall.@rule[-1].dest='wan'
uci set firewall.@rule[-1].proto='udp'
uci set firewall.@rule[-1].dest_port='3478 3479 5349'
uci set firewall.@rule[-1].target='DROP'

uci commit
/etc/init.d/network restart
/etc/init.d/firewall restart
echo ">>> Усиление безопасности завершено."
echo ""

# --- БЛОК 3: ИНТЕРАКТИВНЫЙ ВВОД ПОДПИСКИ ---
echo ">>> Шаг 3: Настройка подписки..."
echo "Пожалуйста, вставьте ссылку на вашу подписку и нажмите Enter:"
read -r SUB_URL
if [ -z "$SUB_URL" ]; then
  echo "Ошибка: Ссылка на подписку не была введена. Прерывание скрипта."
  exit 1
fi
echo ">>> Ссылка на подписку принята."
echo ""

# --- БЛОК 4: КОНФИГУРАЦИЯ PASSWALL ---
echo ">>> Шаг 4: Применение вашей персональной конфигурации PassWall..."
uci -q delete passwall
# (Здесь идет ваш большой блок команд uci set... он остается без изменений)
uci set passwall.global=global
uci set passwall.global.enabled='1'
uci set passwall.global.socks_enabled='0'
uci set passwall.global.filter_proxy_ipv6='0'
uci set passwall.global.dns_shunt='chinadns-ng'
uci set passwall.global.dns_mode='xray'
uci set passwall.global.remote_dns='1.1.1.1'
uci add_list passwall.global.smartdns_remote_dns='https://1.1.1.1/dns-query'
uci set passwall.global.dns_redirect='1'
uci set passwall.global.use_gfw_list='0'
uci set passwall.global.chn_list='proxy'
uci set passwall.global.tcp_proxy_mode='disable'
uci set passwall.global.udp_proxy_mode='disable'
uci set passwall.global.localhost_proxy='1'
uci set passwall.global.client_proxy='1'
uci set passwall.global.acl_enable='0'
uci set passwall.global.log_tcp='1'
uci set passwall.global.log_udp='1'
uci set passwall.global.loglevel='debug'
uci set passwall.global.trojan_loglevel='4'
uci set passwall.global.log_chinadns_ng='1'
uci set passwall.global.force_https_soa='1'
uci set passwall.global.tcp_node_socks_port='1080'
uci set passwall.global.use_block_list='0'
uci set passwall.global.v2ray_dns_mode='tcp+doh'
uci set passwall.global.remote_dns_doh='https://8.8.8.8/dns-query'
uci set passwall.global.use_direct_list='0'
uci set passwall.global_haproxy=global_haproxy
uci set passwall.global_haproxy.balancing_enable='0'
uci set passwall.global_delay=global_delay
uci set passwall.global_delay.start_daemon='1'
uci set passwall.global_delay.start_delay='60'
uci set passwall.global_forwarding=global_forwarding
uci set passwall.global_forwarding.tcp_no_redir_ports='disable'
uci set passwall.global_forwarding.udp_no_redir_ports='disable'
uci set passwall.global_forwarding.tcp_proxy_drop_ports='disable'
uci set passwall.global_forwarding.udp_proxy_drop_ports='443'
uci set passwall.global_forwarding.tcp_redir_ports='1:65535'
uci set passwall.global_forwarding.udp_redir_ports='1:65535'
uci set passwall.global_forwarding.accept_icmp='0'
uci set passwall.global_forwarding.prefer_nft='1'
uci set passwall.global_forwarding.tcp_proxy_way='redirect'
uci set passwall.global_forwarding.ipv6_tproxy='0'
uci set passwall.global_xray=global_xray
uci set passwall.global_xray.sniffing_override_dest='0'
uci set passwall.global_xray.fragment='0'
uci set passwall.global_xray.noise='0'
uci set passwall.global_singbox=global_singbox
uci set passwall.global_singbox.sniff_override_destination='0'
uci set passwall.global_other=global_other
uci set passwall.global_other.auto_detection_time='tcping'
uci set passwall.global_other.show_node_info='0'
uci set passwall.global_other.enable_group_balancing='1'
uci set passwall.global_rules=global_rules
uci set passwall.global_rules.auto_update='0'
uci set passwall.global_rules.chnlist_update='1'
uci set passwall.global_rules.chnroute_update='0'
uci set passwall.global_rules.chnroute6_update='0'
uci set passwall.global_rules.gfwlist_update='0'
uci set passwall.global_rules.geosite_update='0'
uci set passwall.global_rules.geoip_update='0'
uci add_list passwall.global_rules.gfwlist_url='https://cdn.jsdelivr.net/gh/Loyalsoldier/v2ray-rules-dat@release/gfw.txt'
uci set passwall.global_rules.v2ray_location_asset='/usr/share/v2ray/'
uci set passwall.global_rules.geoip_url='https://github.com/Loyalsoldier/geoip/releases/latest/download/geoip.dat'
uci set passwall.global_rules.geosite_url='https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat'
uci set passwall.global_rules.geo2rule='0'
uci set passwall.global_rules.enable_geoview='0'
uci add_list passwall.global_rules.chnlist_url='http://origin.all-streams-24.ru/domenchik.lst'
uci add_list passwall.global_rules.chnlist_url='https://raw.githubusercontent.com/UnionUnllimited/domensrouter/refs/heads/main/manual.lst'
uci add_list passwall.global_rules.chnlist_url='https://storage.yandexcloud.net/domenchik/domenchik.lst'
uci add_list passwall.global_rules.chnlist_url='https://raw.githubusercontent.com/UnionUnllimited/domensrouter/refs/heads/main/domenchik.lst'
uci set passwall.global_app=global_app
uci set passwall.global_app.sing_box_file='/usr/bin/sing-box'
uci set passwall.global_app.xray_file='/usr/bin/xray'
uci set passwall.global_app.hysteria_file='/usr/bin/hysteria'
uci set passwall.global_subscribe=global_subscribe
uci set passwall.global_subscribe.filter_keyword_mode='2'
uci set passwall.global_subscribe.ss_type='xray'
uci set passwall.global_subscribe.trojan_type='xray'
uci set passwall.global_subscribe.vmess_type='xray'
uci set passwall.global_subscribe.vless_type='xray'
uci add_list passwall.global_subscribe.filter_keep_list='Router_'
SUB_ID=$(uci add passwall subscribe_list)
uci set passwall.${SUB_ID}.remark='AtlantaRouter'
uci set passwall.${SUB_ID}.url="${SUB_URL}"
uci set passwall.${SUB_ID}.allowInsecure='0'
uci set passwall.${SUB_ID}.filter_keyword_mode='5'
uci set passwall.${SUB_ID}.ss_type='global'
uci set passwall.${SUB_ID}.trojan_type='global'
uci set passwall.${SUB_ID}.vmess_type='global'
uci set passwall.${SUB_ID}.vless_type='global'
uci set passwall.${SUB_ID}.domain_strategy='global'
uci set passwall.${SUB_ID}.auto_update='1'
uci set passwall.${SUB_ID}.week_update='8'
uci set passwall.${SUB_ID}.interval_update='1'
uci set passwall.${SUB_ID}.user_agent='passwall'
BALANCING_NODE_ID=$(uci add passwall nodes)
uci set passwall.${BALANCING_NODE_ID}.remarks='AtlantaSwitch'
uci set passwall.${BALANCING_NODE_ID}.type='Xray'
uci set passwall.${BALANCING_NODE_ID}.protocol='_balancing'
uci set passwall.${BALANCING_NODE_ID}.balancingStrategy='leastPing'
uci set passwall.${BALANCING_NODE_ID}.useCustomProbeUrl='1'
uci set passwall.${BALANCING_NODE_ID}.probeUrl='https://www.google.com/generate_204'
uci set passwall.${BALANCING_NODE_ID}.probeInterval='5m'
uci add_list passwall.${BALANCING_NODE_ID}.balancing_node=''
NODE_1_ID=$(uci add passwall nodes)
uci set passwall.${NODE_1_ID}.remarks='Router_Finland_1'
uci set passwall.${NODE_1_ID}.group='AtlantaRouter'
uci set passwall.${NODE_1_ID}.type='Xray'
uci set passwall.${NODE_1_ID}.protocol='vless'
uci set passwall.${NODE_1_ID}.address='171.22.114.82'
uci set passwall.${NODE_1_ID}.port='8444'
uci set passwall.${NODE_1_ID}.uuid='77081c57-b7af-40d9-90a4-29fffd2bef59'
uci set passwall.${NODE_1_ID}.encryption='none'
uci set passwall.${NODE_1_ID}.flow='xtls-rprx-vision'
uci set passwall.${NODE_1_ID}.transport='raw'
uci set passwall.${NODE_1_ID}.security='reality'
uci set passwall.${NODE_1_ID}.reality_publicKey='HvLgNF130dDx79APv_HflZ7zFPy3smQS07W_VvZJDxM'
uci set passwall.${NODE_1_ID}.tls_serverName='pimg.mycdn.me'
uci set passwall.${NODE_1_ID}.fingerprint='random'
uci set passwall.${NODE_1_ID}.utls='1'
NODE_2_ID=$(uci add passwall nodes)
uci set passwall.${NODE_2_ID}.remarks='Router_Netherlands_1'
uci set passwall.${NODE_2_ID}.group='AtlantaRouter'
uci set passwall.${NODE_2_ID}.type='Xray'
uci set passwall.${NODE_2_ID}.protocol='vless'
uci set passwall.${NODE_2_ID}.address='176.222.53.230'
uci set passwall.${NODE_2_ID}.port='8444'
uci set passwall.${NODE_2_ID}.uuid='77081c57-b7af-40d9-90a4-29fffd2bef59'
uci set passwall.${NODE_2_ID}.encryption='none'
uci set passwall.${NODE_2_ID}.flow='xtls-rprx-vision'
uci set passwall.${NODE_2_ID}.transport='raw'
uci set passwall.${NODE_2_ID}.security='reality'
uci set passwall.${NODE_2_ID}.reality_publicKey='HvLgNF130dDx79APv_HflZ7zFPy3smQS07W_VvZJDxM'
uci set passwall.${NODE_2_ID}.tls_serverName='pimg.mycdn.me'
uci set passwall.${NODE_2_ID}.fingerprint='random'
uci set passwall.${NODE_2_ID}.utls='1'
NODE_3_ID=$(uci add passwall nodes)
uci set passwall.${NODE_3_ID}.remarks='Router_Foreign_Bridge_1'
uci set passwall.${NODE_3_ID}.group='AtlantaRouter'
uci set passwall.${NODE_3_ID}.type='Xray'
uci set passwall.${NODE_3_ID}.protocol='vless'
uci set passwall.${NODE_3_ID}.address='91.218.115.214'
uci set passwall.${NODE_3_ID}.port='8444'
uci set passwall.${NODE_3_ID}.uuid='77081c57-b7af-40d9-90a4-29fffd2bef59'
uci set passwall.${NODE_3_ID}.encryption='none'
uci set passwall.${NODE_3_ID}.flow='xtls-rprx-vision'
uci set passwall.${NODE_3_ID}.transport='raw'
uci set passwall.${NODE_3_ID}.security='reality'
uci set passwall.${NODE_3_ID}.reality_publicKey='iXJP7ECVE9Rd9iSX18GlrmSI7AQiD9c03Q8ZixMfj0k'
uci set passwall.${NODE_3_ID}.tls_serverName='pimg.mycdn.me'
uci set passwall.${NODE_3_ID}.fingerprint='random'
uci set passwall.${NODE_3_ID}.utls='1'
uci set passwall.@global[0].tcp_node="${BALANCING_NODE_ID}"
uci set passwall.@global[0].udp_node="${BALANCING_NODE_ID}"

echo ">>> Применение конфигурации PassWall завершено."
echo ""

# --- БЛОК 5: ОБНОВЛЕНИЕ И ПЕРЕЗАПУСК ---
echo ">>> Шаг 5: Сохранение, обновление списков и перезапуск службы..."
uci commit passwall
echo "Конфигурация сохранена."
echo "Запуск обновления подписки... Это может занять некоторое время."
/usr/share/passwall/app.sh "subscribe_update"
echo "Обновление подписки завершено."
/etc/init.d/passwall restart
echo "Служба PassWall перезапущена."
echo ""
echo ">>> Автоматическая настройка PassWall полностью завершена!"
echo ""

# --- БЛОК 6: УСТАНОВКА ПАТЧА ---
echo ">>> Шаг 6: Установка патча для выбора групп в узлах балансировки..."
# (Здесь идет ваш скрипт-патч, он остается без изменений)
cat > /tmp/install.sh << 'FINALSCRIPT'
#!/bin/sh
echo "=========================================="
echo "PassWall Group Selection Installer"
echo "=========================================="
if [ ! -d /usr/lib/lua/luci/model/cbi/passwall ]; then
    echo "ОШИБКА: PassWall не установлен!"
    exit 1
fi
echo "✓ PassWall найден"
BACKUP_DIR="/tmp/passwall-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"
[ -f /usr/lib/lua/luci/model/cbi/passwall/client/type/ray.lua ] && cp /usr/lib/lua/luci/model/cbi/passwall/client/type/ray.lua "$BACKUP_DIR/"
echo "✓ Бэкап создан: $BACKUP_DIR"
mkdir -p /usr/lib/lua/luci/view/passwall/cbi
cat > /usr/lib/lua/luci/view/passwall/cbi/subscribe_groups.htm << 'EOF1'
<%+cbi/valueheader%>
<%
    local uci = require "luci.model.uci".cursor()
    local groups = {}
    local current_values = {}
    local current_raw = self:cfgvalue(section)
    if type(current_raw) == "table" then
        for _, v in ipairs(current_raw) do current_values[v] = true end
    elseif type(current_raw) == "string" and current_raw ~= "" then
        current_values[current_raw] = true
    end
    local group_stats = {}
    uci:foreach("passwall", "nodes", function(s)
        if s.type and s.remarks and s.protocol ~= "_balancing" then
            local group_name = s.group or "default"
            group_stats[group_name] = (group_stats[group_name] or 0) + 1
        end
    end)
    uci:foreach("passwall", "nodes", function(s)
        if s.protocol == "_balancing" and s.balancing_node and s[".name"] ~= section then
            local count = 0
            local node_list = s.balancing_node
            if type(node_list) == "table" then
                count = #node_list
            elseif type(node_list) == "string" and node_list ~= "" then
                for _ in string.gmatch(node_list, "%S+") do count = count + 1 end
            end
            if count > 0 then
                table.insert(groups, {
                    id = "BALANCER:" .. s[".name"],
                    name = "♻️ [Balancer] " .. s.remarks .. " (" .. count .. " нод)",
                    sort = 1
                })
            end
        end
    end)
    for group_name, count in pairs(group_stats) do
        if count > 0 then
            table.insert(groups, {
                id = "GROUP:" .. group_name,
                name = "📦 [Subscribe] " .. group_name .. " (" .. count .. " нод)",
                sort = 2
            })
        end
    end
    table.sort(groups, function(a, b)
        if a.sort == b.sort then return a.name < b.name end
        return a.sort < b.sort
    end)
%>
<div class="cbi-value-field">
    <% if #groups == 0 then %>
        <em>Нет доступных групп. Создайте подписки или Balancing ноды.</em>
    <% else %>
        <ul style="list-style:none;padding:0;margin:0;">
        <% for _, group in ipairs(groups) do 
            local is_checked = current_values[group.id] and 'checked="checked"' or ''
            local style = group.sort == 1 and 'style="font-weight:bold;color:#0066cc;"' or 'style="font-weight:bold;color:#00aa00;"'
        %>
            <li style="margin:8px 0;">
                <label <%=style%>>
                    <input class="cbi-input-checkbox" type="checkbox" 
                           name="cbid.passwall.<%=section%>.<%=self.option%>" 
                           value="<%=group.id%>" <%=is_checked%> />
                    <%=group.name%>
                </label>
            </li>
        <% end %>
        </ul>
    <% end %>
</div>
<%+cbi/valuefooter%>
EOF1
echo "✓ subscribe_groups.htm"
mkdir -p /usr/share/passwall
cat > /usr/share/passwall/helper_expand_groups.lua << 'EOF2'
#!/usr/bin/lua
local uci = require "luci.model.uci".cursor()
local appname = "passwall"
local function expand_groups()
    uci:foreach(appname, "nodes", function(node)
        if node.protocol == "_balancing" and node.balancing_node then
            local groups = node.balancing_node
            local expanded = {}
            if type(groups) == "string" then
                local temp = {}
                for v in string.gmatch(groups, "%S+") do table.insert(temp, v) end
                groups = temp
            end
            for _, group_id in ipairs(groups) do
                if string.sub(group_id, 1, 6) == "GROUP:" then
                    local tag = string.sub(group_id, 7)
                    uci:foreach(appname, "nodes", function(n)
                        if n.type and n.protocol ~= "_balancing" then
                            local node_tag = n.group or "default"
                            if node_tag == tag then table.insert(expanded, n[".name"]) end
                        end
                    end)
                elseif string.sub(group_id, 1, 9) == "BALANCER:" then
                    local balancer_id = string.sub(group_id, 10)
                    uci:foreach(appname, "nodes", function(n)
                        if n[".name"] == balancer_id and n.protocol == "_balancing" then
                            local nodes = n.balancing_node or {}
                            if type(nodes) == "string" then
                                for nd in string.gmatch(nodes, "%S+") do
                                    if string.sub(nd, 1, 6) ~= "GROUP:" and string.sub(nd, 1, 9) ~= "BALANCER:" then
                                        table.insert(expanded, nd)
                                    end
                                end
                            elseif type(nodes) == "table" then
                                for _, nd in ipairs(nodes) do
                                    if string.sub(nd, 1, 6) ~= "GROUP:" and string.sub(nd, 1, 9) ~= "BALANCER:" then
                                        table.insert(expanded, nd)
                                    end
                                end
                            end
                        end
                    end)
                else
                    table.insert(expanded, group_id)
                end
            end
            local unique, seen = {}, {}
            for _, v in ipairs(expanded) do
                if v and not seen[v] then table.insert(unique, v) seen[v] = true end
            end
            if #unique > 0 then
                uci:set_list(appname, node[".name"], "_expanded_nodes", unique)
            end
        end
    end)
    uci:save(appname)
end
expand_groups()
EOF2
chmod +x /usr/share/passwall/helper_expand_groups.lua
echo "✓ helper_expand_groups.lua"
cat > /tmp/patch_ray.lua << 'EOF3'
local file = "/usr/lib/lua/luci/model/cbi/passwall/client/type/ray.lua"
local f = io.open(file, "r")
if not f then print("ERROR") os.exit(1) end
local content = f:read("*a")
f:close()
local before = string.match(content, '(.*)o = s:option%(MultiValue, _n%("balancing_node"%)')
local after = string.match(content, '(o = s:option%(ListValue, _n%("balancingStrategy"%).*)')
if not before or not after then print("ERROR") os.exit(1) end
local new_block = [[
o = s:option(MultiValue, _n("balancing_node"), translate("Выбор групп нод"))
o:depends({ [_n("protocol")] = "_balancing" })
o.widget = "checkbox"
o.template = "passwall/cbi/subscribe_groups"
o.validate = function(self, value, section)
    if not value then return nil end
    local result = type(value) == "table" and value or {value}
    for _, v in ipairs(result) do
        if type(v) ~= "string" or (string.sub(v, 1, 6) ~= "GROUP:" and string.sub(v, 1, 9) ~= "BALANCER:") then
            return nil
        end
    end
    return result
end
o.cfgvalue = function(self, section)
    return m.uci:get_list(appname, section, "balancing_node") or {}
end
function o.custom_write(self, section, value)
    local groups = type(value) == "table" and value or (type(value) == "string" and {value} or {})
    if #groups > 0 then
        m.uci:set_list(appname, section, "balancing_node", groups)
    else
        m.uci:delete(appname, section, "balancing_node")
    end
end
]]
local new_content = before .. new_block .. "\n" .. after
f = io.open(file, "w")
f:write(new_content)
f:close()
print("OK")
EOF3
lua /tmp/patch_ray.lua
if [ $? -eq 0 ]; then
    echo "✓ ray.lua пропатчен"
else
    echo "ОШИБКА патча!"
    exit 1
fi
uci set passwall.@global_other[0].enable_group_balancing='1' 2>/dev/null
uci commit passwall
if [ -f /etc/init.d/passwall ] && ! grep -q "helper_expand_groups" /etc/init.d/passwall; then
    sed -i '/start_service()/a\\	lua /usr/share/passwall/helper_expand_groups.lua 2>/dev/null || true' /etc/init.d/passwall
fi
rm -rf /tmp/luci-* /tmp/patch_ray.lua
/etc/init.d/uhttpd restart
echo ""
echo "=========================================="
echo "✓ УСТАНОВКА ЗАВЕРШЕНА!"
echo "=========================================="
echo "Бэкап: $BACKUP_DIR"
echo "Теперь в Balancing только группы!"
FINALSCRIPT
chmod +x /tmp/install.sh && /tmp/install.sh
echo ">>> Установка патча завершена."
