#!/usr/bin/env bash
# GitHub Actions 上连接 / 断开同济 VPN（Array Networks SSL VPN，即 MotionPro 用的协议）。
# 用开源的 openconnect（9.0 起支持 --protocol=array），不需要安装 MotionPro。
#   scripts/cloud_vpn.sh up     连接，并确认 agi.tongji.edu.cn 解析到校内地址、/v1/models 可用
#   scripts/cloud_vpn.sh down   断开
# 需要的环境变量（来自 GitHub Secrets，日志里会被自动打码）：
#   TONGJI_VPN_USER  TONGJI_VPN_PASS  [TONGJI_VPN_HOST，默认 vpn.tongji.cn]  [TONGJI_VPN_METHOD，默认空]  [TONGJI_VPN_IP，默认 202.120.189.34]  TONGJI_API_KEY
set -uo pipefail
ACTION="${1:-up}"
HOST="${TONGJI_VPN_HOST:-vpn.tongji.cn}"
# 在国外解析 vpn.tongji.cn 会得到 202.120.189.175（没有登录页，返回 404）；
# 笔记本上的 MotionPro 连的是 202.120.189.34，这里固定连这个地址，证书和 Host 仍用域名。
VPN_IP="${TONGJI_VPN_IP:-202.120.189.34}"
PIDFILE=/tmp/sandboxhot-openconnect.pid
API_HOST=agi.tongji.edu.cn
FALLBACK_DNS="202.120.190.208"   # 笔记本连 MotionPro 时看到的校内 DNS

log() { echo "[cloud-vpn] $*"; }

resolve_internal() {
  # 先用系统解析；拿不到 10.x 就向 VPN 下发的 DNS 和已知的校内 DNS 直接查询
  local ip
  ip=$(getent ahostsv4 "$API_HOST" | awk '{print $1}' | grep -m1 '^10\.' || true)
  if [ -n "$ip" ]; then echo "$ip"; return 0; fi
  local servers
  servers="$(resolvectl dns tun0 2>/dev/null | sed 's/.*://' | tr ' ' '\n' | grep -E '^[0-9.]+$' || true) $FALLBACK_DNS"
  for s in $servers; do
    ip=$(dig +short +time=3 +tries=1 @"$s" "$API_HOST" A 2>/dev/null | grep -m1 '^10\.' || true)
    if [ -n "$ip" ]; then echo "$ip"; return 0; fi
  done
  return 1
}

up() {
  if [ -z "${TONGJI_VPN_USER:-}" ] || [ -z "${TONGJI_VPN_PASS:-}" ]; then
    log "缺少 TONGJI_VPN_USER / TONGJI_VPN_PASS，请在仓库 Settings → Secrets and variables → Actions 里添加"; return 2
  fi
  log "openconnect 版本：$(openconnect --version 2>&1 | head -1)"
  log "连接 $HOST（固定连接 $VPN_IP；GitHub 这里的系统解析结果是 $(getent ahostsv4 "$HOST" | awk 'NR==1{print $1}')）……"
  # --background：认证成功、隧道建立后才转入后台，所以返回码就代表成败
  # Array 登录表单（auth_id=form）有三个字段：method（认证方式，提示为 authgroup:）、uname、pwd。
  # method 来自可选的 TONGJI_VPN_METHOD（MotionPro 日志 “login successfully, method name:” 后面的值），默认空。
  # 每次运行只尝试一次登录，避免连续失败把账号锁住。
  if ! printf '%s\n' "$TONGJI_VPN_PASS" | sudo openconnect --protocol=array --user="$TONGJI_VPN_USER" \
      --form-entry="form:method=${TONGJI_VPN_METHOD:-}" --form-entry="form:uname=$TONGJI_VPN_USER" \
      --resolve="$HOST:$VPN_IP" \
      --passwd-on-stdin --non-inter --background --pid-file="$PIDFILE" --interface=tun0 \
      --timestamp "$HOST" > /tmp/openconnect.log 2>&1; then
    log "openconnect 连接失败，日志如下："; cat /tmp/openconnect.log; return 3
  fi
  cat /tmp/openconnect.log
  for _ in $(seq 1 30); do ip -4 addr show tun0 2>/dev/null | grep -q inet && break; sleep 2; done
  log "tun0：$(ip -4 -o addr show tun0 2>/dev/null | awk '{print $4}')"
  log "默认路由：$(ip route show default | head -2 | tr '\n' ';')"
  local ip=""
  for _ in $(seq 1 10); do ip=$(resolve_internal) && break; sleep 3; done
  if [ -z "$ip" ]; then
    log "VPN 已连上，但 $API_HOST 没有解析到校内地址"; getent ahostsv4 "$API_HOST" | head -2; return 4
  fi
  if ! getent ahostsv4 "$API_HOST" | grep -q '^10\.'; then
    echo "$ip $API_HOST" | sudo tee -a /etc/hosts > /dev/null
    log "已把 $API_HOST → $ip 写入 /etc/hosts"
  fi
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -H "Authorization: Bearer ${TONGJI_API_KEY:-}" "https://$API_HOST/v1/models" || true)
  log "GET /v1/models → HTTP $code"
  [ "$code" = "200" ] || { log "同济平台接口不可用"; return 5; }
  log "VPN 就绪"
}

down() {
  local pid
  pid=$(sudo cat "$PIDFILE" 2>/dev/null || true)
  if [ -n "$pid" ]; then
    sudo kill -INT "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do sudo kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  fi
  sudo pkill -INT openconnect 2>/dev/null || true
  sudo sed -i "/ $API_HOST\$/d" /etc/hosts 2>/dev/null || true
  log "已断开"
}

case "$ACTION" in
  up) up ;;
  down) down ;;
  *) echo "用法：$0 up|down"; exit 1 ;;
esac
