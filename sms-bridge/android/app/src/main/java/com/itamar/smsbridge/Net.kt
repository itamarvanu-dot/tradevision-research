package com.itamar.smsbridge

import java.net.Inet4Address
import java.net.NetworkInterface

object Net {

    /**
     * The address the iPhone should point at: the phone's own IPv4 on the current Wi-Fi
     * (or Tailscale/VPN) interface. Returns null when the phone is not on any local network.
     */
    fun localIpv4(): String? {
        val candidates = mutableListOf<Pair<Int, String>>()
        try {
            for (nif in NetworkInterface.getNetworkInterfaces()) {
                if (!nif.isUp || nif.isLoopback) continue
                for (addr in nif.inetAddresses) {
                    if (addr !is Inet4Address || addr.isLoopbackAddress || addr.isLinkLocalAddress) continue
                    val ip = addr.hostAddress ?: continue
                    candidates.add(priorityOf(nif.name, ip) to ip)
                }
            }
        } catch (_: Exception) {
            return null
        }
        return candidates.minByOrNull { it.first }?.second
    }

    /** Wi-Fi first, then a VPN/Tailscale interface, then anything else (usually mobile data). */
    private fun priorityOf(interfaceName: String, ip: String): Int = when {
        interfaceName.startsWith("wlan") -> 0
        ip.startsWith("192.168.") || ip.startsWith("10.") -> 1
        interfaceName.startsWith("tun") || interfaceName.startsWith("ts") -> 2
        else -> 3
    }
}
