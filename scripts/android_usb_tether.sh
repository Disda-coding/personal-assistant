#!/usr/bin/env bash
set -euo pipefail

HORNDIS_BIN="horndis"

need_horndis() {
  if ! command -v "$HORNDIS_BIN" >/dev/null 2>&1; then
    echo "未检测到 horndis（HoRNDIS-Userspace）。请在终端按以下步骤安装："
    echo "  1) sudo installer -pkg /tmp/HoRNDIS-Userspace.pkg -target /"
    echo "     （若提示已拦截，到 系统设置 → 隐私与安全性 → 仍要打开）"
    echo "  2) sudo horndis install"
    exit 1
  fi
}

enable_tether() {
  echo "==> 通过 adb 开启手机 USB 网络共享"
  if ! command -v adb >/dev/null 2>&1; then
    echo "未找到 adb，请直接在手机上开启：设置 → 网络共享 → USB 网络共享"
    return 0
  fi
  if ! adb get-state >/dev/null 2>&1; then
    echo "未检测到 adb 设备，请确认 USB 调试已开、数据线支持数据传输。"
    echo "然后手动在手机开启：设置 → USB 网络共享"
    return 0
  fi
  adb shell svc usb setFunctions rndis,adb 2>/dev/null \
    || adb shell svc usb setFunctions rndis 2>/dev/null \
    || echo "adb 自动开启失败，请在手机上手动开启 USB 网络共享。"
  sleep 2
  echo "==> horndis 状态："
  "$HORNDIS_BIN" status || true
  echo "==> 等待接口通过 DHCP 获取 IP 并联网..."
  for _ in $(seq 1 12); do
    if curl -s -m 5 https://ifconfig.me >/dev/null 2>&1; then
      echo "联网成功，公网 IP："
      curl -s -m 5 https://ifconfig.me || true
      echo
      return 0
    fi
    sleep 2
  done
  echo "暂未检测到网络，请确认手机已开启 USB 网络共享，并查看：horndis status"
}

disable_tether() {
  echo "==> 关闭手机 USB 网络共享"
  if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
    adb shell svc usb setFunctions mtp,adb 2>/dev/null || true
  fi
  echo "已尝试将 USB 模式恢复为 mtp,adb。"
}

status() {
  "$HORNDIS_BIN" status || true
  echo "--- 全部网络接口 ---"
  ifconfig -l || true
}

case "${1:-start}" in
  start|enable|on) need_horndis; enable_tether ;;
  stop|disable|off) disable_tether ;;
  status|st) need_horndis; status ;;
  *) echo "用法: $0 [start|stop|status]"; exit 1 ;;
esac
